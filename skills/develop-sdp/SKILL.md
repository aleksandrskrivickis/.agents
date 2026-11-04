---
name: develop-sdp
description: 'Expert on Spark Declarative Pipelines (SDP) — the open-source `pyspark.pipelines` (dp) framework — and the Databricks/Lakeflow closed-source extensions layered on it. Use when editing the 01-*/02-* pipeline notebooks, working with @dp.table / create_streaming_table / append_flow / expectations / foreach_batch_sink, choosing streaming table vs materialized view, AUTO CDC vs APPLY CHANGES, publishing modes / the LIVE schema, Databricks bundles (databricks.yml / resources), or the Lakeflow Pipelines Editor. Flags which features are Apache SDP vs Databricks-only, and current-vs-legacy terminology (DLT -> SDP, DAB -> Declarative Automation Bundles).'
---

# Spark Declarative Pipelines (SDP)

**SDP** is the open-source declarative pipeline framework in Apache Spark (`pyspark.pipelines`,
since Spark 4.1). **Databricks Lakeflow pipelines** is a proprietary superset that runs SDP on the
Databricks Runtime and adds closed-source features (expectations, AUTO CDC, extra sinks, the event
log, bundles, the Pipelines Editor). This repo is an SDP pipeline deployed on Databricks, so it uses
the open-source core **plus** several Databricks-only features — the two are flagged throughout.

Detailed references:

- [references/sdp-python-api.md](./references/sdp-python-api.md) — the `pyspark.pipelines` (`dp`) decorators, functions, coding rules.
- [references/auto-cdc.md](./references/auto-cdc.md) — AUTO CDC / AUTO CDC FROM SNAPSHOT (Databricks-only; replaces APPLY CHANGES).
- [references/bundles-editor-publishing.md](./references/bundles-editor-publishing.md) — Databricks bundles, Lakeflow Pipelines Editor, publishing modes, event log.

## Upstream documentation (sources)

The eight source docs this skill is reconciled against (the *Doc freshness* table below tracks their
current-vs-legacy naming). Re-verify against these before relying on anything here:

- Apache Spark — Declarative Pipelines programming guide: <https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html>
- Apache Spark — PySpark API reference: <https://spark.apache.org/docs/latest/api/python/index.html>
- Databricks — Lakeflow Declarative Pipelines (overview): <https://learn.microsoft.com/en-us/azure/databricks/ldp/>
- Databricks — Pipelines Python reference (the `dp` API) → backs [sdp-python-api.md](./references/sdp-python-api.md): <https://learn.microsoft.com/en-gb/azure/databricks/ldp/developer/python-ref>
- Databricks — AUTO CDC → backs [auto-cdc.md](./references/auto-cdc.md): <https://learn.microsoft.com/en-us/azure/databricks/ldp/cdc>
- Databricks — Multi-file / Pipelines Editor → backs [bundles-editor-publishing.md](./references/bundles-editor-publishing.md): <https://learn.microsoft.com/en-us/azure/databricks/ldp/multi-file-editor>
- Databricks — LIVE virtual schema / publishing → backs [bundles-editor-publishing.md](./references/bundles-editor-publishing.md): <https://docs.databricks.com/aws/en/ldp/live-schema>
- Databricks — Asset Bundles → backs [bundles-editor-publishing.md](./references/bundles-editor-publishing.md): <https://docs.databricks.com/dev-tools/bundles/index.html>

## Apache SDP vs Databricks-only (closed-source)

Everything the repo uses that is **not** in open-source Apache SDP — so a plain
`pip install pyspark[pipelines]` could not run it; it needs the Databricks Runtime:

| Feature | Apache SDP | Databricks/Lakeflow-only |
|---|---|---|
| `@dp.table`, `@dp.materialized_view`, `@dp.temporary_view` | ✅ | — |
| `dp.create_streaming_table`, `@dp.append_flow` | ✅ | — |
| `dp.create_sink` (Kafka/Event Hubs) | ✅ | — |
| `@dp.expect` / `@dp.expect_all` (data quality) | — | ✅ (repo uses) |
| `@dp.foreach_batch_sink`, `@dp.foreach_sink` | — | ✅ (repo uses `foreach_batch_sink`) |
| `@dp.update_flow` | — | ✅ |
| AUTO CDC (`create_auto_cdc_flow` / `_from_snapshot_flow`) | — | ✅ (repo does not use) |
| `event_log` table, event hooks | — | ✅ (repo uses `event_log`) |
| Bundles, Lakeflow Pipelines Editor, serverless pipelines | — | ✅ |

## Doc freshness (evaluated 2026-11-04)

All eight source docs are **current** (last updated Sep–Oct 2026; PySpark 4.3.0, Oct 2026). The
important takeaways are the *renames*, because this repo and its README still use older names:

| Thing | Old name (still in repo/README) | Current name (docs) | Status |
|---|---|---|---|
| The pipeline framework | Delta Live Tables (DLT) | **Lakeflow pipelines** (Databricks) / **Spark Declarative Pipelines (SDP)** (Apache) | DLT name retired |
| Python module | `import dlt` | `from pyspark import pipelines as dp` | `dlt` still works, discouraged |
| Bundles | Databricks Asset Bundles (DAB) | **Declarative Automation Bundles** | Renamed; `databricks.yml` unchanged |
| CDC API | `dlt.apply_changes(...)` / APPLY CHANGES | `dp.create_auto_cdc_flow(...)` / **AUTO CDC** | APPLY CHANGES still works, AUTO CDC preferred |
| Cross-pipeline refs | `LIVE.` virtual schema | unqualified names → pipeline's configured catalog/schema | `LIVE` legacy/deprecated, removal planned |

**Repo-specific freshness findings (not fixed here, flag before relying on docs):**
- The repo **code** correctly uses the current `from pyspark import pipelines as dp` API (per
  [AGENTS.md](../../../databricks-web-scraping/AGENTS.md)). Good — no migration needed there.
- The **README** still says "Delta Live Tables", `@dlt.table`, `dlt.read(...)`, `dlt_params`,
  `@dlt.append_flow` in several places. That is stale relative to both the code and the docs.
- `azure-pipelines.yaml` comments and README call bundles "Databricks Asset Bundles" — now
  "Declarative Automation Bundles". The `databricks.yml` file name and CLI are unchanged, so this
  is cosmetic, not a breaking change.

## This repo's SDP surface

The repo uses the **open-source SDP API** (`from pyspark import pipelines as dp`), not `import dlt`,
and references tables by bare name (`spark.read.table("portals")`), not `LIVE.` prefixes. Decorators
and functions in use: `@dp.table`, `dp.create_streaming_table` + `@dp.append_flow` (incremental
appends), `@dp.expect_all` (two blocks: column presence, then value checks — never dropping rows),
`@dp.foreach_batch_sink` (the `offsets_maintenance` sink). Stateful pairing uses
`applyInPandasWithState`; distributed fetches use `mapInPandas`. Of these, `@dp.expect_all` and
`@dp.foreach_batch_sink` are **Databricks-only** (see the table above).

## Key coding rules (enforced by SDP)

- A dataset function **must return a DataFrame** and contain only defining logic — SDP evaluates it
  multiple times during planning.
- **Never** call `collect()`, `count()`, `toPandas()`, `save()`, `saveAsTable()`, `start()`,
  `toTable()`, or `pivot()` inside dataset code.
- Streaming tables need a streaming read (`spark.readStream`); materialized views a batch read.
- `spark.conf.get` / `dbutils` work **only on the driver** — read config/secrets at module scope and
  close over them in UDFs (the repo's distributed stages do exactly this).

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
  return to a **non-optional** `BaseDeploymentClient` to stop the `None` poisoning downstream
  (relevant to the `develop-pyspark` model-serving stage).
- Add `mlflow/py.typed` containing `partial` so your stubbed submodule coexists with the real typed
  `mlflow` package instead of shadowing all of it.

## When to use this skill

- Editing or adding a `src/pipeline/*` stage, or touching decorators/flows/expectations/sinks.
- Deciding streaming table vs materialized view vs view, or append_flow vs AUTO CDC.
- Working with `databricks.yml` / `resources/*.yml`, or the Lakeflow Pipelines Editor.
- Reconciling the repo's older DLT/DAB naming against current docs.
