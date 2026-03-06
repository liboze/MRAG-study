"""
arXiv API 爬取模块（模式一：关键词 + 日期范围搜索）
通过官方 arXiv API (http://export.arxiv.org/api/query) 搜索论文。
"""

import logging
import time
from datetime import date, datetime
from typing import Any, Dict, Iterator, List, Optional

import feedparser  # type: ignore
import requests

from .utils import build_session, rate_limited_get

logger = logging.getLogger(__name__)

# arXiv API 端点
ARXIV_API_BASE = "http://export.arxiv.org/api/query"

# 单次 API 请求最多返回的结果数（arXiv 限制最大 2000）
MAX_RESULTS_PER_REQUEST = 200


def _build_search_query(keywords: List[str], start_date: date, end_date: date) -> str:
    """
    构建 arXiv API 查询字符串。
    在 title 和 abstract 字段中搜索任意关键词。

    :param keywords: 关键词列表（OR 逻辑）
    :param start_date: 搜索起始日期
    :param end_date: 搜索截止日期
    :return: arXiv API 查询字符串
    """
    # 将每个关键词在 title 和 abstract 中做 OR 搜索
    keyword_parts: List[str] = []
    for kw in keywords:
        # 多词短语需要加引号
        kw_escaped = kw.replace('"', "")
        if " " in kw_escaped:
            term = f'(ti:"{kw_escaped}" OR abs:"{kw_escaped}")'
        else:
            term = f"(ti:{kw_escaped} OR abs:{kw_escaped})"
        keyword_parts.append(term)

    keyword_query = " OR ".join(keyword_parts)

    # 日期范围过滤（submittedDate 格式：YYYYMMDD0000 TO YYYYMMDD2359）
    start_str = start_date.strftime("%Y%m%d") + "0000"
    end_str = end_date.strftime("%Y%m%d") + "2359"
    date_filter = f"submittedDate:[{start_str} TO {end_str}]"

    return f"({keyword_query}) AND {date_filter}"


def _parse_entry(entry: Any, keywords: List[str], crawl_time: datetime) -> Dict[str, Any]:
    """
    将 feedparser 解析的单条 arXiv entry 转换为结构化字典。

    :param entry: feedparser entry 对象
    :param keywords: 本次搜索使用的关键词列表（用于记录）
    :param crawl_time: 爬取时间戳
    :return: 论文数据字典
    """
    # 提取 arXiv ID（格式：arxiv:XXXX.XXXXX）
    arxiv_id = entry.get("id", "")
    # 从 URL 中提取纯 ID：https://arxiv.org/abs/2301.00001
    if "/" in arxiv_id:
        arxiv_id = arxiv_id.rstrip("/").split("/")[-1]

    # 提取作者列表
    authors: List[str] = []
    for author in entry.get("authors", []):
        name = author.get("name", "").strip()
        if name:
            authors.append(name)

    # 提取作者机构（arXiv 通常不提供此信息）
    affiliations: List[str] = []
    for author in entry.get("authors", []):
        aff = author.get("arxiv_affiliation", "").strip()
        if aff:
            affiliations.append(aff)

    # 提取发表日期
    published_str = entry.get("published", "")
    try:
        published_dt = datetime.strptime(published_str[:10], "%Y-%m-%d").date()
        published_date = published_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        published_date = published_str[:10] if published_str else ""

    # 提取摘要，清理多余空白
    abstract = entry.get("summary", "").strip()
    abstract = " ".join(abstract.split())  # 将换行符等合并为空格

    # PDF 链接
    pdf_link = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    # 优先从 links 中提取官方 PDF 链接
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            pdf_link = link.get("href", pdf_link)
            break

    return {
        "crawl_time": crawl_time.strftime("%Y-%m-%d %H:%M:%S"),
        "keywords": ", ".join(keywords),
        "published_date": published_date,
        "title": entry.get("title", "").strip().replace("\n", " "),
        "authors": "; ".join(authors),
        "affiliations": "; ".join(affiliations) if affiliations else "未提供",
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "pdf_link": pdf_link,
    }


class ArxivAPICrawler:
    """
    通过 arXiv 官方 API 爬取论文元数据。
    支持关键词 + 日期范围搜索，自动分页获取所有结果。
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        delay: float = 3.0,
        email: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        """
        初始化 API 爬取器。

        :param session: 可复用的 requests.Session（若不提供则自动创建）
        :param delay: 请求间隔秒数
        :param email: 联系邮箱（写入 From 请求头）
        :param dry_run: 若为 True 则只打印信息，不实际请求
        """
        self.session = session or build_session(email)
        self.delay = delay
        self.dry_run = dry_run

    def search(
        self,
        keywords: List[str],
        start_date: date,
        end_date: Optional[date] = None,
        max_results: int = 2000,
    ) -> Iterator[Dict[str, Any]]:
        """
        搜索满足条件的 arXiv 论文，逐条 yield 结果。

        :param keywords: 关键词列表（至少一个）
        :param start_date: 搜索起始日期
        :param end_date: 搜索截止日期（默认为今天）
        :param max_results: 最大返回结果数
        :return: 论文数据字典的迭代器
        """
        if not keywords:
            raise ValueError("至少需要提供一个关键词")

        if end_date is None:
            end_date = date.today()

        if start_date > end_date:
            raise ValueError(f"起始日期 {start_date} 不能晚于截止日期 {end_date}")

        crawl_time = datetime.now()
        query = _build_search_query(keywords, start_date, end_date)
        logger.info("搜索查询：%s", query)
        logger.info("日期范围：%s ~ %s", start_date, end_date)

        if self.dry_run:
            logger.info("[dry-run] 将要搜索：关键词=%s，日期=%s~%s", keywords, start_date, end_date)
            return

        fetched = 0
        start_index = 0

        while fetched < max_results:
            batch_size = min(MAX_RESULTS_PER_REQUEST, max_results - fetched)
            params = {
                "search_query": query,
                "start": start_index,
                "max_results": batch_size,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            try:
                response = rate_limited_get(
                    self.session,
                    ARXIV_API_BASE,
                    delay=self.delay if start_index > 0 else 0,
                    params=params,
                )
            except requests.RequestException as exc:
                logger.error("API 请求失败：%s", exc)
                break

            # 使用 feedparser 解析 Atom XML 响应
            feed = feedparser.parse(response.content)

            if feed.get("bozo") and not feed.get("entries"):
                logger.error("XML 解析失败：%s", feed.get("bozo_exception"))
                break

            entries = feed.get("entries", [])
            if not entries:
                logger.info("已获取全部结果（共 %d 条）", fetched)
                break

            for entry in entries:
                paper = _parse_entry(entry, keywords, crawl_time)
                # 二次过滤：确保关键词出现在标题或摘要中（API 有时返回不完全匹配结果）
                title_abs = (paper["title"] + " " + paper["abstract"]).lower()
                if any(kw.lower() in title_abs for kw in keywords):
                    yield paper
                    fetched += 1
                    if fetched >= max_results:
                        break

            start_index += len(entries)
            # 若返回条数少于请求条数，说明已到末尾
            if len(entries) < batch_size:
                break

            logger.debug("已获取 %d 条，继续分页…", fetched)
            # 分页请求间增加额外延迟
            time.sleep(self.delay)
