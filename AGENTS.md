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
