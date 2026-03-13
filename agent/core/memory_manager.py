"""Memory, Tasks, and Skills state manager.

Manages three Markdown state files that form the agent's persistent memory:

* ``state/memory.md``  — long-term knowledge, conclusions, configurations
* ``state/tasks.md``   — task tracking with status lifecycle
* ``state/skills.md``  — catalogue of reusable Python skill scripts
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from agent.utils.file_manager import (
    append_to_section,
    ensure_dir,
    format_skill_entry,
    format_task_entry,
    get_section,
    now_str,
    read_file,
    replace_section,
    write_file,
)
from agent.utils.logger import get_logger

logger = get_logger(__name__)

TaskStatus = Literal["todo", "in_progress", "blocked", "done", "new"]


class MemoryManager:
    """Persist and retrieve agent state across runs.

    Parameters
    ----------
    config:
        The ``state`` section from ``config.yaml``.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._memory_file = config.get("memory_file", "state/memory.md")
        self._tasks_file = config.get("tasks_file", "state/tasks.md")
        self._skills_file = config.get("skills_registry", "state/skills.md")
        self._paper_file = config.get("paper_draft_file", "state/paper_draft.md")

        for path in (self._memory_file, self._tasks_file, self._skills_file, self._paper_file):
            ensure_dir(os.path.dirname(path) or ".")

        self._init_files()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _init_files(self) -> None:
        """Create state files with default scaffolding if they don't exist."""
        if not os.path.exists(self._memory_file):
            write_file(self._memory_file, _MEMORY_TEMPLATE)
            logger.info("Created %s", self._memory_file)

        if not os.path.exists(self._tasks_file):
            write_file(self._tasks_file, _TASKS_TEMPLATE)
            logger.info("Created %s", self._tasks_file)

        if not os.path.exists(self._skills_file):
            write_file(self._skills_file, _SKILLS_TEMPLATE)
            logger.info("Created %s", self._skills_file)

        if not os.path.exists(self._paper_file):
            write_file(self._paper_file, _PAPER_TEMPLATE)
            logger.info("Created %s", self._paper_file)

    # ── Memory ─────────────────────────────────────────────────────────────────

    def get_memory(self, section: Optional[str] = None) -> str:
        """Return memory content.  If *section* is given, return only that section."""
        md = read_file(self._memory_file)
        if section:
            return get_section(md, section)
        return md

    def update_memory(self, section: str, content: str) -> None:
        """Replace the *section* in memory.md with *content*."""
        md = read_file(self._memory_file)
        md = replace_section(md, section, content)
        write_file(self._memory_file, md)
        logger.debug("Memory updated: section=%r", section)

    def append_memory(self, section: str, content: str) -> None:
        """Append *content* to *section* in memory.md."""
        md = read_file(self._memory_file)
        md = append_to_section(md, section, content)
        write_file(self._memory_file, md)
        logger.debug("Memory appended: section=%r", section)

    def add_memory_note(self, note: str, section: str = "Notes") -> None:
        """Append a timestamped note to *section*."""
        entry = f"- [{now_str()}] {note}"
        self.append_memory(section, entry)

    # ── Tasks ──────────────────────────────────────────────────────────────────

    def add_task(self, task: Dict[str, Any]) -> None:
        """Add a new task entry to the appropriate status section."""
        task.setdefault("updated_at", now_str())
        status: str = task.get("status", "todo")
        heading = _STATUS_TO_HEADING.get(status, "未完成任务")
        entry = format_task_entry(task)
        md = read_file(self._tasks_file)
        md = append_to_section(md, heading, entry)
        write_file(self._tasks_file, md)
        logger.info("Task added: %s [%s]", task.get("title"), status)

    def update_task_status(self, title: str, new_status: TaskStatus, notes: str = "") -> None:
        """Move a task from its current section to the new status section."""
        md = read_file(self._tasks_file)
        # Find the task block by title in any section
        import re
        pattern = re.compile(r"(- \*\*" + re.escape(title) + r"\*\*.*?)(?=\n- \*\*|\Z)", re.DOTALL)
        m = pattern.search(md)
        if not m:
            logger.warning("Task not found for status update: %r", title)
            return
        old_block = m.group(1)
        # Remove old block
        md = md.replace(old_block, "").strip() + "\n"
        # Build updated block
        updated_task: Dict[str, Any] = {
            "title": title,
            "status": new_status,
            "updated_at": now_str(),
        }
        if notes:
            updated_task["notes"] = notes
        heading = _STATUS_TO_HEADING.get(new_status, "未完成任务")
        new_block = format_task_entry(updated_task)
        md = append_to_section(md, heading, new_block)
        write_file(self._tasks_file, md)
        logger.info("Task status updated: %r → %s", title, new_status)

    def get_tasks_by_status(self, status: TaskStatus) -> str:
        """Return the raw markdown for all tasks with *status*."""
        heading = _STATUS_TO_HEADING.get(status, "未完成任务")
        return get_section(read_file(self._tasks_file), heading)

    def get_all_tasks(self) -> str:
        """Return the full tasks.md content."""
        return read_file(self._tasks_file)

    # ── Skills ─────────────────────────────────────────────────────────────────

    def register_skill(self, skill: Dict[str, Any]) -> None:
        """Add or update a skill entry in skills.md."""
        skill.setdefault("updated_at", now_str())
        entry = format_skill_entry(skill)
        md = read_file(self._skills_file)
        heading = "已注册 Skills"
        md = append_to_section(md, heading, entry)
        write_file(self._skills_file, md)
        logger.info("Skill registered: %s", skill.get("name"))

    def get_skills(self) -> str:
        """Return the full skills.md."""
        return read_file(self._skills_file)

    def find_skill(self, keyword: str) -> str:
        """Return skills.md sections that contain *keyword* (case-insensitive)."""
        md = read_file(self._skills_file)
        lines = md.splitlines()
        results: List[str] = []
        in_block = False
        block: List[str] = []
        for line in lines:
            if line.startswith("### "):
                if in_block and block:
                    results.append("\n".join(block))
                block = [line]
                in_block = True
            elif in_block:
                block.append(line)
        if in_block and block:
            results.append("\n".join(block))

        kw = keyword.lower()
        return "\n\n---\n\n".join(b for b in results if kw in b.lower())

    # ── Paper draft ────────────────────────────────────────────────────────────

    def update_paper_section(self, section: str, content: str) -> None:
        """Replace *section* in the paper draft."""
        md = read_file(self._paper_file)
        md = replace_section(md, section, content)
        write_file(self._paper_file, md)
        logger.info("Paper draft updated: section=%r", section)

    def append_paper_section(self, section: str, content: str) -> None:
        """Append *content* to *section* of the paper draft."""
        md = read_file(self._paper_file)
        md = append_to_section(md, section, content)
        write_file(self._paper_file, md)
        logger.info("Paper draft appended: section=%r", section)

    def get_paper_draft(self) -> str:
        """Return the full paper draft."""
        return read_file(self._paper_file)


# ── Status → Markdown section heading mapping ──────────────────────────────────
_STATUS_TO_HEADING: Dict[str, str] = {
    "done": "已完成任务",
    "in_progress": "进行中任务",
    "todo": "未完成任务",
    "new": "新增任务",
    "blocked": "阻塞任务",
}

# ── Default file templates ─────────────────────────────────────────────────────

_MEMORY_TEMPLATE = """\
# 智能体长期记忆 (Memory)

> 本文件由智能体自动维护。请勿手动大幅改动已有内容。

## 研究目标

（待填写）

## 关键假设

（待填写）

## 有效结论

（待填写）

## 失败经验

（待填写）

## 环境配置

（待填写）

## 重要资源链接

（待填写）

## 实验注意事项

（待填写）

## Notes

（智能体运行时追加的临时备注）
"""

_TASKS_TEMPLATE = """\
# 任务状态跟踪 (Tasks)

> 本文件由智能体自动维护，记录所有任务及其状态。

## 已完成任务

（无）

## 进行中任务

（无）

## 未完成任务

（无）

## 新增任务

（无）

## 阻塞任务

（无）
"""

_SKILLS_TEMPLATE = """\
# 技能注册表 (Skills)

> 本文件由智能体自动维护，记录所有可复用的 Python 技能脚本。

## 已注册 Skills

（尚无注册技能）
"""

_PAPER_TEMPLATE = """\
# 论文草稿 (Paper Draft)

> 本文件由智能体自动维护，随实验进展持续积累论文内容。

## 标题

（待确定）

## 摘要

（待撰写）

## 1. 研究背景与动机

（待撰写）

## 2. 相关工作

（待撰写）

## 3. 方法设计

（待撰写）

## 4. 实验设置

（待撰写）

## 5. 实验结果与分析

（待撰写）

## 6. 结论与展望

（待撰写）

## 参考文献

（待整理）
"""
