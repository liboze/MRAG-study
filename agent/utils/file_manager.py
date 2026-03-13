"""File I/O helpers for Markdown state files and general workspace management."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ── Generic helpers ────────────────────────────────────────────────────────────

def ensure_dir(path: str) -> str:
    """Create *path* (and parents) if it does not exist; return *path*."""
    os.makedirs(path, exist_ok=True)
    return path


def read_file(path: str, default: str = "") -> str:
    """Return the text content of *path*, or *default* if the file is absent."""
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def write_file(path: str, content: str) -> None:
    """Write *content* to *path*, creating parent directories as needed."""
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def append_to_file(path: str, content: str) -> None:
    """Append *content* to *path* (creates the file if absent)."""
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(content)


def backup_file(path: str) -> Optional[str]:
    """Copy *path* to *path*.bak.<timestamp> and return the backup path."""
    if not os.path.exists(path):
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{path}.bak.{ts}"
    shutil.copy2(path, backup)
    return backup


# ── Markdown section helpers ──────────────────────────────────────────────────

def get_section(markdown: str, heading: str) -> str:
    """Return the text of the first section whose heading matches *heading*.

    The heading match is case-insensitive and tolerates leading ``#`` symbols.
    Returns an empty string when the section is not found.
    """
    pattern = re.compile(
        r"^#{1,6}\s+" + re.escape(heading) + r"\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(markdown)
    if not m:
        return ""
    start = m.end()
    # Find the next heading at the same or higher level
    level = len(re.match(r"^(#+)", markdown[m.start() :]).group(1))
    next_heading = re.compile(
        r"^#{1," + str(level) + r"}\s+", re.MULTILINE
    )
    m2 = next_heading.search(markdown, start)
    end = m2.start() if m2 else len(markdown)
    return markdown[start:end].strip()


def replace_section(markdown: str, heading: str, new_content: str) -> str:
    """Replace the body of *heading* in *markdown* with *new_content*.

    If the section does not exist, appends it at the end.
    """
    pattern = re.compile(
        r"^(#{1,6})\s+" + re.escape(heading) + r"\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(markdown)
    if not m:
        sep = "\n\n" if markdown.strip() else ""
        return markdown + f"{sep}## {heading}\n\n{new_content}\n"

    level = len(m.group(1))
    header_end = m.end()
    next_heading = re.compile(
        r"^#{1," + str(level) + r"}\s+", re.MULTILINE
    )
    m2 = next_heading.search(markdown, header_end)
    end = m2.start() if m2 else len(markdown)

    before = markdown[: header_end]
    after = markdown[end:]
    return f"{before}\n\n{new_content}\n\n{after}".strip() + "\n"


def append_to_section(markdown: str, heading: str, new_content: str) -> str:
    """Append *new_content* to an existing section or create the section."""
    existing = get_section(markdown, heading)
    updated = (existing + "\n\n" + new_content).strip() if existing else new_content
    return replace_section(markdown, heading, updated)


# ── Structured record helpers ─────────────────────────────────────────────────

def format_task_entry(task: Dict[str, Any]) -> str:
    """Render a task dict as a Markdown list item."""
    lines = [f"- **{task.get('title', 'Untitled')}**"]
    for key in ("status", "owner", "depends_on", "next_action", "updated_at", "notes"):
        val = task.get(key)
        if val:
            lines.append(f"  - {key}: {val}")
    return "\n".join(lines)


def format_skill_entry(skill: Dict[str, Any]) -> str:
    """Render a skill dict as a Markdown section."""
    name = skill.get("name", "unnamed_skill")
    lines = [
        f"### {name}",
        "",
        f"**功能**: {skill.get('description', '')}",
        f"**输入**: {skill.get('inputs', '')}",
        f"**输出**: {skill.get('outputs', '')}",
        f"**适用场景**: {skill.get('use_cases', '')}",
        f"**调用方式**: `{skill.get('call_signature', '')}`",
        f"**依赖**: {skill.get('dependencies', '')}",
        f"**代码位置**: `{skill.get('file_path', '')}`",
        f"**更新时间**: {skill.get('updated_at', '')}",
    ]
    return "\n".join(lines)


def now_str() -> str:
    """Return current UTC timestamp as a compact ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
