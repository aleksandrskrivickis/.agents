# Reliable API calls inside a Spark pipeline

> **Source.** `[repo]` — distilled from a production Databricks Spark Declarative Pipeline
> and its accumulated fixes. `[docs]` marks a vendor-documented constraint; `[deduced]` an
> inference.

How to call an external HTTP API from a distributed Spark job so that a single failing call **never
aborts the run**, every outcome is **recorded and queryable**, and connections survive the executor
environment. Modeled on a production vendor-API client and its model-serving sibling.

## The non-raising contract

Every client call returns `(envelope, payload)` and **never raises** on an HTTP or transport error.
On failure `payload is None` and the envelope records why. One bad call out of millions must not kill
the pipeline.

```python
envelope, payload = client.get("/contents", params=...)
if payload is None:
    ...  # record the failure envelope on the row; carry on
```

## The request envelope (reusable template)

Stamp this object on **every produced row**, success or failure. It carries three things: the
**outcome**, the **provenance**, and the **position** (so you can resume). This is the part worth
copying into any future API-ingestion pipeline:

| Field | Type | Purpose |
|---|---|---|
| `request_api_version` | string | Which API/model version produced the row — provenance, so a row is attributable to one revision (e.g. `"v2"`, or `"<model>-<ver>-batch-<n>"`). |
| `request_success` | boolean | Did the call succeed. The primary filter for downstream logic and expectations. |
| `request_status_code` | int | HTTP status, **or a synthetic code** (below) for conditions the server doesn't signal. |
| `request_status_message` | string | Reason phrase or the transport exception text — for debugging. |
| `request_retry_count` | int | How many retries were spent (0 = first attempt). A rising count flags a flaky source. |
| `request_date_time_acquired` | string (ISO) | When the row was fetched — freshness/audit. |
| `request_offset_start` | int | Start of the window/page this call covered. |
| `request_offset_end` | int | End of the window. On **success** the actual span returned; on **failure** the *intended* window, so a retry knows what to re-fetch. |

Build it from either a completed response **or** a transport exception, so success and failure share
one shape:

```python
def envelope(*, source=None, success=False, status_code=None, message=None,
             retries=0, offset_start=None, offset_end=None):
    if isinstance(source, Response):
        success, status_code, message = source.ok, source.status_code, source.reason
    elif isinstance(source, RequestException):
        success, message = False, str(source)
        status_code = source.response.status_code if source.response is not None else READ_TIMEOUT
    return {
        "request_api_version": API_VERSION,
        "request_success": success,
        "request_status_code": status_code,
        "request_status_message": message,
        "request_retry_count": retries,
        "request_date_time_acquired": datetime.now().isoformat(),
        "request_offset_start": offset_start,
        "request_offset_end": offset_end,
    }
```

Attach it with pandas `assign(**envelope)` (or `dict.update`) on the batch before yielding.

## Synthetic status codes

Give conditions the server can't report their own code in the same `request_status_code` vocabulary,
so one set of rules covers every failure mode:

- `513` — response body exceeded a byte cap (e.g. 12 MB). Don't load a giant body into executor
  memory; record `513` and move on.
- `598` — read timeout (no response within the read deadline).

## Retry + auth, tuned for executors

- **Retry** (tenacity, exponential backoff) on transient statuses `{403, 429, 500, 502, 503, 504}`
  and transport exceptions; cap attempts (e.g. 5) and record `request_retry_count`.
- **Auth 401** is handled separately: refresh the token **once**, then retry — not a backoff loop.
  Guard the refresh with a lock/event so concurrent workers in the same executor refresh **once**,
  not N times, and fall back to a full re-login if the refresh itself is rejected.

## Connections in the executor environment

- **TCP keep-alive adapter** (`SO_KEEPALIVE` + `TCP_KEEPIDLE/INTVL/CNT`): idle pooled connections
  behind NAT/load-balancer idle timeouts get dropped silently; keep-alive keeps them warm and detects
  dead peers *before* reuse instead of hanging until the read timeout.
- **Bounded, blocking pool** (`pool_block=True`, size = `max_connections`): a checkout **waits** for
  a free connection instead of urllib3 opening throwaway extras, so live connections stay ≤ the cap
  — important when the API rate-limits by connection or token.
- **Optional throttle** (`min_request_interval`) to space request starts across threads.

## Instantiate once per partition

The client (session, pool, token) is expensive and not picklable — build it **inside** the
`mapInPandas` generator, reuse across batches, `close()` in `finally`. Read credentials on the
driver and close over them (see pandas-udfs-and-memory).

## Surface reliability as data-quality, not exceptions

Because calls never raise, make the outcome **queryable** with expectations on the output table —
one rule per status code plus the success/retry checks (guard column-presence rules so failed rows
aren't double-flagged):

```python
expect_all={
    "empty_content": "request_success IS NOT TRUE OR (content IS NOT NULL AND length(trim(content)) > 0)",
    "request_succeeded": "request_success = true",
    "request_retries": "request_retry_count = 0",
    "request_rate_limited": "request_status_code IS DISTINCT FROM 429",
    "request_oversized": "request_status_code IS DISTINCT FROM 513",
    "request_read_timeout": "request_status_code IS DISTINCT FROM 598",
    # ... one `IS DISTINCT FROM <code>` per status you care about (401/403/404/500/502/503/504)
}
```

The run completes; the failures show up as expectation metrics in the event log and as rows you can
query by `request_status_code`.

## Pagination

- **Serial** `paginate(path, params)` → yields `(envelope, items)` per page; a **failed page yields a
  sentinel** (e.g. `[{}]`) so the caller still records the gap.
- **Concurrent** `paginate_concurrent(...)` → fetch page 1 serially to learn `total_count`, then fan
  fixed windows out over a bounded thread pool (`workers`, bounded in-flight futures). Cap `workers`
  to the API's concurrency / single-active-token limit.

## Incremental resume (and a known gap)

Persist `max(request_offset_end)` of **successful** rows per source into an `offsets` table, and
resume each run from there (see throughput-and-partitioning's work-queue). Known gap: a failed
*middle* window under concurrent pagination is skipped by the `max(success)` watermark and not
auto-retried — only matters if you need strict completeness; re-fetch explicitly if so.

Tolerate the offsets table not existing yet on the first run (`AnalysisException`
`TABLE_OR_VIEW_NOT_FOUND` → start at offset 0).
