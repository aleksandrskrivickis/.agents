# Regulating throughput: upstream partitioning + `maxFilesPerTrigger`

Throughput in a streaming SDP pipeline is set by **three independent knobs**. Confusing them is the
usual cause of "too slow", "OOM", or "one task does everything":

| Knob | Where | Controls |
|---|---|---|
| `maxFilesPerTrigger` | streaming **read** option | how many source **files** are admitted per micro-batch = units of work per trigger |
| `spark.sql.execution.arrow.maxRecordsPerBatch` | table `spark_conf` | rows per Arrow batch inside a pandas UDF = **memory** per batch (see pandas-udfs-and-memory) |
| `repartition(n)` / `shuffle.partitions` / `default.parallelism` | transform / conf | task **fan-out** = parallelism (see model-serving-and-batching) |

## The upstream-partitioning trick

**An upstream table's partitioning determines how many files it writes, and the downstream
`maxFilesPerTrigger` admits that many per trigger.** Pair them to regulate per-micro-batch work
precisely.

- Give the upstream streaming table `partition_cols=[...]` on the **work key** (e.g.
  `["iso", "name", "offset_start"]`) and `spark.sql.shuffle.partitions: "1"` so each logical unit
  lands in its own file.
- Downstream, read it with `maxFilesPerTrigger` set to the number of units you want per batch:
  - `"1"` — exactly one unit per micro-batch (lowest memory, heavy payloads commit one at a time,
    respects a single-token / rate-limited API).
  - `concurrency * 2` — admit a few so the scheduler can overlap a slow unit with a fast one.

```python
# upstream: one file per (iso, name, offset_start)
dp.create_streaming_table("contents_markdown_batches",
    partition_cols=["iso", "name", "offset_start"],
    spark_conf={"spark.sql.shuffle.partitions": "1", "spark.default.parallelism": "1"})

# downstream: one unit of work per trigger, collapsed to a single task
@dp.append_flow(name="contents_markdown_flow", target="contents_markdown")
def flow():
    batches = (spark.readStream.option("maxFilesPerTrigger", "1")
               .table("contents_markdown_batches").coalesce(1))
    return batches.mapInPandas(fetch_markdown, schema=SCHEMA)
```

## `coalesce(1)` to serialise a heavy per-partition UDF

`.coalesce(1)` before a `mapInPandas` forces a single task, so the per-partition client does the
work serially — used when each call is heavy (large markdown fetch) or the API allows only one
active token. Combine with `maxFilesPerTrigger="1"` for strict one-unit-at-a-time progress. The
opposite end is `.repartition(CONCURRENCY)` for a serving endpoint that *wants* parallel callers.

## Two-stage work-queue pattern (pace a heavy step incrementally)

When the expensive step must commit incrementally, split it:

1. **Stage 1 — build a queue** streaming table: one row per unit of work (e.g. a document-offset
   window), partitioned by the work key. Cheap to produce.
2. **Stage 2 — drain the queue** with `maxFilesPerTrigger` pacing the heavy fetch/compute, one (or a
   few) windows per micro-batch.

Now throughput is a predictable function of *queue file count × `maxFilesPerTrigger`*, and heavy
payloads land one window at a time instead of one giant batch — this is how large markdown fetches
avoid both timeouts and OOM.

## Mix a batch snapshot with a streaming read

Inside a streaming flow you can `spark.read.table(...)` (batch) for a **static snapshot** and
`spark.readStream.table(...)` for the **incremental** side, then join. The batch read is stateless,
so it does **not** disturb the streaming checkpoint — use it to pin "the newest row per key" or a
shared offsets snapshot while the stream drives new work:

```python
latest = spark.read.table("portals").groupBy("iso", "name").agg(spark_max("pipeline_timestamp")...)
stream = spark.readStream.option("maxFilesPerTrigger", "1").table("portals") \
            .join(latest, ["iso", "name", "pipeline_timestamp"], "left_semi")
```

## Single-task vs fan-out, by stage

- `shuffle.partitions=1` / `default.parallelism=1` — small upstream, or deliberately serial heavy
  work (e.g. slicing, the batches queue).
- `= CONCURRENCY` + explicit `repartition(CONCURRENCY)` — when a downstream service (model serving)
  wants parallel callers. Only the repartition guarantees the fan-out.
