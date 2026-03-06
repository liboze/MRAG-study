"""
Google Translate 翻译器
基于 deep-translator 库实现，免费且无需 API Key。
"""

import logging
import time
from typing import List

from .base import BaseTranslator

logger = logging.getLogger(__name__)


class GoogleTranslator(BaseTranslator):
    """
    使用 deep-translator 库调用 Google 翻译服务。
    翻译失败时优雅降级，返回原文，确保程序不中断。
    """

    # 单次翻译的最大字符数（Google 翻译单次上限约 5000 字符）
    MAX_CHARS = 4500

    def translate(self, text: str, dest_lang: str = "zh-CN") -> str:
        """
        翻译单段文本到目标语言。

        :param text: 待翻译的原始文本
        :param dest_lang: 目标语言代码（默认简体中文 zh-CN）
        :return: 翻译后的文本；失败时返回原文
        """
        if not text or not text.strip():
            return text

        try:
            from deep_translator import GoogleTranslator as _GT  # type: ignore

            # Google Translate API 语言代码映射
            lang_map = {"zh-CN": "zh-CN", "zh": "zh-CN", "en": "en"}
            target = lang_map.get(dest_lang, dest_lang)

            # 超长文本分段翻译
            if len(text) > self.MAX_CHARS:
                return self._translate_long_text(text, target)

            translator = _GT(source="auto", target=target)
            result = translator.translate(text)
            return result if result else text

        except ImportError:
            logger.error("未安装 deep-translator，请运行：pip install deep-translator")
            return text
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Google 翻译失败，返回原文。原因：%s", exc)
            return text

    def _translate_long_text(self, text: str, target: str) -> str:
        """
        将超长文本按段落拆分后逐段翻译，再拼接结果。

        :param text: 超长原始文本
        :param target: 目标语言代码
        :return: 拼接后的翻译文本
        """
        from deep_translator import GoogleTranslator as _GT  # type: ignore

        # 按字符数硬切分为等长块，保留词边界（在空格处切断）
        # 比按句子边界更健壮，避免误切缩写词（如 "et al.", "e.g.", "Fig."）
        chunks: List[str] = []
        while len(text) > self.MAX_CHARS:
            # 在 MAX_CHARS 附近找最近的空格作为切分点
            split_pos = text.rfind(" ", 0, self.MAX_CHARS)
            if split_pos == -1:
                # 没有空格则强制切分
                split_pos = self.MAX_CHARS
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip()
        if text:
            chunks.append(text)

        translated_parts: List[str] = []
        for chunk in chunks:
            try:
                translator = _GT(source="auto", target=target)
                part = translator.translate(chunk)
                translated_parts.append(part if part else chunk)
                # 避免请求过于频繁
                time.sleep(0.5)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("分段翻译失败，保留原文。原因：%s", exc)
                translated_parts.append(chunk)

        return " ".join(translated_parts)

    def translate_batch(self, texts: List[str], dest_lang: str = "zh-CN") -> List[str]:
        """
        批量翻译，每条之间加入短暂延迟，避免触发频率限制。

        :param texts: 待翻译文本列表
        :param dest_lang: 目标语言代码
        :return: 翻译结果列表
        """
        results: List[str] = []
        for i, text in enumerate(texts):
            results.append(self.translate(text, dest_lang))
            # 每 5 条请求后增加额外延迟，防止被封锁
            if (i + 1) % 5 == 0:
                time.sleep(1.0)
        return results
