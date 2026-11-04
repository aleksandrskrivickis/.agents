# Pandas UDFs (`mapInPandas` / `applyInPandas`) and memory

## Arrow batch sizing is the primary OOM control

A pandas UDF receives Arrow record batches as pandas DataFrames. The executor holds
`spark.sql.execution.arrow.maxRecordsPerBatch` rows **per concurrent worker** at once, and a pandas
UDF has a ~**1 GB** memory ceiling. When rows are large (markdown bodies, embedding arrays, a
stateful group's accumulated versions), a default batch (10,000 rows) blows that ceiling.

Fix: cap it on the table's `spark_conf` (SDP) or session conf:

```python
spark_conf = {"spark.sql.execution.arrow.maxRecordsPerBatch": "20"}  # 20 for heavy rows, ~100 for light
```

Rule of thumb: **executor footprint ≈ maxRecordsPerBatch × worker concurrency.** When near the
limit, lower the batch size, not the concurrency (concurrency is what buys throughput).

## Keep heavy columns out of the UDF/state

Pair or aggregate on light keys only, then join the big column back afterward. Carrying a large
`content_markdown` column through `applyInPandasWithState` caused UDF OOMs; the fix split the
stateful pairing (ids/version only) from the markdown, which is joined back in a later `@dp.table`.

## The all-NaN → ChunkedArray schema trap

When you shape an API payload with `json_normalize(...).reindex(columns=SCHEMA_COLS)`, columns the
source omitted come back as **all-NaN `float64`**. Arrow then builds a `ChunkedArray`/double, not the
declared `string`/`array` type, and `mapInPandas` fails with a schema/type mismatch. Cast to object
and null the NaNs so Arrow infers the declared types:

```python
result = pd.json_normalize(items, sep="_").assign(**envelope, iso=iso).reindex(columns=COLUMNS)
# list columns: coerce non-lists to None
result["tags"] = result["tags"].apply(lambda v: v if isinstance(v, list) else None)
yield result.astype(object).replace(np.nan, None)
```

### Complex types (map / array) from the declared schema

Derive which columns are `MapType`/`ArrayType` from the schema, then coerce the pandas values so
Arrow can build them — a nested map must become a flat `string -> string` map, so JSON-encode the
values:

```python
MAP_COLS = [f.name for f in SCHEMA.fields if isinstance(f.dataType, MapType)]
ARRAY_COLS = [f.name for f in SCHEMA.fields if isinstance(f.dataType, ArrayType)]


def encode_map(m):  # MapType(String, String): JSON-encode nested values
    return {k: json.dumps(v) for k, v in m.items()} if isinstance(m, dict) else None


def coerce_array(v):  # ArrayType: only real lists/tuples survive, else null
    return list(v) if isinstance(v, (list, tuple)) else None
```

## Instantiate expensive clients once per partition

`mapInPandas` runs the generator once per partition. Create HTTP/serving clients there, reuse across
batches, and close in `finally`. Read secrets/config on the driver (module scope) and close over
them — the UDF runs on executors where `dbutils`/`spark.conf` are unavailable.

```python
EMAIL = dbutils.secrets.get(SCOPE, KEY)  # driver only
BASE_URL = spark.conf.get("lawstronaut_base_url")  # driver only


def fetch_partition(iterator):
    client = None
    try:
        for pdf in iterator:
            if client is None:
                client = Client(email=EMAIL, base_url=BASE_URL)  # once per partition
            ...
            yield shaped_pdf
    finally:
        if client is not None:
            client.close()


df.mapInPandas(fetch_partition, schema=OUT_SCHEMA)
```

## Build the output schema programmatically

For `mapInPandas` you must declare the full output schema. Reuse carried columns from the source
schema and append derived ones, so renames stay in sync:

```python
fields = [source.schema[name] for name in carried_columns]
fields += [StructField(name, StringType()) for name in new_columns]
source.mapInPandas(fn, schema=StructType(fields))
```

## Per-group logic without state: `applyInPandas` and `cogroup`

- **One grouped frame:** `df.groupBy(keys).applyInPandas(fn, schema)` — `fn(pdf)` sees one group.
- **Two aligned frames** (e.g. match A's rows against B's per key): `a.groupBy(keys).cogroup(
  b.groupBy(keys)).applyInPandas(fn, schema)` — `fn(left_pdf, right_pdf)`; used here for rapidfuzz
  title matching.
- **Deterministic per-partition order** (greedy one-to-one assignment): `repartition(key)` +
  `sortWithinPartitions(...)` + `mapInPandas(fn)`, so each partition holds one key's candidates
  already sorted; the pandas function just walks them.

## Greedy one-to-one assignment in `mapInPandas`

Bipartite greedy match per group. `repartition(key)` + `sortWithinPartitions(key, score desc)` so
each partition holds one group's candidate pairs best-first; accept the first time **both** sides are
still unused (first-wins == highest score, because the input is pre-sorted):

```python
def assign_one_to_one(batches):
    key, used_left, used_right = None, set(), set()
    for batch in batches:
        out = []
        for p in batch.itertuples(index=False):
            if p.match_id != key:  # new group -> reset the used-sets
                key, used_left, used_right = p.match_id, set(), set()
            if p.previous_slice_id in used_left or p.current_slice_id in used_right:
                continue
            used_left.add(p.previous_slice_id)
            used_right.add(p.current_slice_id)
            out.append((p.match_id, p.previous_slice_id, p.current_slice_id, p.similarity_score))
        if out:
            yield pd.DataFrame(out, columns=ASSIGN_COLS)
```

Because the rows arrive sorted, this stays O(n) and streams output per batch — no full-group
buffering.

## Don't

- Don't call `collect()`, `count()`, `toPandas()`, `save()`, `start()` inside SDP dataset code.
- Don't build the client on the driver and pass it into the UDF (it won't pickle / won't be warm).
