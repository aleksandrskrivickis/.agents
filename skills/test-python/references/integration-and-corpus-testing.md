# Integration & golden-corpus testing

Patterns for tests that touch real infrastructure or score a fixture corpus, beyond the fast
pure-Python unit tests in the main skill. All three keep the default `uv run pytest` run **green for
contributors who lack the backing service** — the missing dependency *skips*, and CI is the gate.

## Remote Spark via Databricks Connect

For tests that must run on a real cluster (not a local JVM `SparkSession`), use a Databricks Connect
session fixture:

```python
# conftest.py
from databricks.connect import DatabricksSession
from databricks.sdk import WorkspaceClient


@pytest.fixture()
def spark():
    return DatabricksSession.builder.getOrCreate()


def _enable_fallback_compute():
    conf = WorkspaceClient().config
    if conf.serverless_compute_id or conf.cluster_id or os.environ.get("SPARK_REMOTE"):
        return
    os.environ["DATABRICKS_SERVERLESS_COMPUTE_ID"] = "auto"  # fall back to serverless


def pytest_configure(config):
    _enable_fallback_compute()
    if hasattr(DatabricksSession.builder, "validateSession"):  # DB Connect 15+
        DatabricksSession.builder.validateSession().getOrCreate()
    else:
        DatabricksSession.builder.getOrCreate()
```

- **Serverless fallback:** when no compute is configured (`serverless_compute_id` / `cluster_id` /
  `SPARK_REMOTE`), set `DATABRICKS_SERVERLESS_COMPUTE_ID = "auto"` so the suite still has somewhere to
  run. Print the notice to stderr with pytest capture disabled.
- **`validateSession()`** (DB Connect 15+) catches client/cluster version skew up front instead of a
  confusing runtime error; guard it with `hasattr`.
- This is a **remote** session, distinct from the local-JVM integration tests in the main skill — keep
  it skippable when no workspace auth is present.

## Containerised dependencies with Testcontainers

Start a real dependency (here Postgres) once per session, and give each test an isolated slice:

```python
POSTGRES_IMAGE = "postgres:18-alpine"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


@pytest.fixture(scope="session")
def postgres_container():
    if not _docker_available():
        pytest.skip("Docker is not running; skipping integration tests.")
    container = PostgresContainer(POSTGRES_IMAGE, driver="asyncpg")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture()
def scratch_database_url(postgres_container):
    admin = create_engine(
        postgres_container.get_connection_url(driver="psycopg"), isolation_level="AUTOCOMMIT"
    )  # CREATE/DROP DATABASE can't run in a txn
    name = f"scratch_{uuid.uuid4().hex[:12]}"
    try:
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
        yield make_url(...).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
```

- **Start the heavy container once** (`scope="session"`); carve a cheap **scratch database per test**
  so a test that migrates/downgrades never mutates a shared one under later tests. Use a
  `scope="module"` variant when even per-test setup is too costly.
- `CREATE DATABASE` / `DROP DATABASE` cannot run inside a transaction — the admin engine needs
  `isolation_level="AUTOCOMMIT"`; drop with `WITH (FORCE)` to evict lingering connections.
- **Auto-skip when Docker is down** (`docker info`, short timeout) rather than failing, and mark the
  tests `@pytest.mark.integration` so `pytest -m "not integration"` deselects them.

## Golden / regression corpus with a terminal summary

For a suite that scores many fixtures (parsers, alignment, extraction quality), parametrise by fixture
and print an aggregate table:

- **Discover fixtures by glob** and use the filename stem as **both** the pytest test id **and** the
  RNG seed, so synthesised mutations are reproducible per fixture:
  ```python
  FIXTURE_SLUGS = [p.stem for p in sorted(SAMPLES_DIR.glob("*.md")) if p.name != "README.md"]
  ```
- A **session-scoped reporter** (a dataclass per fixture) collects precision / recall / F1.
- **`pytest_terminal_summary`** renders an ASCII score table *after* the run — emitted whether tests
  pass or fail, so a regression's **shape** (which fixtures degraded, by how much) is visible without
  re-running. Failures still contribute their degraded scores.
- **Make the suite exercise the production selection path.** If the test picks a fixture's config by a
  looser key than production (e.g. ISO prefix only, not `(iso, portal, type)`), it can run — and pass
  — a configuration production never uses. Match on the exact keys the live system matches on.
