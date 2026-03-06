"""
翻译器抽象基类
定义所有翻译后端必须实现的统一接口。
"""

from abc import ABC, abstractmethod
from typing import List


class BaseTranslator(ABC):
    """翻译器抽象基类，所有具体翻译实现均需继承此类。"""

    @abstractmethod
    def translate(self, text: str, dest_lang: str = "zh-CN") -> str:
        """
        翻译单段文本。

        :param text: 待翻译的原始文本
        :param dest_lang: 目标语言代码（默认简体中文）
        :return: 翻译后的文本；若翻译失败应返回原文
        """

    def translate_batch(self, texts: List[str], dest_lang: str = "zh-CN") -> List[str]:
        """
        批量翻译文本列表。默认逐条调用 translate()，子类可覆盖以实现批量优化。

        :param texts: 待翻译文本列表
        :param dest_lang: 目标语言代码
        :return: 翻译后的文本列表，顺序与输入保持一致
        """
        return [self.translate(t, dest_lang) for t in texts]
