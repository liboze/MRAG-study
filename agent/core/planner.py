"""Task Planner — decomposes high-level research goals into actionable tasks.

The planner uses the LLM to:
  1. Break a research goal into ordered sub-tasks.
  2. Assign priority and dependencies.
  3. Dynamically add / reorder tasks as the research evolves.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from agent.core.memory_manager import MemoryManager
from agent.tools.llm_client import LLMClient
from agent.utils.file_manager import now_str
from agent.utils.logger import get_logger

logger = get_logger(__name__)

# ── Prompts ────────────────────────────────────────────────────────────────────

_DECOMPOSE_SYSTEM = """你是一名 AI 科研任务规划专家。
你的职责是将用户给出的科研总目标分解为清晰、可执行、有优先级的子任务列表。

输出要求：
- 仅输出 JSON 数组，不要有额外说明。
- 每个元素为对象，包含以下字段：
  - title: 任务标题（简洁，≤30 字）
  - description: 任务描述（≤100 字）
  - status: "todo"
  - priority: 1–5（1 最高）
  - depends_on: 依赖的任务标题列表（可为空数组）
  - owner: "agent"
  - next_action: 第一步行动描述（≤50 字）
"""

_NEXT_TASK_SYSTEM = """你是一名 AI 科研任务调度专家。
根据当前任务状态，选择下一个应执行的任务。

输出要求：
- 仅输出 JSON 对象，不要额外说明。
- 包含字段：title（任务标题）、reason（选择理由，≤80 字）。
"""


class Planner:
    """Research task planner.

    Parameters
    ----------
    llm:
        Configured :class:`~agent.tools.llm_client.LLMClient` instance.
    memory:
        Configured :class:`~agent.core.memory_manager.MemoryManager` instance.
    """

    def __init__(self, llm: LLMClient, memory: MemoryManager) -> None:
        self._llm = llm
        self._memory = memory

    # ── Public API ─────────────────────────────────────────────────────────────

    def decompose_goal(self, goal: str) -> List[Dict[str, Any]]:
        """Ask the LLM to decompose *goal* into sub-tasks.

        The tasks are saved to ``tasks.md`` and returned.
        """
        prompt = f"研究总目标：{goal}\n\n请将其分解为有序子任务列表。"
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_DECOMPOSE_SYSTEM,
        )
        tasks = self._parse_json_list(raw)
        if not tasks:
            logger.warning("Planner: LLM returned no parseable tasks. Raw=%r", raw[:200])
            return []

        # Save research goal to memory
        self._memory.update_memory("研究目标", goal)

        # Register tasks
        for t in tasks:
            t.setdefault("status", "todo")
            t.setdefault("updated_at", now_str())
            self._memory.add_task(t)

        logger.info("Planner: decomposed goal into %d tasks.", len(tasks))
        return tasks

    def pick_next_task(self) -> Optional[Dict[str, str]]:
        """Ask the LLM to pick the highest-priority executable next task.

        Returns a dict with ``title`` and ``reason``, or ``None`` if all tasks
        are done or blocked.
        """
        todo = self._memory.get_tasks_by_status("todo")
        in_progress = self._memory.get_tasks_by_status("in_progress")

        if not re.search(r"- \*\*", todo + in_progress):
            logger.info("Planner: no pending tasks found.")
            return None

        context = f"## 未完成任务\n{todo}\n\n## 进行中任务\n{in_progress}"
        prompt = f"以下是当前任务状态，请选择下一个应执行的任务：\n\n{context}"
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_NEXT_TASK_SYSTEM,
        )
        result = self._parse_json_obj(raw)
        if not result or "title" not in result:
            logger.warning("Planner: could not parse next-task selection. Raw=%r", raw[:200])
            return None
        logger.info("Planner: next task selected → %r", result["title"])
        return result

    def add_task(self, title: str, description: str, status: str = "new",
                 priority: int = 3, depends_on: Optional[List[str]] = None,
                 next_action: str = "") -> None:
        """Programmatically add a single new task."""
        task: Dict[str, Any] = {
            "title": title,
            "description": description,
            "status": status,
            "priority": priority,
            "depends_on": ", ".join(depends_on or []),
            "owner": "agent",
            "next_action": next_action,
            "updated_at": now_str(),
        }
        self._memory.add_task(task)
        logger.info("Planner: task added manually → %r", title)

    def mark_done(self, title: str, notes: str = "") -> None:
        """Mark *title* as done in tasks.md."""
        self._memory.update_task_status(title, "done", notes)

    def mark_blocked(self, title: str, reason: str) -> None:
        """Mark *title* as blocked, recording the *reason*."""
        self._memory.update_task_status(title, "blocked", reason)

    def mark_in_progress(self, title: str) -> None:
        """Mark *title* as in-progress."""
        self._memory.update_task_status(title, "in_progress")

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json_list(text: str) -> List[Dict[str, Any]]:
        text = text.strip()
        # Extract JSON array from possible markdown fences
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            text = m.group(0)
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
        return []

    @staticmethod
    def _parse_json_obj(text: str) -> Dict[str, Any]:
        text = text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        return {}
