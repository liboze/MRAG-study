"""Paper writing module — incrementally build a research paper draft.

The paper is written in sections as the research progresses:
  1. Background & Motivation  (after survey)
  2. Related Work             (after survey)
  3. Method Design            (after idea selection)
  4. Experiment Setup         (after experiment planning)
  5. Results & Analysis       (after evaluation)
  6. Conclusion & Future Work (near the end)
  7. Abstract & Title         (finalised last)
  8. References               (collected throughout)

Each section can be updated multiple times; the draft is stored in
``state/paper_draft.md``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.core.memory_manager import MemoryManager
from agent.tools.llm_client import LLMClient
from agent.utils.file_manager import now_str
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_WRITE_SYSTEM = """你是一名顶级 AI 领域论文写作专家，熟悉 NeurIPS / ICML / ACL 等顶会写作规范。
请根据提供的素材和研究上下文，撰写或改进指定的论文章节。

要求：
- 学术风格，严谨准确；
- 中文写作（除非另行指定）；
- 引用已提供的文献时使用 [作者, 年份] 格式；
- 逻辑清晰，层次分明；
- 输出纯文本，不含 Markdown 标题（章节标题由系统管理）。
"""

# ── Section prompts ──────────────────────────────────────────────────────────

_SECTION_PROMPTS: Dict[str, str] = {
    "研究背景与动机": (
        "请根据以下文献综述和研究目标，撰写论文的'研究背景与动机'章节（约 400 字）。\n\n"
        "要求：阐明该领域的重要性、现有方法的不足，以及本工作的动机。"
    ),
    "相关工作": (
        "请根据以下文献综述内容，撰写论文的'相关工作'章节（约 500 字）。\n\n"
        "要求：按方向分类介绍相关工作，指出与本文的关联或差异。"
    ),
    "方法设计": (
        "请根据以下研究 idea 和实现方案，撰写论文的'方法'章节（约 600 字）。\n\n"
        "要求：清晰描述模型结构、算法流程、关键设计决策及其理论依据。"
    ),
    "实验设置": (
        "请根据以下实验配置信息，撰写论文的'实验设置'章节（约 300 字）。\n\n"
        "要求：说明数据集、评估指标、基线方法、超参数设置和运行环境。"
    ),
    "实验结果与分析": (
        "请根据以下实验结果和评估，撰写论文的'实验结果与分析'章节（约 500 字）。\n\n"
        "要求：客观呈现定量结果，进行对比分析，解释性能差异，并讨论关键发现。"
    ),
    "结论与展望": (
        "请根据以下研究总结，撰写论文的'结论与展望'章节（约 250 字）。\n\n"
        "要求：总结本文贡献，指出局限性，展望未来工作方向。"
    ),
    "摘要": (
        "请根据以下论文各章节摘要，撰写一个全文摘要（约 200 字）。\n\n"
        "要求：包含研究问题、方法、主要结果和贡献。"
    ),
}


class PaperWriter:
    """Incrementally write and update a research paper draft.

    Parameters
    ----------
    llm:
        Configured LLM client.
    memory:
        Memory manager for reading context and persisting the draft.
    """

    def __init__(self, llm: LLMClient, memory: MemoryManager) -> None:
        self._llm = llm
        self._memory = memory

    # ── Public API ─────────────────────────────────────────────────────────────

    def write_section(
        self,
        section_name: str,
        context: str,
        append: bool = False,
    ) -> str:
        """Write or update *section_name* using *context* as material.

        Parameters
        ----------
        section_name:
            Must match one of the keys in ``_SECTION_PROMPTS`` or be a
            free-form section name.
        context:
            Relevant material (survey results, experiment outputs, etc.)
        append:
            If ``True``, append to the existing section instead of replacing.

        Returns the generated text.
        """
        logger.info("PaperWriter: writing section %r", section_name)
        base_prompt = _SECTION_PROMPTS.get(section_name, f"请撰写论文的'{section_name}'章节。")
        prompt = f"{base_prompt}\n\n## 参考素材\n{context[:3000]}"
        text = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_WRITE_SYSTEM,
        )
        if append:
            self._memory.append_paper_section(section_name, text)
        else:
            self._memory.update_paper_section(section_name, text)
        logger.info("PaperWriter: section %r written (%d chars).", section_name, len(text))
        return text

    def write_background(self, survey_synthesis: str) -> str:
        """Write or refresh the Background section from survey synthesis."""
        return self.write_section("研究背景与动机", survey_synthesis)

    def write_related_work(self, survey_synthesis: str) -> str:
        """Write or refresh the Related Work section."""
        return self.write_section("相关工作", survey_synthesis)

    def write_method(self, idea: Dict[str, Any]) -> str:
        """Write the Method section from a selected idea dict."""
        context = (
            f"Idea 标题: {idea.get('title', '')}\n"
            f"假设: {idea.get('hypothesis', '')}\n"
            f"实现路径: {idea.get('approach', '')}\n"
            f"动机: {idea.get('motivation', '')}"
        )
        return self.write_section("方法设计", context)

    def write_experiment_setup(self, dataset_summary: str, plan: str) -> str:
        """Write the Experiment Setup section."""
        context = f"数据集:\n{dataset_summary}\n\n实验计划:\n{plan}"
        return self.write_section("实验设置", context)

    def write_results(self, evaluation: Dict[str, Any]) -> str:
        """Write the Results & Analysis section from an evaluation dict."""
        import json
        context = json.dumps(evaluation, ensure_ascii=False, indent=2)
        return self.write_section("实验结果与分析", context)

    def write_conclusion(self) -> str:
        """Write the Conclusion from accumulated memory."""
        conclusions = self._memory.get_memory("有效结论")
        failures = self._memory.get_memory("失败经验")
        goal = self._memory.get_memory("研究目标")
        context = f"研究目标:\n{goal}\n\n有效结论:\n{conclusions}\n\n失败经验:\n{failures}"
        return self.write_section("结论与展望", context)

    def write_abstract(self) -> str:
        """Generate the abstract from all other sections."""
        draft = self._memory.get_paper_draft()
        return self.write_section("摘要", draft[:4000])

    def suggest_title(self) -> str:
        """Ask the LLM to suggest 3 candidate paper titles."""
        draft_summary = self._memory.get_paper_draft()[:2000]
        prompt = (
            "请根据以下论文草稿，提出 3 个候选论文标题（中英文各一），"
            "并简述每个标题的优缺点：\n\n" + draft_summary
        )
        titles = self._llm.complete(prompt)
        self._memory.update_paper_section("标题", titles)
        return titles

    def add_reference(self, ref: str) -> None:
        """Append a formatted reference to the References section."""
        self._memory.append_paper_section("参考文献", f"- {ref}")

    def get_draft(self) -> str:
        """Return the current paper draft."""
        return self._memory.get_paper_draft()
