"""Idea generation module.

Combines literature synthesis, current task context, and available
resources to propose concrete, verifiable research ideas.
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

# ── Field label map used when formatting ideas ────────────────────────────────
_IDEA_FIELD_LABELS: Dict[str, str] = {
    "motivation": "动机",
    "hypothesis": "假设",
    "approach": "实现路径",
    "validation": "验证方式",
    "risks": "风险",
}

_IDEA_SYSTEM = """你是一名顶级 AI 科研专家，擅长提出创新且可验证的研究想法。
请基于提供的文献综述、已有结论、以及当前研究目标，提出 3–5 个具体的研究 idea。

每个 idea 必须包含以下字段（JSON 数组输出，不含其他文字）：
- id: 编号（"idea_1", "idea_2", ...）
- title: idea 标题（≤30 字）
- motivation: 动机与背景（≤100 字）
- hypothesis: 核心假设（≤80 字）
- approach: 实现路径与方法（≤150 字）
- validation: 验证方式与评估指标（≤100 字）
- risks: 主要风险（≤80 字）
- priority: 优先级 1–5（1 最高）
- feasibility: 可行性评分 1–5（1 最低）
"""

_SELECT_SYSTEM = """你是一名 AI 科研顾问，擅长评估研究方向的价值与可行性。
请从提供的 idea 列表中，选择最值得优先验证的一个。

输出 JSON 对象（不含其他文字），包含：
- selected_id: 选中的 idea id
- title: idea 标题
- reason: 选择理由（≤120 字）
- suggested_first_step: 建议的第一步行动（≤80 字）
"""


class IdeaGenerator:
    """Generate and select research ideas based on current context.

    Parameters
    ----------
    llm:
        Configured LLM client.
    memory:
        Memory manager for reading context and persisting ideas.
    """

    def __init__(self, llm: LLMClient, memory: MemoryManager) -> None:
        self._llm = llm
        self._memory = memory

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_ideas(
        self,
        topic: str,
        extra_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Generate research ideas for *topic*.

        Reads existing memory (survey, datasets, conclusions) as context,
        calls the LLM, persists results, and returns the idea list.
        """
        logger.info("IdeaGenerator: generating ideas for %r", topic)

        survey = self._memory.get_memory("相关工作调研")
        datasets = self._memory.get_memory("数据集资源")
        conclusions = self._memory.get_memory("有效结论")

        context_parts = [f"研究目标：{topic}"]
        if survey:
            context_parts.append(f"## 文献综述\n{survey[:1000]}")
        if datasets:
            context_parts.append(f"## 数据集\n{datasets[:500]}")
        if conclusions:
            context_parts.append(f"## 已有结论\n{conclusions[:500]}")
        if extra_context:
            context_parts.append(f"## 额外上下文\n{extra_context}")

        prompt = "\n\n".join(context_parts)
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_IDEA_SYSTEM,
        )
        ideas = self._parse_json_list(raw)
        if not ideas:
            logger.warning("IdeaGenerator: no parseable ideas returned. Raw=%r", raw[:200])
            return []

        # Persist ideas to memory
        ideas_md = "\n\n".join(self._format_idea(i) for i in ideas)
        self._memory.update_memory("候选 Ideas", f"**主题**: {topic}\n\n{ideas_md}")
        logger.info("IdeaGenerator: %d ideas generated.", len(ideas))
        return ideas

    def select_idea(self, ideas: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Ask the LLM to select the best idea from *ideas*.

        Updates memory with the selection and returns the chosen idea dict
        (augmented with ``selection_reason`` and ``suggested_first_step``).
        """
        if not ideas:
            return None
        prompt = "以下是候选 idea 列表：\n\n" + json.dumps(ideas, ensure_ascii=False, indent=2)
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_SELECT_SYSTEM,
        )
        sel = self._parse_json_obj(raw)
        if not sel or "selected_id" not in sel:
            logger.warning("IdeaGenerator: could not parse selection. Raw=%r", raw[:200])
            return ideas[0] if ideas else None

        selected_id = sel["selected_id"]
        chosen = next((i for i in ideas if i.get("id") == selected_id), ideas[0])
        chosen["selection_reason"] = sel.get("reason", "")
        chosen["suggested_first_step"] = sel.get("suggested_first_step", "")

        self._memory.update_memory(
            "当前选定 Idea",
            self._format_idea(chosen) + f"\n\n**选择理由**: {chosen['selection_reason']}\n**第一步**: {chosen['suggested_first_step']}",
        )
        self._memory.update_memory(
            "关键假设",
            chosen.get("hypothesis", ""),
        )
        logger.info("IdeaGenerator: selected idea %r", chosen.get("title"))
        return chosen

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_idea(idea: Dict[str, Any]) -> str:
        lines = [f"### {idea.get('id', 'idea')} — {idea.get('title', '')}"]
        for k, label in _IDEA_FIELD_LABELS.items():
            v = idea.get(k, "")
            if v:
                lines.append(f"**{label}**: {v}")
        lines.append(f"**优先级**: {idea.get('priority', '-')} | **可行性**: {idea.get('feasibility', '-')}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json_list(text: str) -> List[Dict[str, Any]]:
        text = text.strip()
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
