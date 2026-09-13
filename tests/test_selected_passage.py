from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core.chat_service import ChatService
from app.core.session_store import SessionStore
from app.ui.main_window import MainWindow


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class NoopRagEngine:
    def __init__(self):
        self.search_calls = 0

    def search(self, _query, top_k=5):
        self.search_calls += 1
        return []

    @staticmethod
    def format_context(_results):
        return ""

    @staticmethod
    def contains_document(_path):
        return False

    def close(self):
        pass


class CapturingChatService:
    def __init__(self):
        self.messages = None
        self.context = None

    def answer(self, messages, paper_context):
        self.messages = messages
        self.context = paper_context
        return "该段介绍了 U-Net 的网络结构。[选中段落]"


class FakeCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="段落回答"))]
        )


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class SelectedPassageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_old_session_database_is_migrated_for_message_metadata(self):
        database_path = self.root / "legacy.db"
        connection = sqlite3.connect(database_path)
        connection.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                paper_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls_json TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.close()

        store = SessionStore(database_path)
        try:
            session = store.create_session()
            store.add_message(
                session.session_id,
                "user",
                "解释这一段",
                metadata={"selected_passage": {"text": "Original passage."}},
            )
            message = store.get_messages(session.session_id)[0]
            self.assertEqual(
                message.metadata["selected_passage"]["text"],
                "Original passage.",
            )
        finally:
            store.close()

    def test_chat_service_sends_selected_original_and_translation(self):
        store = SessionStore(self.root / "sessions.db")
        try:
            session = store.create_session()
            store.add_message(
                session.session_id,
                "user",
                "这段主要表达什么？",
                metadata={
                    "selected_passage": {
                        "paper_title": "U-Net",
                        "page": 3,
                        "text": "The contracting path follows the typical architecture.",
                        "translation": "收缩路径遵循典型架构。",
                    }
                },
            )
            client = FakeClient()
            ChatService(client, "test-model").answer(
                store.get_messages(session.session_id), ""
            )
            sent = client.completions.kwargs["messages"][-1]["content"]
            self.assertIn("[选中段落]", sent)
            self.assertIn("The contracting path", sent)
            self.assertIn("收缩路径遵循典型架构", sent)
            self.assertIn("这段主要表达什么", sent)
        finally:
            store.close()

    def test_long_selected_passage_does_not_expand_chat_column(self):
        store = SessionStore(self.root / "sessions.db")
        window = MainWindow(session_store=store, rag_engine=NoopRagEngine())
        window.resize(1200, 800)
        window.centralWidget().widget(2).setCurrentIndex(1)
        window.show()
        self.qt_app.processEvents()
        splitter = window.centralWidget()
        splitter.setSizes([200, 650, 350])
        self.qt_app.processEvents()
        before = splitter.sizes()[2]

        window.chat_panel.set_selected_passage(
            {
                "paper_title": "Very Long Paper Title " * 20,
                "page": 1,
                "text": "A_very_long_unbroken_passage_" * 500,
            }
        )
        self.qt_app.processEvents()
        after = splitter.sizes()[2]
        try:
            self.assertLessEqual(abs(after - before), 2)
            self.assertLessEqual(
                window.chat_panel.passage_attachment.width(),
                splitter.sizes()[2],
            )
            self.assertLessEqual(
                window.chat_panel.passage_preview.width(),
                window.chat_panel.passage_attachment.width(),
            )
        finally:
            window.close()

    def test_selected_pdf_block_is_persisted_and_replaces_full_pdf_fallback(self):
        database_path = self.root / "sessions.db"
        store = SessionStore(database_path)
        rag_engine = NoopRagEngine()
        window = MainWindow(session_store=store, rag_engine=rag_engine)
        window.load_pdf(PROJECT_ROOT / "data" / "Unet.pdf")
        block_index = next(
            index
            for index, block in enumerate(window.document.pages[0].blocks)
            if block.kind != "formula" and len(block.text.strip()) >= 20
        )
        block = window.document.pages[0].blocks[block_index]
        block.translation = "用于验证附件持久化的译文。"
        window.select_block(block_index)
        self.assertFalse(window.chat_panel.passage_attachment.isHidden())
        window.chat_panel.clear_passage_button.click()
        self.assertTrue(window.chat_panel.passage_attachment.isHidden())
        self.assertIsNone(window._selected_passage)
        window.select_block(block_index)

        service = CapturingChatService()
        window.chat_service = service
        window.send_chat_message("请解释选中的这一段。")
        for _ in range(300):
            self.qt_app.processEvents()
            if window.current_session_id:
                messages = store.get_messages(window.current_session_id)
                if len(messages) == 2:
                    break
            QTest.qWait(10)
        for _ in range(100):
            self.qt_app.processEvents()
            if window._chat_thread is None:
                break
            QTest.qWait(10)
        session_id = window.current_session_id
        try:
            messages = store.get_messages(session_id)
            passage = messages[0].metadata["selected_passage"]
            self.assertEqual(passage["text"], block.text.strip())
            self.assertEqual(passage["translation"], block.translation)
            self.assertEqual(passage["page"], 1)
            self.assertEqual(service.context, "")
            self.assertEqual(rag_engine.search_calls, 0)
            self.assertTrue(window.chat_panel.passage_attachment.isHidden())
            self.assertIn("选中段落", window.chat_panel.messages.toPlainText())
        finally:
            window.close()

        reopened = SessionStore(database_path)
        try:
            restored = reopened.get_messages(session_id)[0]
            self.assertEqual(
                restored.metadata["selected_passage"]["text"],
                block.text.strip(),
            )
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
