# The agent skills handbook

<p align="center">
  <strong>Production-tested engineering knowledge, written so a coding agent and a human can read the same page.</strong>
</p>

<p align="center">
  <a href="https://aleksandrskrivickis.github.io/.agents/"><img alt="Read the handbook" src="https://img.shields.io/badge/read%20the-handbook-3f51b5?style=flat-square"></a>
  <a href="https://github.com/aleksandrskrivickis/.agents/actions/workflows/publish.yml"><img alt="Publish" src="https://img.shields.io/github/actions/workflow/status/aleksandrskrivickis/.agents/publish.yml?branch=main&label=site&style=flat-square"></a>
  <a href="https://github.com/aleksandrskrivickis/.agents/releases"><img alt="Release" src="https://img.shields.io/github/v/release/aleksandrskrivickis/.agents?label=release&color=3f51b5&style=flat-square"></a>
  <img alt="Chapters" src="https://img.shields.io/badge/chapters-9-3f51b5?style=flat-square">
  <img alt="Agents" src="https://img.shields.io/badge/agents-Copilot%20%C2%B7%20Claude%20Code-3f51b5?style=flat-square">
  <a href="https://github.com/aleksandrskrivickis/.agents/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-GPL--3.0-3f51b5?style=flat-square"></a>
</p>

---

Nine chapters on building data platforms on Databricks and Azure — what breaks, why it breaks, and
what the fix actually was. Every entry came out of a production incident, a failed deploy, or a
value nobody could defend in review.

They are **agent skills**: Markdown files that GitHub Copilot and Claude Code load as context when
the task matches. They are also just good documentation, so they are published as a
**[browsable handbook](https://aleksandrskrivickis.github.io/.agents/)** you can read without an
editor open.

## What it covers

```
┌─ your transform code ───────────────────────────────────────────────────┐
│  develop-pyspark           Arrow & memory · serving · chunking · joins  │
│  develop-scala             custom DataSource · UnsafeRow · shading      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─ the declarative framework ─────────────────────────────────────────────┐
│  develop-sdp               tables & flows · expectations · event log    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─ how it ships ──────────────────────────────────────────────────────────┐
│  databricks-asset-bundles  targets · variables · Lakebase · deploy      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─ what it runs on ───────────────────────────────────────────────────────┐
│  develop-infrastructure    Bicep · Terraform UC · DevOps pipelines      │
└─────────────────────────────────────────────────────────────────────────┘

┌─ across all of it ──────────────────────────────────────────────────────┐
│  test-python               harness · local Spark · wheel & bundle       │
│  test-workflows-*          GitHub Actions · Azure DevOps                │
│  document-decisions        decision register · findings log             │
└─────────────────────────────────────────────────────────────────────────┘
```

## The chapters

**Data pipelines**

| Chapter | What you get |
|---|---|
| [develop-sdp](skills/develop-sdp/SKILL.md) | Spark Declarative Pipelines: the `dp` API, streaming table vs materialized view, choosing an expectations policy, the event log, refresh semantics and a triage playbook. Flags what is Apache SDP vs Databricks-only. |
| [develop-pyspark](skills/develop-pyspark/SKILL.md) | What goes wrong inside a transform: pandas-UDF OOM, intermittent Arrow `ChunkedArray` crashes, model serving and registration, document chunking vs embedding context windows, skew, throughput, never-raise API calls. |
| [develop-scala](skills/develop-scala/SKILL.md) | A custom Spark `FileFormat` DataSource — `UnsafeRow` construction, short-name registration, shaded packaging. |

**Deployment and infrastructure**

| Chapter | What you get |
|---|---|
| [databricks-asset-bundles](skills/databricks-asset-bundles/SKILL.md) | `databricks.yml`: targets and deployment modes, variable interpolation, resource types, Lakebase and its Data API, post-deploy runs, and the deploy-time traps. |
| [develop-infrastructure](skills/develop-infrastructure/SKILL.md) | The Azure platform underneath: Bicep at subscription scope in four planes, Terraform for Unity Catalog, and the Azure DevOps pipelines that orchestrate both through a locked-down network. |

**Testing and practice**

| Chapter | What you get |
|---|---|
| [test-python](skills/test-python/SKILL.md) | pytest layout, testing notebook modules that cannot be imported, a hardened local `SparkSession` fixture, wheel and bundle-validation tests. |
| [test-workflows-github](skills/test-workflows-github/SKILL.md) | A GitHub Actions lint-and-test workflow, and how merges actually get gated. |
| [test-workflows-devops](skills/test-workflows-devops/SKILL.md) | The Azure DevOps equivalent, including the Azure Repos `pr:` trigger trap. |
| [document-decisions](skills/document-decisions/SKILL.md) | How to write down the constants and thresholds a system rests on, so "nobody knows why this is 0.8" stops being true. |

→ **[Full chapter index, with a reading order](skills/README.md)**

## Start here

**Just want to read it.** → **[aleksandrskrivickis.github.io/.agents](https://aleksandrskrivickis.github.io/.agents/)**.
Start with [document-decisions](skills/document-decisions/SKILL.md) — it is the shortest, and it
explains why the other chapters keep rationale next to values.

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

Every `SKILL.md` follows the same spine, which is what makes the handbook read as one book:

| Section | What it gives you |
|---|---|
| Opening note | The subject, where the knowledge came from, and what it does **not** cover |
| Detailed references | The deep material, one file per topic |
| Rules | The handful of things that prevent most failures in this area |
| Symptom → fix index | A lookup table for when something is already broken |
| Commands · When to use · Related | The commands worth memorising, and where the boundaries are |

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

| Agent | Project-scope paths it scans (at a workspace root) | Personal/global path |
|---|---|---|
| GitHub Copilot (VS Code) | `.github/skills/`, `.agents/skills/`, `.claude/skills/` | `~/.copilot/skills/`, `~/.agents/skills/`, `~/.claude/skills/` |
| Claude Code | `.claude/skills/` (documented) | `~/.claude/skills/` |

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

<details markdown="1">
<summary><strong>Why this is manual rather than committed — the Windows trap</strong></summary>

- **Git stores symlinks portably** (a blob with mode `120000`), but **checkout materialization is
  OS-dependent.** On Windows a real symlink needs `SeCreateSymbolicLinkPrivilege` — Developer Mode
  (Settings → Privacy & security → For developers) or an elevated shell — plus `core.symlinks=true`.
  Without that, git writes a **plain text file containing the target path**, silently breaking it.
- `core.symlinks` is *local* config and `.gitattributes` has no symlink setting, so the repo cannot
  force correct materialization. That is why the symlink is neither committed nor automated — each
  clone creates the form that works on its OS.
- The target is **relative** (`../skills`), so moving the link to a different-depth folder breaks it.
  Recreate it there rather than moving it.

Lowest-friction alternative: skip the symlink and keep a second **real** `.claude/skills/` folder.

</details>

## The published handbook

`.github/workflows/publish.yml` renders the skills with **Zensical** (the maintained successor to
Material for MkDocs) and deploys to GitHub Pages on each push to `main` that touches `skills/`,
`README.md`, `AGENTS.md`, `mkdocs.yml` or the review instructions — the same run also versions and
releases the handbook (see below). This file is the site's home page; navigation is built
automatically from the staged tree, so there is no nav list to maintain.

One-time setup: **Settings → Pages → Source = "GitHub Actions"**.

> ⚠️ **Confidentiality — read before going public.** GitHub Pages is **public** on public repos, and
> on Free/Pro even when the repo is private. Skills carrying **internal** material are kept out of
> this repo entirely via `.gitignore`, and dropped from the staged content in the Pages build as a
> second guard, so they never reach the remote or the published site. Everything committed here is
> generic, public-safe knowledge.

<details markdown="1">
<summary><strong>Local preview, and the link rules that keep both renderings working</strong></summary>

```bash
pip install zensical
rm -rf docs site && mkdir -p docs docs/github/instructions docs/contributing
cp -R skills docs/skills
cp README.md docs/index.md
cp .github/copilot-instructions.md docs/github/
cp .github/instructions/*.md docs/github/instructions/
cp AGENTS.md docs/contributing/index.md
zensical serve
```

`docs/` and `site/` are gitignored — neither Zensical nor MkDocs allows a `docs_dir` equal to the
config file's own directory, so content is staged into a child `docs/`.

Because staging copies `skills/` wholesale and this file becomes `docs/index.md`:

- **Relative links into `skills/…` resolve in both renderings** — use them freely.
- **`AGENTS.md` and `.github/*` move during staging**, so link them with absolute GitHub URLs
  instead of relative paths.
- Cross-skill links are `../<skill>/SKILL.md` from a `SKILL.md`, `../../<skill>/SKILL.md` from a
  reference file. Those survive staging unchanged.
- The build is **non-strict**, so a link into a sibling repo won't fail it — but it **404s on the
  public site**. Keep public-facing skills self-contained.

</details>

## This repo as a worked example

It also demonstrates two GitHub automation patterns on itself.

<details markdown="1">
<summary><strong>Governing Copilot code review — applied to this repo's own pull requests</strong></summary>

GitHub's PR reviewer reads review customization from **the repository under review**, on the **head
(PR) branch**, so these files take effect in the same PR that changes them:

| Layer | File | Role |
|---|---|---|
| Repo-wide | [`.github/copilot-instructions.md`](https://github.com/aleksandrskrivickis/.agents/blob/main/.github/copilot-instructions.md) | Always-on rules the reviewer applies to every PR here |
| Path-specific | [`.github/instructions/skills.instructions.md`](https://github.com/aleksandrskrivickis/.agents/blob/main/.github/instructions/skills.instructions.md) (`applyTo: skills/**`) | Rules scoped to the skills; `excludeAgent` can target one agent |
| Agent instructions | [`AGENTS.md`](https://github.com/aleksandrskrivickis/.agents/blob/main/AGENTS.md) | Cross-tool always-on rules; also consumed by review |

Review is regulated with **instructions only**. A dedicated "code-review" skill is intentionally
omitted — reviewing PRs is already Copilot code review's built-in job, and instructions are what
shape *how* it reviews. Skills stay for on-demand authoring and analysis.

GitHub reads this customization from the repo under review, not from another repo's
`.agents/skills`, so this shared repo can only self-review. To regulate review elsewhere, copy the
same `.github/` instruction files into that repository.

**Manual steps (settings, not files):** turn on automatic review under **Settings → Copilot → Code
review** or via an organization/branch ruleset; pick a review effort level (Lite / Balanced / Max);
note that full-context agentic review needs GitHub Actions runners, and falls back to a more limited
mode with Actions disabled.

</details>

<details markdown="1">
<summary><strong>Automated test generation (a copyable template)</strong></summary>

- [`.github/instructions/tests.instructions.md`](https://github.com/aleksandrskrivickis/.agents/blob/main/.github/instructions/tests.instructions.md)
  (`applyTo: src/**,tests/**`) tells the Copilot cloud agent **how** to generate tests — mirror
  `src/` under `tests/unit/`, `test_<module>.py` naming that preserves hyphens and stage numbers,
  mock external I/O, keep integration tests skippable.
- `.github/workflows/tests.yml` runs them on push and PR as a GitHub Actions mirror of the Azure
  DevOps pipeline (uv + advisory ruff + pytest + a JUnit artifact).

It is a **template**: this repo is Markdown-only, so the workflow guards on `pyproject.toml` and
no-ops here, staying green. Copy both files into a code repository — or widen the `applyTo` glob —
to activate. The matching authoring guidance is in
[test-python](skills/test-python/SKILL.md).

</details>

<details markdown="1">
<summary><strong>Versioning and releases</strong></summary>

The single `.github/workflows/publish.yml` run does it all: it derives the next patch version from
the latest GitHub release, stages the docs, builds the site, zips the staged docs as
`agent-skills-handbook-vX.Y.Z.zip`, publishes the release (tag `vX.Y.Z` + generated notes + the zip),
then deploys the site to Pages. Nothing is hardcoded — the site **header** shows the latest release
automatically (Zensical requests it from GitHub via `repo_url`). The `docs/`, `site/` and `dist/`
build dirs are gitignored and never committed.

</details>

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

## Maintainer

Created and maintained by **Aleksandrs Krivickis** —
[LinkedIn](https://www.linkedin.com/in/aleksandrskrivickis/).
Licensed under [GPL-3.0](https://github.com/aleksandrskrivickis/.agents/blob/main/LICENSE).
