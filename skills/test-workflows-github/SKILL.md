---
name: test-workflows-github
description: 'Use when building a GitHub Actions pipeline to run Python tests. Covers setup-python + uv install, uv sync, advisory ruff, pytest with a JUnit report, artifact upload, push/PR + paths triggers, and gating merges via branch protection or rulesets. Mirrors the databricks-web-scraping test pipeline.'
---

# GitHub Actions: Python test pipeline

Pattern for a GitHub Actions workflow that lints (advisory) and runs pytest with `uv`, mirroring the
`databricks-web-scraping` test CI. Pairs with the **`test-python`** skill (how to write the tests).

## Skeleton

```yaml
name: Tests
on:
  push:
    branches: [main]
    paths: ["src/**", "tests/**", "pyproject.toml", ".github/workflows/tests.yml"]
  pull_request:
    paths: ["src/**", "tests/**", "pyproject.toml"]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12" # matches requires-python
      - name: Install uv
        run: |
          curl -LsSf https://astral.sh/uv/install.sh | sh
          echo "$HOME/.local/bin" >> "$GITHUB_PATH"
      - run: uv sync --group dev
      - name: Ruff check (advisory)
        continue-on-error: true
        run: uv run ruff check src/ tests/
      - name: Ruff format check (advisory)
        continue-on-error: true
        run: uv run ruff format --check src/ tests/
      - name: Unit tests
        run: uv run pytest -q --junitxml=junit/test-results.xml
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: junit/test-results.xml
```

## Notes

- **Gating merges:** the `pull_request` trigger *runs* the check; to *require* it, add it as a
  required status check via **branch protection** or a **ruleset** (Settings → Rules) — the trigger
  alone does not block merges.
- **Advisory lint:** keep ruff `continue-on-error: true` until the tree is clean, then drop it to
  make lint blocking.
- **Test report UI:** GitHub Actions has no built-in JUnit publisher (unlike Azure DevOps'
  `PublishTestResults`). Upload the XML as an artifact, or add a reporter action (e.g.
  `dorny/test-reporter`) for inline PR annotations.
- **uv install:** the `curl` installer mirrors the DevOps pipeline; `astral-sh/setup-uv` is a
  first-class alternative that adds caching.
- **JVM-dependent integration tests:** provision a JDK (`actions/setup-java`) or let them skip (see
  the `test-python` harness reference).
- The Azure DevOps equivalent is the **`test-workflows-devops`** skill.
