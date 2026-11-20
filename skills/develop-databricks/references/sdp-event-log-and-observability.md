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
[sdp-expectations-policy.md](./sdp-expectations-policy.md).

> **`details` is a VARIANT/JSON column.** Struct fields use a dot (`origin.update_id`); paths inside
> `details` use a colon (`details:flow_progress.status`). Mixing the two is the most common reason a
> first event-log query returns nulls.

> **`timestamp` is stored UTC.** Every run you triage against wall-clock time is silently off by
> your offset, and in a DST-observing zone it is off by a different amount depending on the month.
> Wrap it per query — `from_utc_timestamp(timestamp, 'Europe/London')`, a **named zone** rather than
> a fixed `+01:00`, so the GMT/BST switch handles itself — or set
> `spark.conf.set("spark.sql.session.timeZone", "Europe/London")` once at the top of the notebook so
> every timestamp renders locally. Per-query conversion makes a shared query self-contained; the
> session setting is less error-prone if you debug the event log often. `[repo]`

### Event types beyond `flow_progress`

| `event_type` | Granularity | Notes |
|---|---|---|
| `flow_progress` | Flow lifecycle transitions | Carries `FlowMetrics` and `DataQualityMetrics`; the workhorse |
| `stream_progress` | **Once per microbatch**, per streaming flow | The Structured Streaming progress object, shaped like `StreamingQueryListener` output. A couple of fields (`numInputRows`) are dropped relative to vanilla Structured Streaming. Join back via `origin.batch_id`, which is unique within a flow |
| `flow_definition` | Per flow, per update | `input_datasets` / `output_dataset` — the only reliable source of **dependency** order |
| `update_progress` | Per update | `state`, which separates `FAILED` from `CANCELED` |
| `cluster_resources`, `autoscale` | Per cluster event | **Classic compute only** — never populated on serverless `[docs]` |

> **`level = 'METRICS'` events are stored in the table but never shown in the pipelines UI.** This
> is the entire explanation for "the UI shows nothing" — high-volume per-batch events land at that
> level by design. If you want microbatch detail you must query the table; there is no UI path to
> it. `[docs]`

### Ordering events: `sequence` is the right key, but not the obvious way

`timestamp` ties. Several events routinely land in the same millisecond, so a `ORDER BY timestamp`
on a `QUEUED` batch returns an arbitrary order. The `sequence` struct exists for this — and it holds
**two unrelated numbering spaces**:

- `sequence.control_plane_seq_no` — events emitted by the control plane.
- `sequence.data_plane_id.{instance, seq_no}` — events emitted by the data plane, which is where
  `flow_progress` lives.

They are not comparable to each other, and `data_plane_id.seq_no` is monotonic **only within one
`instance`**. So confirm the instance is uniform before trusting a bare sort:

```sql
SELECT sequence.data_plane_id.instance, COUNT(*)
FROM event_log WHERE event_type = 'flow_progress' GROUP BY 1;
```

One row back → `ORDER BY sequence.data_plane_id.seq_no DESC` is a correct total order, and strictly
better than `timestamp` because it breaks millisecond ties in true emission order. More than one row
(restarts, or a query widened past `flow_progress`) → fall back to
`ORDER BY timestamp DESC, sequence.data_plane_id.seq_no DESC`.

> **It orders events, not tables.** Independent flows interleave their status transitions, so the
> sequence faithfully reconstructs *what happened when* and is **not** a topological sort of the
> graph. For dependency order use `flow_definition`'s `input_datasets`/`output_dataset`. `[docs]`

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

One more reason the published form wins: **the TVF is batch-only — you cannot `readStream` from
it.** To build a live monitor you need a Unity Catalog view over the event log and you stream the
view. Two things then break that worked in batch, and both are full-relation operations streaming
forbids: the global `ORDER BY`, and the `ORDER BY … LIMIT 1` subquery that picked the latest
`update_id`. The streaming-friendly substitute is to move `update_id` into the grouping key and
aggregate over a watermarked tumbling `window(timestamp, '1 hour')`, which keeps runs separated
without needing to know which is newest. `[docs]`

## Aggregation rules queries must respect

Getting these wrong **silently over-counts failures**, which is worse than an error:

1. **`num_output_rows` is per micro-batch** → `SUM` it over an update.
2. **Data-quality counters are cumulative for the flow** → take `MAX` per flow, *then* `SUM` across
   flows. Summing them directly multiplies them.
3. **Expectation metrics may arrive on `RUNNING` events**, not only on `COMPLETED`. Don't filter to
   `COMPLETED` and assume you have the totals.
4. **Exclude the sentinel** `origin.flow_name = 'pipelines.flowTimeMetrics.missingFlowName'`.
5. **`MAX` is only safe because the run is triggered.** The counter is cumulative within a triggered
   run, so the peak equals the final total. For a **continuous** flow there is no final total — use
   `MAX_BY(num_output_rows, timestamp)` to get the last reported value instead. `[deduced]`
6. **"Latest update" is not "latest successful update".** Pinning to the `update_id` of the most
   recent event shows that run's truth including its `SKIPPED` and `EXCLUDED` flows, which is
   usually what you want for *how did the last run go* — but it is not a health summary. Say which
   one you meant in the query name.

Flow names arrive fully qualified (`catalog.schema.table`). `substring_index(origin.flow_name, '.', -1)`
shortens them and is safe on unqualified names too — with `-1` it returns the whole string when
there is no dot, rather than failing.

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

## Event hooks are reactive, and cannot carry your own events

Custom monitoring belongs in event hooks rather than dataset definitions — but "belongs in" is not
"is possible in", and the limits decide designs:

- **There is no API to write a custom event into the event log.** `on_event_hook` fires when events
  the platform *already* persists are written; you can inspect, forward or alert on them, never
  inject a new event type or add fields to an existing one. `[docs]`
- Hooks fire only for events whose `maturity_level` is `STABLE`.
- They run **asynchronously from the update but serially with each other** — one slow hook blocks
  the rest — and **Databricks does not guarantee every hook fires before compute is torn down**.
  That last point disqualifies hooks as a durable audit mechanism: the hook you most want to fire is
  the one at the end of the run.

So hooks are the right place for *egress* (Slack, PagerDuty, a webhook, appending to another Delta
table for external monitoring) and the wrong place for anything that must not be lost.

### Always-true expectations as named counters

Because every expectation reports itself by name into
`details:flow_progress.data_quality.expectations` with `passed_records`/`failed_records`, an
expectation that cannot fail is a queryable per-flow counter:

```python
@dp.expect("processed_iso_de", "1=1")          # not a quality rule — a metric
```

This is the closest thing to a custom metric that flows naturally into `flow_progress`, and it is a
legitimate technique. Note the overlap with
[sdp-expectations-policy.md](./sdp-expectations-policy.md) → anti-pattern 4, *an expectation that
can only ever pass*: that is an anti-pattern when it was **reached by accident** (a self-referential
check someone believed was testing something) and a deliberate instrument when it was **chosen as a
counter**. The difference is entirely in whether anyone decided. Name it so the next reader can
tell — a `processed_`/`count_` prefix and a comment saying it is a metric — because a reviewer
applying the anti-pattern rule mechanically will otherwise delete it.

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

- [sdp-expectations-policy.md](./sdp-expectations-policy.md) — what lands in `data_quality` and why the
  policy decides whether it means anything.
- [sdp-operations-and-refresh.md](./sdp-operations-and-refresh.md) — using the event log to triage a run.
- [dab-resources-and-deploy.md](./dab-resources-and-deploy.md) — the `event_log:` block in the pipeline
  resource.
