---
name: obsidian-tags-generate
description: 'Use when generating or applying YAML tags to Obsidian notes from an existing vault taxonomy. Covers Claude chat tags, GitHub Copilot chat notes, nested tags, and the tag helper script.'
---

# Obsidian tag generation

> **What this is.** A workflow and helper that tag Obsidian notes by using the tags already present in Claude chat notes. The taxonomy stays in the vault, not in this skill. The helper applies topic rules to GitHub Copilot notes and preserves note text.
>
> Use the [Copilot export skill](../obsidian-github-copilot/SKILL.md) to create the source notes. This skill does not export chats.

## Rules that prevent most failures

- Read existing `tags` lists from `LLM chats/claude` before you assign tags.
- Tag the subject of each conversation, not the chat provider.
- Prefer an existing root tag and an existing nested tag such as `engineering` and `engineering/python`.
- Use lowercase tags and slash-separated categories.
- Add no more than three tags to one note.
- Add a new nested tag only when no existing tag fits the subject.
- Preserve all other frontmatter fields and the full note body.
- Do not add Obsidian wikilinks.
- Use dry-run mode before you change notes.

## Commands

Run this from the workspace root to review tag suggestions:

```bash
python .agents/skills/obsidian-tags-generate/scripts/generate_tags.py --vault ".obsidian/General vault" --dry-run
```

Remove `--dry-run` to apply the tags. The helper reads Claude tags at runtime and updates notes under `LLM chats/github`.

## When to use this skill

Use this skill when you need to tag new Obsidian chat notes or align tags with the existing Claude chat taxonomy.
