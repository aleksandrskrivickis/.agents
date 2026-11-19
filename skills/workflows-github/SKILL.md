---
name: workflows-github
description: 'Use when building GitHub Actions workflows for a code repo: a test pipeline on push/pull_request (setup-python + uv or setup-node, advisory ruff, pytest/vitest, JUnit artifact, path triggers, gating via branch protection/rulesets) and an automated version-bump + release-on-merge workflow (bump-my-version via pipx, [skip ci] loop prevention, default GITHUB_TOKEN semantics, gh release --generate-notes). Distilled from the databricks-web-scraping test pipeline and the calendar-privacy-blur release pipeline.'
---

# GitHub Actions: test and release workflows

> **What this is.** Working GitHub Actions workflows: one that lints (advisory) and runs the tests
> with `uv`, and one that bumps the version and publishes a release on every merge to `main`. The
> test half pairs with [test-python](../test-python/SKILL.md), which covers how to write the tests.
>
> The three things worth reading even if you have workflows already: **a `pull_request` trigger does
> not gate a merge** (see Notes), **advisory lint is a deliberate transitional state**, and the
> release workflow **must not trigger itself** (see Release & version bump).

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
  [the harness reference](../test-python/references/notebook-harness.md)).
- **Credentialled tests stay opt-in.** Anything needing a cloud login — bundle validation, a remote
  Spark session — should run in a separate job gated on secrets being present, so a fork's pull
  request still gets the fast suite instead of a wall of red:
  ```yaml
  validate-bundle:
    if: github.event_name == 'push'      # or: secrets are available
    steps:
      - run: uv run pytest tests/unit/bundle --validate-bundle --bundle-target dev
  ```
- **Never run a deploy from CI by default.** Validation only. See
  [bundle-and-wheel-tests](../test-python/references/bundle-and-wheel-tests.md).

## Release & version bump

A second workflow gives every merge a distinct version and a GitHub release. Keep it apart from the
test workflow, so a publish failure does not re-bump, and run it on `main` (not in the pull request),
which serialises it — two merges cannot collide on a version.

```yaml
name: Release
on:
  push:
    branches: [main]
    paths: ["src/**"] # only bump when shipping code changed
  workflow_dispatch:
permissions:
  contents: write # to push the bump commit and create the release
jobs:
  release:
    # Belt-and-suspenders: [skip ci] also makes GitHub skip the run outright.
    if: ${{ !contains(github.event.head_commit.message, '[skip ci]') }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { ref: main }
      - name: Bump, commit and tag
        id: bump
        run: |
          git config user.name "${{ github.actor }}"
          git config user.email "${{ github.actor_id }}+${{ github.actor }}@users.noreply.github.com"
          pipx run bump-my-version bump patch   # pipx is preinstalled on the runner; config commits + tags
          echo "version=$(pipx run bump-my-version show current_version)" >> "$GITHUB_OUTPUT"
          git push --follow-tags
      - name: Publish the release
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release create "v${{ steps.bump.outputs.version }}" --generate-notes
```

`bump-my-version` reads its config from `.bumpversion.toml` (or a `[tool.bumpversion]` table in
`pyproject.toml`). Keep `current_version` in `.bumpversion.toml` so it does not match the `[project]`
version line in `pyproject.toml`:

```toml
# .bumpversion.toml
[tool.bumpversion]
current_version = "0.1.0"
commit = true
tag = true
message = "Release v{new_version} [skip ci]"
tag_name = "v{new_version}"

[[tool.bumpversion.files]]
filename = "pyproject.toml"
search = 'version = "{current_version}"'
replace = 'version = "{new_version}"'
```

- **Why it does not loop.** `bump-my-version` writes a commit whose message carries `[skip ci]`,
  which GitHub honours by skipping the run; and a push made with the default `GITHUB_TOKEN` does not
  start new workflow runs at all. Either alone suffices — keep both, because swapping in a Personal
  Access Token (to trigger downstream workflows) removes the second guarantee.
- **Attribute the commit to a person, not the bot.** `${{ github.actor }}` and `${{ github.actor_id }}`
  name whoever triggered the run, so the bump commit counts on their GitHub contribution graph through
  the `id+login@users.noreply.github.com` noreply address. To credit the Actions bot instead, hardcode
  `github-actions[bot]` with id `41898282`.
- **Use a known tool, not a hand-rolled script.**
  [`bump-my-version`](https://github.com/callowayproject/bump-my-version) (the maintained successor to
  `bumpversion` / `bump2version`) edits the version in every file its config lists, then commits and
  tags. Run it with `pipx run`, which is preinstalled on GitHub-hosted runners, so the workflow needs
  no install step. `bump patch` raises the last component; `show current_version` prints the new
  value for the release tag. The `callowayproject/bump-my-version` action is an alternative.
- **One version, many files.** Add a `[[tool.bumpversion.files]]` block for each file that holds the
  version, such as `pyproject.toml` and, for a JS package, `package.json`. The tool updates them
  together, so they cannot drift. Run `npm install --package-lock-only` after the bump so the lock
  file's version tracks too — otherwise `npm ci` fails its sync check.
- **Store the version where the ecosystem reads it.** Python: a static `version` in `pyproject.toml`,
  read at runtime with `importlib.metadata.version("<dist-name>")`. JS: the `version` in
  `package.json`, injected into the bundle (Vite `define`). An editable install freezes the metadata
  at install time, so trigger a rebuild on a `pyproject.toml` change if the running process must show
  the new number.
- **Attach artefacts to the release**, not a rebuild of them: `gh release create vX a.zip b.zip`. For
  a store/registry upload, split it into a dependent job so "re-run failed jobs" retries only the
  upload, never the bump.

## Related skills

- [test-python](../test-python/SKILL.md) — how to write the tests this workflow runs, and the
  `pyproject.toml` configuration it relies on.
- [workflows-devops](../workflows-devops/SKILL.md) — the Azure DevOps equivalent, with a
  significant trigger difference.
- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — what `bundle validate` checks,
  if you add the credentialled job.
