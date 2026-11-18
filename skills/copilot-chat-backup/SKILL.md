---
name: copilot-chat-backup
description: 'Use when exporting GitHub Copilot chat sessions from VS Code to Obsidian Markdown. Covers workspaceStorage hash detection, JSON and JSONL sessions, .code-workspace files, and recurring exports.'
---

# Copilot chat export

> **What this is.** A local helper that exports visible Copilot chat turns as Markdown notes. It finds the workspace storage folder from `workspace.json`, reads JSON and JSONL sessions, and writes notes to `LLM chats/github/YYYY/MM` in an Obsidian vault. VS Code treats this storage format as internal, so future versions can need parser changes.
>
> Chat notes can contain private information. Protect the vault and any remote sync or backup service.

## Rules that prevent most failures

- Pass the Obsidian vault root as the destination.
- Run the helper from the workspace root, or pass `--workspace` with a folder path.
- Pass the `.code-workspace` file to `--workspace` when the current folder belongs to more than one workspace file.
- Use `--dry-run` to list note paths before the export.
- Pass `--storage-root` when VS Code uses Insiders, a custom profile, or a non-default user-data path.
- The exporter reads `.json` and `.jsonl` chat files. It prefers JSONL when both files have the same session ID.
- Each note contains user and Copilot text. The exporter omits tool-call records and hidden transcript requests.
- The exporter uses standard Markdown. It does not create Obsidian wikilinks.
- The exporter replaces a note when its session runs again. It does not delete notes for removed sessions.
- The exporter does not include debug logs or chat editing sessions.

## Commands

Set the destination to the vault root. Run this command from the workspace root:

```bash
python .agents/skills/copilot-chat-backup/scripts/export_copilot_chats_to_obsidian.py --workspace "$PWD" --destination "./.obsidian/General vault" --dry-run
```

Remove `--dry-run` to write the notes. To select a workspace file, pass its path:

```bash
python .agents/skills/copilot-chat-backup/scripts/export_copilot_chats_to_obsidian.py --workspace "C:/path/workspace.code-workspace" --destination "C:/code-repositories/.obsidian/General vault"
```

The exporter writes notes to `<destination>/LLM chats/github/YYYY/MM/<topic>.md`. It adds the session ID to a filename when titles collide.

## Recurring backup

Use Windows Task Scheduler to run the exporter on a daily or weekly trigger:

1. Create a task and add a daily or weekly trigger.
2. Set `Program/script` to the full path of `python.exe`.
3. Set `Add arguments` to the exporter path, workspace path, and vault path:

	```text
	"C:/path/.agents/skills/copilot-chat-backup/scripts/export_copilot_chats_to_obsidian.py" --workspace "C:/path/workspace.code-workspace" --destination "C:/code-repositories/.obsidian/General vault"
	```

4. Run the task as the same Windows account that runs VS Code.
5. Add `--storage-root "C:/Users/<user>/AppData/Roaming/Code/User/workspaceStorage"` if the task does not set `APPDATA`.

The scheduled task calls Python directly. It does not use a shell. Each run updates notes for existing sessions and keeps notes for sessions that no longer appear in VS Code.

## When to use this skill

Use this skill when you need Obsidian notes from Copilot chat files in a VS Code workspace.
