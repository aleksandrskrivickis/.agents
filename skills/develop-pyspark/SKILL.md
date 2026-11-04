---
name: develop-pyspark
description: 'Use when writing PySpark / Spark Declarative Pipelines transforms on Databricks and hitting real problems: mapInPandas / applyInPandas / applyInPandasWithState, pandas-UDF OOM and Arrow batch tuning (maxRecordsPerBatch), calling a model-serving endpoint from Spark (concurrency, request-size/batching, retries), append_flow checkpoints and foreach_batch sinks, streaming read options (maxFilesPerTrigger, ignoreChanges, skipChangeCommits), broadcast / left_semi / left_anti joins, skew sharding with explode+cogroup, window forward-fill, and driver-vs-executor config, throughput regulation via upstream partitioning + maxFilesPerTrigger, the reusable request envelope, and reliable never-raise API calls. Distilled from the databricks-web-scraping pipeline''s accumulated fixes.'
---

# PySpark on Databricks — hard-won patterns

Problem→solution knowledge distilled from a production Spark Declarative Pipeline (SDP) and many
fix branches. Each topic below has a reference with concrete code:

- [references/pandas-udfs-and-memory.md](./references/pandas-udfs-and-memory.md) — `mapInPandas` / `applyInPandas`, Arrow batch sizing, pandas-UDF OOM, the ChunkedArray schema trap, building output schemas, client-per-partition.
- [references/stateful-streaming-and-flows.md](./references/stateful-streaming-and-flows.md) — `applyInPandasWithState`, `append_flow` checkpoints, `foreach_batch_sink`, `maxFilesPerTrigger`, tolerating Delta source changes.
- [references/model-serving-and-batching.md](./references/model-serving-and-batching.md) — calling a serving endpoint from Spark: concurrency matching, byte-aware batching under the request-size limit, retries, never-raise.
- [references/joins-windows-performance.md](./references/joins-windows-performance.md) — broadcast / left_semi / left_anti, skew sharding (explode+cogroup), `struct`-max, window forward-fill.
- [references/throughput-and-partitioning.md](./references/throughput-and-partitioning.md) — regulating throughput: upstream partitioning ↔ `maxFilesPerTrigger`, `coalesce(1)`, the work-queue pattern, batch-snapshot-in-a-stream.
- [references/reliable-api-calls.md](./references/reliable-api-calls.md) — non-raising client, the reusable **request envelope**, synthetic status codes, retry/auth, executor connection pooling, pagination.
- [references/file-and-document-ingestion.md](./references/file-and-document-ingestion.md) — `binaryFile` reads, Auto Loader (`cloudFiles`) staging, document-extraction UDF strategy, external (SharePoint) file sources, and the anti-patterns to avoid.

## Upstream documentation (sources)

- Apache Spark — PySpark API reference: <https://spark.apache.org/docs/latest/api/python/index.html>
- Apache Spark — Structured Streaming programming guide (`readStream`/triggers/checkpoints): <https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html>
- Apache Spark — pandas function APIs & Arrow (`mapInPandas`/`applyInPandas`/`maxRecordsPerBatch`): <https://spark.apache.org/docs/latest/api/python/user_guide/sql/arrow_pandas.html>
- For the SDP/Lakeflow pipeline docs (the `dp` API, bundles, AUTO CDC, LIVE schema), see the **develop-sdp** skill's *Upstream documentation* section.

## The five rules that prevent most incidents

1. **Driver vs executor.** `spark.conf.get` and `dbutils.secrets.get` work **only on the driver**.
   Read all config/secrets at **module scope** and close over them in the UDF; a UDF that calls
   `spark.conf.get` fails on the executor.
2. **Cap Arrow batches for pandas UDFs.** A pandas UDF has a ~**1 GB** memory ceiling and the
   executor holds `maxRecordsPerBatch × concurrency` rows at once. Set
   `spark.sql.execution.arrow.maxRecordsPerBatch` **low** (e.g. 20) whenever rows are large
   (markdown, embeddings, stateful groups). This is the single most common OOM fix here.
3. **Instantiate expensive clients once per partition**, inside the `mapInPandas` generator (HTTP
   session, `mlflow.deployments` client), and `close()` in a `finally`. Never per row; never on the
   driver and ship it.
4. **Keep heavy payloads out of state and out of stateful operators.** Pair/aggregate on light
   keys, then join the big column (e.g. the document markdown) back afterward — carrying it through
   `applyInPandasWithState` caused UDF OOMs.
5. **Match serving-endpoint concurrency and set it in three places.** `spark.sql.shuffle.partitions`,
   `spark.default.parallelism`, **and** an explicit `.repartition(n)` — only the repartition
   guarantees fan-out; bin-packing may collapse small files into a single task.

## Quick symptom → fix index

| Symptom | Likely fix | Reference |
|---|---|---|
| Pandas UDF OOM / executor killed | Lower `maxRecordsPerBatch`; drop heavy cols from the UDF/state | pandas-udfs-and-memory |
| `ArrowTypeError` / "expected string got double" from `mapInPandas` | All-NaN columns are `float64`; `.astype(object).replace(np.nan, None)` | pandas-udfs-and-memory |
| Serving endpoint returns 429 / slow | Concurrency > endpoint's provisioned size; cap to it | model-serving-and-batching |
| "Request too large" from the endpoint | Byte-aware batching under the size budget; truncate oversized rows | model-serving-and-batching |
| Model swap needs full refresh | Key the `append_flow` **name** on the model → fresh checkpoint, no refresh | stateful-streaming-and-flows |
| Stream fails on upstream Delta update/delete | `readStream.option("ignoreChanges"/"skipChangeCommits", "true")` | stateful-streaming-and-flows |
| One task does all the work (skew) | `repartition(key)` + `sortWithinPartitions`; or shard with `explode(sequence)` | joins-windows-performance |
| Need per-group greedy/fuzzy logic | `repartition(key)+sortWithinPartitions+mapInPandas`, or `cogroup().applyInPandas` | joins-windows-performance |
| Pipeline too slow / uneven micro-batches | Tune `maxFilesPerTrigger` against upstream file count; work-queue + `coalesce(1)` | throughput-and-partitioning |
| An API/HTTP call aborts the run | Non-raising client returning `(envelope, payload)`; record the outcome per row | reliable-api-calls |
| Need per-row call outcome / provenance | Stamp the **request envelope** on every row (success and failure) | reliable-api-calls |
| Ingest PDFs/Office/HTML/images into Spark | `spark.read.format("binaryFile")`; or Auto Loader `cloudFiles` for incremental | file-and-document-ingestion |
| Files arriving over time, schema drifts | Auto Loader `schemaEvolutionMode="rescue"` + `trigger(availableNow=True)` | file-and-document-ingestion |

## When to use this skill

Editing `src/pipeline/*` transforms (or any PySpark job) that uses pandas UDFs, stateful streaming,
model serving, or non-trivial joins/windows — especially when debugging OOM, Arrow/schema errors,
serving limits, checkpoint behaviour, or skew.
