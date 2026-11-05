# Testing non-importable pipeline/notebook modules

> **Source.** `[repo]` — from a production Databricks project's test suite. `[deduced]` marks
> generalisation advice the suite does not itself state.

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

### The local `SparkSession` fixture

Every line of this earns its place; a plain `SparkSession.builder.getOrCreate()` fails or hangs on a
developer laptop often enough to be worth the boilerplate.

```python
# tests/unit/pipeline/conftest.py
def _looks_like_jdk(path):
    return bool(path) and os.path.isdir(path) and os.path.exists(os.path.join(path, "bin"))


def _discover_jdk():
    explicit = os.environ.get("PIPELINE_TEST_JDK") or os.environ.get("JAVA_HOME")
    if _looks_like_jdk(explicit):
        return explicit
    # install-jdk (`jdk.install('21')`) unpacks to ~/.jdk/jdk-21*
    for candidate in sorted(glob.glob(os.path.join(os.path.expanduser("~"), ".jdk", "jdk-21*")), reverse=True):
        if _looks_like_jdk(candidate):
            return candidate
    return None


@pytest.fixture(scope="session")
def spark():
    java_home = _discover_jdk()
    if java_home:
        os.environ["JAVA_HOME"] = java_home
        os.environ["PATH"] = os.path.join(java_home, "bin") + os.pathsep + os.environ.get("PATH", "")

    # Pin the worker interpreter and keep everything on loopback.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")

    try:
        from pyspark.sql import SparkSession

        warehouse = tempfile.mkdtemp(prefix="spark-warehouse-")
        session = (
            SparkSession.builder.master("local[1]")
            .appName("pipeline-integration-tests")
            .config("spark.driver.bindAddress", "127.0.0.1")
            .config("spark.driver.host", "127.0.0.1")
            .config("spark.sql.shuffle.partitions", "1")
            .config("spark.default.parallelism", "1")
            .config("spark.sql.warehouse.dir", warehouse)
            .config("spark.ui.enabled", "false")
            .config("spark.sql.execution.arrow.pyspark.enabled", "true")
            .getOrCreate()
        )
    except Exception as exc:  # noqa: BLE001 — any JVM/startup failure means "no Spark here"
        pytest.skip(f"local SparkSession unavailable (no JDK 21?): {exc}")

    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()
```

| Line | Why |
|---|---|
| `PYSPARK_PYTHON = sys.executable` | **The Windows fix.** Without it, Spark launches `python` from PATH, hits the Microsoft Store shim, and the worker never connects back — the symptom is a timeout, not an error |
| `SPARK_LOCAL_IP` + `bindAddress` + `driver.host` on `127.0.0.1` | Avoids Spark picking a VPN/Docker/Wi-Fi interface and failing to bind, or binding somewhere the worker can't reach |
| `master("local[1]")`, `shuffle.partitions=1`, `default.parallelism=1` | One partition is faster and makes output ordering deterministic for assertions |
| `warehouse.dir` on a tempdir | Keeps `spark-warehouse/` and `metastore_db/` out of the repo |
| `ui.enabled=false` | No port binding, no leaked ports between sessions |
| Arrow enabled | So tests exercise the same conversion path as production — the place Arrow bugs actually live |
| `try/except` → `pytest.skip` | A missing or broken JVM is "not testable here", not a failure. Catch broadly: the ways Spark fails to start are many and all mean the same thing |
| `scope="session"` + `stop()` | JVM startup dominates runtime; one session for the suite |
| `setLogLevel("ERROR")` | Spark's INFO output buries assertion failures |

`install-jdk` as a dev dependency plus a one-off
`python -c "import jdk; jdk.install('21')"` is the lowest-friction way to satisfy the JDK
requirement on a workstation; `_discover_jdk` then finds it without any further configuration.

## Why not just import?

Importing a pipeline notebook executes its module-scope side effects (config reads, secret lookups,
decorator registration) which fail or require the Databricks runtime. The harness isolates the
*pure* logic — the part worth unit-testing — from that untestable scaffolding.
