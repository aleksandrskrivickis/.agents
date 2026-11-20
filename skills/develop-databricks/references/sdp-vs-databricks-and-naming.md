# Apache SDP vs Databricks-only, legacy naming & IDE typing

> **Source.** `[docs]` for the feature split and the renames (Apache Spark + Databricks Lakeflow
> documentation, re-verified 2026-11-04 against PySpark 4.3.0, Oct 2026); `[repo]` for what a
> production pipeline used and for the stub tree that fixed its IDE. `[deduced]` marks an inference.

Three questions this file answers: will my pipeline run outside Databricks, what was this feature
called before, and why does the IDE flag code that works at runtime.

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

Lakeflow requires the Premium plan. Most real pipelines are the open-source core **plus** several
Databricks-only features, so "does this run anywhere else" is answered feature by feature, not once
for the whole file.

## Current vs legacy naming

The thing most worth knowing is the **renames**, because older code and documentation are full of
the old names:

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

## Sources

- Apache Spark — Declarative Pipelines programming guide: <https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html>
- Apache Spark — PySpark API reference: <https://spark.apache.org/docs/latest/api/python/index.html>
- Databricks — Lakeflow Declarative Pipelines (overview): <https://learn.microsoft.com/en-us/azure/databricks/ldp/>
- Databricks — LIVE virtual schema / publishing: <https://docs.databricks.com/aws/en/ldp/live-schema>

## Related

- [sdp-python-api.md](./sdp-python-api.md) — the `dp` surface itself, and the DLT→SDP mapping.
- [sdp-pipelines-editor-and-publishing.md](./sdp-pipelines-editor-and-publishing.md) — the Pipelines Editor
  and publishing modes, where the `LIVE.` rename lands in practice.
- [test-python](../../test-python/SKILL.md) — testing the pipeline source files these stubs type.
