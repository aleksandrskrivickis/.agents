from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname


def _parse_jsonc(text: str) -> dict:
    cleaned = []
    index = 0
    in_string = False
    escaped = False

    while index < len(text):
        character = text[index]

        if in_string:
            cleaned.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue

        if character == '"':
            in_string = True
            cleaned.append(character)
            index += 1
            continue

        if text.startswith("//", index):
            newline = text.find("\n", index)
            if newline == -1:
                break
            cleaned.append("\n")
            index = newline + 1
            continue

        if text.startswith("/*", index):
            end_comment = text.find("*/", index + 2)
            if end_comment == -1:
                raise ValueError("The workspace file has an unclosed comment.")
            cleaned.extend("\n" for character in text[index : end_comment + 2] if character == "\n")
            index = end_comment + 2
            continue

        if character == ",":
            next_value = index + 1
            while next_value < len(text) and text[next_value].isspace():
                next_value += 1
            if next_value < len(text) and text[next_value] in "]}":
                index += 1
                continue

        cleaned.append(character)
        index += 1

    return json.loads("".join(cleaned))


def _path_from_file_uri(uri: str) -> Path:
    parsed = urlsplit(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Unsupported workspace URI: {uri}")

    path = url2pathname(unquote(parsed.path))
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    return Path(path).resolve()


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _workspace_folders(workspace_file: Path) -> list[Path]:
    data = _parse_jsonc(workspace_file.read_text(encoding="utf-8"))
    folders = []
    for folder in data.get("folders", []):
        folder_path = folder.get("path")
        if folder_path:
            path = Path(folder_path)
            if not path.is_absolute():
                path = workspace_file.parent / path
            folders.append(path.resolve())
    return folders


def find_workspace_storage(storage_root: Path, workspace: Path) -> Path:
    workspace = workspace.resolve()
    exact_matches = []
    containing_matches = []

    for metadata_file in storage_root.glob("*/workspace.json"):
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            stored_workspace = _path_from_file_uri(metadata["workspace"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue

        if stored_workspace.suffix.lower() == ".code-workspace":
            if workspace.suffix.lower() == ".code-workspace":
                if stored_workspace == workspace:
                    exact_matches.append(metadata_file.parent)
                continue

            try:
                roots = _workspace_folders(stored_workspace)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        else:
            roots = [stored_workspace]

        for root in roots:
            if root == workspace:
                exact_matches.append(metadata_file.parent)
                break
            if _contains(root, workspace):
                containing_matches.append(metadata_file.parent)
                break

    matches = exact_matches or containing_matches
    unique_matches = list(dict.fromkeys(matches))
    if not unique_matches:
        raise FileNotFoundError(f"No VS Code workspace storage matches: {workspace}")
    if len(unique_matches) > 1:
        locations = ", ".join(str(path) for path in unique_matches)
        raise RuntimeError(f"More than one workspace storage matches. Specify --workspace. Found: {locations}")
    return unique_matches[0]


def _path_part(container: dict | list, part: str | int) -> str | int:
    if isinstance(container, list):
        return int(part)
    return str(part)


def _get_path(root: dict | list, path: list[str | int]) -> dict | list:
    current = root
    for part in path:
        current = current[_path_part(current, part)]
    return current


def _set_path(root: dict | list, path: list[str | int], value: object) -> None:
    if not path:
        raise ValueError("A JSONL update has an empty path.")
    parent = _get_path(root, path[:-1])
    parent[_path_part(parent, path[-1])] = value


def _load_jsonl_session(path: Path) -> dict:
    state = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        event = json.loads(line)
        kind = event.get("kind")

        if kind == 0:
            if state is not None:
                raise ValueError(f"Multiple JSONL snapshots in {path.name}.")
            state = copy.deepcopy(event["v"])
        elif state is None:
            raise ValueError(f"JSONL update precedes its snapshot in {path.name}:{line_number}.")
        elif kind == 1:
            _set_path(state, event["k"], event["v"])
        elif kind == 2:
            target = _get_path(state, event["k"])
            if not isinstance(target, list):
                raise ValueError(f"Invalid JSONL list update in {path.name}:{line_number}.")
            if "v" in event:
                values = event["v"] if isinstance(event["v"], list) else [event["v"]]
                if "i" in event:
                    target[int(event["i"]) : int(event["i"])] = copy.deepcopy(values)
                else:
                    target.extend(copy.deepcopy(values))
            else:
                del target[int(event["i"])]
        else:
            raise ValueError(f"Unsupported JSONL event type in {path.name}:{line_number}: {kind}")

    if state is None:
        raise ValueError(f"No JSONL snapshot found in {path.name}.")
    return state


def load_sessions(source: Path) -> tuple[list[tuple[Path, dict]], int]:
    files_by_session = {}
    for path in source.iterdir():
        if path.suffix not in {".json", ".jsonl"} or not path.is_file():
            continue
        existing = files_by_session.get(path.stem)
        if existing is None or path.suffix == ".jsonl":
            files_by_session[path.stem] = path

    sessions = []
    failures = 0
    for path in sorted(files_by_session.values()):
        try:
            if path.suffix == ".jsonl":
                session = _load_jsonl_session(path)
            else:
                session = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(session, dict) or not isinstance(session.get("requests"), list):
                raise ValueError("The session has no requests list.")
            sessions.append((path, session))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures += 1
            print(f"Skipped {path.name}: {error}", file=sys.stderr)
    return sessions, failures


def _request_text(message: object) -> str:
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, dict):
        return ""

    text = message.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    parts = message.get("parts", [])
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()


def _response_text(response: object) -> str:
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, list):
        return ""

    return "".join(
        item["value"] for item in response if isinstance(item, dict) and isinstance(item.get("value"), str)
    ).strip()


def _conversation(session: dict) -> list[tuple[str, str]]:
    turns = []
    for request in session["requests"]:
        if not isinstance(request, dict) or request.get("hiddenFromTranscript"):
            continue
        user_text = _request_text(request.get("message"))
        assistant_text = _response_text(request.get("response"))
        if user_text or assistant_text:
            turns.append((user_text, assistant_text))
    return turns


def _session_date(session: dict, path: Path) -> datetime:
    timestamp = session.get("creationDate")
    if not isinstance(timestamp, (int, float)):
        requests = session.get("requests", [])
        timestamp = requests[0].get("timestamp") if requests and isinstance(requests[0], dict) else None
    if not isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.fromtimestamp(timestamp / 1000)


def _session_title(session: dict, turns: list[tuple[str, str]], session_id: str) -> str:
    title = session.get("customTitle")
    if isinstance(title, str) and title.strip():
        return title.strip()
    if turns:
        first_line = turns[0][0].splitlines()[0] if turns[0][0] else ""
        if first_line:
            return first_line[:100].strip()
    return f"Copilot chat {session_id[:8]}"


def _topic_slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:80].rstrip("-") or "copilot-chat"


def _markdown(session: dict, session_id: str, title: str, created: datetime, turns: list[tuple[str, str]]) -> str:
    frontmatter = {
        "title": title,
        "session_id": session_id,
        "created": created.date().isoformat(),
        "source": "github-copilot",
    }
    lines = ["---"]
    lines.extend(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items())
    lines.extend(["---", "", f"# {title}", ""])

    for index, (user_text, assistant_text) in enumerate(turns, start=1):
        lines.extend([f"## Turn {index}", ""])
        if user_text:
            lines.extend(["### User", "", user_text, ""])
        if assistant_text:
            lines.extend(["### GitHub Copilot", "", assistant_text, ""])

    return "\n".join(lines).rstrip() + "\n"


def export_to_obsidian(storage: Path, vault: Path, dry_run: bool = False) -> tuple[int, int, int]:
    source = storage / "chatSessions"
    if not source.is_dir():
        raise FileNotFoundError(f"Chat sessions folder does not exist: {source}")

    sessions, failures = load_sessions(source)
    notes = []
    for path, session in sessions:
        turns = _conversation(session)
        if not turns:
            continue
        session_id = str(session.get("sessionId") or path.stem)
        created = _session_date(session, path)
        title = _session_title(session, turns, session_id)
        notes.append((path, session_id, title, created, turns))

    slug_counts = Counter((created.strftime("%Y/%m"), _topic_slug(title)) for _, _, title, created, _ in notes)
    output_root = vault / "LLM chats" / "github"
    written = 0

    for path, session_id, title, created, turns in notes:
        slug = _topic_slug(title)
        relative_dir = Path(created.strftime("%Y")) / created.strftime("%m")
        filename = f"{slug}.md"
        target = output_root / relative_dir / filename
        collision = slug_counts[(created.strftime("%Y/%m"), slug)] > 1
        if collision or (target.exists() and f'session_id: "{session_id}"' not in target.read_text(encoding="utf-8")):
            filename = f"{slug}-{session_id[:8]}.md"
            target = output_root / relative_dir / filename

        if dry_run:
            print(target)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_markdown(session, session_id, title, created, turns), encoding="utf-8")
        written += 1

    return len(notes), written, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Export VS Code Copilot chats as Obsidian Markdown notes.")
    parser.add_argument("--destination", type=Path, required=True, help="Obsidian vault root folder.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace folder or .code-workspace file.")
    parser.add_argument(
        "--storage-root",
        type=Path,
        help="VS Code workspaceStorage folder. Defaults to the Stable VS Code user-data path.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List note paths without writing files.")
    arguments = parser.parse_args()

    storage_root = arguments.storage_root
    if storage_root is None:
        app_data = os.environ.get("APPDATA")
        if not app_data:
            parser.error("Set APPDATA or pass --storage-root.")
        storage_root = Path(app_data) / "Code" / "User" / "workspaceStorage"

    try:
        storage = find_workspace_storage(storage_root, arguments.workspace)
        total, written, failures = export_to_obsidian(storage, arguments.destination.resolve(), arguments.dry_run)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    action = "Would export" if arguments.dry_run else "Exported"
    print(f"{action} {total} chat notes to {arguments.destination.resolve() / 'LLM chats' / 'github'}")
    if failures:
        print(f"Skipped {failures} session files due to errors", file=sys.stderr)
        return 1
    if not arguments.dry_run and written != total:
        print(f"Wrote {written} notes; {total - written} sessions had no visible messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
