# AGENTS.md

Always-on guidance for an agent **working on this skills repo** (authoring/maintaining skills).
`README.md` is the full reference — read it for discovery rules, cross-agent compatibility, and the
symlink/Windows caveats. Don't restate the README here; keep this file to rules an agent must not
miss.

## Scope

This file governs edits **inside `.agents/`** only. It is not cross-repo guidance for sibling
projects like `databricks-web-scraping/`; those carry their own `AGENTS.md`.

## Rules

- A skill's folder name **must** equal the `name` in its `SKILL.md` frontmatter, or it is silently
  ignored. Quote `description` values that contain a colon.
- Keep `SKILL.md` lean; push exhaustive detail into `references/` and link with `./references/...`.
  The `description` is the discovery surface — write "Use when…" with concrete trigger keywords.
- `.claude/skills` is a **local, gitignored** per-clone symlink to `skills/` (Claude Code only);
  it is not committed or automated. See `README.md` → "Post-clone setup".
- Links into a sibling repo are workspace-relative from a skill file
  (e.g. `../../../databricks-web-scraping/...`) and resolve only when that repo is a sibling under
  the same workspace root.
- Don't add `.github/copilot-instructions.md` as a dumping ground; it holds **review** rules for
  Copilot code review (see `README.md` → "Regulating GitHub code review"). This `AGENTS.md` stays
  the single always-on source for authoring conventions — update it in the same commit as any
  convention change.

## Presentation (the skills are also published documentation)

The skills render to a public handbook via GitHub Pages, so every file has two audiences: an agent
loading it as context, and a person reading it cold. Both are served by the same shape — keep it.

- **`SKILL.md` spine**, in this order, omitting what doesn't apply: `# Title`; a
  `> **What this is.**` blockquote (subject, where the knowledge came from, what it does *not*
  cover, and where to go instead); `## Detailed references`; `## The rules that prevent most …`;
  `## Quick symptom → fix index`; `## Commands`; `## Upstream documentation (sources)`;
  `## When to use this skill`; `## Related skills`.
- **Reference-file spine:** `# Title`, then a `> **Source.**` blockquote giving provenance and the
  confidence-tag legend (`[repo]` / `[docs]` / `[deduced]` / `[?]`), then topic sections.
- **Never write "this repo".** A site reader has no repo. Say "the source project", or name the
  pattern generically.
- **Cross-skill mentions must be links**, not bold text: `../<skill>/SKILL.md` from a `SKILL.md`,
  `../../<skill>/SKILL.md` from a reference. Those paths resolve both in-editor and on the site.
- **Callouts are `> **Label.** …` blockquotes.** Do not use `!!!`-style admonitions: they render as
  literal text in GitHub, in VS Code preview, and in agent context.
- `skills/README.md` is the handbook's Skills landing page — add a row when you add a skill, and
  keep the repo `README.md` contents tree in step.
- No client names, tenant/subscription IDs, object IDs, IP ranges, internal hostnames or emails in a
  committed skill. Genericise the pattern; keep the gotcha.
