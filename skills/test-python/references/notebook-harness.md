# Testing non-importable pipeline/notebook modules

Databricks SDP notebooks can't be imported: they call `spark.conf.get`, `dbutils`, and framework
decorators (`@dp.table`, `@dp.append_flow`) at module scope. Two harness patterns test their pure
logic without importing the module or needing the framework runtime.

## 1. AST helper extraction (no Spark)

Parse the file, find named function definitions (e.g. a `mapInPandas` body or a pure transform), and
compile just those against a namespace of fakes:

```python
# load_functions(file, names, namespace) -> dict of compiled callables
funcs = load_functions("01-02-....py", ["_rows_to_frame"], {"logger": FakeLogger()})
out = funcs["_rows_to_frame"](sample_rows)
```

Use for pandas/Arrow logic, parsing, similarity scoring, fuzzy matching — anything that does not
need a live Spark session.

## 2. Dataset-as-PySpark stub (real local SparkSession)

Replace the SDP decorators and `spark.read.table(...)` with a stub so a dataset function runs as
plain PySpark against in-memory upstream tables:

```python
result_df = (
    PipelineNotebook("02-00-documents-markdown.py", spark)
    .with_upstream_table("contents", contents_df)
    .with_upstream_table("contents_markdown", markdown_df)
    .run("documents_markdown_flow")  # a real pyspark DataFrame
)
```

These are `test_integration_*.py`. They need a **full JDK 21** (Spark 4.1 launches with
`--add-modules=jdk.incubator.vector`, which trimmed runtimes omit). Discover the JDK (or accept
`JAVA_HOME`/`PIPELINE_TEST_JDK`) and **skip** when no JVM is present, so the pure-Python unit layer
stays green on a machine without Java.

## Why not just import?

Importing a pipeline notebook executes its module-scope side effects (config reads, secret lookups,
decorator registration) which fail or require the Databricks runtime. The harness isolates the
*pure* logic — the part worth unit-testing — from that untestable scaffolding.
