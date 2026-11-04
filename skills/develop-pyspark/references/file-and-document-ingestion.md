# File & document ingestion into Spark

Patterns for getting **binary files / documents** (PDF, Office, HTML, images) into a DataFrame and
extracting text — distilled from a DLT document-ingestion framework. Complements the API-ingestion
patterns in reliable-api-calls.

## Read binary files with the `binaryFile` source

Spark reads whole files into rows without materialising them on the driver:

```python
df = (
    spark.read.format("binaryFile")
    .option("recursiveFileLookup", "true")  # descend into subfolders
    .option("pathGlobFilter", "*.pdf")  # filter by name/extension
    .load(path)
)
# columns: path (string), modificationTime (timestamp), length (long), content (binary)
```

Derive an `extension` from `path`, carry `length` for size guards, and pass `content` (the bytes)
into an extraction UDF. This is a **batch** source; for continuous arrival use Auto Loader (below).

Already have bytes in a table/DataFrame (e.g. HTML in a column)? Convert to the same shape rather
than re-reading files: `df.withColumn("content", F.encode(F.col("html"), "UTF-8"))` and reuse the
extraction transform.

## Auto Loader (`cloudFiles`) for incremental, schema-drifting file ingestion

For files landing over time, stream them with Auto Loader and a medallion staging layout — **each
stage gets its own `schemaLocation` and checkpoint**:

```python
(
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "avro")  # or json/csv/parquet/binaryFile
    .option("cloudFiles.schemaLocation", f"{ckpt}/schema")
    .option("cloudFiles.schemaEvolutionMode", "rescue")  # new/unexpected cols go to _rescued_data, no fail
    .load(bronze_path)
    .writeStream.option("checkpointLocation", f"{ckpt}/silver")
    .trigger(availableNow=True)  # drain all available, then stop (batch-like)
    .table("silver")
)
```

- `schemaEvolutionMode="rescue"` keeps the stream alive when columns change — unexpected data lands
  in `_rescued_data` instead of failing.
- `trigger(availableNow=True)` processes everything currently available then stops — scheduled
  batch semantics over a streaming source.
- Separate `schemaLocation`/`checkpointLocation` **per medallion stage**; sharing them corrupts
  progress tracking.
- **Gotcha from the source repo:** `maxFilesPerTrigger` belongs on the **read** stream, not the
  write — it throttles admission (see throughput-and-partitioning); placing it on the writer does
  nothing.

## Extraction UDF strategy — scalar vs pandas

- **Scalar `@udf(StringType())`** to route one document at a time (simple, per-row): fine for calling
  an external parser per file.
- **`@pandas_udf(BinaryType())`** for Arrow-batched enrichment over a Series of byte columns —
  cheaper serialization, but the per-document work is still Python per row.
- **Call a parser *service*, don't package every parser in the worker.** Sending bytes to a running
  Tika server (`parser.from_buffer(bytes, serverEndpoint, headers={"X-Tika-...": ...}, timeout=...)`)
  keeps OCR/format parsers off the executors. Match partition count to the server's capacity — too
  many partitions overwhelm a single parser server (observed), so cap partitions near its concurrency
  (see model-serving-and-batching for the same concurrency-matching rule).
- For big documents, **don't materialise the whole document in pandas per row** (char-level geometry,
  all tables) — it's unbounded memory; keep extraction streaming/bounded or push it to a service.

## External (non-Spark) file sources: enumerate on driver, download per-row

For a source Spark's filesystem reader can't see (SharePoint/Office365, an API file store):

1. **Enumerate on the driver** (e.g. `ClientContext.get_files(recursive=True)`), build a DataFrame of
   file *metadata* (path, size).
2. **Download bytes per-row in a UDF**, guarded by a **size threshold** before fetching.
3. Then feed the bytes into the same extraction transform.

This is driver-side listing + row-level remote fetch, **not** a native connector — it doesn't scale
to huge listings. Cautions carried over from the source implementation (treat as **don'ts**):

- **Don't** stuff error/oversize messages as UTF-8 bytes into the *same* content column — a failure
  becomes indistinguishable from a real document. Use a separate status/error field (the request
  envelope idea from reliable-api-calls applies here too).
- **Don't** perform *writes/uploads* (side effects) inside a Spark UDF — task retries repeat the side
  effect. Keep UDFs pure reads; do writes in a `foreach_batch`/driver step with idempotency.

## Architecture note (optional)

A clean shape: **source adapters** (`read_to_binary()` for files / tables / SharePoint) feeding one
**shared `transform()`**, with extension-keyed **ingestor/enricher** interfaces (ABCs with
`ingest_type(bytes, **kwargs)`). Good for many formats; just verify UDFs that close over config/
clients actually serialize to executors before relying on it.
