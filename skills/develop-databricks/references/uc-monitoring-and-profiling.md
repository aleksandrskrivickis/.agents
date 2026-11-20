# Lakehouse Monitoring: profiling the tables a pipeline publishes

> **Source.** `[docs]` — Databricks Lakehouse Monitoring / data profiling documentation, checked
> against a design question about applying it to declarative-pipeline outputs. `[deduced]` marks an
> inference; `[?]` a claim worth verifying for your region and runtime.

Lakehouse Monitoring — surfaced in current docs as **data profiling** — watches a published table's
distributions over time and raises drift. It is the longitudinal half of data quality, and the
boundary against the pipeline's own mechanisms is the thing worth internalising:

| | Expectations + event log | Lakehouse Monitoring |
|---|---|---|
| **When** | During the update, per row | After materialisation, on a schedule |
| **Scope** | One flow's input | The published table as it now stands |
| **Question** | "Should this row be written, and did anything violate a rule this run?" | "Has the shape of this data changed since last month?" |
| **Attaches to** | The flow definition | The **table**, never the pipeline |
| **Output** | `data_quality` counters in `flow_progress` | Metric tables plus a generated dashboard |

Running both is the normal arrangement: expectations as the gate inside the pipeline, profiling as
the watch on what came out. Neither substitutes for the other — an expectation cannot see a gradual
distribution shift, and a profile cannot stop a bad row being written.

## It applies to pipeline outputs, because they are ordinary UC tables

A streaming table is a Unity Catalog managed table and a materialized view is a precomputed Delta
table, so both are inside the supported set: managed tables, external tables, views, materialized
views and streaming tables. The only hard requirement is Delta in a Unity Catalog-enabled
workspace. `[docs]`

The consequence for how you wire it: **you attach a profile to the published target after the
pipeline has materialised it.** There is no pipeline-side declaration, nothing in the `pipelines:`
resource block, and no ordering relationship the bundle can express — which puts it in the same
category as the Lakebase Data API in [dab-lakebase.md](./dab-lakebase.md): a real part of the
system that the declarative surface does not reach, so it needs a scripted step with an owner.

## The five constraints that decide whether you can use it

- **Materialized-view profiles do not support incremental processing.** Every run reprofiles the
  whole table rather than the delta. On a large gold-layer MV that is a recurring cost with no
  natural ceiling — price it before scheduling it. `[docs]`
- **Snapshot profiles cap at 4 TB.** Above that you are pushed to time-series profiles, which
  compute over the **last 30 days by default** — a different question than "all history", and one
  that quietly changes what your dashboard means.
- **It runs on serverless and is not available in every region.** Check your region against the
  AI/ML feature-availability table before promising it to anyone. `[?]`
- **Permissions are `MANAGE` on the catalog/schema/table *plus* `SELECT`.** This is the one that
  bites in practice: a pipeline commonly writes into a schema the engineer does not own, so the
  person who wants the profile cannot create it. Sort the grant out when you provision the schema
  — see [uc-catalog-administration.md](./uc-catalog-administration.md).
- **Profiles are per table.** There is no "profile this pipeline's outputs" operation, so a
  medallion stack means deciding per layer. Profiling every bronze streaming table is usually
  waste; the useful placement is the gold tables something downstream actually consumes, plus any
  bronze table whose *source* you do not control.

## Choosing a layer

The question to answer before creating anything is which failure you are trying to catch, because
it picks the layer for you:

- **A source changed shape without telling you** — a vendor added a column, started sending nulls,
  changed a code list. Profile the **bronze** table closest to ingestion, and accept the cost.
- **A transform degraded gradually** — a parser handling fewer cases, embeddings drifting after a
  model swap. Profile the **gold** output, where the effect is visible and the volume is lower.
- **A consumer is complaining and nobody can say whether the data moved** — profile what the
  consumer reads, which is the only table whose history settles the argument.

If the answer is "general data-quality dashboards across the whole stack", profile gold only and
rely on the event log for the rest. Expectation counters are already free per flow; a profile is
not.

## Sources

- Databricks — Lakehouse Monitoring / data profiling: <https://learn.microsoft.com/en-us/azure/databricks/lakehouse-monitoring/>

## Related

- [sdp-expectations-policy.md](./sdp-expectations-policy.md) — the in-flight gate, and why a bare
  `expect_all` cannot stop anything.
- [sdp-event-log-and-observability.md](./sdp-event-log-and-observability.md) — per-run quality
  metrics, which answer a different question than drift.
- [uc-catalog-administration.md](./uc-catalog-administration.md) — getting the `MANAGE` grant in
  place when the pipeline writes into a schema you do not own.
