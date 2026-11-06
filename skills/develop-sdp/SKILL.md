---
name: develop-sdp
description: 'Expert on Spark Declarative Pipelines (SDP) — the open-source `pyspark.pipelines` (dp) framework — and the Databricks/Lakeflow closed-source extensions layered on it. Use when writing pipeline source files, working with @dp.table / create_streaming_table / append_flow / expectations / foreach_batch_sink, choosing streaming table vs materialized view, AUTO CDC vs APPLY CHANGES, publishing modes / the LIVE schema, choosing an expectations policy (expect_all vs _or_drop vs _or_fail), reading the pipeline event log, triaging a bad run, full refresh vs selective full refresh vs a new flow generation, pipeline retry and cluster-shutdown settings, ignoreChanges vs skipChangeCommits, or the Lakeflow Pipelines Editor. Flags which features are Apache SDP vs Databricks-only, and current-vs-legacy terminology (DLT -> SDP, DAB -> Declarative Automation Bundles).'
---

# Spark Declarative Pipelines (SDP)

> **What this is.** **SDP** is the open-source declarative pipeline framework in Apache Spark
> (`pyspark.pipelines`, since Spark 4.1). **Databricks Lakeflow pipelines** is a proprietary superset
> that runs SDP on the Databricks Runtime and adds closed-source features — expectations, AUTO CDC,
> extra sinks, the event log, bundles, the Pipelines Editor.
>
> Most real pipelines are, like the production one this skill is distilled from, the open-source core
> **plus** several Databricks-only features. The two are flagged throughout, because the distinction
> decides whether your code runs anywhere else.

## Detailed references

- [references/sdp-python-api.md](./references/sdp-python-api.md) — the `pyspark.pipelines` (`dp`) decorators and functions, the DLT→SDP mapping, and the coding rules the framework enforces.
- [references/expectations-policy.md](./references/expectations-policy.md) — `expect_all` vs `_or_drop` vs `_or_fail` and what each decides, the presence/value two-block structure, and the four anti-patterns an audit found in 21 real expectation blocks.
- [references/event-log-and-observability.md](./references/event-log-and-observability.md) — the event log as the primary observability primitive: its schema, the aggregation rules that stop you over-counting failures, publishing vs the TVF, where `print()` actually goes on serverless, and the row-provenance vs run-execution boundary.
- [references/operations-and-refresh.md](./references/operations-and-refresh.md) — full refresh vs selective full refresh vs a new flow generation, why a full refresh is not always a mitigation, retry and cluster-shutdown settings, `ignoreChanges` vs `skipChangeCommits`, table properties and layout, and a four-check triage playbook.
- [references/auto-cdc.md](./references/auto-cdc.md) — AUTO CDC / AUTO CDC FROM SNAPSHOT (Databricks-only; replaces APPLY CHANGES).
- [references/bundles-editor-publishing.md](./references/bundles-editor-publishing.md) — bundles, the Lakeflow Pipelines Editor, publishing modes, and the `event_log:` resource block.

## The rules that prevent most pipeline failures

1. **A dataset function must return a DataFrame and contain only defining logic.** SDP evaluates it
   multiple times during planning. **Never** call `collect()`, `count()`, `toPandas()`, `save()`,
   `saveAsTable()`, `start()`, `toTable()` or `pivot()` inside dataset code.
2. **Streaming table ⇔ streaming read.** A streaming table needs `spark.readStream`; a materialized
   view needs a batch read. Mismatching them is the most common first error.
3. **`spark.conf.get` and `dbutils` work only on the driver.** Read config and secrets at **module
   scope** and close over them in UDFs. Pass secret scope/key *names* as configuration and resolve
   them in the source file — don't rely on `{{secrets/…}}` substitution.
4. **Choose an expectations policy deliberately.** Bare `expect_all` is advisory: violating rows are
   written exactly like valid ones and no column carries the verdict. That is a defensible choice,
   but it is reached by default rather than decided, and it means no quality rule can stop anything.
5. **The event log is the observability mechanism, not your logs.** On serverless there is no Spark
   UI and no Spark logs, and executor `print`/`logger` output has **no documented route** anywhere.
   Row-scoped provenance goes in a column; run-scoped execution is already in the event log.
6. **Don't write a `pipeline_logs` table.** It duplicates `flow_progress`, then drifts from it; it
   ties log durability to the success of the flow that writes it; and it has no `update_id` to join
   on unless you invent one.
7. **A full refresh resets your position, not the world's history.** If the source only moves forward
   — a resume offset, a cursor-paginated API, an append-only feed — a full refresh re-reads the
   source *as it is today*. It cannot recover what the source no longer offers.
8. **Prefer a new flow generation to a truncating full refresh.** Each `append_flow` owns a
   checkpoint keyed by its **name**, so naming the flow after the thing that changed (the model, a
   config digest) appends a new generation beside the old rows — no truncation, prior results stay
   comparable.
9. **`ignoreChanges` against a full-recompute upstream re-emits everything, every run.** Use
   `skipChangeCommits` for an append-only logical source whose files get rewritten, and never paper
   over the duplication with an unwatermarked `dropDuplicates` — that hides the symptom and grows
   state without bound.
10. **Let Spark errors surface.** Broad `try`/`except` around transformations masks real errors from
    the event log. Where you must catch an `AnalysisException`, match the specific condition and
    re-raise everything else.
11. **Set retry behaviour in every target, not just `dev`.** If `pipelines.maxFlowRetryAttempts` and
    `pipelines.numUpdateRetryAttempts` are only set in development, nobody can state how many times a
    production flow retries before failing.

## Quick symptom → fix index

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| "Expected a streaming source" / "expected batch" | Streaming table with a batch read, or the reverse | sdp-python-api |
| UDF fails with no `spark` / `dbutils` | Config read on the executor — move it to module scope | sdp-python-api |
| Violating rows appear in the published table | Bare `expect_all` is advisory by design | expectations-policy |
| Quality metrics show ~100% violations | A presence rule copied downstream and applied to an optional column | expectations-policy |
| Violation count permanently inflated | A rule treats every retry as a failure | expectations-policy |
| An expectation can only ever pass | Self-referential check (hash vs recomputation of itself, same row) | expectations-policy |
| Event-log query over-counts failures | Data-quality counters are cumulative — `MAX` per flow, then `SUM` | event-log-and-observability |
| Event-log query returns nulls | `details` is a variant: `details:path`, while struct fields use `origin.field` | event-log-and-observability |
| `print()` output nowhere to be found | Serverless: no Spark UI, no Spark logs, no executor route | event-log-and-observability |
| Pipeline update fails after a schema cleanup | The published event log or its schema was dropped | event-log-and-observability |
| Need to refresh one table, UI only offers all | Selective full refresh via SDK/CLI — no UI click-path | operations-and-refresh |
| Full refresh didn't recover the missing data | The source no longer offers it; refresh resets your position only | operations-and-refresh |
| Changing a streaming source forces a full refresh | Checkpoint is bound to the source; expect duplicates on an unkeyed target | operations-and-refresh |
| Downstream table duplicates on every run | `ignoreChanges` against a full-recompute upstream | operations-and-refresh |
| Streaming dedup state grows without bound | `dropDuplicates` with no watermark | operations-and-refresh |
| Many small files / most rows in one partition | `partition_cols` on a mostly-null column, or partitioning while writing single-partition | operations-and-refresh |
| Nobody knows how many times prod retries | Retry settings only configured in `dev` | operations-and-refresh |
| Need CDC / SCD semantics | `dp.create_auto_cdc_flow` (Databricks-only) | auto-cdc |
| `LIVE.` prefix silently ignored | Default publishing mode — use unqualified names | bundles-editor-publishing |

## Apache SDP vs Databricks-only (closed-source)

What a plain `pip install pyspark[pipelines]` **cannot** run — it needs the Databricks Runtime:

| Feature | Apache SDP | Databricks/Lakeflow-only |
|---|---|---|
| `@dp.table`, `@dp.materialized_view`, `@dp.temporary_view` | ✅ | — |
| `dp.create_streaming_table`, `@dp.append_flow` | ✅ | — |
| `dp.create_sink` (Kafka/Event Hubs) | ✅ | — |
| `@dp.expect` / `@dp.expect_all` (data quality) | — | ✅ |
| `@dp.foreach_batch_sink`, `@dp.foreach_sink` | — | ✅ |
| `@dp.update_flow` | — | ✅ |
| AUTO CDC (`create_auto_cdc_flow` / `_from_snapshot_flow`) | — | ✅ |
| `event_log` table, event hooks | — | ✅ |
| Bundles, Lakeflow Pipelines Editor, serverless pipelines | — | ✅ |

Lakeflow requires the Premium plan.

## Current vs legacy naming (evaluated 2026-11-04)

All eight upstream source docs were current at that date (PySpark 4.3.0, Oct 2026). The thing most
worth knowing is the **renames**, because older code and documentation are full of the old names:

| Thing | Legacy name | Current name | Status |
|---|---|---|---|
| The framework | Delta Live Tables (DLT) | **Lakeflow pipelines** (Databricks) / **Spark Declarative Pipelines** (Apache) | DLT name retired |
| Python module | `import dlt` | `from pyspark import pipelines as dp` | `dlt` still works, discouraged |
| Bundles | Databricks Asset Bundles (DAB) | **Declarative Automation Bundles** | Renamed; `databricks.yml` and the CLI unchanged — cosmetic |
| CDC API | `dlt.apply_changes(...)` / APPLY CHANGES | `dp.create_auto_cdc_flow(...)` / **AUTO CDC** | APPLY CHANGES still works, AUTO CDC preferred |
| Cross-dataset refs | `LIVE.` virtual schema | unqualified names → the pipeline's configured catalog/schema | `LIVE` legacy/deprecated, removal planned |

**Reading an older codebase**, expect these in roughly this order of frequency: `import dlt` and
`@dlt.*` decorators; `dlt.read(...)` instead of `spark.read.table(...)`; `LIVE.` prefixes; a shared
`dlt_params` dict; "Databricks Asset Bundles" in comments and READMEs. Only the first two are
behavioural; the rest are naming. Migrate the module import and the decorators; treat the bundle
rename as cosmetic.

> **Documentation drifts faster than code.** In the source project the *code* used the current API
> correctly while the README still described `@dlt.table`, `dlt.read`, and a `dlt_params` dict that
> no longer existed anywhere. When code and docs disagree about the API, believe the code — and fix
> the doc in the same pass.

## IDE typing: pyright stubs for the Databricks runtime

The OSS `pyspark` wheel ships **narrower** typed signatures than the Databricks runtime, so pyright
flags runtime-only kwargs (`expect_all`, `cluster_by_auto`, `spark_conf`, …) and runtime-only
members even though they work at runtime. Fix it with a local stub tree on the pyright/Pylance
`stubPath` (e.g. `typings/`), not with `# type: ignore` everywhere:

- `typings/pyspark/pipelines/__init__.pyi` — **re-declare each `dp` member** to override the narrow
  OSS signature. Use permissive `def name(*args: Any, **kwargs: Any) -> Any: ...` for most, and spell
  out the full signature only where you want real checking (e.g. `create_streaming_table` with its
  `cluster_by_auto` / `expect_all*` kwargs). A trailing `def __getattr__(name: str) -> Any: ...`
  resolves anything you didn't list. Members the OSS wheel declares narrowly **must** be listed —
  `__getattr__` alone won't override an existing signature.
- `typings/mlflow/deployments/__init__.pyi` — `get_deploy_client` has a `return None` branch, so
  pyright infers `Client | None` and flags every `.predict(...)` / `response.data`. Narrow the stub
  return to a **non-optional** `BaseDeploymentClient` to stop the `None` poisoning downstream.
- Add `mlflow/py.typed` containing `partial` so your stubbed submodule coexists with the real typed
  `mlflow` package instead of shadowing all of it.
- Declare notebook globals (`spark`, `dbutils`, `dlt`) as ruff builtins and type them in a
  `__builtins__.pyi` so the linter and the IDE agree.

## Upstream documentation (sources)

The eight source docs this skill is reconciled against. Re-verify against these before relying on
anything here:

- Apache Spark — Declarative Pipelines programming guide: <https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html>
- Apache Spark — PySpark API reference: <https://spark.apache.org/docs/latest/api/python/index.html>
- Databricks — Lakeflow Declarative Pipelines (overview): <https://learn.microsoft.com/en-us/azure/databricks/ldp/>
- Databricks — Pipelines Python reference (the `dp` API) → backs [sdp-python-api.md](./references/sdp-python-api.md): <https://learn.microsoft.com/en-gb/azure/databricks/ldp/developer/python-ref>
- Databricks — AUTO CDC → backs [auto-cdc.md](./references/auto-cdc.md): <https://learn.microsoft.com/en-us/azure/databricks/ldp/cdc>
- Databricks — Multi-file / Pipelines Editor → backs [bundles-editor-publishing.md](./references/bundles-editor-publishing.md): <https://learn.microsoft.com/en-us/azure/databricks/ldp/multi-file-editor>
- Databricks — LIVE virtual schema / publishing → backs [bundles-editor-publishing.md](./references/bundles-editor-publishing.md): <https://docs.databricks.com/aws/en/ldp/live-schema>
- Databricks — Asset Bundles → backs [bundles-editor-publishing.md](./references/bundles-editor-publishing.md): <https://docs.databricks.com/dev-tools/bundles/index.html>

## When to use this skill

- Writing or editing a pipeline source file; adding a table, flow, expectation or sink.
- Deciding streaming table vs materialized view vs view, or `append_flow` vs AUTO CDC.
- Choosing an expectations policy, or auditing one that was never chosen.
- Triaging a bad run, or deciding how to refresh after a logic change.
- Reconciling older DLT/DAB naming against current docs.

## Related skills

- [develop-pyspark](../develop-pyspark/SKILL.md) — what goes wrong *inside* a dataset function:
  Arrow/pandas UDFs, OOM, model serving, chunking, joins and skew.
- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — deploying the pipeline:
  targets, variables, resources, schedules, post-deploy runs.
- [test-python](../test-python/SKILL.md) — testing pipeline source files that cannot be imported.
