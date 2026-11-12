![The agent skills handbook](https://m.media-amazon.com/images/M/MV5BMjEzODMzMzg1NF5BMl5BanBnXkFtZTYwNDE2NTE3._V1_.jpg)

# The agent skills handbook

Production-tested engineering knowledge, written so a coding agent and a human can read the same page.

Nine chapters on building data platforms on Databricks and Azure — what breaks, why it breaks, and
what the fix actually was. Every entry came out of a production incident, a failed deploy, or a
value nobody could defend in review.

They are **agent skills**: Markdown files that GitHub Copilot and Claude Code load as context when
the task matches. They are also just good documentation, so they are published as a
**[browsable handbook](https://aleksandrskrivickis.github.io/.agents/)** you can read without an
editor open.

## The chapters

**Data pipelines**

- [develop-sdp](skills/develop-sdp/SKILL.md) — Spark Declarative Pipelines: the `dp` API, streaming table vs materialized view, expectations, the event log, refresh semantics and a triage playbook.
- [develop-pyspark](skills/develop-pyspark/SKILL.md) — what goes wrong inside a transform: pandas-UDF OOM, Arrow `ChunkedArray` crashes, model serving, document chunking, skew, throughput, never-raise API calls.
- [develop-scala](skills/develop-scala/SKILL.md) — a custom Spark `FileFormat` DataSource: `UnsafeRow` construction, short-name registration, shaded packaging.
- [develop-databricks](skills/develop-databricks/SKILL.md) — the platform itself: Unity Catalog introspection, migrating tables into UC, the copy-vs-refresh trap, and Delta time travel.

**Deployment and infrastructure**

- [databricks-asset-bundles](skills/databricks-asset-bundles/SKILL.md) — `databricks.yml`: targets and modes, variable interpolation, resource types, Lakebase, post-deploy runs, and the deploy-time traps.
- [develop-infrastructure](skills/develop-infrastructure/SKILL.md) — the Azure platform underneath: Bicep in four planes, Terraform for Unity Catalog, and the Azure DevOps pipelines that orchestrate both.

**Testing**

- [test-python](skills/test-python/SKILL.md) — pytest layout, testing non-importable notebook modules, a hardened local `SparkSession` fixture, wheel and bundle-validation tests.
- [workflows-github](skills/workflows-github/SKILL.md) — a GitHub Actions lint-and-test workflow plus version-bump + release-on-merge, and how merges get gated.
- [workflows-devops](skills/workflows-devops/SKILL.md) — the Azure DevOps equivalent, including the Azure Repos `pr:` trigger trap.

**Engineering practice**

- [write-technical](skills/write-technical/SKILL.md) — write every output in ASD-STE100 Simplified Technical English; once active, it governs all prose, not only the task that triggered it.

Full chapter index, with a reading order: [skills/README.md](skills/README.md).

## Start here

**Just want to read it.** → **[aleksandrskrivickis.github.io/.agents](https://aleksandrskrivickis.github.io/.agents/)**.

**Use it in VS Code with Copilot.** Clone so the path ends in `code-repositories/.agents`, and
Copilot picks the skills up for every repo under that root:

```bash
git clone https://github.com/aleksandrskrivickis/.agents.git /path/to/code-repositories/.agents
```

Then **Developer: Reload Window**. Loaded skills appear as slash commands (type `/`) and are also
auto-selected by their `description`.

**Use it with Claude Code.** Same clone, plus a one-time local symlink so `.claude/skills` points at
`skills/` — see [post-clone setup](#post-clone-setup-the-claudeskills-symlink) below.

**Carry it everywhere on one machine.** Clone into a personal skills path instead, and the skills
apply in every workspace:

```bash
git clone https://github.com/aleksandrskrivickis/.agents.git ~/.copilot/skills   # or ~/.agents/skills
```

`git pull` to update; reload the window to pick up changes.

## How a chapter is built

A skill is a folder. Its `SKILL.md` carries YAML frontmatter plus a lean body; the bulky material
lives in `references/` and loads only when it is needed.

```
skills/develop-sdp/
├── SKILL.md                  # frontmatter + the lean body an agent always loads
└── references/
    ├── sdp-python-api.md     # loaded on demand, one file per topic
    ├── expectations-policy.md
    └── …
```

```yaml
---
name: develop-sdp            # MUST equal the folder name, or the skill is silently ignored
description: 'Use when …'    # the discovery surface — concrete trigger keywords
---
```

Every `SKILL.md` follows the same spine: an opening note (subject, where the knowledge came from,
what it does **not** cover), detailed references, the handful of rules that prevent most failures, a
symptom → fix index, and the commands worth memorising.

Reference files open with a **Source** note. Where a claim is inferred rather than observed it is
tagged inline — `[repo]` confirmed in code, `[docs]` a vendor-documented constraint, `[deduced]` an
inference, `[?]` a guess worth verifying.

## Why it reads the way it does

Three choices account for most of the difference from ordinary documentation:

- **The failure comes before the remedy.** A section is titled by what went wrong, not by the API it
  uses, because that is how you arrive at it — mid-incident, searching for a symptom.
- **A value never appears without its reason.** "Set the Arrow batch to 20" is useless; "a pandas UDF
  has a ~1 GB ceiling and the executor holds `maxRecordsPerBatch × concurrency` rows at once" is
  something you can reason from when your rows are a different size.
- **Dead ends are recorded.** Mitigations that only reduced a failure rate, settings that turned out
  to be inert, hypotheses that measurement killed. They are the cheapest thing to read and the most
  expensive to rediscover.

## How agents discover skills

Discovery is anchored at **workspace-folder roots**, not arbitrary nested subfolders. Because this
`.agents/` sits at the `code-repositories/` root, its skills are visible to every repo opened under
that root. A skill buried inside a nested repo (`code-repositories/some-repo/.agents/skills/…`) is
**not** found when the workspace root is `code-repositories/` — that nesting trap is exactly why
these skills live here.

- **GitHub Copilot (VS Code)** scans `.github/skills/`, `.agents/skills/` and `.claude/skills/` at a
  workspace root (personal paths: `~/.copilot/skills/`, `~/.agents/skills/`, `~/.claude/skills/`).
- **Claude Code** scans `.claude/skills/` (personal: `~/.claude/skills/`).

> **Verified vs assumed.** Copilot's three project paths are documented. Whether Claude Code also
> scans `.agents/skills/` (rather than only `.claude/skills/`) is **not confirmed** — don't rely on
> it without testing that tool directly.

Different tools scan different directories, so one `.agents/skills/` is not automatically read by
everything:

- **Copilot** reads `.agents/skills/` directly — no extra setup.
- **Claude Code** reads `.claude/skills/`. Expose it as a symlink to `skills/` (below), or keep a
  second real `.claude/skills/` folder.
- **Settings Sync does NOT sync skills.** VS Code Settings Sync roams prompts, instructions and
  agents but *not* skills. The mechanism for carrying skills across machines is **git** — this repo.

## Post-clone setup: the `.claude/skills` symlink

Claude Code only. There is **no automation** for this: the symlink is a per-clone, local step,
because it cannot be materialised reliably on every OS. It is gitignored, so it never travels with
the repo. Copilot needs nothing.

```bash
# macOS / Linux
mkdir -p .claude && ln -s ../skills .claude/skills
```

```bash
# Windows with Developer Mode on (or an elevated shell), in Git Bash
mkdir -p .claude && MSYS=winsymlinks:nativestrict ln -s ../skills .claude/skills
```

```bat
REM Windows without Developer Mode: a directory junction (no privilege needed)
mkdir .claude & mklink /J .claude\skills skills
```

Verify with `ls -l .claude/skills` — it should show `skills -> ../skills`, or a junction on Windows.

On Windows a real symlink needs Developer Mode (or an elevated shell) plus `core.symlinks=true`;
without that git writes a plain text file of the target path and breaks it. `core.symlinks` is local
config, so the repo can't force it — hence the per-clone step. The target is relative (`../skills`),
so recreate (don't move) the link if it changes depth. Simplest alternative: skip the symlink and
keep a second real `.claude/skills/` folder.

## The published handbook

`.github/workflows/publish.yml` renders the skills with **Zensical** (the maintained successor to
Material for MkDocs) and deploys to GitHub Pages on each push to `main` that touches `skills/`,
`README.md`, `AGENTS.md`, `mkdocs.yml` or the review instructions — the same run also versions and
releases the handbook (see below). This file is the site's home page; navigation is built
automatically from the staged tree, so there is no nav list to maintain.

One-time setup: **Settings → Pages → Source = "GitHub Actions"**.

> ⚠️ **Confidentiality — read before going public.** GitHub Pages is **public** on public repos, and
> on Free/Pro even when the repo is private. Skills carrying **internal** material are kept out of
> the repo entirely via `.gitignore`, so they are never committed — and therefore never reach the
> Actions checkout the Pages build runs from, nor the published site. Everything committed here is
> generic, public-safe knowledge.

### Local preview

```bash
pip install zensical
rm -rf docs site && mkdir -p docs docs/github/instructions docs/contributing
cp -R assets docs/assets
cp -R skills docs/skills
cp README.md docs/index.md
cp .github/copilot-instructions.md docs/github/
cp .github/instructions/*.md docs/github/instructions/
cp AGENTS.md docs/contributing/index.md
zensical serve
```

`docs/`, `site/` and `dist/` are gitignored. Relative links into `skills/…` resolve in both the repo
and the staged site; link `AGENTS.md` and `.github/*` with absolute GitHub URLs since they move
during staging. The build is non-strict, so a sibling-repo link won't fail it but 404s on the public
site — keep public-facing skills self-contained.

## This repo as a worked example

It also demonstrates two GitHub automation patterns on itself.

### Governing Copilot code review (on this repo's own PRs)

GitHub's PR reviewer reads review customization from the repository under review, on the head (PR)
branch, so these files take effect in the same PR that changes them:

- `.github/copilot-instructions.md` — repo-wide, always-on rules for every PR here.
- `.github/instructions/skills.instructions.md` (`applyTo: skills/**`) — rules scoped to the skills.
- `AGENTS.md` — cross-tool always-on rules, also consumed by review.

Review is regulated with instructions only; a dedicated "code-review" skill is intentionally omitted
(reviewing PRs is already Copilot's built-in job). GitHub reads these from the repo under review, so
this shared repo can only self-review — copy the `.github/` files into another repo to govern review
there. Turn review on under Settings → Copilot → Code review (or a branch ruleset).

### Automated test generation (a copyable template)

`.github/instructions/tests.instructions.md` (`applyTo: src/**,tests/**`) tells the Copilot cloud
agent how to generate tests — mirror `src/` under `tests/unit/`, `test_<module>.py` naming, mock
external I/O, keep integration tests skippable. `.github/workflows/tests.yml` runs them in CI (uv +
ruff + pytest). This repo is Markdown-only, so the workflow guards on `pyproject.toml` and no-ops;
copy both files into a code repository to activate. Authoring guidance:
[test-python](skills/test-python/SKILL.md).

### Versioning and releases

The `publish.yml` run derives the next patch version from the latest GitHub release, zips the
handbook, publishes the release (tag + generated notes + zip), then deploys the site. Nothing is
hardcoded — the site header shows the latest release automatically (fetched from GitHub via
`repo_url`), so a version only appears once the first release exists.

## Contributing

Authoring conventions live in
[`AGENTS.md`](https://github.com/aleksandrskrivickis/.agents/blob/main/AGENTS.md) — the single
always-on source, read by both Copilot and Claude Code when working in this repo. The rules that
matter most:

- A skill's folder name **must** equal the `name` in its `SKILL.md` frontmatter, or the skill is
  silently ignored.
- Keep `SKILL.md` lean; push exhaustive detail into `references/` so it loads only when needed.
- The `description` is the discovery surface — write "Use when…" with concrete trigger keywords.
- Follow the `SKILL.md` spine and the reference-file **Source** header, so every chapter reads the
  same way for an agent and for a person.
- No client names, tenant or subscription IDs, object IDs, IP ranges, internal hostnames or emails
  in a committed skill. Genericise the pattern; keep the gotcha.

Found a bug, or want to suggest a chapter?
[**Open an issue**](https://github.com/aleksandrskrivickis/.agents/issues).
