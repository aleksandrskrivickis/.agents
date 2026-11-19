from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

TAG_RULES = [
    (
        "engineering/databricks",
        (
            "databricks",
            "delta live tables",
            "lakeflow",
            "unity catalog",
            "lakebase",
            "dbx",
            "metastore",
            "cluster policy",
            "cluster policies",
            "workspace grants",
            "sdp",
            "catalog",
            "data plane",
            "serverless",
        ),
    ),
    (
        "engineering/spark",
        (
            "pyspark",
            "spark",
            "foreachbatch",
            "streamingquery",
            "microbatch",
            "arrow",
            "dataframe",
            "udf",
            "clustering",
            "partitioning",
            "streaming table",
        ),
    ),
    (
        "engineering/azure",
        (
            "azure",
            "azurerm",
            "bicep",
            "key vault",
            "vnet",
            "subnet",
            "nsg",
            "private endpoint",
            "storage account",
            "backup vault",
            "resource group",
            "fca handbook",
            "fca",
        ),
    ),
    (
        "engineering/infrastructure",
        (
            "terraform",
            "infrastructure",
            "bicep",
            "vnet",
            "subnet",
            "private endpoint",
            "resource group",
            "nat gateway",
            "role assignment",
            "network security group",
            "deployment type",
            "regional",
            "resourceincrement",
            "lock deletion",
            "main tf",
            "simulate apply",
            "infra changes",
            "change propagation",
            "cluster policy",
            "secret key",
            "dev target",
        ),
    ),
    (
        "engineering/ci-cd",
        (
            "azure devops",
            "devops",
            "github actions",
            "ci cd",
            "pipeline yaml",
            "build validation",
            "release pipeline",
            "preflight",
            "deploy stage",
            "approval stage",
            "requirement",
            "retrycountontaskfailure",
            "template",
            "rule expiration",
            "job execution",
            "deployment failure",
            "bump my version",
            "assets folder",
            "execution order",
            "utils library",
        ),
    ),
    (
        "engineering/pipelines",
        (
            "data pipeline",
            "streaming pipeline",
            "pipeline",
            "ingestion",
            "foreachbatch",
            "streamingquery",
            "append only",
            "microbatch",
            "flow",
            "infinite loop",
            "initialization stage",
            "computationally bearable",
            "contents markdown",
            "streaming table",
            "exclude records",
            "max concurrent runs",
            "maximum concurrent runs",
            "out of memory",
            "memory limit",
            "quarantine table",
            "batch size",
            "stream failure",
            "document search",
            "yielding efficiency",
            "progress error",
            "timestamp to tables",
            "sink error",
            "contents flow",
        ),
    ),
    (
        "engineering/python",
        (
            "python",
            "pytest",
            "pandas",
            "pyright",
            "ruff",
            "module not found",
            "attributeerror",
            "typeerror",
            "valueerror",
            "beautifulsoup",
            "python script",
            "package import",
            "bump my version",
        ),
    ),
    ("engineering/git", ("git", "branch", "commit", "clone", "push", "pull request")),
    ("engineering/sql", ("sql", "query", "join", "joins", "database", "postgres")),
    (
        "engineering/web-scraping",
        (
            "lawstronaut",
            "web scraping",
            "scraper",
            "crawling",
            "portal",
            "contents table",
            "handbook url",
            "fca handbook",
            "as of date",
            "url generation",
            "overheid nl",
            "markdown slices",
            "document versions",
            "contents",
            "markdown content",
            "log analytics",
        ),
    ),
    (
        "engineering/web-dev",
        (
            "web interface",
            "frontend",
            "html",
            "css",
            "javascript",
            "npm",
            "centered layout",
            "layout effectiveness",
            "layout",
        ),
    ),
    (
        "engineering/ide",
        (
            "vs code",
            "vscode",
            "visual studio code",
            "pylance",
            "settings.json",
            "editor",
            "extension",
            "terminal",
            "bash sessions",
            "settings sync",
        ),
    ),
    ("engineering/apis", ("api", "apis", "endpoint", "rest api", "http request")),
    (
        "engineering/data-modelling",
        (
            "schema",
            "data model",
            "table column",
            "column",
            "data structure",
            "json parameter",
            "record",
            "variable",
            "declaration",
            "configuration",
            "groups",
            "grants",
            "json formatter",
            "filter",
            "cluster policy",
            "containers from json",
            "timestamp to tables",
            "emptiness checks",
            "suffix columns",
            "quarantine table",
        ),
    ),
    (
        "engineering/architecture",
        (
            "architecture",
            "module",
            "refactor",
            "modular",
            "dependency",
            "organizing dependencies",
            "decoupling",
            "code analysis",
            "codebase evaluation",
            "codebase",
            "weaknesses",
            "creating dependencies",
            "effort duplication",
        ),
    ),
    (
        "ai/machine-learning",
        (
            "machine learning",
            "model serving",
            "embeddings",
            "embedding",
            "llm",
            "language model",
            "qwen",
            "model swap",
            "model warmup",
        ),
    ),
    (
        "ai/coding-agents",
        ("copilot cli", "coding agent", "coding agents", "claude code", "mcp", "skills and agents", "agent mode"),
    ),
    ("career/hiring", ("hiring", "interview", "recruiter", "job application", "hiring test")),
    ("productivity/obsidian", ("obsidian", "vault", "wikilink")),
    ("productivity/documents", ("document comprehension", "document editing")),
    ("writing/messages", ("email", "message wording", "recipient name", "proofread")),
]


def _frontmatter(text: str) -> tuple[str, str, str]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?=\r?\n|$)", text, re.DOTALL)
    if not match:
        raise ValueError("Note has no YAML frontmatter.")
    return text[: match.start(1)], match.group(1), text[match.end(1) :]


def _field_value(frontmatter: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.*)$", frontmatter)
    if not match:
        return ""
    value = match.group(1).strip()
    if value.startswith('"'):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value.strip('"')
    return value


def _read_tags(frontmatter: str) -> list[str]:
    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^tags:\s*(.*)$", line)
        if not match:
            continue
        inline = match.group(1).strip()
        if inline.startswith("["):
            try:
                value = json.loads(inline)
                return [tag for tag in value if isinstance(tag, str)] if isinstance(value, list) else []
            except json.JSONDecodeError:
                return []
        if inline:
            return [inline.strip("'\"")]
        tags = []
        for item in lines[index + 1 :]:
            tag_match = re.match(r"^\s+-\s+(.+?)\s*$", item)
            if not tag_match:
                break
            tags.append(tag_match.group(1).strip("'\""))
        return tags
    return []


def _taxonomy(claude_root: Path) -> set[str]:
    tags = set()
    for path in claude_root.rglob("*.md"):
        try:
            _, frontmatter, _ = _frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tags.update(_read_tags(frontmatter))
    if not tags:
        raise ValueError(f"No tags found in Claude notes: {claude_root}")
    return tags


def _topic_text(text: str) -> str:
    _, frontmatter, body = _frontmatter(text)
    title = _field_value(frontmatter, "title")
    first_user_section = []
    capture = False
    for line in body.splitlines():
        if line.strip() == "### User":
            capture = True
            continue
        if line.startswith("### ") or line.startswith("## Turn "):
            if capture:
                break
        if capture:
            first_user_section.append(line)
    return f"{title}\n{' '.join(first_user_section)}"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _suggest_tags(topic: str, taxonomy: set[str]) -> list[str]:
    normalized = f" {_normalize(topic)} "
    matches = []
    for order, (tag, terms) in enumerate(TAG_RULES):
        if tag not in taxonomy:
            continue
        hits = [term for term in terms if f" {_normalize(term)} " in normalized]
        if hits:
            matches.append((len(hits), -order, tag))
    matches.sort(reverse=True)

    selected = []
    for _, _, tag in matches:
        parent = tag.split("/", 1)[0]
        additions = [value for value in (parent, tag) if value not in selected]
        if len(selected) + len(additions) > 3:
            continue
        selected.extend(additions)
        if sum("/" in value for value in selected) >= 2:
            break
    return selected


def _replace_tags(text: str, tags: list[str]) -> str:
    prefix, frontmatter, suffix = _frontmatter(text)
    lines = frontmatter.splitlines()
    start = next((index for index, line in enumerate(lines) if re.match(r"^tags:\s*", line)), None)
    if start is not None:
        end = start + 1
        while end < len(lines) and re.match(r"^\s+-\s+", lines[end]):
            end += 1
        replacement = ["tags:", *(f"  - {tag}" for tag in tags)]
        lines[start:end] = replacement
    else:
        lines.extend(["tags:", *(f"  - {tag}" for tag in tags)])
    return prefix + "\n".join(lines) + suffix


def tag_notes(vault: Path, dry_run: bool) -> tuple[int, int, int, Counter[str]]:
    claude_root = vault / "LLM chats" / "claude"
    github_root = vault / "LLM chats" / "github"
    if not github_root.is_dir():
        raise FileNotFoundError(f"GitHub chat folder does not exist: {github_root}")

    taxonomy = _taxonomy(claude_root)
    files = sorted(github_root.rglob("*.md"))
    tagged = 0
    unchanged = 0
    unclassified = 0
    counts: Counter[str] = Counter()

    for path in files:
        text = path.read_text(encoding="utf-8")
        _, frontmatter, _ = _frontmatter(text)
        existing = _read_tags(frontmatter)
        suggestions = _suggest_tags(_topic_text(text), taxonomy)
        tags = list(existing)
        for suggestion in suggestions:
            if suggestion not in tags and len(tags) < 3:
                tags.append(suggestion)
        if not suggestions:
            unclassified += 1
        if tags == existing:
            unchanged += 1
            continue
        tagged += 1
        counts.update(tags)
        if not dry_run:
            path.write_text(_replace_tags(text, tags), encoding="utf-8")
        else:
            print(f"{path}: {', '.join(tags)}")

    return tagged, unchanged, unclassified, counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Add tags to Copilot notes from the Claude vault taxonomy.")
    parser.add_argument("--vault", type=Path, required=True, help="Obsidian vault root folder.")
    parser.add_argument("--dry-run", action="store_true", help="Show tag suggestions without changing notes.")
    arguments = parser.parse_args()

    try:
        tagged, unchanged, unclassified, counts = tag_notes(arguments.vault.resolve(), arguments.dry_run)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    action = "Would update" if arguments.dry_run else "Updated"
    print(f"{action} {tagged} notes; left {unchanged} unchanged; {unclassified} had no matching tag rule")
    print("Tag totals:", ", ".join(f"{tag}={count}" for tag, count in counts.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
