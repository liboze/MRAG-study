"""
arXiv 今日新提交论文爬取模块（模式二：Today's Papers）
通过 arXiv API 按类别获取当天提交的最新论文。
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

import feedparser  # type: ignore
import requests

from .utils import build_session, rate_limited_get

logger = logging.getLogger(__name__)

ARXIV_API_BASE = "http://export.arxiv.org/api/query"

# 今日论文爬取的默认类别（主要 CS/统计/工程领域）
DEFAULT_CATEGORIES = ["cs", "stat", "eess", "math"]

# 常用的 arXiv 子类别（用于 list 页面爬取）
CS_SUBCATEGORIES = [
    "cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.IR",
    "cs.NE", "cs.RO", "cs.DB", "cs.DC", "cs.SE",
]

MAX_RESULTS_PER_CATEGORY = 500


def _get_today_date_range():
    """返回今日的日期范围（考虑 arXiv 按 UTC 发布的习惯，取前一天到今天）。"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    return yesterday, today


def _parse_entry_today(entry: Any, category: str, crawl_time: datetime) -> Dict[str, Any]:
    """
    解析今日论文的 feedparser entry。

    :param entry: feedparser entry 对象
    :param category: 所属 arXiv 类别
    :param crawl_time: 爬取时间
    :return: 论文数据字典
    """
    arxiv_id = entry.get("id", "")
    if "/" in arxiv_id:
        arxiv_id = arxiv_id.rstrip("/").split("/")[-1]

    authors: List[str] = []
    for author in entry.get("authors", []):
        name = author.get("name", "").strip()
        if name:
            authors.append(name)

    affiliations: List[str] = []
    for author in entry.get("authors", []):
        aff = author.get("arxiv_affiliation", "").strip()
        if aff:
            affiliations.append(aff)

    published_str = entry.get("published", "")
    try:
        published_dt = datetime.strptime(published_str[:10], "%Y-%m-%d").date()
        published_date = published_dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        published_date = published_str[:10] if published_str else ""

    abstract = entry.get("summary", "").strip()
    abstract = " ".join(abstract.split())

    pdf_link = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            pdf_link = link.get("href", pdf_link)
            break

    return {
        "crawl_time": crawl_time.strftime("%Y-%m-%d %H:%M:%S"),
        "keywords": f"category:{category}",
        "published_date": published_date,
        "title": entry.get("title", "").strip().replace("\n", " "),
        "authors": "; ".join(authors),
        "affiliations": "; ".join(affiliations) if affiliations else "未提供",
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "pdf_link": pdf_link,
    }


class TodayPaperCrawler:
    """
    按类别爬取 arXiv 当日新提交论文。
    使用 arXiv API 按类别和日期范围过滤，获取当天最新提交的论文列表。
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        delay: float = 3.0,
        email: Optional[str] = None,
        dry_run: bool = False,
    ) -> None:
        """
        初始化今日论文爬取器。

        :param session: 可复用的 requests.Session
        :param delay: 请求间隔秒数
        :param email: 联系邮箱
        :param dry_run: 仅预览，不实际请求
        """
        self.session = session or build_session(email)
        self.delay = delay
        self.dry_run = dry_run

    def crawl(
        self,
        categories: Optional[List[str]] = None,
        max_per_category: int = MAX_RESULTS_PER_CATEGORY,
    ) -> Iterator[Dict[str, Any]]:
        """
        爬取指定类别的今日论文。

        :param categories: arXiv 类别列表（如 ["cs", "stat"]），默认使用 DEFAULT_CATEGORIES
        :param max_per_category: 每个类别最多获取的论文数
        :return: 论文数据字典的迭代器
        """
        if categories is None:
            categories = DEFAULT_CATEGORIES

        crawl_time = datetime.now()
        yesterday, today = _get_today_date_range()

        # 格式化日期用于 arXiv API
        start_str = yesterday.strftime("%Y%m%d") + "0000"
        end_str = today.strftime("%Y%m%d") + "2359"

        seen_ids: set = set()  # 去重，避免同一论文在多个类别中重复出现

        for category in categories:
            logger.info("正在爬取类别 [%s] 的今日论文…", category)

            if self.dry_run:
                logger.info("[dry-run] 将要爬取类别：%s", category)
                continue

            # 构建类别查询：cat:cs.* 或精确类别
            if "." in category:
                cat_query = f"cat:{category}"
            else:
                # 主类别匹配所有子类别（如 cs 匹配 cs.LG, cs.CL 等）
                cat_query = f"cat:{category}.*"

            query = f"{cat_query} AND submittedDate:[{start_str} TO {end_str}]"

            start_index = 0
            category_count = 0

            while category_count < max_per_category:
                batch_size = min(200, max_per_category - category_count)
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
                        delay=self.delay,
                        params=params,
                    )
                except requests.RequestException as exc:
                    logger.error("类别 [%s] 请求失败：%s", category, exc)
                    break

                feed = feedparser.parse(response.content)

                if feed.get("bozo") and not feed.get("entries"):
                    logger.error("类别 [%s] XML 解析失败", category)
                    break

                entries = feed.get("entries", [])
                if not entries:
                    logger.info("类别 [%s] 已获取全部结果（%d 条）", category, category_count)
                    break

                for entry in entries:
                    arxiv_id = entry.get("id", "")
                    if "/" in arxiv_id:
                        arxiv_id = arxiv_id.rstrip("/").split("/")[-1]

                    # 跳过已处理的论文
                    if arxiv_id in seen_ids:
                        continue
                    seen_ids.add(arxiv_id)

                    paper = _parse_entry_today(entry, category, crawl_time)
                    yield paper
                    category_count += 1

                start_index += len(entries)
                if len(entries) < batch_size:
                    break

            logger.info("类别 [%s] 共获取 %d 篇论文", category, category_count)
