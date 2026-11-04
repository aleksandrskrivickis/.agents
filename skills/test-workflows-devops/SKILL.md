---
name: test-workflows-devops
description: 'Use when building an Azure DevOps (azure-pipelines.yml) pipeline to run Python tests. Covers UsePythonVersion + uv, advisory ruff, pytest with PublishTestResults, and the critical Azure Repos caveat that a pr: trigger is ignored (PR validation is a Build Validation branch policy). Mirrors the databricks-web-scraping azure-pipelines.'
---

# Azure DevOps: Python test pipeline

Pattern for an Azure Pipelines YAML that lints (advisory) and runs pytest with `uv`, mirroring the
`databricks-web-scraping` test CI. Pairs with the **`test-python`** skill (how to write the tests).

## Skeleton

```yaml
trigger:
  branches:
    include: [main]
pool:
  vmImage: ubuntu-latest
steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: "3.12" # matches requires-python
  - script: |
      set -euo pipefail
      curl -LsSf https://astral.sh/uv/install.sh | sh
      echo "##vso[task.prependpath]$HOME/.local/bin"
    displayName: Install uv
  - script: uv sync --group dev
    displayName: Install dependencies
  - script: uv run ruff check src/ tests/
    displayName: Ruff check (advisory)
    continueOnError: true
  - script: uv run ruff format --check src/ tests/
    displayName: Ruff format check (advisory)
    continueOnError: true
  - script: uv run pytest -q --junitxml=junit/test-results.xml
    displayName: Unit tests
  - task: PublishTestResults@2
    displayName: Publish test results
    condition: succeededOrFailed()
    inputs:
      testResultsFormat: JUnit
      testResultsFiles: junit/test-results.xml
      failTaskOnFailedTests: true
```

## Critical caveat — PR gating on Azure Repos Git

A `pr:` trigger in YAML is **ignored** for an Azure Repos Git repository; pull-request validation is
a **Build Validation branch policy**, not a YAML trigger. After registering the pipeline, add the
policy on `main` (requires Project Administrator) — in the UI (Repos → Branches → main → Branch
policies → Build validation) or via CLI:

```bash
az repos policy build create \
  --repository-id "$(az repos show --repository <repo> --query id -o tsv)" \
  --branch main --blocking true --enabled true \
  --build-definition-id <pipeline id from `az pipelines list`> \
  --display-name "Lint and unit tests" \
  --queue-on-source-update-only true --manual-queue-only false
```

## Notes

- `PublishTestResults@2` renders the JUnit report in the run summary. The GitHub Actions equivalent
  is an artifact upload or a reporter action — see **`test-workflows-github`**.
- Keep ruff `continueOnError: true` while the tree has pre-existing findings; drop it to gate.
- JVM-dependent integration tests: install a JDK or let them skip (see the `test-python` harness
  reference).
