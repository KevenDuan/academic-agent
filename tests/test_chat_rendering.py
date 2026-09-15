from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.core.session_store import Message
from app.ui.chat_panel import ChatPanel


def make_message(
    role: str,
    content: str,
    metadata: object | None = None,
) -> Message:
    return Message(
        message_id=1,
        session_id="session",
        role=role,
        content=content,
        tool_calls=None,
        created_at="2026-09-13T00:00:00+00:00",
        metadata=metadata,
    )


class ChatRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_markdown_renders_common_answer_elements(self):
        rendered = ChatPanel._render_markdown(
            "# 结论\n\n**重点**\n\n- 条目\n\n```python\nprint('ok')\n```\n\n"
            "| A | B |\n| - | - |\n| 1 | 2 |"
        )

        self.assertIn("<h1>结论</h1>", rendered)
        self.assertIn("<strong>重点</strong>", rendered)
        self.assertIn("<ul>", rendered)
        self.assertIn('<code class="language-python">', rendered)
        self.assertIn("<table>", rendered)

    def test_raw_html_is_rendered_as_text(self):
        rendered = ChatPanel._render_markdown(
            '<script>alert("unsafe")</script>\n\n<img src="bad" onerror="alert(1)">'
        )

        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img ", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;img", rendered)

    def test_user_and_assistant_turns_have_distinct_alignment(self):
        user = ChatPanel._render_turn(make_message("user", "请解释 **U-Net**。"))
        assistant = ChatPanel._render_turn(
            make_message("assistant", "它使用编码器和解码器。")
        )

        self.assertIn("class='user-bubble'", user)
        self.assertIn("align='right'", user)
        self.assertTrue(user.index("width='16%'") < user.index("user-bubble"))
        self.assertIn("class='assistant-bubble'", assistant)
        self.assertIn("align='left'", assistant)
        self.assertIn(
            "<tr><td class='assistant-bubble'", assistant
        )
        self.assertIn(
            "</td><td width='8%'></td></tr>", assistant
        )

    def test_selected_passage_is_escaped_inside_user_bubble(self):
        rendered = ChatPanel._render_turn(
            make_message(
                "user",
                "这段是什么意思？",
                metadata={
                    "selected_passage": {
                        "paper_title": "Paper <unsafe>",
                        "page": 3,
                        "text": "Original <script>alert(1)</script> text.",
                    }
                },
            )
        )

        bubble_start = rendered.index("class='user-bubble'")
        passage_start = rendered.index("class='passage'")
        question_start = rendered.index("这段是什么意思？")
        self.assertLess(bubble_start, passage_start)
        self.assertLess(passage_start, question_start)
        self.assertIn("Paper &lt;unsafe&gt;", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_widget_exposes_rendered_markdown_as_readable_text(self):
        panel = ChatPanel()
        try:
            panel.show_messages(
                [
                    make_message("user", "**问题**"),
                    make_message("assistant", "## 回答\n\n- 第一项\n- 第二项"),
                ]
            )
            plain_text = panel.messages.toPlainText()
            self.assertIn("你", plain_text)
            self.assertIn("Academic Agent", plain_text)
            self.assertIn("问题", plain_text)
            self.assertIn("回答", plain_text)
            self.assertNotIn("**", plain_text)
        finally:
            panel.close()


if __name__ == "__main__":
    unittest.main()
