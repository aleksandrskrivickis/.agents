---
name: develop-pyspark
description: 'Use when writing PySpark / Spark Declarative Pipelines transforms on Databricks and hitting real problems: mapInPandas / applyInPandas / applyInPandasWithState, pandas-UDF OOM and Arrow batch tuning (maxRecordsPerBatch), intermittent ChunkedArray / ArrowTypeError conversion crashes and the mapInArrow + combine_chunks escape hatch, calling a model-serving endpoint from Spark (concurrency, request-size/batching, retries), registering a model into Unity Catalog and standing up its serving endpoint, chunking documents for embedding and making chunk size fit the model context window, append_flow checkpoints and foreach_batch sinks, streaming read options (maxFilesPerTrigger, ignoreChanges, skipChangeCommits), broadcast / left_semi / left_anti joins, skew sharding with explode+cogroup, window forward-fill, and driver-vs-executor config, throughput regulation via upstream partitioning + maxFilesPerTrigger, the reusable request envelope, and reliable never-raise API calls. Distilled from a production Databricks pipeline''s accumulated fixes.'
---

# PySpark on Databricks — hard-won patterns

> **What this is.** Problem→cause→fix knowledge from a production Spark Declarative Pipeline and
> three years of fix branches, organised by the failure rather than by the API. Nearly every entry
> exists because something broke in production: an OOM, a silently truncated embedding, an
> intermittent Arrow crash, a stage that did all its work on one task. Where a value appears, the
> reasoning behind it appears with it.
>
> It assumes you are writing PySpark on the Databricks Runtime. For the declarative pipeline layer
> around these transforms, see [develop-sdp](../develop-sdp/SKILL.md).

## Detailed references

- [references/pandas-udfs-and-memory.md](./references/pandas-udfs-and-memory.md) — `mapInPandas` / `applyInPandas`, Arrow batch sizing, pandas-UDF OOM, the all-NaN schema trap, building output schemas, client-per-partition.
- [references/arrow-conversion-failures.md](./references/arrow-conversion-failures.md) — the *intermittent* `ChunkedArray` crash, bool/int coercion before Arrow, simplifying a declared type instead of fighting the converter, `mapInArrow` + `combine_chunks()`, and the `ModuleNotFoundError` regression that comes with it.
- [references/stateful-streaming-and-flows.md](./references/stateful-streaming-and-flows.md) — `applyInPandasWithState`, `append_flow` checkpoints, `foreach_batch_sink`, `maxFilesPerTrigger`, tolerating Delta source changes.
- [references/model-serving-and-batching.md](./references/model-serving-and-batching.md) — calling a serving endpoint from Spark: concurrency matching, byte-aware batching under the request-size limit, retries, never-raise.
- [references/model-registration-and-endpoints.md](./references/model-registration-and-endpoints.md) — the other side: a `pyfunc` wrapper, idempotent registration via a signature tag, `validate_serving_input`, provisioned-concurrency sizing, and the preconditions a calling stage silently depends on.
- [references/chunking-and-embedding-fit.md](./references/chunking-and-embedding-fit.md) — splitting documents for embedding: the separator ladder as policy, chunk size vs the model's context window (silent truncation), deterministic chunk ids, generation stamping, and how to measure chunking quality.
- [references/joins-windows-performance.md](./references/joins-windows-performance.md) — broadcast / left_semi / left_anti, skew sharding (explode+cogroup), `struct`-max, window forward-fill.
- [references/throughput-and-partitioning.md](./references/throughput-and-partitioning.md) — regulating throughput: upstream partitioning ↔ `maxFilesPerTrigger`, `coalesce(1)`, the work-queue pattern, batch-snapshot-in-a-stream.
- [references/reliable-api-calls.md](./references/reliable-api-calls.md) — non-raising client, the reusable **request envelope**, synthetic status codes, retry/auth, executor connection pooling, pagination.
- [references/file-and-document-ingestion.md](./references/file-and-document-ingestion.md) — `binaryFile` reads, Auto Loader (`cloudFiles`) staging, document-extraction UDF strategy, external file sources, and the anti-patterns to avoid.

## The rules that prevent most incidents

1. **Driver vs executor.** `spark.conf.get` and `dbutils.secrets.get` work **only on the driver**.
   Read all config/secrets at **module scope** and close over them in the UDF; a UDF that calls
   `spark.conf.get` fails on the executor.
2. **Cap Arrow batches for pandas UDFs.** A pandas UDF has a ~**1 GB** memory ceiling and the
   executor holds `maxRecordsPerBatch × concurrency` rows at once. Set
   `spark.sql.execution.arrow.maxRecordsPerBatch` **low** (e.g. 20) whenever rows are large
   (markdown, embeddings, stateful groups). This is the single most common OOM fix here — but see
   rule 4 before treating it as *the* fix.
3. **Instantiate expensive clients once per partition**, inside the `mapInPandas` generator (HTTP
   session, `mlflow.deployments` client), and `close()` in a `finally`. Never per row; never on the
   driver and ship it.
4. **Bound what a worker *holds*, not what a batch *contains*.** With `maxFilesPerTrigger = 1` a
   micro-batch *is* one file, and nothing bounds a file — `maxBytesPerTrigger` is a soft cap that
   always admits at least one file whole. If one file is the problem, no trigger-level setting can
   help; the fix goes into the UDF's emission. And separate *row count* from *row size* by
   measurement before choosing, because they have different fixes.
5. **A setting that cannot act is worse than an absent one**, because it gets cited as protection
   already in place. `maxRecordsPerBatch` governs Arrow-based APIs only — on a scalar `@udf` it does
   nothing. Check that your control is on the code path before arguing about its value.
6. **Keep heavy payloads out of state and out of stateful operators.** Pair/aggregate on light
   keys, then join the big column (e.g. the document markdown) back afterward — carrying it through
   `applyInPandasWithState` caused UDF OOMs.
7. **Match serving-endpoint concurrency and set it in three places.** `spark.sql.shuffle.partitions`,
   `spark.default.parallelism`, **and** an explicit `.repartition(n)` — only the repartition
   guarantees fan-out; bin-packing may collapse small files into a single task.
8. **A derived artifact must carry the identity of the method that produced it.** Chunks carry a
   digest of the chunker config; embeddings carry the model name. Name the `append_flow` after that
   identity, and a configuration change gets a fresh checkpoint that appends a new generation beside
   the old rows instead of corrupting comparisons against them — no full refresh needed.
9. **An embedding model whose context window is shorter than your chunk truncates silently.** No
   error, well-formed vector, every downstream score computed on the opening fragment. Check the p99
   chunk size against the window at selection time, not the mean, and not at inference time.
10. **Don't copy a Spark config from a neighbouring stage without its reason.** Single-partition
    pinning and `maxFilesPerTrigger = 1` are load-bearing where a one-file-per-window commit cadence
    matters and actively harmful on a CPU-bound stage. Copied settings caused the most expensive OOM
    in the source project.

## Quick symptom → fix index

| Symptom | Likely fix | Reference |
|---|---|---|
| Pandas UDF OOM / executor killed | Lower `maxRecordsPerBatch`; drop heavy cols from the UDF/state | pandas-udfs-and-memory |
| OOM only at full scale; batch caps didn't help | Bound the UDF's emission, not the batch; measure row count vs row size | arrow-conversion-failures |
| `ArrowTypeError` / "expected string got double" | All-NaN columns are `float64`; `.astype(object).replace(np.nan, None)` | pandas-udfs-and-memory |
| `Expected bytes, got a 'ChunkedArray' object`, **intermittently** | Multi-chunk Arrow array — `mapInArrow` + `combine_chunks()` | arrow-conversion-failures |
| Bool/int column rejected by Arrow | Coerce to real Python `bool`/`int` (`None if pd.isna(v) else …`) | arrow-conversion-failures |
| Nested map/array conversion keeps failing | Declare `StringType` + `json.dumps` at the producer instead | arrow-conversion-failures |
| `ModuleNotFoundError: No module named <pkg>` after a `mapInArrow` rewrite | First-party wheel import doesn't resolve on the executor | arrow-conversion-failures |
| `maxRecordsPerBatch` changed nothing | Stage is a scalar `@udf`, not an Arrow API | arrow-conversion-failures |
| Serving endpoint returns 429 / slow | Concurrency > endpoint's provisioned size; cap to it | model-serving-and-batching |
| "Request too large" from the endpoint | Byte-aware batching under the size budget; truncate oversized rows | model-serving-and-batching |
| Endpoint name not found, whole update fails | Endpoint resolved on the driver at module scope and doesn't exist | model-registration-and-endpoints |
| Registration churns a new version every deploy | Tag versions with a config signature and skip when it matches | model-registration-and-endpoints |
| Cold-start latency on the first micro-batch | `scale_to_zero_enabled=False` + a `min_provisioned_concurrency` floor | model-registration-and-endpoints |
| Embeddings all look plausible but scores are wrong | Chunk exceeds the model's context window — silent truncation | chunking-and-embedding-fit |
| Chunks cut mid-sentence | A bare-number regex ranked above `\n\n` in the separator ladder | chunking-and-embedding-fit |
| Many chunks at exactly `chunk_size` | `hard_cut_rate` high — the ladder found no separator | chunking-and-embedding-fit |
| Changing the chunker invalidates old comparisons | Stamp a chunker generation; key the `append_flow` on it | chunking-and-embedding-fit |
| Model swap needs full refresh | Key the `append_flow` **name** on the model → fresh checkpoint | stateful-streaming-and-flows |
| Stream fails on upstream Delta update/delete | `readStream.option("ignoreChanges"/"skipChangeCommits", "true")` | stateful-streaming-and-flows |
| One task does all the work (skew) | `repartition(key)` + `sortWithinPartitions`; or shard with `explode(sequence)` | joins-windows-performance |
| Python worker OOM in a `cogroup` | Shard the group key; the cogroup hands one worker a whole group | joins-windows-performance |
| Need per-group greedy/fuzzy logic | `repartition(key)+sortWithinPartitions+mapInPandas`, or `cogroup().applyInPandas` | joins-windows-performance |
| Pipeline too slow / uneven micro-batches | Tune `maxFilesPerTrigger` against upstream file count; work-queue + `coalesce(1)` | throughput-and-partitioning |
| An API/HTTP call aborts the run | Non-raising client returning `(envelope, payload)`; record the outcome per row | reliable-api-calls |
| Need per-row call outcome / provenance | Stamp the **request envelope** on every row (success and failure) | reliable-api-calls |
| Ingest PDFs/Office/HTML/images into Spark | `spark.read.format("binaryFile")`; or Auto Loader `cloudFiles` for incremental | file-and-document-ingestion |
| Files arriving over time, schema drifts | Auto Loader `schemaEvolutionMode="rescue"` + `trigger(availableNow=True)` | file-and-document-ingestion |

## Upstream documentation (sources)

- Apache Spark — PySpark API reference: <https://spark.apache.org/docs/latest/api/python/index.html>
- Apache Spark — Structured Streaming programming guide (`readStream`/triggers/checkpoints): <https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html>
- Apache Spark — pandas function APIs & Arrow (`mapInPandas`/`applyInPandas`/`maxRecordsPerBatch`): <https://spark.apache.org/docs/latest/api/python/user_guide/sql/arrow_pandas.html>
- Apache Arrow — Python `Table`/`RecordBatch` (`combine_chunks`): <https://arrow.apache.org/docs/python/api/table.html>
- MLflow — `pyfunc` models and model serving input validation: <https://mlflow.org/docs/latest/python_api/mlflow.pyfunc.html>
- For the SDP/Lakeflow pipeline docs (the `dp` API, bundles, AUTO CDC, LIVE schema), see
  [develop-sdp](../develop-sdp/SKILL.md) → *Upstream documentation*.

## When to use this skill

Editing PySpark transforms that use pandas/Arrow UDFs, stateful streaming, model serving, document
chunking, or non-trivial joins and windows — especially when debugging OOM, Arrow/schema errors,
serving limits, checkpoint behaviour, embedding quality or skew.

## Related skills

- [develop-sdp](../develop-sdp/SKILL.md) — the declarative pipeline layer these transforms live in:
  tables vs flows, expectations, the event log, refresh semantics.
- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — how the pipeline and its
  serving endpoints get deployed and parameterised per environment.
- [test-python](../test-python/SKILL.md) — testing a pipeline notebook's pure logic without Spark,
  and the local-SparkSession harness for the rest.
