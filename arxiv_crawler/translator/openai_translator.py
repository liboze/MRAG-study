"""
OpenAI 翻译器
使用 OpenAI Chat Completion API 进行高质量翻译，支持学术文本。
需要提供有效的 OpenAI API Key（通过 --api-key 参数传入）。
"""

import logging
from typing import List, Optional

from .base import BaseTranslator

logger = logging.getLogger(__name__)

# 翻译系统提示词：针对学术论文优化
_SYSTEM_PROMPT = (
    "You are a professional academic translator specializing in computer science "
    "and machine learning papers. Translate the following text into Simplified Chinese "
    "(简体中文). Keep technical terms accurate. Return only the translated text, "
    "no explanations."
)


class OpenAITranslator(BaseTranslator):
    """
    使用 OpenAI API 进行翻译的实现类。
    支持 gpt-3.5-turbo 和 gpt-4 等模型，适合高质量学术翻译。
    翻译失败时优雅降级，返回原文。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-3.5-turbo",
        base_url: Optional[str] = None,
    ) -> None:
        """
        初始化 OpenAI 翻译器。

        :param api_key: OpenAI API Key
        :param model: 使用的模型名称（默认 gpt-3.5-turbo）
        :param base_url: 自定义 API 端点（可选，用于代理或兼容接口）
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = None  # 延迟初始化，避免导入时报错

    def _get_client(self):
        """延迟初始化 OpenAI 客户端。"""
        if self._client is None:
            try:
                import openai  # type: ignore

                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = openai.OpenAI(**kwargs)
            except ImportError:
                logger.error("未安装 openai，请运行：pip install openai")
                raise
        return self._client

    def translate(self, text: str, dest_lang: str = "zh-CN") -> str:
        """
        使用 OpenAI API 翻译单段文本。

        :param text: 待翻译的原始文本
        :param dest_lang: 目标语言（当前固定为简体中文）
        :return: 翻译后的文本；失败时返回原文
        """
        if not text or not text.strip():
            return text

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,  # 较低的温度以保证翻译准确性
                max_tokens=2048,
            )
            translated = response.choices[0].message.content
            return translated.strip() if translated else text

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("OpenAI 翻译失败，返回原文。原因：%s", exc)
            return text

    def translate_batch(self, texts: List[str], dest_lang: str = "zh-CN") -> List[str]:
        """
        批量翻译：将多条文本合并为一次 API 调用以节省费用。

        :param texts: 待翻译文本列表
        :param dest_lang: 目标语言代码
        :return: 翻译结果列表
        """
        if not texts:
            return []

        # 将文本用编号分隔符合并，便于 LLM 按序返回
        numbered_texts = "\n---ITEM_SEP---\n".join(
            f"[{i + 1}] {t}" for i, t in enumerate(texts)
        )
        batch_prompt = (
            f"Please translate each numbered item below into Simplified Chinese. "
            f"Return only the translations, preserving the [N] numbering:\n\n"
            f"{numbered_texts}"
        )

        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": batch_prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            raw = response.choices[0].message.content or ""
            # 解析编号结果
            results = self._parse_numbered_response(raw, len(texts))
            # 解析失败时回退到逐条翻译
            if len(results) != len(texts):
                logger.warning("批量翻译解析失败，回退到逐条翻译")
                return super().translate_batch(texts, dest_lang)
            return results

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("OpenAI 批量翻译失败，回退到逐条翻译。原因：%s", exc)
            return super().translate_batch(texts, dest_lang)

    @staticmethod
    def _parse_numbered_response(raw: str, expected_count: int) -> List[str]:
        """
        解析带编号的翻译响应。

        :param raw: LLM 返回的原始文本
        :param expected_count: 预期翻译条数
        :return: 解析出的翻译列表
        """
        import re

        lines = raw.strip().split("\n")
        results: List[str] = []
        current_item: List[str] = []

        for line in lines:
            # 匹配 [N] 或 N. 开头的编号行
            match = re.match(r"^\[(\d+)\]\s*(.*)$", line.strip())
            if match:
                if current_item:
                    results.append(" ".join(current_item).strip())
                    current_item = []
                content = match.group(2).strip()
                if content:
                    current_item.append(content)
            elif current_item:
                current_item.append(line.strip())

        if current_item:
            results.append(" ".join(current_item).strip())

        return results if len(results) == expected_count else []
