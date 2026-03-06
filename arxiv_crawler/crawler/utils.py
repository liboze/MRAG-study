"""
共享工具模块
提供 User-Agent 轮换、请求频率限制、指数退避重试等功能。
"""

import time
import random
import logging
from typing import Optional, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 真实浏览器 User-Agent 池，用于轮换请求头，降低被封锁风险
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.1; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


def get_random_user_agent() -> str:
    """随机返回一个浏览器 User-Agent 字符串。"""
    try:
        # 优先尝试使用 fake-useragent 库获取更多样化的 UA
        from fake_useragent import UserAgent  # type: ignore
        ua = UserAgent()
        return ua.random
    except Exception:
        # 回退到内置 UA 池
        return random.choice(USER_AGENTS)


def build_session(email: Optional[str] = None) -> requests.Session:
    """
    构建并返回一个配置好的 requests.Session 对象。
    包含连接池复用、基础重试策略（仅针对连接/读取超时），
    以及 arXiv API 推荐的 From 请求头。

    :param email: 可选的联系邮箱，arXiv API 文档建议在 From 头中提供
    :return: 配置完成的 Session 对象
    """
    session = requests.Session()

    # 配置 urllib3 层面的重试（仅针对连接/读取错误，不含 HTTP 错误码）
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 设置默认请求头
    session.headers.update({
        "User-Agent": get_random_user_agent(),
        "Accept": "application/atom+xml,application/xml,text/xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })

    # 若提供邮箱，添加 From 头（arXiv API 礼貌性要求）
    if email:
        session.headers.update({"From": email})

    return session


def rotate_user_agent(session: requests.Session) -> None:
    """为现有 Session 更换随机 User-Agent，每次请求前调用以降低检测风险。"""
    session.headers.update({"User-Agent": get_random_user_agent()})


def rate_limited_get(
    session: requests.Session,
    url: str,
    delay: float = 3.0,
    max_retries: int = 3,
    timeout: int = 30,
    **kwargs,
) -> requests.Response:
    """
    带频率限制和指数退避重试的 HTTP GET 请求。

    :param session: requests.Session 对象
    :param url: 请求 URL
    :param delay: 请求前等待的秒数（合规延迟）
    :param max_retries: 最大重试次数
    :param timeout: 单次请求超时秒数
    :param kwargs: 传递给 session.get 的额外参数
    :return: requests.Response 对象
    :raises requests.RequestException: 所有重试失败后抛出
    """
    # 请求前轮换 UA
    rotate_user_agent(session)

    # 合规延迟：遵守 arXiv 访问策略
    if delay > 0:
        logger.debug("等待 %.1f 秒（合规延迟）…", delay)
        time.sleep(delay)

    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug("发送 GET 请求：%s（第 %d 次尝试）", url, attempt)
            response = session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            logger.warning("请求超时（第 %d/%d 次）：%s", attempt, max_retries, url)
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            logger.warning("连接错误（第 %d/%d 次）：%s", attempt, max_retries, url)
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else "?"
            logger.warning(
                "HTTP 错误 %s（第 %d/%d 次）：%s", status, attempt, max_retries, url
            )
            # 4xx 客户端错误（除 429 Too Many Requests 外）不重试
            if (
                exc.response is not None
                and 400 <= exc.response.status_code < 500
                and exc.response.status_code != 429
            ):
                raise

        if attempt < max_retries:
            # 指数退避：2^attempt 秒 + 随机抖动
            backoff = (2 ** attempt) + random.uniform(0, 1)
            logger.info("%.1f 秒后重试…", backoff)
            time.sleep(backoff)

    raise requests.RequestException(
        f"请求失败，已重试 {max_retries} 次：{url}"
    ) from last_exc
