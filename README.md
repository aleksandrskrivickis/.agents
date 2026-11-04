# .agents

Shared, version-controlled **agent customizations** (skills) for the repositories under
`code-repositories/`. This folder sits at the workspace root, so a coding agent opened anywhere in
the workspace can discover these skills — and the repo can be cloned onto another machine to carry
them with you.

## Contents

```
.agents/
├── mkdocs.yml                        # GitHub Pages site config (MkDocs Material)
├── skills/                           # all skills live here, centralised
│   ├── develop-sdp/             # Spark Declarative Pipelines (SDP) + Databricks/Lakeflow extensions
│   ├── develop-pyspark/         # PySpark on Databricks: memory, serving, stateful, joins, throughput, envelope, file ingestion
│   ├── develop-scala/           # Scala on Spark: custom FileFormat DataSource, UnsafeRow, Maven shade, ScalaTest
│   ├── databricks-asset-bundles/ # Databricks Asset Bundles (databricks.yml): targets/modes, variables, resources, deploy
│   ├── test-python/             # Python test authoring (pytest layout, mocking, harness)
│   ├── test-workflows-github/   # GitHub Actions test pipeline pattern
│   └── test-workflows-devops/   # Azure DevOps test pipeline pattern
└── .github/
    ├── copilot-instructions.md       # repo-wide rules Copilot code review applies to PRs here
    ├── instructions/
    │   ├── skills.instructions.md    # path-specific review rules (applyTo: skills/**)
    │   └── tests.instructions.md     # how GitHub should generate tests (applyTo: src/**, tests/**)
    └── workflows/
        ├── pages.yml                 # renders skills → GitHub Pages site
        └── tests.yml                 # runs generated tests (template; mirrors the DevOps pipeline)
```

Each skill is a folder whose `SKILL.md` has YAML frontmatter (`name` **must** match the folder
name) plus an on-demand body; bulky material lives in `references/` and loads only when needed.

## How agents discover skills

Discovery is anchored at **workspace-folder roots**, not arbitrary nested subfolders. Because this
`.agents/` sits at the `code-repositories/` root (a workspace folder), its skills are visible to
every repo opened under that root. A skill buried inside a nested repo
(`code-repositories/some-repo/.agents/skills/…`) is **not** found when the workspace root is
`code-repositories/` — that nesting trap is exactly why these skills live here.

| Agent | Project-scope skill paths it scans (at a workspace root) | Personal/global path |
|---|---|---|
| GitHub Copilot (VS Code) | `.github/skills/`, `.agents/skills/`, `.claude/skills/` | `~/.copilot/skills/`, `~/.agents/skills/`, `~/.claude/skills/` |
| Claude Code | `.claude/skills/` (documented) | `~/.claude/skills/` |

In Copilot, loaded skills appear as **slash commands** (type `/`) and are also auto-selected by
their `description`. After adding/moving skills, run **Developer: Reload Window**.

> **Verified vs assumed.** Copilot's three project paths are documented. Whether Claude Code also
> scans `.agents/skills/` (rather than only `.claude/skills/`) is **not confirmed** — don't rely on
> it without testing that tool directly.

## Compatibility with other agent systems

Different tools scan different directories, so a single `.agents/skills/` is not automatically read
by everything:

- **Copilot** reads `.agents/skills/` directly — no extra setup here.
- **Claude Code** reads `.claude/skills/`. To serve the same skills to Claude without duplicating
  files, expose `.claude/skills` as a **symlink** to `.agents/skills` (see below), or keep a second
  real `.claude/skills/` folder.
- **Settings Sync does NOT sync skills.** VS Code Settings Sync roams prompts/instructions/agents
  (the user-prompts folder) but *not* skills. The mechanism for carrying skills across machines is
  **git** — this repo — not Settings Sync.

## Post-clone setup: the `.claude/skills` symlink (Claude Code only)

There is **no automation** for this — the symlink is a **per-clone, local step**, because it can't
be materialised reliably on every OS (see the Windows trap below). It is **gitignored**, so it never
travels with the repo. Create it after cloning **only if you use Claude Code**; Copilot needs
nothing (it reads `skills/` via the `.agents/skills` path directly).

From the repo root:

```bash
# macOS / Linux
mkdir -p .claude && ln -s ../skills .claude/skills      # .claude/skills -> ../skills
```

```bash
# Windows with Developer Mode on (or an elevated shell), in Git Bash
mkdir -p .claude && MSYS=winsymlinks:nativestrict ln -s ../skills .claude/skills
```

```bat
REM Windows without Developer Mode: a directory junction (no privilege needed, Windows-only)
mkdir .claude & mklink /J .claude\skills skills
```

Verify: `ls -l .claude/skills` should show `skills -> ../skills` (or a junction on Windows).

### The Windows trap (why this is manual, not committed)

- **Git stores symlinks portably** (a blob with mode `120000`), but **checkout materialization is
  OS-dependent.** On **Windows** a real symlink needs `SeCreateSymbolicLinkPrivilege` — Developer
  Mode (Settings → Privacy & security → For developers) or an elevated shell — plus
  `core.symlinks=true`. Without that, git writes a **plain text file containing the target path**,
  silently breaking it.
- `core.symlinks` is *local* config and `.gitattributes` has **no** symlink setting, so the repo
  can't force correct materialization. That's why the symlink is **not committed** and **not
  automated** — each clone creates the form that works on its OS.
- Because the target is **relative** (`../skills`), moving the link to a different-depth folder
  breaks it; recreate it there rather than `mv`-ing it.

Lowest-friction alternative: skip the symlink and keep a second **real** `.claude/skills/` folder
(one duplicate) if you dislike the per-OS setup.

## Regulating GitHub code review (self-review demo)

This repo doubles as a worked example of how to **govern GitHub Copilot code review** — and it
applies the rules to its **own** pull requests. GitHub's PR reviewer reads review customization from
**the repository under review**, on the **head (PR) branch**, so these files take effect in the same
PR that changes them:

| Layer | File | Role |
|---|---|---|
| Repo-wide instructions | `.github/copilot-instructions.md` | Always-on rules the reviewer applies to every PR here |
| Path-specific instructions | `.github/instructions/skills.instructions.md` (`applyTo: skills/**`) | Rules scoped to the skills; supports `excludeAgent: "code-review" \| "cloud-agent"` to target one agent |
| Agent instructions | `AGENTS.md` (root) | Cross-tool always-on rules; also consumed by review |

Review is regulated with **instructions only** — a dedicated "code-review" skill is intentionally
omitted, since reviewing PRs is already Copilot code review's built-in job; instructions are what
shape *how* it reviews. (Skills remain for on-demand *authoring/analysis* workflows, not to re-state
review itself.)

**Important:** GitHub code review reads this customization from **the repo under review**, not from
another repo's `.agents/skills`. So this shared repo can only self-review; to regulate review in
another project, copy the same `.github/` instruction files into that repository.

**Manual steps (settings, not files):**
- Turn on automatic review: repo **Settings → Copilot → Code review**, or an organization/branch
  **ruleset** that requests Copilot review. Custom instructions are **on by default** for review.
- Pick a **review effort level** (Lite / Balanced / Max) to match risk.
- Full-context agentic review needs **GitHub Actions runners**; with Actions disabled, review falls
  back to a more limited mode.

Caveat: instructions are the reliable lever here — they are always applied. (A dedicated review
*skill* was omitted on purpose; skills activate only "when relevant", so they're better kept for
on-demand authoring/analysis tasks than for enforcing review rules.)

## Automated test generation (template)

The same instruction mechanism also demonstrates **test automation**, modeled on
`databricks-web-scraping`'s unit-test layout and its Azure DevOps test pipeline:

- `.github/instructions/tests.instructions.md` (`applyTo: src/**,tests/**`) tells Copilot cloud
  agent **how** to generate tests — mirror `src/` under `tests/unit/`, `test_<module>.py` naming
  preserving hyphens/stage numbers, mock external I/O, keep integration tests skippable.
- `.github/workflows/tests.yml` runs them on push/PR as a **GitHub Actions** mirror of the DevOps
  pipeline (uv + advisory ruff + pytest + JUnit artifact).

It is a **template**: this repo is Markdown-only, so the workflow guards on `pyproject.toml` and
no-ops here (stays green). Copy both files into a code repository — or broaden/narrow the
`applyTo` glob — to activate. GitHub reads these from the repo under review/work, not from another
repo's `.agents/`.

## Published knowledge site (GitHub Pages)

The skills are also published as a browsable site, so they read as general reference and not only
in-editor context. `.github/workflows/pages.yml` renders the skills into a browsable **handbook**
with **Zensical** (the maintained successor to Material for MkDocs) and deploys to GitHub Pages on
each push to `main` that touches `skills/`, `README.md`, `AGENTS.md`, or `mkdocs.yml`. `README.md`
is the site's home page; the theme is configured in `mkdocs.yml` and the navigation is built
automatically from the staged pages.

One-time setup: **Settings → Pages → Source = "GitHub Actions"**.

> ⚠️ **Confidentiality — read before going public.** GitHub Pages is **public** on public repos
> (and on Free/Pro even when the repo is private). Skills that carry **internal** material are kept
> OUT of this repo entirely via `.gitignore` (and dropped from the staged content in the Pages build
> as a second guard), so they never reach the remote or the published site. The skills committed
> here are generic, public-safe knowledge.

Notes:
- The build is **non-strict**, so the internal sibling-repo links
  (`../../../databricks-web-scraping/...`) don't fail it — but they **404 on the public site**. Make
  public-facing skills self-contained, or replace those links with plain text.
- Local preview: `pip install zensical`, then stage the content the same way CI does and serve it:
  `rm -rf docs site && mkdir -p docs docs/.github/instructions docs/contributing && cp -R skills docs/skills && rm -rf docs/skills/api-lawstronaut && cp README.md docs/index.md && cp .github/copilot-instructions.md docs/.github/ && cp .github/instructions/*.md docs/.github/instructions/ && cp AGENTS.md docs/contributing/index.md && zensical serve`
  (the generated `docs/` and `site/` dirs are gitignored — neither Zensical nor MkDocs allow a
  `docs_dir` equal to the config file's own directory, so content is staged into a child `docs/`;
  the internal `api-lawstronaut` skill is dropped from the staging).

## Using these skills on another computer

1. Clone this repo to the workspace root so the path is `code-repositories/.agents/` (skills apply
   to every repo opened under that root):
   ```bash
   git clone <remote-url> /path/to/code-repositories/.agents
   ```
   …or clone into a **personal/global** skills path to make them apply in *every* workspace on that
   machine:
   ```bash
   git clone <remote-url> ~/.copilot/skills      # or ~/.agents/skills
   ```
2. `git pull` to update; **Developer: Reload Window** in VS Code to pick up changes.

## Authoring conventions

- Folder name **must** equal the `name` in `SKILL.md` frontmatter, else the skill is silently
  ignored.
- The `description` is the discovery surface — write "Use when…" with concrete trigger keywords.
- Keep `SKILL.md` lean; push exhaustive detail into `references/` (progressive loading). Use
  relative `./references/...` links within a skill.
- The published site's navigation is **built automatically** by Zensical from the staged `docs/`
  tree: each skill folder appears under **Skills**, and page titles come from each file's first `#`
  heading. There is no nav list to maintain.
- Links into a sibling repo are workspace-relative from here (e.g.
  `../../../databricks-web-scraping/...`); they resolve only when that repo is a sibling under the
  same root.
