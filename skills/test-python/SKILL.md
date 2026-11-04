---
name: test-python
description: 'Use when generating or maintaining Python tests. Covers the pytest layout (tests/unit mirroring src/), test_ naming that preserves hyphens and stage numbers, mocking external I/O, testing non-importable notebook/pipeline modules via an AST/stub harness, and running with uv. Modeled on the databricks-web-scraping suite.'
---

# Python testing

How to author Python tests following the conventions accumulated in the `databricks-web-scraping`
suite. Referenced by `.github/instructions/tests.instructions.md`.

## Layout — mirror `src/`

- `tests/unit/` mirrors `src/` one-to-one: `src/<pkg>/<mod>.py` → `tests/unit/<pkg>/test_<mod>.py`.
  Mirror sub-package folders so a test is easy to locate from its source.
- Use the `test_` prefix (default pytest discovery) and **preserve the source module's hyphens and
  stage numbers** — e.g. `test_02-05-documents-markdown-slices-aligned.py`. Do **not** add a
  `python_files` override.
- Integration tests: `test_integration_*.py`; they may spin a real local `SparkSession`. Keep them
  **skippable** (skip, don't fail) when a runtime dependency is missing (e.g. no JDK/JVM).

## What to generate

- When code under `src/` changes, add or update the mirroring unit test **in the same PR**.
- Prefer fast, pure-Python tests; **mock external I/O** (HTTP via `requests` mocks, filesystem,
  services) instead of hitting the network.
- Cover the success path, failure/error paths, and documented boundaries/edge cases.

## Non-importable modules (notebook/pipeline files)

Some files can't be imported — top-level `spark.conf.get` / `dbutils`, framework decorators
(`@dp.table`, `@dp.append_flow`), or globals injected at runtime. Don't import them; test their pure
logic via a harness (AST helper extraction, or a dataset-as-PySpark stub). See
[references/notebook-harness.md](./references/notebook-harness.md).

## Integration tests against real services

When a test needs a real cluster, container, or a scored fixture corpus — a remote Databricks Connect
session (with serverless fallback), a session-scoped Testcontainers database with per-test scratch
DBs, or a golden corpus with a `pytest_terminal_summary` score table — keep it **skippable** when the
backing service is absent and see
[references/integration-and-corpus-testing.md](./references/integration-and-corpus-testing.md).

## Running

- Use `uv run pytest` (not bare `python -m pytest`) so tests run in the project `.venv` on the
  supported Python.
- Config lives in `pyproject.toml`: `pythonpath = ["src"]`, `testpaths = ["tests/unit"]`.
- For CI, use the **`test-workflows-github`** or **`test-workflows-devops`** skill.

## Don'ts

- Don't make exploratory/scratch scripts pytest-discoverable, or "fix" them to be.
- Don't add comments or docstrings to tests unless they clarify genuinely non-obvious intent.
