---
name: test-python
description: 'Use when generating or maintaining Python tests. Covers the pytest layout (tests/unit mirroring src/), test_ naming that preserves hyphens and stage numbers, mocking external I/O, testing non-importable notebook/pipeline modules via an AST/stub harness, a hardened local SparkSession fixture (JDK discovery, the Windows worker fix, loopback binding), testing the wheel build and bundle validation with custom pytest options, integration and golden-corpus testing, and the uv / ruff / version-bump tooling around it all. Modeled on a production Databricks pipeline suite.'
---

# Python testing

> **What this is.** Test-authoring conventions accumulated in a production Databricks pipeline
> repository — where most of the code under test is a notebook that cannot be imported, the
> integration layer needs a JVM, and a packaging mistake fails on a cluster rather than in CI. The
> layout and naming rules are ordinary pytest; the harnesses are the interesting part.
>
> If you are reading this as general Python-testing guidance, the transferable material is
> [the notebook harness](./references/notebook-harness.md) (how to test a module you cannot import)
> and [the build tests](./references/bundle-and-wheel-tests.md) (how to assert a wheel contains what
> you think it does).

## Detailed references

- [references/notebook-harness.md](./references/notebook-harness.md) — testing modules that can't be imported: AST helper extraction with no Spark, a dataset-as-PySpark stub, and the hardened local `SparkSession` fixture (JDK discovery, the Windows worker fix, loopback binding, skip-not-fail).
- [references/bundle-and-wheel-tests.md](./references/bundle-and-wheel-tests.md) — custom pytest options (`--validate-bundle`, `--bundle-target`), safe subprocess invocation, asserting the wheel contains your package, and read-only bundle validation.
- [references/integration-and-corpus-testing.md](./references/integration-and-corpus-testing.md) — remote Spark via Databricks Connect, containerised dependencies, and a golden/regression corpus with a scored terminal summary.

## Layout — mirror `src/`

- `tests/unit/` mirrors `src/` one-to-one: `src/<pkg>/<mod>.py` → `tests/unit/<pkg>/test_<mod>.py`.
  Mirror sub-package folders so a test is easy to locate from its source.
- Use the `test_` prefix (default pytest discovery) and **preserve the source module's hyphens and
  stage numbers** — e.g. `test_02-05-documents-markdown-slices-aligned.py`. Do **not** add a
  `python_files` override; the filename should be greppable from the module name.
- Integration tests: `test_integration_*.py`; they may spin a real local `SparkSession`. Keep them
  **skippable** (skip, don't fail) when a runtime dependency is missing.
- Build/deploy tests get their own folder (`tests/unit/bundle/`) so they can be excluded by path.

```
tests/
├── unit/                    # the suite. testpaths points here.
│   ├── conftest.py          # pytest_addoption MUST live at the root of the collected tree
│   ├── bundle/              # wheel build + bundle validate
│   ├── pipeline/
│   │   ├── conftest.py      # the local SparkSession fixture
│   │   └── _harness/        # notebook loader + pipeline stub
│   └── utils/
├── exploratory/             # notebook scratch — NOT collected
├── analytical-queries/      # notebook scratch — NOT collected
└── data-quality/            # notebook scratch — NOT collected
```

## What to generate

- When code under `src/` changes, add or update the mirroring unit test **in the same change**.
- Prefer fast, pure-Python tests; **mock external I/O** (HTTP via `requests` mocks, filesystem,
  services) instead of hitting the network.
- Cover the success path, failure/error paths, and documented boundaries/edge cases.
- **Test the thing that would fail silently.** In a data pipeline that is rarely the happy path: it
  is the all-null column that changes a dtype, the id format another stage parses, the config key a
  digest is supposed to cover. A test that asserts a config dict's **key set** catches the class of
  bug where someone adds a splitter argument and a generation stamp stops being an identity.

## Non-importable modules (notebook/pipeline files)

Some files can't be imported — top-level `spark.conf.get` / `dbutils`, framework decorators
(`@dp.table`, `@dp.append_flow`), or globals injected at runtime. Don't import them; test their pure
logic via a harness (AST helper extraction, or a dataset-as-PySpark stub). See
[references/notebook-harness.md](./references/notebook-harness.md).

## Testing the build and the deploy config

The wheel and the bundle config break deploys more often than application code does, and both are
cheap to test — behind flags, so the default run stays fast and credential-free. Assert that the
wheel **contains your package**, not merely that it built. See
[references/bundle-and-wheel-tests.md](./references/bundle-and-wheel-tests.md).

> **Never let a test deploy.** `databricks bundle validate` only — not `deploy`, not behind a flag.

## Integration tests against real services

When a test needs a real cluster, container, or a scored fixture corpus — a remote Databricks Connect
session (with serverless fallback), a session-scoped Testcontainers database with per-test scratch
DBs, or a golden corpus with a `pytest_terminal_summary` score table — keep it **skippable** when the
backing service is absent and see
[references/integration-and-corpus-testing.md](./references/integration-and-corpus-testing.md).

## Running, and the tooling around it

```bash
uv sync --group dev                     # install dev deps
uv run pytest                           # = tests/unit, verbose
uv run pytest tests/unit/pipeline       # skip the build tests (they shell out)
uv run pytest tests/unit/bundle --validate-bundle --bundle-target dev
uv run ruff check src/ tests/unit
uv run ruff format src/ tests/unit
```

Use `uv run pytest`, not bare `python -m pytest`, so tests run in the project `.venv` on the
supported Python.

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]            # import the package without installing it
testpaths  = ["tests/unit"]     # scratch notebooks are never collected
addopts    = "-v"

[tool.ruff]
line-length = 120
builtins = ["spark", "dlt", "dbutils"]   # notebook globals: stop F821 on every pipeline file

[tool.uv]
system-certs = true             # corporate TLS interception
```

Conventions worth copying:

- **`builtins = ["spark", "dlt", "dbutils"]`** is what makes ruff usable on notebook-format sources.
  Pair it with a `__builtins__.pyi` so the IDE agrees with the linter — see
  [develop-sdp](../develop-sdp/SKILL.md) → *IDE typing*.
- **Pin the pure-Python transformation libraries into the dev group**, even when the runtime
  installs them elsewhere, so the logic that uses them is actually covered. A similarity function or
  a fuzzy matcher is testable; it is only tested if its library is installed in the test env.
- **`install-jdk` as a dev dependency** plus a one-off `python -c "import jdk; jdk.install('21')"`
  satisfies the local-Spark requirement without a manual JDK install.
- **Behind a TLS-intercepting proxy**, `[tool.uv] system-certs = true` usually fixes
  `invalid peer certificate: UnknownIssuer`. When it doesn't, fall back to running tools from the
  existing venv (`.venv/Scripts/python -m pytest`) rather than through `uv run`.
- **If a pre-commit hook bumps the version** on every commit, expect merge conflicts on that one
  line in parallel branches — resolve by taking the higher version — and make the hook skip during
  merges and rebases:
  ```bash
  if [ -f .git/MERGE_HEAD ] || [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then exit 0; fi
  ```
  Share it via `core.hooksPath` (`git config core.hooksPath .githooks`) so it is versioned rather
  than per-clone. Never assert an exact version string in a test when a hook moves it.

For CI, use the [test-workflows-github](../test-workflows-github/SKILL.md) or
[test-workflows-devops](../test-workflows-devops/SKILL.md) skill.

## Don'ts

- Don't make exploratory/scratch scripts pytest-discoverable, or "fix" them to be. Keep them out of
  `testpaths`, and don't run formatter fixes over them unasked.
- Don't add comments or docstrings to tests unless they clarify genuinely non-obvious intent.
- Don't let a test deploy, mutate a shared workspace, or write outside `tmp_path`.
- Don't assert on a version string a hook rewrites.
- Don't use `check=True` on a subprocess whose stdout you need in the failure message.

## Related skills

- [develop-pyspark](../develop-pyspark/SKILL.md) — what the pipeline logic under test is doing, and
  which parts are pure enough to unit-test.
- [develop-sdp](../develop-sdp/SKILL.md) — why pipeline source files can't be imported.
- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — what `bundle validate` checks.
- [test-workflows-github](../test-workflows-github/SKILL.md) /
  [test-workflows-devops](../test-workflows-devops/SKILL.md) — running this suite in CI.
