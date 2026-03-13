"""Tests for agent/tools/search_client.py — arXiv XML parser (offline)."""

from __future__ import annotations

from agent.tools.search_client import SearchClient

_SAMPLE_ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>A Great Paper on RAG</title>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <summary>This paper proposes a novel RAG method.</summary>
    <published>2023-01-01T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00002v1</id>
    <title>Another Paper</title>
    <author><name>Carol White</name></author>
    <summary>Second abstract.</summary>
    <published>2023-02-01T00:00:00Z</published>
  </entry>
</feed>
"""


def test_parse_arxiv_feed():
    results = SearchClient._parse_arxiv_feed(_SAMPLE_ARXIV_XML)
    assert len(results) == 2
    assert results[0]["title"] == "A Great Paper on RAG"
    assert "Alice Smith" in results[0]["authors"]
    assert "2301.00001" in results[0]["id"]
    assert results[0]["url"].startswith("https://arxiv.org/abs/")


def test_parse_arxiv_feed_empty():
    results = SearchClient._parse_arxiv_feed("<feed></feed>")
    assert results == []


def test_parse_arxiv_feed_invalid_xml():
    results = SearchClient._parse_arxiv_feed("not xml at all")
    assert results == []


def test_search_client_init():
    client = SearchClient({
        "arxiv": {"max_results": 5, "sort_by": "relevance"},
        "semantic_scholar": {},
        "serper": {},
    })
    assert client._arxiv_cfg["max_results"] == 5
