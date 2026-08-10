from __future__ import annotations

import os
from typing import Any

from openai import OpenAI
from .pdf_parser import Block


class TranslationNotConfigured(RuntimeError):
    """Raised when the translation API is not configured."""
    pass


class Translator:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        client: Any | None = None,
    ) -> None:
        """
        Initialize the translator with the given API key, base URL, model, and client.

        Args:
            api_key (str | None): The API key for the translation service. If not provided, it will be read from the environment variable LLM_API_KEY or OPENAI_API_KEY.
            base_url (str | None): The base URL for the translation service. If not provided, it will be read from the environment variable LLM_BASE_URL or OPENAI_BASE_URL.
            model (str | None): The model to use for translation. If not provided, it will be read from the environment variable LLM_MODEL_ID or ACADEMIC_AGENT_MODEL.
            client (Any | None): An existing client instance to use. If not provided, a new client will be created.

        Returns:
            None
        """
        self.model = (
            model
            or os.getenv("LLM_MODEL_ID")
            or os.getenv("ACADEMIC_AGENT_MODEL")
            or "deepseek-chat"
        )
        configured_api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        configured_base_url = (
            base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        )
        try:
            timeout = float(os.getenv("LLM_TIMEOUT") or os.getenv("OPENAI_TIMEOUT") or "60")
        except ValueError:
            timeout = 60.0
        if client is not None:
            self.client = client
        elif configured_api_key:
            client_options: dict[str, Any] = {
                "api_key": configured_api_key,
                "timeout": timeout,
            }
            if configured_base_url:
                client_options["base_url"] = configured_base_url
            self.client = OpenAI(**client_options)
        else:
            self.client = None

    def translate_block(self, block: Block) -> str:
        """Translate a given block of text.

        Args:
            block (Block): The block of text to translate.

        Returns:
            str: The translated text.
        """
        if block.kind == "formula":
            block.translation = "公式（见原文）"
            return block.translation
        translation = self.translate_text(block.text)
        block.translation = translation
        return translation

    def translate_text(self, text: str) -> str:
        """Translate a given string of text.

        Args:
            text (str): The text to translate.

        Returns:
            str: The translated text.
        """
        if not text.strip():
            return ""
        if self.client is None:
            raise TranslationNotConfigured(
                "未配置模型 API。请设置 LLM_API_KEY，或在设置页配置 API。"
            )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "将用户提供的科研文本翻译为简体中文。只返回译文，不要解释。",
                },
                {"role": "user", "content": text},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("模型返回了空译文。")
        return content.strip()
