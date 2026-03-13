"""Data collection module.

Searches for public datasets relevant to the current research topic,
summarises their properties, and records them in memory.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.core.memory_manager import MemoryManager
from agent.tools.llm_client import LLMClient
from agent.tools.search_client import SearchClient
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_DATASET_SYSTEM = """你是一名 AI 数据工程师，擅长发现与评估公开数据集。
根据用户提供的研究任务和检索结果，请：
1. 列出最适合当前研究的 3–8 个公开数据集；
2. 对每个数据集给出：名称、简介、规模、格式、适用任务、获取链接（如有）、优缺点；
3. 以 Markdown 表格或列表形式输出。
"""


class DataCollector:
    """Discover and catalogue relevant datasets.

    Parameters
    ----------
    llm:
        Configured LLM client.
    search:
        Configured search client.
    memory:
        Memory manager for persisting results.
    """

    def __init__(self, llm: LLMClient, search: SearchClient, memory: MemoryManager) -> None:
        self._llm = llm
        self._search = search
        self._memory = memory

    # ── Public API ─────────────────────────────────────────────────────────────

    def collect(self, topic: str, task_description: str = "") -> Dict[str, Any]:
        """Search for datasets for *topic* and return a structured summary.

        Returns a dict with ``raw_results`` (search hits) and ``summary``
        (LLM-synthesised Markdown table/list).
        """
        logger.info("DataCollector: collecting datasets for %r", topic)

        # Web search for datasets
        web_query = f"{topic} public dataset benchmark download"
        web_results = self._search.search_web(web_query, max_results=10)

        # arXiv search for papers with dataset contributions
        arxiv_results = self._search.search_arxiv(
            f"{topic} dataset benchmark", max_results=10
        )

        combined_text = self._format_search_results(web_results, arxiv_results)
        task_ctx = f"研究任务：{task_description}\n\n" if task_description else ""
        prompt = (
            f"研究主题：{topic}\n\n"
            f"{task_ctx}"
            f"以下是关于数据集的检索结果：\n\n{combined_text}"
        )
        summary = self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_DATASET_SYSTEM,
        )

        self._memory.update_memory("数据集资源", f"**主题**: {topic}\n\n{summary}")
        logger.info("DataCollector: dataset collection complete.")
        return {"raw_results": {"web": web_results, "arxiv": arxiv_results}, "summary": summary}

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _format_search_results(
        web: List[Dict[str, str]], arxiv: List[Dict[str, str]]
    ) -> str:
        lines: List[str] = []
        if web:
            lines.append("### Web 搜索结果")
            for r in web:
                lines.append(f"- [{r['title']}]({r['link']}): {r['snippet']}")
        if arxiv:
            lines.append("\n### arXiv 相关论文")
            for p in arxiv[:8]:
                lines.append(f"- [{p['title']}]({p['url']}): {p['summary'][:150]}")
        return "\n".join(lines)
