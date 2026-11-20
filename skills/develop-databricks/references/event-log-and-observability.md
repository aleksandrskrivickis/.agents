# The event log, and where pipeline output actually goes

> **Source.** `[docs]` for the event-log schema and the serverless limitations (Databricks Lakeflow
> documentation); `[repo]` for the patterns and defects observed in a production pipeline that
> audited its own observability. `[deduced]` marks an inference.

Databricks states the position plainly: **the pipeline event log is the primary observability
primitive in pipelines.** It is the ground truth under both the Jobs & Pipelines list and the
monitoring UI. Most pipelines reinvent a fraction of it badly before discovering this.

## What the event log already carries

| Concern | Columns / paths |
|---|---|
| **Identity** | `origin.update_id` (equivalent to run id), `pipeline_id`, `pipeline_name`, `flow_name`, `flow_id` (stable across incremental refreshes), `batch_id`, `request_id` |
| **Execution** | `event_type = 'flow_progress'` → `details:flow_progress.status` (`QUEUED`, `STARTING`, `RUNNING`, `COMPLETED`, `FAILED`, `SKIPPED`, `STOPPED`, `IDLE`, `EXCLUDED`) and `details:flow_progress.metrics.{num_output_rows, num_upserted_rows, num_deleted_rows, num_output_bytes, executor_time_ms}` |
| **Update lifecycle** | `event_type = 'update_progress'` → `state`, which is what separates `FAILED` from `CANCELED` |
| **Quality** | `details:flow_progress.data_quality.expectations` — an array of `{name, dataset, passed_records, failed_records}` — plus `data_quality.dropped_records` and `warned_records` |
| **Lineage** | `flow_definition.{input_datasets, output_dataset, explain_text}` |
| **Audit** | `user_action` (who started the update), `level` (`INFO`/`WARN`/`ERROR`/`METRICS`), and `error` — which carries the **full stack trace the UI truncates** |

Every `expect_all` constraint you declare reports itself here **by name**. Metrics are emitted
regardless of policy, so warn-only expectations still produce full pass/fail counts — see
[expectations-policy.md](./expectations-policy.md).

> **`details` is a VARIANT/JSON column.** Struct fields use a dot (`origin.update_id`); paths inside
> `details` use a colon (`details:flow_progress.status`). Mixing the two is the most common reason a
> first event-log query returns nulls.

## Publish it as a table; don't rely on the TVF

```yaml
# resources/pipelines.yml
event_log:
    catalog: ${var.catalog}
    schema: ${var.schema}
    name: event_log
```

The alternative is the `event_log(<pipeline_id>)` table-valued function, which is materially weaker:
it can be called **only by the owner** of a streaming table or materialized view, a view over it
**cannot be shared** with other users, and it **cannot span pipelines**. The published form is an
ordinary Unity Catalog table you can grant, join and build a dashboard on. `[docs]`

Two constraints come attached:

- **Never delete the event log, or the catalog/schema it is published to.** Deleting it may cause
  future pipeline updates to fail. This is a real hazard: the source project had a maintenance
  notebook running `DROP SCHEMA … CASCADE` against the schema holding its own published event log.
  Check your teardown scripts.
- **The event-log location doubles as the schema location for any Auto Loader queries in the
  pipeline.** And Databricks recommends creating a **view** over the table before granting on it,
  because sharing the table directly can expose schema metadata under some compute settings.

Retention is asymmetric in your favour: the UI and Pipelines API retain 60 days of updates, but
older updates **remain in the event-log table**, which has no stated expiry.

## Aggregation rules queries must respect

Getting these wrong **silently over-counts failures**, which is worse than an error:

1. **`num_output_rows` is per micro-batch** → `SUM` it over an update.
2. **Data-quality counters are cumulative for the flow** → take `MAX` per flow, *then* `SUM` across
   flows. Summing them directly multiplies them.
3. **Expectation metrics may arrive on `RUNNING` events**, not only on `COMPLETED`. Don't filter to
   `COMPLETED` and assume you have the totals.
4. **Exclude the sentinel** `origin.flow_name = 'pipelines.flowTimeMetrics.missingFlowName'`.

```sql
WITH q AS (
  SELECT origin.update_id                     AS update_id,
         origin.flow_name                     AS flow_name,
         MAX(details:flow_progress.data_quality.dropped_records::BIGINT) AS dropped
  FROM   event_log
  WHERE  event_type = 'flow_progress'
    AND  origin.flow_name <> 'pipelines.flowTimeMetrics.missingFlowName'
  GROUP BY 1, 2                               -- MAX per flow first
)
SELECT update_id, SUM(dropped) AS dropped FROM q GROUP BY 1   -- then SUM across flows
```

## System tables worth a dashboard

| Table | Use | Caveat |
|---|---|---|
| `system.lakeflow.pipelines` | Pipeline inventory | Stable |
| `system.lakeflow.pipeline_update_timeline` | Update history; `result_state IS NULL` ⇒ still running | Stable |
| `system.billing.usage` | Cost, attributed via `usage_metadata.dlt_pipeline_id` | Stable |
| `system.lakeflow_pipeline_events_preview.pipeline_events` | Region-wide copy of the event log | **Beta** — at GA it moves to `system.lakeflow.pipeline_events` and the schema may change. Do not build alerts on it yet. |

## Where `print()` and `logging` output actually goes

> **On serverless compute, mostly nowhere.** This surprises everyone once.

On **classic** compute: `print` and `logging` from notebooks, jobs and libraries go to the **Spark
driver logs**, readable from the Driver logs tab (stdout / stderr / Log4j). Worker output is not
there — it is reached through the Spark UI or configured log delivery.

On **serverless** compute, none of that applies: the Spark UI is **not available**, Spark logs are
**not available** (only client-side application logs), and a serverless pipeline **rejects a
`clusters` block outright**, so `cluster_log_conf` delivery to a volume is not configurable either.
`[docs]`

The practical consequence, by where your code runs:

| Code location | Output |
|---|---|
| Driver (module scope, a `@dp.table` body) | Client-side application logs — the most reachable thing available, still not durable or queryable |
| Executor (inside `mapInPandas`, `applyInPandas`, a UDF) | **No documented route to it at all** on serverless |

And even on classic compute, stdout is unstructured text, cannot be joined to data, is tied to
compute lifetime rather than to the data it describes, and scales with partition count — a single
`logger.info` inside a per-partition loop fires once per key per partition.

**Treat stdout as ephemeral developer convenience.** It is not the observability mechanism.

## Row provenance belongs in the table; run execution belongs in the event log

The boundary that resolves most "should we add a log table?" arguments:

| Scope | Belongs in | Because |
|---|---|---|
| **Row-scoped provenance** — was this row trustworthy, and if not why | **A column on the table** | Keyed to a business row, must outlive the run, read by analysts and downstream stages at query time |
| **Run-scoped execution** — flow status, row counts, failures, expectation counts | **The event log** | The platform already records it, keyed to `update_id`, and you don't have to |

The **request envelope** pattern — stamping `request_success`, `request_status_code`,
`request_status_message`, `request_retry_count`, `request_date_time_acquired` on every ingested row —
is the row-scoped half done right. See
[reliable-api-calls](../../develop-pyspark/references/reliable-api-calls.md). On serverless it is not
merely defensible: **it is the only durable per-call record the pipeline can produce.** And it feeds
the event log rather than competing with it, because the `request_succeeded` expectation turns a
failed-call row into an event-log metric.

Two defects to avoid when you build an envelope, both observed:

- `datetime.now().isoformat()` gives **naive local time stored as a string**. Use UTC-aware and type
  it `TIMESTAMP`.
- Carrying a pipeline version but **no update identity** means a Delta row cannot be joined to the
  event-log rows of the update that produced it. Stamp something that joins. `[repo]`

### Don't add a `pipeline_logs` table

A purpose-built Delta table is right when the records are **domain events with independent business
value** — a decision taken, a classification made, an external response retained for audit. Those
are data.

A hand-rolled log table that duplicates the event log is a mistake, for concrete reasons:

- It restates `flow_progress` metrics the platform already emits, and then drifts from them.
- Writing it from inside a flow **ties log durability to that flow's success** — the case where logs
  matter most is the case where they are not written.
- Writing it from an executor needs either a collect to the driver or a second write path per
  partition, adding failure modes to the ingest path.
- It has no `update_id` unless you invent one, so it cannot be joined to the platform's own record.
- It is one more object to grant, retain, vacuum, back up, and forget about when a schema is dropped.

## Let Spark errors surface

The production-readiness guidance is explicit: do not wrap transformations in broad `try`/`except`
blocks that catch `AnalysisException` — **catching those exceptions masks real errors from the event
log.** `[docs]`

An API client that catches HTTP/transport errors at the boundary and records them as columns is not
what that warns about. But where you *do* need to catch a Spark exception, keep it narrow and
re-raise everything else:

```python
try:
    offsets = spark.read.table(OFFSETS_TABLE)
except AnalysisException as error:
    if "TABLE_OR_VIEW_NOT_FOUND" not in str(error):
        raise                       # never broaden this
    offsets = spark.createDataFrame([], OFFSETS_SCHEMA)
```

That narrowness is the property to preserve.

## Flattening the event log for downstream use

The raw `event_log` is a securable whose kind makes it an unsupported source for some consumers
(e.g. a Lakebase synced table). Flattening it into a streaming table of scalar columns solves that
and gives you a cheap, incremental observability table — including the trick for forcing it to run
*after* the pipeline it observes. The recipe is in
[stateful-streaming-and-flows](../../develop-pyspark/references/stateful-streaming-and-flows.md).

## Related

- [expectations-policy.md](./expectations-policy.md) — what lands in `data_quality` and why the
  policy decides whether it means anything.
- [operations-and-refresh.md](./operations-and-refresh.md) — using the event log to triage a run.
- [bundles-editor-publishing.md](./bundles-editor-publishing.md) — the `event_log:` block in the
  pipeline resource.
