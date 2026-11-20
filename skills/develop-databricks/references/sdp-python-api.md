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
| CDC | `dp.create_auto_cdc_flow`, `dp.create_auto_cdc_from_snapshot_flow` | **Lakeflow-only**; see [sdp-auto-cdc.md](./sdp-auto-cdc.md) |

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
- **A function body runs at analysis time, not at materialisation.** The body is called to *build*
  the DataFrame definition, so a blocking network call in it — a model-serving warm-up, a token
  fetch — makes **graph resolution** sit on that call. Against a scale-to-zero endpoint that is a
  cold start of up to ten minutes, and it surfaces as an *analysis* timeout, not a task failure. If
  the call must happen, put it in the body of the one table that needs it rather than at module
  scope, so it is scoped to that flow's setup and its failure fails only that flow. `[repo]`
- **`spark.catalog.tableExists()` is not available inside a pipeline.** Pipeline execution runs in
  an isolated context where the Python catalog API is not wired up. Use plain SQL instead, which
  needs no exception handling either way. `[repo]`

  ```python
  catalog, schema = spark.conf.get("pipelines.catalog"), spark.conf.get("pipelines.schema")
  exists = spark.sql(f"""
      SELECT 1 FROM {catalog}.information_schema.tables
      WHERE table_schema = '{schema}' AND table_name = 'contents_markdown'
  """).limit(1).count() > 0
  ```

- **Spark SQL has no parameter markers for identifiers** — only for literal values. A catalog,
  schema or table name stays an f-string no matter how much you would prefer to bind it, so build
  three-part names from `pipelines.catalog`/`pipelines.schema` (or `current_catalog()`) rather than
  from anything a caller can influence. The usual remedy does not exist here. `[docs]`

## Reading a table the pipeline itself writes

A flow cannot read its own target: SDP resolves an acyclic graph, so
`@dp.table def foo(): return spark.table("foo")…` fails with a cyclic-dependency error at
graph-resolution time. What is widely misunderstood is *how* SDP decides that, and the
misunderstanding is load-bearing — a source project carried this comment in production:

> Referenced by published name (NOT LIVE) so it reads the prior update's committed state and adds
> no edge to the pipeline graph.

That is wrong. **SDP builds the graph from the DataFrame lineage of whatever the function
returns.** A bare or fully-qualified `spark.table("x")` that gets `.join()`ed into the returned
frame still carries `x` in that logical plan, so the edge exists whichever name you wrote. Naming
is irrelevant; lineage is everything. And if `x` is itself downstream of this table, that is a real
cycle, not a false positive. `[repo]`

Three patterns are legitimate, in rough order of preference:

1. **AUTO CDC** — the declarative "compare incoming rows against existing keys and upsert". You
   never write the read-back; the framework merges internally. See
   [sdp-auto-cdc.md](./sdp-auto-cdc.md).
2. **Stateful streaming operators** — `dropDuplicatesWithinWatermark`, `flatMapGroupsWithState`,
   `applyInPandasWithState`. State lives in the flow's checkpoint, so "have I seen this key" never
   requires reading the sink.
3. **Treat it as a plain Delta table, outside the pipeline.** A streaming table is a Unity Catalog
   managed table, so a separate job can `MERGE INTO` it. Own it with *either* the pipeline or the
   external process, never both — mixing pipeline-managed and external writes conflicts, and the
   external rows go on the next full refresh.

### Severing lineage, and why it is a last resort

Where the state genuinely has to come from the target — per-key resume offsets are the usual case —
the trick is to materialise the lookup into plain Python **before** it touches the returned frame,
then rebuild it. `spark.createDataFrame` from collected rows has no plan-level reference for the
graph resolver to walk back to:

```python
@dp.table(name="contents_markdown_offsets")
def contents_markdown_offsets():
    if table_exists:                      # see the information_schema check above
        rows = (spark.table(f"{catalog}.{schema}.contents_markdown")
                .filter(col("request_success"))
                .groupBy("iso", "portal_name")
                .agg(spark_max("request_offset_end").alias("offset_start"))
                .collect())               # <- lineage ends here, deliberately
        offsets = spark.createDataFrame(rows, "iso string, name string, offset_start int")
    else:
        offsets = spark.createDataFrame([], "iso string, name string, offset_start int")

    return (spark.readStream.table("portals")
            .join(offsets, ["iso", "name"], "left")
            .withColumn("offset_start", coalesce(col("offset_start"), lit(0))))
```

Be honest about what this costs, because the tension is real and unresolved:

- `collect()` is on the never-call list at the top of this file, and the docs separately say *"do
  not try to implement custom monitoring logic in your dataset definitions"*. This is explicitly
  against guidance.
- The body is re-evaluated during planning, so the scan runs more often than once per update.
- It depends on the resolver inspecting the returned plan rather than intercepting `spark.table`
  at call time. That matches documented behaviour, but it is an implementation detail. `[?]`

**The robust alternative** is to stop deriving the state inside the pipeline: have a separate
scheduled job aggregate into a standalone `offsets_state` table that this pipeline does not own,
and read *that*. It costs a scheduling dependency — the job has to run between updates — and it
cannot cycle by construction. Prefer it for anything you have to defend.

For the per-key-cursor case specifically there is a better answer again, which avoids the offsets
table entirely: see [sdp-custom-data-sources.md](./sdp-custom-data-sources.md).

## CLI note

The Apache `spark-pipelines` CLI (`init`/`run`/`dry-run`, `spark-pipeline.yml` spec) is **not used
on Databricks** — there you deploy via bundles and iterate in the Lakeflow Pipelines Editor.
See [sdp-pipelines-editor-and-publishing.md](./sdp-pipelines-editor-and-publishing.md).

## Sources

- Databricks — Pipelines Python reference (the `dp` API): <https://learn.microsoft.com/en-gb/azure/databricks/ldp/developer/python-ref>
- Apache Spark — Declarative Pipelines programming guide: <https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html>
- Apache Spark — PySpark API reference: <https://spark.apache.org/docs/latest/api/python/index.html>
