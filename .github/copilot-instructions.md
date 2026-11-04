# Copilot instructions — `.agents` skills repo

This repository stores shared agent **skills** (Markdown with YAML frontmatter). `AGENTS.md` (repo
root) holds the authoring conventions; this file tells **Copilot code review** what to check when a
pull request is opened here. It is read automatically on the PR's **head branch**, so review-rule
changes take effect in the same PR that introduces them.

## What to flag in review

- **Frontmatter validity.** Every `SKILL.md` must have YAML frontmatter whose `name` exactly
  matches its folder name, plus a non-empty `description`. A mismatch or missing field makes the
  skill silently undiscoverable — flag it. Quote any value containing a colon.
- **Lean `SKILL.md`.** The body should stay short; exhaustive detail belongs in `references/`,
  linked with `./references/...`. Flag large reference blocks inlined into `SKILL.md`.
- **Reference-link hygiene.** Keep resource links one level deep. Flag links that will not resolve;
  sibling-repo links are intentional only in the form `../../../<repo>/...`.
- **Discovery surface.** The `description` should follow "Use when…" with concrete trigger
  keywords. Flag vague descriptions ("a helpful skill").
- **No secrets or credentials** in any skill or reference file.
- **No duplication drift.** Authoring rules live once in `README.md`/`AGENTS.md`. Flag content
  copied between them, or into a skill, that will drift out of sync.

Keep review comments specific and actionable — cite the file and line, and prefer a concrete fix.
