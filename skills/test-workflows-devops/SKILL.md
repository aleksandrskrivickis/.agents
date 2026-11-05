---
name: test-workflows-devops
description: 'Use when building an Azure DevOps (azure-pipelines.yml) pipeline to run Python tests. Covers UsePythonVersion + uv, advisory ruff, pytest with PublishTestResults, and the critical Azure Repos caveat that a pr: trigger is ignored (PR validation is a Build Validation branch policy). Mirrors the databricks-web-scraping azure-pipelines.'
---

# Azure DevOps: Python test pipeline

> **What this is.** A working Azure Pipelines YAML that lints (advisory) and runs pytest with `uv`,
> taken from a production Databricks pipeline repository. It pairs with
> [test-python](../test-python/SKILL.md), which covers how to write the tests this runs.
>
> **Read the caveat section even if you have a pipeline already.** On Azure Repos Git a `pr:`
> trigger in YAML is silently ignored — pull-request validation is a *branch policy*, configured
> outside the file. This surprises everyone arriving from GitHub Actions, and it means a pipeline
> that looks like it gates merges may not.

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
  is an artifact upload or a reporter action — see
  [test-workflows-github](../test-workflows-github/SKILL.md).
- **`failTaskOnFailedTests: true` on the publish step is what fails the build.** The pytest step's
  own exit code also fails it, but when you make pytest advisory during a migration this is the lever
  that keeps results visible while still gating.
- Keep ruff `continueOnError: true` while the tree has pre-existing findings; drop it to gate. Say
  *in a comment* how many findings remain, so "advisory" reads as a tracked state rather than a
  permanent one.
- JVM-dependent integration tests: install a JDK or let them skip (see
  [the harness reference](../test-python/references/notebook-harness.md)).
- **Credentialled tests belong in their own stage**, gated on branch or on a variable group being
  available, so an ordinary pull-request validation run stays fast and credential-free:
  ```yaml
  - script: uv run pytest tests/unit/bundle --validate-bundle --bundle-target dev
    displayName: Bundle validation
    condition: eq(variables['Build.SourceBranchName'], 'main')
  ```
- **Never run a deploy from CI.** Validation only — see
  [bundle-and-wheel-tests](../test-python/references/bundle-and-wheel-tests.md).
- If the repository has a separate deployment pipeline, keep lint and tests in **one** file rather
  than two. A split invites the state where the test pipeline is registered and the deploy pipeline
  is the one with the branch policy attached.

## Related skills

- [test-python](../test-python/SKILL.md) — how to write the tests this pipeline runs, and the
  `pyproject.toml` configuration it relies on.
- [test-workflows-github](../test-workflows-github/SKILL.md) — the GitHub Actions equivalent.
- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — what `bundle validate` checks.
- [develop-infrastructure](../develop-infrastructure/SKILL.md) — a much larger Azure DevOps pipeline
  set (preflight, approvals, locks, Terraform, PSRule) if you need more than lint-and-test.
