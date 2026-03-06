#!/usr/bin/env python3
"""
arXiv 论文爬取工具 — 主入口

支持两种爬取模式：
  search  : 关键词 + 日期范围搜索（调用 arXiv API）
  today   : 今日新提交论文（按类别爬取）

用法示例：
  # 模式一：关键词搜索
  python arxiv_crawler.py search --start-date 2025-01-01 --keywords "RAG" "multimodal"

  # 模式二：今日论文
  python arxiv_crawler.py today --categories cs stat

  # 使用 OpenAI 翻译
  python arxiv_crawler.py search --start-date 2025-01-01 --keywords "LLM" \\
      --translator openai --api-key sk-xxx

  # dry-run 模式（仅预览，不下载）
  python arxiv_crawler.py today --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from tqdm import tqdm  # type: ignore

# 将本脚本所在目录（arxiv_crawler/）加入搜索路径，支持直接运行
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from crawler import ArxivAPICrawler, TodayPaperCrawler, build_session  # type: ignore
from exporter import ExcelExporter  # type: ignore
from translator.base import BaseTranslator  # type: ignore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

def setup_logging(log_level: str = "INFO", output_dir: Optional[str] = None) -> None:
    """
    配置日志系统：同时输出到控制台和日志文件。

    :param log_level: 日志级别（DEBUG / INFO / WARNING / ERROR）
    :param output_dir: 日志文件保存目录（为 None 时只输出到控制台）
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        log_file = os.path.join(
            output_dir, f"arxiv_crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        print(f"日志文件：{log_file}")

    logging.basicConfig(level=numeric_level, format=fmt, datefmt=datefmt, handlers=handlers)


# ---------------------------------------------------------------------------
# 翻译器工厂
# ---------------------------------------------------------------------------

def build_translator(
    translator_type: str,
    api_key: Optional[str] = None,
    openai_model: str = "gpt-3.5-turbo",
    openai_base_url: Optional[str] = None,
) -> Optional[BaseTranslator]:
    """
    根据命令行参数构建翻译器实例。

    :param translator_type: 翻译器类型（"google" 或 "openai" 或 "none"）
    :param api_key: OpenAI API Key（仅 openai 模式需要）
    :param openai_model: OpenAI 模型名称
    :param openai_base_url: OpenAI 自定义端点（可选）
    :return: 翻译器实例；若类型为 "none" 则返回 None
    """
    if translator_type == "none":
        logger.info("翻译功能已禁用")
        return None

    if translator_type == "google":
        from translator.google_translator import GoogleTranslator  # type: ignore
        logger.info("使用 Google Translate 翻译器")
        return GoogleTranslator()

    if translator_type == "openai":
        if not api_key:
            logger.error("使用 OpenAI 翻译器时必须提供 --api-key 参数")
            sys.exit(1)
        from translator.openai_translator import OpenAITranslator  # type: ignore
        logger.info("使用 OpenAI 翻译器（模型：%s）", openai_model)
        return OpenAITranslator(
            api_key=api_key, model=openai_model, base_url=openai_base_url
        )

    logger.warning("未知翻译器类型 '%s'，禁用翻译", translator_type)
    return None


# ---------------------------------------------------------------------------
# 模式一：关键词搜索
# ---------------------------------------------------------------------------

def cmd_search(args: argparse.Namespace) -> int:
    """
    执行关键词 + 日期范围搜索模式。

    :param args: 解析后的命令行参数
    :return: 退出码（0=成功，1=失败）
    """
    # 校验日期格式
    try:
        start_date = date.fromisoformat(args.start_date)
    except ValueError:
        logger.error("无效的日期格式：%s（请使用 YYYY-MM-DD）", args.start_date)
        return 1

    end_date = date.today()
    if start_date > end_date:
        logger.error("起始日期 %s 不能晚于截止日期 %s", start_date, end_date)
        return 1

    keywords: List[str] = args.keywords
    if not keywords:
        logger.error("至少需要提供一个关键词（--keywords）")
        return 1

    logger.info("=" * 60)
    logger.info("模式：关键词搜索")
    logger.info("关键词：%s", keywords)
    logger.info("日期范围：%s ~ %s", start_date, end_date)
    logger.info("输出目录：%s", args.output_dir)
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("[dry-run] 模拟搜索，不实际请求")

    session = build_session(email=args.email)
    crawler = ArxivAPICrawler(
        session=session,
        delay=args.delay,
        email=args.email,
        dry_run=args.dry_run,
    )

    # 收集所有论文（带进度条）
    papers: List[Dict[str, Any]] = []
    logger.info("开始爬取…")
    try:
        for paper in tqdm(
            crawler.search(
                keywords=keywords,
                start_date=start_date,
                end_date=end_date,
                max_results=args.max_results,
            ),
            desc="爬取论文",
            unit="篇",
        ):
            papers.append(paper)
    except ValueError as exc:
        logger.error("参数错误：%s", exc)
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("爬取过程出错：%s", exc)
        return 1

    if args.dry_run:
        logger.info("[dry-run] 预计爬取结果（实际未请求）")
        return 0

    logger.info("共获取 %d 篇论文", len(papers))
    if not papers:
        logger.warning("未找到符合条件的论文")
        return 0

    # 构建翻译器并导出
    translator = build_translator(
        args.translator,
        api_key=getattr(args, "api_key", None),
        openai_model=getattr(args, "openai_model", "gpt-3.5-turbo"),
        openai_base_url=getattr(args, "openai_base_url", None),
    )

    exporter = ExcelExporter(output_dir=args.output_dir, translator=translator)
    try:
        paths = exporter.export(papers)
        logger.info("导出完成：")
        for file_type, path in paths.items():
            logger.info("  [%s] %s", file_type, path)
    except OSError as exc:
        logger.error("文件保存失败：%s", exc)
        return 1

    return 0


# ---------------------------------------------------------------------------
# 模式二：今日论文
# ---------------------------------------------------------------------------

def cmd_today(args: argparse.Namespace) -> int:
    """
    执行今日新提交论文爬取模式。

    :param args: 解析后的命令行参数
    :return: 退出码
    """
    categories: List[str] = args.categories or ["cs", "stat", "eess", "math"]

    logger.info("=" * 60)
    logger.info("模式：今日新提交论文")
    logger.info("类别：%s", categories)
    logger.info("输出目录：%s", args.output_dir)
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("[dry-run] 模拟爬取，不实际请求")

    session = build_session(email=args.email)
    crawler = TodayPaperCrawler(
        session=session,
        delay=args.delay,
        email=args.email,
        dry_run=args.dry_run,
    )

    papers: List[Dict[str, Any]] = []
    try:
        for paper in tqdm(
            crawler.crawl(categories=categories),
            desc="爬取今日论文",
            unit="篇",
        ):
            papers.append(paper)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("爬取过程出错：%s", exc)
        return 1

    if args.dry_run:
        logger.info("[dry-run] 已模拟爬取 %d 个类别", len(categories))
        return 0

    logger.info("共获取 %d 篇论文", len(papers))
    if not papers:
        logger.warning("今日暂无新提交论文（可能还未发布）")
        return 0

    translator = build_translator(
        args.translator,
        api_key=getattr(args, "api_key", None),
        openai_model=getattr(args, "openai_model", "gpt-3.5-turbo"),
        openai_base_url=getattr(args, "openai_base_url", None),
    )

    exporter = ExcelExporter(output_dir=args.output_dir, translator=translator)
    try:
        paths = exporter.export(papers)
        logger.info("导出完成：")
        for file_type, path in paths.items():
            logger.info("  [%s] %s", file_type, path)
    except OSError as exc:
        logger.error("文件保存失败：%s", exc)
        return 1

    return 0


# ---------------------------------------------------------------------------
# CLI 参数解析
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """构建并返回命令行参数解析器。"""
    # 主解析器
    parser = argparse.ArgumentParser(
        prog="arxiv_crawler",
        description="arXiv 论文爬取工具 — 支持关键词搜索和今日新提交两种模式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python arxiv_crawler.py search --start-date 2025-01-01 "
            "--keywords \"RAG\" \"multimodal\"\n"
            "  python arxiv_crawler.py today --categories cs stat\n"
            "  python arxiv_crawler.py today --dry-run\n"
        ),
    )

    # 公共参数（所有子命令共享）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--output-dir", default="./arxiv_output",
        help="输出目录（默认：./arxiv_output）",
    )
    common.add_argument(
        "--delay", type=float, default=3.0,
        help="请求间隔秒数，遵守 arXiv 访问限制（默认：3.0）",
    )
    common.add_argument(
        "--email", default=None,
        help="联系邮箱（写入 From 请求头，arXiv 推荐提供）",
    )
    common.add_argument(
        "--translator", choices=["google", "openai", "none"], default="google",
        help="翻译后端：google（默认）/ openai / none（不翻译）",
    )
    common.add_argument(
        "--api-key", default=None,
        help="OpenAI API Key（使用 --translator openai 时必填）",
    )
    common.add_argument(
        "--openai-model", default="gpt-3.5-turbo",
        help="OpenAI 模型名称（默认：gpt-3.5-turbo）",
    )
    common.add_argument(
        "--openai-base-url", default=None,
        help="OpenAI API 自定义端点（可选）",
    )
    common.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别（默认：INFO）",
    )
    common.add_argument(
        "--dry-run", action="store_true",
        help="仅预览将要执行的操作，不实际爬取或下载",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # 子命令：search（关键词搜索）
    sp_search = subparsers.add_parser(
        "search",
        parents=[common],
        help="关键词 + 日期范围搜索",
        description="通过 arXiv API 搜索指定日期范围和关键词的论文",
    )
    sp_search.add_argument(
        "--start-date", required=True, metavar="YYYY-MM-DD",
        help="搜索起始日期（包含），格式：YYYY-MM-DD",
    )
    sp_search.add_argument(
        "--keywords", nargs="+", required=True, metavar="KEYWORD",
        help="搜索关键词（一个或多个，用空格分隔）",
    )
    sp_search.add_argument(
        "--max-results", type=int, default=500,
        help="最大返回结果数（默认：500）",
    )
    sp_search.set_defaults(func=cmd_search)

    # 子命令：today（今日新提交）
    sp_today = subparsers.add_parser(
        "today",
        parents=[common],
        help="爬取今日新提交论文",
        description="爬取今天在 arXiv 上新提交的论文",
    )
    sp_today.add_argument(
        "--categories", nargs="+", default=None, metavar="CATEGORY",
        help="arXiv 类别（如 cs stat eess math），默认：cs stat eess math",
    )
    sp_today.set_defaults(func=cmd_today)

    return parser


# ---------------------------------------------------------------------------
# 程序入口
# ---------------------------------------------------------------------------

def main() -> int:
    """主函数：解析参数并分发到对应子命令处理函数。"""
    parser = build_parser()
    args = parser.parse_args()

    # 初始化日志（在解析参数后，这样 --log-level 和 --output-dir 已可用）
    setup_logging(
        log_level=args.log_level,
        output_dir=args.output_dir,
    )

    logger.info("arXiv 论文爬取工具启动（命令：%s）", args.command)

    try:
        return args.func(args)
    except KeyboardInterrupt:
        logger.info("用户中断，程序退出")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("程序异常退出：%s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
