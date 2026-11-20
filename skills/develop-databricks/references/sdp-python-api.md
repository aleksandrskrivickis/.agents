# SDP / Lakeflow Python API (`pyspark.pipelines`)

> **Source.** `[docs]` for the API surface and documented behaviour (Apache Spark + Databricks
> Lakeflow documentation); `[repo]` for what a production pipeline actually used and hit.
> `[deduced]` marks an inference.

Reference for the Python pipeline API, from the Spark Declarative Pipelines Programming Guide and
the Lakeflow pipelines Python reference (both current as of Oct 2026; SDP ships in Apache Spark
since **4.1**; pin it, e.g. `pyspark[pipelines]==4.1.2`).

## Import and session

```python
from pyspark import pipelines as dp
```

- Alias to `dp` by convention. The module was previously `dlt` on Databricks; `import dlt` still
  works but is discouraged.
- **Spark session:** in Spark 4.1 each pipeline file had to declare `spark = SparkSession.active()`.
  From **Spark 4.2** the framework injects `spark` into each file's namespace automatically. On
  Databricks the runtime injects `spark`/`dbutils` as globals (the repo types them via
  `__builtins__.pyi` and ruff `builtins`). For static analysis you may add `spark: SparkSession` at
  module scope — SDP still injects the real session.
- Most of the module works **only inside a pipeline**. `@dp.materialized_view` and `@dp.table` can
  also be used outside a pipeline on serverless general compute to define standalone objects.

## Datasets and flows

| Concept | Decorator / function | Notes |
|---|---|---|
| Streaming table | `@dp.table` (streaming read) or `dp.create_streaming_table("name")` | Incremental; one or more streaming flows write into it |
| Materialized view | `@dp.materialized_view` (batch read) | Precomputed; exactly one batch flow |
| Temporary view | `@dp.temporary_view` | Scoped to a pipeline run; not published |
| Append flow | `@dp.append_flow(target="t")` | Multiple flows fan-in to one streaming table |
| Update flow | `@dp.update_flow` | **Lakeflow-only** (not Apache) |
| Sink | `dp.create_sink(name, format, options)` + `@dp.append_flow(target=sink)` | Kafka/Event Hubs etc.; streaming + Python only |
| ForEachBatch sink | `@dp.foreach_batch_sink(...)` | **Lakeflow-only**; the repo's `offsets_maintenance` uses this |
| ForEach sink | `@dp.foreach_sink(...)` | **Lakeflow-only** |
| Expectations | `@dp.expect(...)`, `@dp.expect_all({...})` | **Lakeflow-only**; data-quality constraints |
| CDC | `dp.create_auto_cdc_flow`, `dp.create_auto_cdc_from_snapshot_flow` | **Lakeflow-only**; see [auto-cdc.md](./auto-cdc.md) |

Full API list (Lakeflow Python reference): `append_flow`, `create_auto_cdc_flow`,
`create_auto_cdc_from_snapshot_flow`, `create_table`, `create_sink`, `create_streaming_table`,
`Expectations`, `foreach_batch_sink`, `foreach_sink`, `materialized_view`, `replace_flow`, `table`,
`temporary_view`, `update_flow`.

### DLT → SDP mapping (for reading old code/README)

| Old (DLT) | Current (SDP / Lakeflow) | In Apache Spark? |
|---|---|---|
| `import dlt` | `from pyspark import pipelines` (`as dp`) | Yes |
| `@dlt.table` (streaming df) | `@dp.table` | Yes |
| `@dlt.table` (batch df) | `@dp.materialized_view` | Yes |
| `@dlt.view` | `@dp.temporary_view` | Yes |
| `@dlt.append_flow` | `@dp.append_flow` | Yes |
| `dlt.apply_changes(...)` | `dp.create_auto_cdc_flow(...)` | No (Lakeflow-only) |
| `@dlt.expect(...)` | `dp.expect(...)` | No (Lakeflow-only) |
| `@dlt.create_sink(...)` | `dp.create_sink(...)` | Yes |
| (unavailable) | `@dp.foreach_batch_sink / foreach_sink / update_flow` | No |
| `spark.read.table("event_log")` | same | No |

## Basic examples

```python
from pyspark import pipelines as dp
from pyspark.sql import DataFrame


@dp.materialized_view  # batch read → materialized view
def basic_mv() -> DataFrame:
    return spark.table("samples.nyctaxi.trips")


@dp.table  # streaming read → streaming table
def basic_st() -> DataFrame:
    return spark.readStream.table("samples.nyctaxi.trips")


dp.create_streaming_table("customers_us")  # fan-in target for append flows


@dp.append_flow(target="customers_us")
def from_west() -> DataFrame:
    return spark.readStream.table("customers_us_west")
```

Reference other pipeline tables by bare name (`spark.table("orders")` /
`spark.readStream.table("orders")`) — the DAG is inferred from these references; do **not** use
`LIVE.` prefixes in default publishing mode.

## Coding requirements (hard rules)

- A dataset-defining function **must return a `pyspark.sql.DataFrame`** and include only the code
  needed to define the table/view. SDP evaluates the source **multiple times** during planning/runs.
- **Never** use these inside dataset code: `collect()`, `count()`, `toPandas()`, `pivot()`,
  `save()`, `saveAsTable()`, `start()`, `toTable()`.
- Never write/save to files or tables from dataset code.
- For the `for`-loop table-generation pattern, the list of values must be **additive** across runs;
  bind loop variables as default args to avoid late-binding (`def f(region_filter=region)`).
- Custom monitoring belongs in **event hooks**, not dataset definitions.
- SQL: `PIVOT` is not supported in SDP SQL.

## CLI note

The Apache `spark-pipelines` CLI (`init`/`run`/`dry-run`, `spark-pipeline.yml` spec) is **not used
on Databricks** — there you deploy via bundles and iterate in the Lakeflow Pipelines Editor.
See [bundles-editor-publishing.md](./bundles-editor-publishing.md).

## Sources

- Databricks — Pipelines Python reference (the `dp` API): <https://learn.microsoft.com/en-gb/azure/databricks/ldp/developer/python-ref>
- Apache Spark — Declarative Pipelines programming guide: <https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html>
- Apache Spark — PySpark API reference: <https://spark.apache.org/docs/latest/api/python/index.html>
