"""Result evaluation module.

Parses experiment output, computes/extracts quantitative metrics,
evaluates whether results support the research hypothesis, and
suggests next steps.
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

_EVAL_SYSTEM = """你是一名 AI 实验评估专家，擅长分析实验结果并给出客观评价。
请根据提供的研究假设和实验输出，给出：

输出 JSON 对象（不含其他文字）：
{
  "hypothesis_supported": true/false/partial,
  "key_metrics": {"指标名": 数值或字符串},
  "analysis": "结果分析（≤200 字）",
  "conclusion": "结论（≤100 字）",
  "next_steps": ["下一步建议1", "下一步建议2"],
  "paper_worthy": true/false,
  "paper_contribution": "论文贡献点（≤100 字）"
}
"""

_COMPARE_SYSTEM = """你是一名 AI 科研评审专家，擅长横向比较多组实验结果。
请根据提供的多个实验记录，给出：
1. 各实验的核心指标对比表；
2. 最优配置及原因；
3. 规律总结与改进建议。
以 Markdown 格式输出。
"""


class Evaluator:
    """Evaluate experiment results against the research hypothesis.

    Parameters
    ----------
    llm:
        Configured LLM client.
    memory:
        Memory manager for persisting evaluations.
    """

    def __init__(self, llm: LLMClient, memory: MemoryManager) -> None:
        self._llm = llm
        self._memory = memory

    # ── Public API ─────────────────────────────────────────────────────────────

    def evaluate(
        self,
        hypothesis: str,
        experiment_output: str,
        idea_title: str = "",
    ) -> Dict[str, Any]:
        """Evaluate *experiment_output* against *hypothesis*.

        Returns a structured evaluation dict and persists to memory.
        """
        logger.info("Evaluator: evaluating %r", idea_title or "experiment")
        prompt = (
            f"研究假设：{hypothesis}\n\n"
            f"实验输出（最后 3000 字）：\n{experiment_output[-3000:]}"
        )
        raw = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_EVAL_SYSTEM,
        )
        evaluation = self._parse_json(raw)
        if not evaluation:
            logger.warning("Evaluator: could not parse evaluation. Raw=%r", raw[:200])
            evaluation = {"analysis": raw, "hypothesis_supported": "unknown"}

        # Persist
        self._save_evaluation(idea_title or "experiment", hypothesis, evaluation)
        return evaluation

    def compare_experiments(self, records: List[Dict[str, Any]]) -> str:
        """Compare multiple experiment records and return a Markdown summary."""
        if not records:
            return "无实验记录可比较。"
        records_text = json.dumps(records, ensure_ascii=False, indent=2)[:3000]
        prompt = f"以下是多组实验记录：\n\n{records_text}"
        comparison = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_COMPARE_SYSTEM,
        )
        self._memory.update_memory("实验对比分析", comparison)
        return comparison

    def extract_metrics(self, text: str) -> Dict[str, Any]:
        """Heuristically extract numeric metrics from raw output text.

        Looks for patterns like ``accuracy: 0.85``, ``F1=0.72``, etc.
        """
        metrics: Dict[str, Any] = {}
        patterns = [
            (r"(?:accuracy|acc)[:\s=]+([0-9.]+)", "accuracy"),
            (r"(?:f1|f-1)[:\s=]+([0-9.]+)", "f1"),
            (r"(?:precision|prec)[:\s=]+([0-9.]+)", "precision"),
            (r"(?:recall|rec)[:\s=]+([0-9.]+)", "recall"),
            (r"(?:bleu)[:\s=]+([0-9.]+)", "bleu"),
            (r"(?:rouge)[:\s=]+([0-9.]+)", "rouge"),
            (r"(?:loss)[:\s=]+([0-9.]+)", "loss"),
            (r"(?:perplexity|ppl)[:\s=]+([0-9.]+)", "perplexity"),
            (r"(?:map|mrr)[:\s=]+([0-9.]+)", "map"),
        ]
        lower = text.lower()
        for pattern, name in patterns:
            m = re.search(pattern, lower)
            if m:
                try:
                    metrics[name] = float(m.group(1))
                except ValueError:
                    pass
        return metrics

    # ── Internal ───────────────────────────────────────────────────────────────

    def _save_evaluation(
        self, title: str, hypothesis: str, evaluation: Dict[str, Any]
    ) -> None:
        supported = evaluation.get("hypothesis_supported", "unknown")
        analysis = evaluation.get("analysis", "")
        conclusion = evaluation.get("conclusion", "")
        next_steps_raw = evaluation.get("next_steps", [])
        next_steps = "\n".join(f"- {s}" for s in next_steps_raw) if isinstance(next_steps_raw, list) else str(next_steps_raw)
        metrics = evaluation.get("key_metrics", {})

        entry = (
            f"### {title} ({now_str()})\n\n"
            f"**假设**: {hypothesis}\n\n"
            f"**假设得到支持**: {supported}\n\n"
            f"**关键指标**: {json.dumps(metrics, ensure_ascii=False)}\n\n"
            f"**分析**: {analysis}\n\n"
            f"**结论**: {conclusion}\n\n"
            f"**下一步建议**:\n{next_steps}"
        )

        if supported is True or supported == "true":
            self._memory.append_memory("有效结论", entry)
        else:
            self._memory.append_memory("失败经验", entry)

        logger.info(
            "Evaluator: evaluation saved. supported=%s", supported
        )

    @staticmethod
    def _parse_json(text: str) -> Dict[str, Any]:
        text = text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(0))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass
        return {}
