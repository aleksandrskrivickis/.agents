# Joins, windows, and performance

## Prune the big side before the shuffle

Broadcast the small key set and semi-join to drop rows that can't match, so only relevant data is
shuffled:

```python
candidates = big.join(
    F.broadcast(unmatched.select("jurisdiction_iso").dropDuplicates()),
    on="jurisdiction_iso",
    how="left_semi",
)
```

- `left_semi` — keep big-side rows that have a match (no columns added, no fan-out).
- `left_anti` — keep big-side rows with **no** match (find leftovers/unmatched).
- `dropDuplicates(keys)` **before** a join to avoid accidental row multiplication.

## Beat skew by sharding + fan-out

When one key (or one jurisdiction) dominates, hashing into shards spreads the work; replicate the
small side across all shards so correctness is preserved:

```python
shard = F.pmod(F.hash(F.col("candidate")), F.lit(N_SHARDS))
candidates = candidates.withColumn("candidate_shard", shard)

# each probe row is compared against every shard -> explode across shards
probes = probes.withColumn("candidate_shard", F.explode(F.sequence(F.lit(0), F.lit(N_SHARDS - 1))))

best = (
    probes.groupBy("key", "candidate_shard")
    .cogroup(candidates.groupBy("key", "candidate_shard"))
    .applyInPandas(best_in_shard, schema=SCHEMA)
)
```

Then reduce shard-level winners to the global best with a `struct`-max (keeps the payload beside the
score):

```python
best.groupBy("key").agg(F.max(F.struct("score", "candidate")).alias("best"))
# best.score, best.candidate
```

### The per-shard handler (`best_in_shard`) — rapidfuzz

The `cogroup(...).applyInPandas` function the sharding calls: best candidate per probe row within one
shard (the global winner is the `struct`-max above). Import the heavy lib **inside** the function so
it ships to executors with the UDF, not the driver:

```python
def best_in_shard(inventory_pdf, lawstronaut_pdf):  # cogroup -> (left, right) per key
    from rapidfuzz import fuzz, process

    if inventory_pdf.empty:
        return pd.DataFrame(columns=COLS)
    choices = lawstronaut_pdf["lawstronaut_title"].tolist()
    rows = []
    for r in inventory_pdf.itertuples(index=False):
        best_title, best_score = None, 0.0
        if choices:
            m = process.extractOne(r.title, choices, scorer=fuzz.WRatio)
            if m:
                best_title, best_score = m[0], float(m[1])
        rows.append((r.jurisdiction_iso, r.title, best_title, best_score))
    return pd.DataFrame(rows, columns=COLS)
```

## Pick-the-max-row idiom

`F.max(F.struct(score_col, *payload_cols))` returns the whole row with the maximum score — simpler
and cheaper than a `row_number()` window when you only need the top-1 per group.

## Cosine similarity of two embedding columns (scalar UDF)

```python
from sklearn.preprocessing import normalize
from sklearn.metrics.pairwise import linear_kernel


def cosine(a, b):
    if a is None or b is None:
        return None
    va, vb = np.array(a).reshape(1, -1), np.array(b).reshape(1, -1)
    if np.linalg.norm(va) == 0 or np.linalg.norm(vb) == 0:
        return None
    return float(linear_kernel(normalize(va), normalize(vb))[0][0])  # cosine = dot of L2-normalized


cosine_udf = udf(cosine, DoubleType())
df.withColumn("similarity", cosine_udf(col("prev_embedding"), col("curr_embedding")))
```

Guard `None` and zero-norm vectors (they divide by zero). A scalar `udf` is fine for a per-row score;
for very large batches prefer a pandas UDF.

## Window: forward-fill / anchoring

Anchor rows that lack a position to the nearest preceding known position (forward-fill), then order:

```python
anchor = (
    Window.partitionBy("match_id")
    .orderBy(F.col("previous_position").asc_nulls_last())
    .rowsBetween(Window.unboundedPreceding, Window.currentRow)
)
df = df.withColumn(
    "slot", F.coalesce(F.col("current_position"), F.last("current_position", ignorenulls=True).over(anchor), F.lit(-1))
)

order = Window.partitionBy("match_id").orderBy(F.col("slot").asc(), F.col("previous_position").asc_nulls_last())
df = df.withColumn("alignment_order", F.row_number().over(order))
```

Key window pieces: `rowsBetween(unboundedPreceding, currentRow)` for a running frame,
`last(col, ignorenulls=True)` for forward-fill, `asc_nulls_last()` to push nulls to the end,
`row_number()` for a deterministic ordinal.

## Combine frames with differing columns

```python
matches.unionByName(previous_only, allowMissingColumns=True).unionByName(current_only, allowMissingColumns=True)
```

`unionByName` aligns by column name (order-independent); `allowMissingColumns=True` fills absent
columns with null so match rows and one-sided gap rows can share a table.

## Small but load-bearing column ops

- Parse a composite id: `F.split(col, "-").getItem(1).cast("int")`.
- Clamp a score: `F.greatest(F.lit(0.0), F.least(F.lit(1.0), expr))`.
- Content hashing / change detection: `md5(col)` and a data-quality expectation
  `hash_col = md5(content_col)`.

## Physical layout

- `cluster_by_auto=True` (liquid clustering) for most tables — no manual partition columns.
- Explicit `partition_cols=[...]` only when a column has low, stable cardinality and is a frequent
  filter (e.g. `jurisdiction_country`, `portal_name`).
