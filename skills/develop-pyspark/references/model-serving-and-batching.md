# Calling a model-serving endpoint from Spark

> **Source.** `[repo]` — distilled from a production Databricks Spark Declarative Pipeline
> and its accumulated fixes. `[docs]` marks a vendor-documented constraint; `[deduced]` an
> inference.

Pattern for embedding/scoring slices through a Databricks model-serving endpoint inside a
`mapInPandas` UDF — tuned for throughput without tripping the endpoint's concurrency and
request-size limits.

## Match concurrency to the endpoint, set it in three places

A `workload_size: Small` endpoint serves ~**0–4** concurrent callers; beyond that requests **queue
or 429**, they don't go faster. Pick `CONCURRENCY = 4` (or the endpoint's provisioned value) and
apply it to shuffle partitions, default parallelism, **and** an explicit repartition:

```python
CONCURRENCY = 4
spark_conf = {
    "spark.sql.shuffle.partitions": str(CONCURRENCY),
    "spark.default.parallelism": str(CONCURRENCY),
    "spark.sql.execution.arrow.maxRecordsPerBatch": str(BATCH_SIZE * 4),
}
...
stream.repartition(CONCURRENCY).mapInPandas(embed_partition, SCHEMA)
```

**Only the `repartition` guarantees the fan-out** — file bin-packing can otherwise pack everything
into one task and serialise the calls. Admit `CONCURRENCY * 2` files per trigger so a slow file can
overlap a fast one.

## Byte-aware batching under the request-size limit

> **A scale-to-zero endpoint enforces a tighter cap than a provisioned one.** The same batch size
> that works against a warm provisioned endpoint fails against scale-to-zero, and the message says
> so explicitly:
>
> ```
> 400 Client Error: Bad Request … {"error_code":"Bad request.","message":"Max request size
> exceeded for a scale to zero endpoint. Please reduce the request size or use an endpoint
> without scale to zero."}
> ```
>
> So `scale_to_zero_enabled` is a **payload** decision as well as the latency decision described in
> [model-registration-and-endpoints.md](./model-registration-and-endpoints.md) — size the budget
> below for the endpoint you are actually calling, and re-test after flipping that flag.
>
> Two things make this expensive to diagnose. The cause sits four layers down —
> `StreamingQueryException` → `PythonException` → `HTTPError`, after four task retries — so the
> stack trace does not read as a sizing problem at all. And the endpoint **also rejects requests
> while it is waking up**, which looks identical. That makes a plain retry of the same batch the
> wrong reflex: retry by **splitting**, falling back to sending items individually, so a genuine
> size rejection converges instead of looping. `[repo]`

The endpoint caps request size (here a conservative **8 MB** budget under a 32 MB hard limit). The
limit is on **encoded bytes**, which multi-byte characters inflate — count `len(text.encode())`, not
`len(text)`. Grow a batch until it reaches the row cap **or** the next text would exceed the byte
budget:

```python
def iter_batch_bounds(texts):
    sizes = [len(t.encode("utf-8")) for t in texts]
    start = 0
    while start < len(texts):
        end, total = start + 1, sizes[start]  # a batch always carries >= 1 row
        while end < len(texts) and end - start < BATCH_SIZE and total + sizes[end] <= MAX_REQUEST_BYTES:
            total += sizes[end]
            end += 1
        yield start, end
        start = end
```

Also **truncate a single oversized text** so one row can't blow the budget:

```python
texts = [t.encode("utf-8")[:MAX_REQUEST_BYTES].decode("utf-8", errors="ignore") for t in col.fillna("")]
```

Keep the batch bounds **contiguous and row-aligned** so you can write each result back to
`pdf.iloc[start:end]`.

## Resolve the model version on the driver

So every row is attributable to one model revision (and the client isn't rebuilt per row for
metadata):

```python
cfg = mlflow.deployments.get_deploy_client("databricks").get_endpoint(MODEL_NAME)["config"]
MODEL_VERSION = cfg["served_entities"][0]["entity_version"]
```

## Call, retry, and never raise

Instantiate the deploy client **once per partition**; wrap `predict` in tenacity; on failure record
a failure envelope for the batch instead of aborting the pipeline:

```python
def embed_partition(iterator):
    client = mlflow.deployments.get_deploy_client("databricks")
    retrying = Retrying(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2), reraise=True)
    for pdf in iterator:
        texts = clamp(pdf["slice_content"].fillna("").tolist())
        for start, end in iter_batch_bounds(texts):
            try:
                resp = retrying(client.predict, endpoint=MODEL_NAME, inputs={"input": texts[start:end]})
                embeddings = [d["embedding"] for d in resp["data"]]
                outcome = envelope(success=True, status_code=200, message="OK")
            except requests.RequestException as error:
                embeddings = [None] * (end - start)
                outcome = envelope(source=error)  # recorded, not raised
            outcome.update(
                request_retry_count=retrying.statistics["attempt_number"] - 1,
                request_offset_start=start,
                request_offset_end=end,
            )
            chunk = pdf.iloc[start:end].copy()
            chunk["slice_embeddings"] = embeddings
            yield chunk.assign(**outcome)
```

Surface serving failures as data-quality expectations on the output table (`request_status_code IS
DISTINCT FROM 429`, `... = 200`, `request_retry_count = 0`) rather than exceptions — the run
completes and the failures are queryable.

## Pre-filter to only what must be scored

Embedding/serving is the expensive step. Narrow the input first (e.g. only documents in a
multi-version lineage, via a `groupBy(...).agg(count_distinct(...))` + `left_semi` join) so you don't
pay to embed rows that can never be used.
