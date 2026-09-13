from __future__ import annotations

from typing import Any, Sequence

from app.core.session_store import Message, selected_passage_from_metadata


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
                    "你是科研论文阅读助手。请优先依据下面提供的论文资料回答，"
                    "信息不足时明确说明，不要编造。使用简体中文。资料中若有"
                    "[来源N]标记，请在相关结论后保留该标记作为引用。用户消息中"
                    "若附有[选中段落]，优先依据该段回答，并使用[选中段落]引用。\n\n"
                    f"论文资料：\n{paper_context or '当前没有可用论文资料。'}"
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
        selected: list[tuple[Message, str]] = []
        used_chars = 0
        for message in reversed(messages):
            if message.role not in {"user", "assistant"} or not message.content: # 系统消息和空消息不考虑
                continue
            content = self._message_content(message)
            if selected and used_chars + len(content) > self.max_history_chars: # 超过最大字符数，停止添加
                break
            selected.append((message, content))
            used_chars += len(content)
        return [
            {"role": message.role, "content": content}
            for message, content in reversed(selected)
        ]

    @staticmethod
    def _message_content(message: Message) -> str:
        content = message.content or ""
        if message.role != "user":
            return content
        passage = selected_passage_from_metadata(message.metadata)
        if passage is None:
            return content
        title = passage.get("paper_title") or "当前论文"
        page = passage.get("page") or "未知"
        translation = passage.get("translation")
        sections = [
            "[选中段落]",
            f"论文：{title}，第 {page} 页",
            f"原文：\n{passage['text']}",
        ]
        if translation:
            sections.append(f"中文译文：\n{translation}")
        sections.append(f"用户问题：\n{content}")
        return "\n\n".join(sections)
