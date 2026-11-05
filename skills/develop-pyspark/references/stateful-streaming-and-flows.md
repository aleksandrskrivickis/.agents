# Stateful streaming, flows, and checkpoints

> **Source.** `[repo]` — distilled from a production Databricks Spark Declarative Pipeline
> and its accumulated fixes. `[docs]` marks a vendor-documented constraint; `[deduced]` an
> inference.

## `applyInPandasWithState` for cross-microbatch pairing

Use it to carry state between micro-batches (e.g. pair each document version with its predecessor
within a key). Keep the **state small** — ids/version, never the heavy payload.

```python
from pyspark.sql.streaming.state import GroupStateTimeout

(
    versioned.groupBy("iso", "portal_name", "title").applyInPandasWithState(
        pair_versions,  # fn(key, pdfs_iter, state) -> yields pandas frames
        outputStructType=OUTPUT_SCHEMA,
        stateStructType=STATE_SCHEMA,
        outputMode="append",
        timeoutConf=GroupStateTimeout.NoTimeout,
    )
)
```

Inside the function: read `state.get` if `state.exists`, process the batch in arrival order, then
`state.update(newest)` to carry the group's latest forward. Cap `maxRecordsPerBatch` (≈20) so a
group's accumulated rows don't spike UDF memory.

A concrete handler (pair each new version with its predecessor; gap- and out-of-order-tolerant):

```python
def pair_versions(key, pdfs, state):
    batch = pd.concat(list(pdfs), ignore_index=True)
    batch = batch[batch["version"].notna()].sort_values(["version", "pipeline_timestamp", "document_id"], kind="stable")
    previous = tuple(state.get) if state.exists else None
    last_version = previous[VERSION_IDX] if previous else None
    for row in batch.itertuples(index=False):
        if last_version is not None and row.version <= last_version:
            continue  # dup / late version — already paired
        current = tuple(getattr(row, c) for c in COLUMNS)
        last_version = row.version
        if previous is not None:
            yield pd.DataFrame([interleave(previous, current)], columns=OUTPUT_COLUMNS)
        previous = current
    if previous is not None:
        state.update(previous)  # carry the newest forward
```

State is a plain tuple; emit pairs one at a time (no per-group buffering); the `<= last_version`
guard makes re-delivered or out-of-order versions idempotent.

## `append_flow` checkpoints are keyed by the flow NAME

Each `@dp.append_flow(name=...)` owns its own streaming checkpoint, keyed by that name. Two
consequences you can exploit:

- **Parameterised reprocessing without a full refresh.** Key the name on a parameter (e.g. the
  embedding model). Swapping the parameter yields a new flow name whose **fresh checkpoint re-reads
  the source from the start** and appends a new generation, while the old rows remain.
- **Flow names are restricted** to alphanumerics + underscore. Sanitise:
  `re.sub(r"\W+", "_", value).strip("_")`.

```python
@dp.append_flow(name=re.sub(r"\W+", "_", MODEL_NAME).strip("_"), target="...embeddings")
def flow():
    return spark.readStream.option("maxFilesPerTrigger", str(N)).table("...slices").mapInPandas(...)
```

## Control micro-batch size with `maxFilesPerTrigger`

- `"1"` — one source file per trigger: smallest batches, strict-ish ordering, lowest memory.
- `concurrency * 2` — admit a few files so the scheduler can offset a slow file against a fast one;
  at parity a single straggler leaves the other workers idle.

## Tolerate upstream Delta changes in a stream

A streaming read over a Delta table fails if the source sees updates/deletes (not just appends):

- `readStream.option("ignoreChanges", "true")` — re-emit changed files (may yield duplicates
  downstream; dedupe/idempotency needed).
- `readStream.option("skipChangeCommits", "true")` — skip commits that are pure changes (used when
  reading the pipeline `event_log`).

## `foreach_batch_sink` for side-effect writes (MERGE / maintenance)

For a custom write (upsert, maintenance table) that shouldn't be a barrier for downstream datasets:

```python
@dp.foreach_batch_sink(name="offsets_maintenance")
def sink(batch_df, batch_id):
    session = batch_df.sparkSession
    DeltaTable.createIfNotExists(session).tableName(TABLE).addColumn(...).execute()
    if batch_df.isEmpty():
        return
    if batch_id == 0:
        ...  # one-time rebuild / reconciliation
    # MERGE batch_df into TABLE
```

Notes: get the session from `batch_df.sparkSession`; guard `batch_df.isEmpty()`; special-case
`batch_id == 0`; the sink runs as a **sibling flow**, not a blocking dependency, so downstream
fetches aren't gated on it.

## Force a flow to run after another chain (no-op join)

SDP infers run-order from table references. To make a flow run **after** a chain it doesn't actually
read from, add a never-matching join purely to register the dependency, then drop the columns. Handy
for flattening the pipeline's own `event_log` only once the data chain has produced metrics:

```python
(
    spark.readStream.option("skipChangeCommits", "true")
    .table(EVENT_LOG_TABLE)
    .join(spark.read.table("documents_markdown_slices_aligned"), on=lit(False), how="left")  # ordering only
    .selectExpr(
        "id",
        "event_type",
        "origin.update_id AS update_id",  # struct field: dot
        "substring_index(origin.flow_name, '.', -1) AS flow_name",  # last dotted segment
        "details:flow_progress.status AS status",  # JSON/variant path: colon
        "CAST(details:flow_progress.metrics.num_output_rows AS BIGINT) AS num_output_rows",
    )
)
```

`struct.field` for nested structs, `col:json.path` for a JSON/variant string column,
`substring_index(x, '.', -1)` for the last segment. Flattening `event_log` makes a pipeline's own
metrics a queryable table (and a supported source for a synced table).

## Streaming source reads

Reference tables by bare name (`spark.readStream.table("contents")`) — SDP infers the DAG from the
reference. A **batch** read (`spark.read.table`) inside a flow keeps that step stateless and leaves
the streaming checkpoint valid when you need a full snapshot (e.g. recomputing offsets).
