"""Autonomous research survey module.

Searches arXiv, Semantic Scholar, and the web to survey a research topic,
then uses the LLM to synthesise insights and identify research gaps.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.core.memory_manager import MemoryManager
from agent.tools.llm_client import LLMClient
from agent.tools.search_client import SearchClient
from agent.utils.logger import get_logger

logger = get_logger(__name__)

_SURVEY_SYSTEM = """你是一名顶级 AI 研究员，擅长文献综述与研究方向分析。
根据提供的论文摘要列表，请：
1. 总结该领域的主要研究方向与代表性方法；
2. 识别现有方法的主要不足与研究空白；
3. 提出 3–5 个值得深入研究的方向；
4. 以 Markdown 结构化格式输出，包含：## 主要研究方向、## 研究空白、## 推荐深入方向。
"""


class Researcher:
    """Survey research directions, summarise literature, identify gaps.

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

    def survey(self, topic: str, max_papers: int = 20) -> Dict[str, Any]:
        """Conduct a full literature survey on *topic*.

        Steps:
          1. Fetch papers from arXiv and Semantic Scholar.
          2. Ask LLM to synthesise findings.
          3. Persist results to memory.md.

        Returns a dict with ``papers``, ``synthesis``.
        """
        logger.info("Researcher: starting survey on %r", topic)

        arxiv_papers = self._search.search_arxiv(topic, max_results=max_papers)
        ss_papers = self._search.search_semantic_scholar(topic, max_results=max_papers // 2)

        all_papers: List[Dict[str, str]] = arxiv_papers + [
            {
                "id": p["id"],
                "title": p["title"],
                "authors": p.get("authors", ""),
                "summary": p.get("abstract", ""),
                "published": str(p.get("year", "")),
                "url": p.get("url", ""),
            }
            for p in ss_papers
        ]

        # Deduplicate by title (simple)
        seen_titles: set = set()
        unique: List[Dict[str, str]] = []
        for p in all_papers:
            key = p["title"].lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                unique.append(p)

        synthesis = self._synthesise(topic, unique)

        # Persist
        self._memory.update_memory(
            "相关工作调研",
            f"**主题**: {topic}\n\n**论文数量**: {len(unique)}\n\n{synthesis}",
        )
        self._memory.append_memory(
            "重要资源链接",
            "\n".join(f"- [{p['title']}]({p['url']})" for p in unique[:10] if p.get("url")),
        )

        logger.info("Researcher: survey complete. %d unique papers.", len(unique))
        return {"papers": unique, "synthesis": synthesis}

    def find_related_work_for_paper(self, related_section: str) -> str:
        """Generate a 'Related Work' section draft given already-collected paper list."""
        prompt = (
            "请基于以下文献综述内容，撰写一段适合 AI 领域论文的'相关工作'章节（约 500 字，中文）：\n\n"
            + related_section
        )
        return self._llm.complete(prompt)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _synthesise(self, topic: str, papers: List[Dict[str, str]]) -> str:
        """Ask the LLM to analyse the collected papers."""
        if not papers:
            return "未找到相关论文，请检查搜索关键词或网络连接。"

        paper_lines = []
        for i, p in enumerate(papers[:30], 1):
            paper_lines.append(
                f"{i}. **{p['title']}** ({p.get('published', '')})\n"
                f"   作者: {p.get('authors', '')}\n"
                f"   摘要: {p.get('summary', '')[:200]}"
            )
        papers_text = "\n\n".join(paper_lines)
        prompt = f"研究主题：{topic}\n\n以下是收集到的相关论文列表：\n\n{papers_text}"
        return self._llm.chat(
            [{"role": "user", "content": prompt}],
            system_prompt=_SURVEY_SYSTEM,
        )
