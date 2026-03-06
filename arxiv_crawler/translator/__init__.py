"""
翻译器模块
提供 Google Translate 和 OpenAI 两种翻译后端。
"""

from .base import BaseTranslator
from .google_translator import GoogleTranslator
from .openai_translator import OpenAITranslator

__all__ = ["BaseTranslator", "GoogleTranslator", "OpenAITranslator"]
