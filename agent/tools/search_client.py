"""Search & literature retrieval client.

Supported backends:
  - ``arxiv``            : arXiv preprint search (no API key needed)
  - ``semantic_scholar`` : Semantic Scholar API
  - ``serper``           : Google Search via Serper.dev (general web search)
"""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from agent.utils.logger import get_logger

logger = get_logger(__name__)


_REQUEST_TIMEOUT = 30  # seconds for all external HTTP requests


class SearchClient:
    """Unified search client for literature and web resources.

    Parameters
    ----------
    config:
        The ``search`` section from ``config.yaml``.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._cfg = config
        self._arxiv_cfg = config.get("arxiv", {})
        self._ss_cfg = config.get("semantic_scholar", {})
        self._serper_cfg = config.get("serper", {})

        self._ss_api_key = os.environ.get(
            self._ss_cfg.get("api_key_env", "SEMANTIC_SCHOLAR_API_KEY"), ""
        )
        self._serper_api_key = os.environ.get(
            self._serper_cfg.get("api_key_env", "SERPER_API_KEY"), ""
        )

    # ── arXiv ─────────────────────────────────────────────────────────────────

    def search_arxiv(
        self,
        query: str,
        max_results: Optional[int] = None,
        sort_by: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Search arXiv and return a list of paper metadata dicts.

        Each dict contains: ``id``, ``title``, ``authors``, ``summary``,
        ``published``, ``url``.
        """
        n = max_results or self._arxiv_cfg.get("max_results", 20)
        sb = sort_by or self._arxiv_cfg.get("sort_by", "relevance")
        base = "https://export.arxiv.org/api/query?"
        params = urllib.parse.urlencode({
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": n,
            "sortBy": sb,
            "sortOrder": "descending",
        })
        url = base + params
        logger.info("arXiv search | query=%r max=%d", query, n)
        try:
            with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT) as resp:
                data = resp.read().decode("utf-8")
        except Exception as exc:
            logger.warning("arXiv request failed: %s", exc)
            return []
        return self._parse_arxiv_feed(data)

    @staticmethod
    def _parse_arxiv_feed(xml_text: str) -> List[Dict[str, str]]:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        results = []
        for entry in root.findall("atom:entry", ns):
            def _txt(tag: str) -> str:
                el = entry.find(tag, ns)
                return (el.text or "").strip() if el is not None else ""

            arxiv_id = _txt("atom:id").split("/abs/")[-1]
            authors = ", ".join(
                (a.find("atom:name", ns).text or "").strip()
                for a in entry.findall("atom:author", ns)
            )
            results.append({
                "id": arxiv_id,
                "title": _txt("atom:title").replace("\n", " "),
                "authors": authors,
                "summary": _txt("atom:summary").replace("\n", " ")[:500],
                "published": _txt("atom:published")[:10],
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            })
        return results

    # ── Semantic Scholar ──────────────────────────────────────────────────────

    def search_semantic_scholar(
        self,
        query: str,
        max_results: Optional[int] = None,
        fields: str = "title,authors,year,abstract,externalIds,url",
    ) -> List[Dict[str, Any]]:
        """Search Semantic Scholar and return paper metadata dicts."""
        n = max_results or self._ss_cfg.get("max_results", 20)
        params = urllib.parse.urlencode({"query": query, "limit": n, "fields": fields})
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
        headers: Dict[str, str] = {}
        if self._ss_api_key:
            headers["x-api-key"] = self._ss_api_key
        logger.info("Semantic Scholar search | query=%r max=%d", query, n)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Semantic Scholar request failed: %s", exc)
            return []
        papers = data.get("data", [])
        results = []
        for p in papers:
            authors = ", ".join(
                a.get("name", "") for a in p.get("authors", [])
            )
            results.append({
                "id": p.get("paperId", ""),
                "title": p.get("title", ""),
                "authors": authors,
                "year": p.get("year", ""),
                "abstract": (p.get("abstract") or "")[:500],
                "url": p.get("url", ""),
            })
        return results

    # ── Serper (Google Search) ─────────────────────────────────────────────────

    def search_web(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, str]]:
        """General web search via Serper.dev.  Returns list of result dicts
        containing ``title``, ``snippet``, ``link``.
        """
        if not self._serper_api_key:
            logger.warning("Serper API key not set; skipping web search.")
            return []
        n = max_results or self._serper_cfg.get("max_results", 10)
        payload = json.dumps({"q": query, "num": n}).encode("utf-8")
        req = urllib.request.Request(
            "https://google.serper.dev/search",
            data=payload,
            headers={
                "X-API-KEY": self._serper_api_key,
                "Content-Type": "application/json",
            },
        )
        logger.info("Serper search | query=%r max=%d", query, n)
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Serper request failed: %s", exc)
            return []
        organic = data.get("organic", [])
        return [
            {"title": r.get("title", ""), "snippet": r.get("snippet", ""), "link": r.get("link", "")}
            for r in organic[:n]
        ]
