from __future__ import annotations

from typing import Any, Sequence

from app.core.session_store import Message


class ChatNotConfigured(RuntimeError):
    pass


class ChatService:
    """Run paper-grounded chat through an OpenAI-compatible client."""

    def __init__(
        self,
        client: Any | None,
        model: str,
        max_history_chars: int = 24000,
    ) -> None:
        """
        初始化llm服务

        Args:
            client: OpenAi 客户端
            model: 模型名称
            max_history_chars: 最大历史字符数
        """
        self.client = client
        self.model = model
        self.max_history_chars = max_history_chars

    def answer(self, messages: Sequence[Message], paper_context: str) -> str:
        """
        回答用户问题

        Args:
            messages: 用户消息列表
            paper_context: 论文原文内容
        
        Returns:
            str: 模型回答内容
        """
        if self.client is None:
            raise ChatNotConfigured("未配置 LLM_API_KEY，无法进行论文问答。")
        request_messages = [
            {
                "role": "system",
                "content": (
                    "你是科研论文阅读助手。请优先依据下面的论文原文回答，"
                    "信息不足时明确说明，不要编造。使用简体中文。\n\n"
                    f"论文原文：\n{paper_context or '当前未打开论文。'}"
                ),
            }
        ]
        request_messages.extend(self._recent_messages(messages))
        response = self.client.chat.completions.create(
            model=self.model,
            messages=request_messages,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("模型返回了空回复。")
        return content.strip()

    def _recent_messages(self, messages: Sequence[Message]) -> list[dict[str, str]]:
        """
        获取最近的用户和助手消息，按时间顺序排列，并限制总字符数不超过 max_history_chars。

        Args:
            messages: 用户消息列表
        
        Returns:
            list[dict[str, str]]: 最近的用户和助手消息列表，每条消息包含角色和内容
        """
        selected: list[Message] = []
        used_chars = 0
        for message in reversed(messages):
            if message.role not in {"user", "assistant"} or not message.content: # 系统消息和空消息不考虑
                continue
            if selected and used_chars + len(message.content) > self.max_history_chars: # 超过最大字符数，停止添加
                break
            selected.append(message)
            used_chars += len(message.content)
        return [
            {"role": message.role, "content": message.content or ""}
            for message in reversed(selected)
        ]

