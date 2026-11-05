# Arrow conversion failures: `ChunkedArray`, dtype coercion, and `mapInArrow`

> **Source.** `[repo]` — reconstructed from a production pipeline's multi-week fix for an
> intermittent Arrow crash across four ingestion stages, including four reverts and the commit
> sequence that settled it. `[docs]` marks documented Arrow/Spark behaviour; `[deduced]` an
> inference from the fix narrative.

This is the companion to [pandas-udfs-and-memory.md](./pandas-udfs-and-memory.md), which covers the
*deterministic* schema trap (all-NaN columns arriving as `float64`). This file covers the harder
case: a conversion that works on most batches and fails on some, and the escape hatch for when
coercing pandas stops being enough.

## Two different failures with one error message

A `mapInPandas` UDF returns pandas; Spark converts it to Arrow against your **declared** schema. The
same family of errors — `ArrowTypeError`, "expected string got double", "Expected bytes, got a
'ChunkedArray' object" — arises from two unrelated causes, and they need different fixes:

| Failure | Trigger | Fix |
|---|---|---|
| **Deterministic type mismatch** | A column's pandas dtype can never satisfy the declared type (all-NaN → `float64` vs declared `string`) | Coerce in pandas: `.astype(object).replace(np.nan, None)` — see the sibling reference |
| **Intermittent `ChunkedArray`** | A column arrives backed by a *multi-chunk* Arrow array; conversion succeeds when it happens to be single-chunk | `combine_chunks()`, which means taking control of the Arrow batch — i.e. `mapInArrow` |

The second one is the trap, because it looks like flakiness. It correlates with payload size and
batch composition, so it appears under load and disappears in testing, and every reviewer's first
instinct is to blame concurrency.

## Lowering the Arrow batch size is a mitigation, not a fix

The first remedy reached for is `spark.sql.execution.arrow.maxRecordsPerBatch`. It does reduce the
failure rate, because smaller batches are likelier to be single-chunk. It never eliminates it.

> **Record it as a mitigation.** In the source project the cap was in place for weeks and the
> reporter's own assessment was that it "reduced the frequency without ever eliminating it". A
> mitigation that lowers a failure rate while costing throughput, and is believed to be a fix, is
> the worst of the three states — the real cause stays unfound *and* you are paying for it.

Two corollaries worth internalising:

- **A setting that cannot act is worse than an absent one**, because it is cited as a control that is
  already in place. The same cap was set on a stage that used a plain `@udf` — which Spark evaluates
  a row at a time — and was argued about through three failed fixes while doing nothing at all.
  `maxRecordsPerBatch` governs **Arrow-based APIs only**: `mapInPandas`, `applyInPandas`,
  `mapInArrow`, `toPandas`. On a scalar `@udf` it is inert. `[repo]`
- Once the real fix lands, **re-test whether the cap is still needed** rather than leaving it in
  place. It may be paying a throughput cost for nothing.

## Coerce to the exact Python type the declared schema wants

Before reaching for `mapInArrow`, eliminate the dtype mismatches that pandas introduces silently.
Arrow will not widen or narrow for you, and pandas' nullable extension dtypes and `object` columns
do not map to Arrow primitives the way the declared schema implies.

```python
# BooleanType: pandas may hold None/np.nan/"true"/numpy.bool_ in an object column.
# Arrow wants real Python bools (or None).
result["repealed"] = result["repealed"].map(lambda v: None if pd.isna(v) else bool(v))
result["request_success"] = result["request_success"].map(lambda v: None if pd.isna(v) else bool(v))

# LongType/IntegerType: a column with any null becomes float64, and 1.0 is not an int64.
result["document_id"] = result["document_id"].map(lambda v: None if pd.isna(v) else int(v))
result["version"] = result["version"].map(lambda v: None if pd.isna(v) else int(v))
```

Both of those are real fix commits. The pattern — `None if pd.isna(v) else <ctor>(v)` per column,
driven off the declared schema — is the reliable form:

```python
COERCERS = {BooleanType: bool, LongType: int, IntegerType: int, DoubleType: float, StringType: str}

for field in SCHEMA.fields:
    ctor = COERCERS.get(type(field.dataType))
    if ctor is not None:
        result[field.name] = result[field.name].map(lambda v, c=ctor: None if pd.isna(v) else c(v))
```

> **`pd.isna` on a list raises.** It returns an elementwise array for array-likes, so guard list and
> map columns out of the loop above and handle them separately. `[deduced]`

## Prefer a simpler declared type over fighting the converter

For map and array columns, there are two routes, and the source project tried the harder one first:

1. **JSON-encode the values but keep the declared `MapType`/`ArrayType`.** Attempted, committed,
   **reverted** the same day. The conversion still has to build a nested Arrow type from an object
   column, which is exactly the fragile path.
2. **Change the declared type to `StringType` and `json.dumps` at the producer.** This is what
   survived:

> `portal_tags` schema type changed from `ArrayType(StringType())` → `StringType()`. The fetch
> function now JSON-encodes the tags list (`json.dumps(value)`) instead of passing a native Python
> list, with `None` preserved for portals that had no tags.

What this costs and what it buys:

- **Costs:** consumers must `from_json` / `get_json_object` to read it; you lose Arrow-level
  type safety and Delta column statistics on the element values.
- **Buys:** the Arrow conversion becomes a string conversion, which is the one path that does not
  surprise you. For a column that is passed through and rarely filtered on, that is the right trade.
- **Expectations survive the change** if they assert *presence* rather than shape — a
  `portal_tags IS NOT NULL` rule is equally valid against a JSON string. Check your quality rules
  before switching; a rule asserting `size(portal_tags) > 0` would need rewriting. `[repo]`

Decide by how the column is consumed, not by which type is "more correct".

## The escape hatch: `mapInArrow` + `combine_chunks()`

When coercion is not enough, stop going through pandas. `mapInArrow` hands you
`pyarrow.RecordBatch` objects and lets you emit them, so you build the declared types yourself
instead of hoping pandas→Arrow inference agrees with the schema.

```python
import pyarrow as pa

def fetch_arrow(batches):
    client = Client(...)                       # once per partition
    try:
        for batch in batches:
            # combine_chunks() collapses a multi-chunk ChunkedArray into one contiguous array —
            # the step the pandas path never gets to perform, and the actual remedy.
            table = pa.Table.from_batches([batch]).combine_chunks()
            keys = table.column("iso").to_pylist()

            rows = [r for key in keys for r in client.fetch(key)]

            # Build against the declared schema explicitly, not by inference.
            out = pa.Table.from_pylist(rows, schema=ARROW_SCHEMA)
            for out_batch in out.to_batches():
                yield out_batch
    finally:
        client.close()


df.mapInArrow(fetch_arrow, schema=SPARK_SCHEMA)
```

Notes that matter:

- **`combine_chunks()` is the fix**, and it is only reachable from the Arrow API. That is the whole
  reason for the rewrite — not performance. `[repo]`
- Derive `ARROW_SCHEMA` from the Spark schema once, at module scope, so the two cannot drift.
- `mapInArrow` is available from Spark 3.3. `[docs]`
- The generator contract is the same as `mapInPandas`: yield, don't accumulate. See
  [pandas-udfs-and-memory.md](./pandas-udfs-and-memory.md) for why that bounds memory.

### The `ModuleNotFoundError` regression

> **The sharpest trap in this whole sequence.** Converting a stage to `mapInArrow` broke it with
> `ModuleNotFoundError: No module named utils` — and the conversion was reverted.

The stage imported the project's own wheel (`from utils.client import Client`). The same import
worked under `mapInPandas` and failed under `mapInArrow` on the same cluster.

- **Practical rule:** when converting a stage to `mapInArrow`, verify that any first-party package
  import still resolves **on the executor**, and convert one stage at a time so a failure is
  attributable. The source project converted three stages in one commit and had to unpick which one
  regressed. `[repo]`
- **Mitigations** if you hit it: import inside the UDF body rather than at module scope; or inline
  the needed helper so the stage has no first-party dependency; or keep that stage on `mapInPandas`
  and apply the Arrow rewrite only where the crash actually occurs. `[deduced]`
- Do not assume the two APIs share a dependency-resolution path just because they share a cluster.

## Diagnosing before fixing

The source project burned **four attempts and five measurements** on a related OOM in the same code
before the fix landed. Three habits came out of it, and they generalise past Arrow:

**1. Separate row count from row size by measurement, not argument.**

> "R63's cause separated by measurement the same day: document size over 261,259 rows, max 7.79 MB,
> so **row count rather than row size**."

The two have different fixes — row count is bounded by batch caps, row size by dropping columns —
and you cannot tell them apart by reading code.

**2. Name the axis the fix acts on.**

> "The remedy went into what a worker *holds* (`mapInPandas` with bounded emission) rather than what
> a batch *contains* — the distinction that matters, because rows per file are capped at 900 while
> bytes per file reach 318.4 MB, so a batch cannot be bounded below one file."

And the reason bounding the batch could not work:

> **`maxBytesPerTrigger` is a soft cap: it always admits at least one file whole.** If a single file
> is the problem, no trigger-level setting can help. `[docs]`

So with `maxFilesPerTrigger = 1`, a micro-batch *is* one file, the file inherits the upstream
writer's skew (31-fold variation in the source project), and the only remaining lever is what a
worker holds.

**3. Write the falsifying number down before you run the query.** A hypothesis that the OOM came
from line-heavy documents was given a threshold of 2.5M lines *before* the query ran; the corpus
maximum turned out to be 211,334 lines, and the hypothesis died cleanly instead of being argued
about. See [document-decisions](../../document-decisions/SKILL.md) for the practice.

## Quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `ArrowTypeError: expected string, got double` | All-NaN column is `float64` | `.astype(object).replace(np.nan, None)` |
| `Expected bytes, got a 'ChunkedArray' object`, intermittently | Multi-chunk Arrow array | `mapInArrow` + `combine_chunks()` |
| Works small, fails at scale | Batch composition dependent | Not concurrency — measure chunking, then `mapInArrow` |
| Bool column rejected | `object`/nullable dtype, not real `bool` | `None if pd.isna(v) else bool(v)` |
| Int column rejected / arrives as float | Any null promotes to `float64` | `None if pd.isna(v) else int(v)` |
| Nested map/array conversion keeps failing | Fighting Arrow's nested type construction | Declare `StringType` + `json.dumps` at the producer |
| `ModuleNotFoundError` after a `mapInArrow` rewrite | First-party wheel import doesn't resolve on the executor | Import inside the UDF, inline the helper, or leave that stage on `mapInPandas` |
| Lowering `maxRecordsPerBatch` reduced but didn't stop it | It is a mitigation, not the cause | Find the real cause; re-test the cap afterwards |
| `maxRecordsPerBatch` changed nothing at all | Stage is a scalar `@udf`, not an Arrow API | Convert to `mapInPandas`/`mapInArrow`, or remove the misleading setting |
