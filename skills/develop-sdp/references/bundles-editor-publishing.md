# Bundles, the Pipelines Editor, publishing modes & event log

## Declarative Automation Bundles (formerly Databricks Asset Bundles / DAB)

Bundles are the infrastructure-as-code wrapper that defines a Databricks project (jobs, pipelines,
dashboards, model-serving endpoints, MLflow experiments/models) as YAML alongside source, deployed
with the Databricks CLI. **The product was renamed from "Databricks Asset Bundles" to "Declarative
Automation Bundles"** (docs, Sep 2026); the `databricks.yml` file and `databricks bundle` CLI are
unchanged, so this repo's "DAB" naming still works — it's cosmetic.

- Defined in `databricks.yml` + resource files (this repo: `resources/pipelines.yml`,
  `resources/jobs.yml`). Deploy with `databricks bundle validate` / `deploy` / `run`.
- CLI **v0.218.0+** required for bundles; Databricks recommends staying current. You can also
  create/deploy bundles entirely in the workspace UI without installing the CLI.
- `bundle validate` catches schema/duplicate-key errors locally before auth. Resource **keys are
  globally unique** across resource types within a bundle.
- Auth: OAuth U2M (`databricks auth login`) is the recommended path.

## Lakeflow Pipelines Editor

The IDE for pipeline development (files, not notebooks). Relevant facts:

- Pipeline source lives under a **root folder** with a default structure:
  - `transformations/` — **source code** (Python/SQL table definitions; evaluated on run).
  - `explorations/` — notebooks/queries **not** part of the pipeline (ad hoc).
  - `utilities/` — importable Python modules (`from <filename> import ...`).
  - Markdown (`.md`) files in `transformations/` are allowed but **ignored** on run.
- New pipelines default to **Unity Catalog**, **serverless compute**, **current channel**.
- Run granularity: whole pipeline, single file (**Run file**), single table, a selected set, or
  selected SQL. Single-file/table runs reuse other tables' last materialization and can show a
  disjoint graph — run the whole pipeline before shipping.
- **`%pip install` is not supported from files** — add dependencies in **Settings → Pipeline
  environment** (pin with `==`). `%pip` still works from a notebook used as source.
- Python modules are **not found from within a UDF** by default; append the path to `sys.path`
  inside the UDF: `sys.path.append(os.path.abspath("/Workspace/Users/path/to/modules"))`.
- Version-control source in a Git folder; version-control **configuration** via bundles.
- Genie Code (agentic authoring) is in Public Preview.

## Publishing mode (do not use `LIVE.`)

New pipelines use the **default publishing mode**: unqualified names resolve to the pipeline's
configured catalog/schema, which is exactly how this repo reads tables
(`spark.read.table("contents")`). The old `LIVE.` virtual schema is **legacy and deprecated**
(silently ignored in default mode, removal planned) — do not introduce it in new code.

## Event log

Query the pipeline event log via `spark.read.table("event_log")` (Lakeflow; not Apache SDP). New
pipelines publish it to the pipeline's configured catalog/schema; the repo flattens it in stage
`04-00-event-log-flat.py`.

## Pipeline concepts recap

- **Flow**: reads a source, applies logic, writes a target (streaming or batch semantics).
- **Streaming table**: incremental target with one+ streaming flows. **Materialized view**:
  precomputed, exactly one batch flow. **Temporary view**: run-scoped.
- **Pipeline**: resolves dependencies among datasets and orchestrates order/parallelism
  automatically — you don't wire the DAG manually.
- Lakeflow requires the Premium plan; it extends Apache SDP and runs on the Databricks Runtime.

## Sources

- Databricks — Asset Bundles: <https://docs.databricks.com/dev-tools/bundles/index.html>
- Databricks — Multi-file / Pipelines Editor: <https://learn.microsoft.com/en-us/azure/databricks/ldp/multi-file-editor>
- Databricks — LIVE virtual schema / publishing: <https://docs.databricks.com/aws/en/ldp/live-schema>

> For bundle depth — targets & modes, variables/interpolation, resource types, `job_runs`,
> synced-table bin-packing, and deploy gotchas — see the dedicated **databricks-asset-bundles** skill.
