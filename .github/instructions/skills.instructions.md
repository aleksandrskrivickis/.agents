---
applyTo: "skills/**/*.md"
---

Path-specific review rules for the distributable skills under `skills/`. These apply in addition to
`.github/copilot-instructions.md`. (To scope a rule to one agent, add `excludeAgent: "code-review"`
or `"cloud-agent"` to this frontmatter — omitted here so both the reviewer and the cloud agent use
these rules.)

When reviewing a change to a file under `skills/`:

- The containing skill folder must have a `SKILL.md` whose `name` equals the folder name.
- Prefer moving tables and long reference material out of `SKILL.md` into `references/`, linked with
  `./references/...`. Flag reference content growing inside `SKILL.md`.
- Every relative link must resolve: `./references/...` within the skill; `../../../<repo>/...` only
  for a sibling repo under the same workspace root (flag a bare `../../../<path>` that assumes files
  at the workspace root).
- Reference files carrying **deduced or external** information must state their source/confidence
  with a per-claim tag (`[repo]` / `[deduced]` / `[?]`); flag unlabelled claims presented as fact.
