from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QSplitter

from app.core.chat_service import ChatService
from app.core.session_store import SessionStore
from app.ui.main_window import MainWindow


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="论文提出了 U-Net。"))]
        )


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class LocalChatService:
    def answer(self, messages, paper_context):
        assert messages[-1].content == "这篇论文主要讲什么？"
        assert "U-Net" in paper_context
        return "论文提出了 U-Net，用于生物医学图像分割。"


class P2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sessions.db"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_session_store_survives_reopen(self):
        store = SessionStore(self.database_path)
        session = store.create_session("U-Net 讨论", "paper.pdf")
        store.add_message(session.session_id, "user", "主要贡献是什么？")
        store.add_message(session.session_id, "assistant", "提出了 U-Net。")
        store.close()

        reopened = SessionStore(self.database_path)
        try:
            restored = reopened.get_session(session.session_id)
            messages = reopened.get_messages(session.session_id)
            self.assertEqual(restored.title, "U-Net 讨论")
            self.assertEqual(restored.paper_id, "paper.pdf")
            self.assertEqual([message.role for message in messages], ["user", "assistant"])
            self.assertEqual(messages[-1].content, "提出了 U-Net。")
        finally:
            reopened.close()

    def test_delete_session_cascades_messages(self):
        store = SessionStore(self.database_path)
        try:
            session = store.create_session()
            store.add_message(session.session_id, "user", "hello")
            store.delete_session(session.session_id)
            self.assertEqual(store.list_sessions(), [])
            self.assertEqual(store.get_messages(session.session_id), [])
        finally:
            store.close()

    def test_chat_service_includes_paper_and_history(self):
        store = SessionStore(self.database_path)
        try:
            session = store.create_session()
            store.add_message(session.session_id, "user", "这篇论文主要讲什么？")
            client = FakeClient()
            answer = ChatService(client, "test-model").answer(
                store.get_messages(session.session_id),
                "U-Net is a convolutional network for biomedical image segmentation.",
            )
            request = client.completions.kwargs
            self.assertEqual(answer, "论文提出了 U-Net。")
            self.assertEqual(request["model"], "test-model")
            self.assertIn("U-Net", request["messages"][0]["content"])
            self.assertEqual(request["messages"][-1]["role"], "user")
        finally:
            store.close()

    def test_main_window_persists_and_restores_conversation(self):
        store = SessionStore(self.database_path)
        window = MainWindow(session_store=store)
        window.load_pdf(PROJECT_ROOT / "data" / "Unet.pdf")
        window.chat_service = LocalChatService()
        window.send_chat_message("这篇论文主要讲什么？")
        for _ in range(200):
            self.qt_app.processEvents()
            if window.current_session_id:
                messages = store.get_messages(window.current_session_id)
                if len(messages) == 2:
                    break
            QTest.qWait(10)
        session_id = window.current_session_id
        self.assertIsNotNone(session_id)
        self.assertEqual(len(store.get_messages(session_id)), 2)
        window.close()

        reopened_store = SessionStore(self.database_path)
        reopened_window = MainWindow(session_store=reopened_store)
        try:
            self.qt_app.processEvents()
            self.assertEqual(reopened_window.current_session_id, session_id)
            self.assertIsNotNone(reopened_window.document)
            self.assertEqual(reopened_window.document.path.name, "Unet.pdf")
            self.assertIn("生物医学图像分割", reopened_window.chat_panel.messages.toPlainText())
        finally:
            reopened_window.close()

    def test_main_window_uses_three_column_layout(self):
        store = SessionStore(self.database_path)
        window = MainWindow(session_store=store)
        try:
            splitter = window.centralWidget()
            self.assertIsInstance(splitter, QSplitter)
            self.assertEqual(splitter.count(), 3)
            self.assertIs(splitter.widget(0), window.session_sidebar)
            self.assertIs(splitter.widget(1).layout().itemAt(1).widget(), window.pdf_view)
            self.assertFalse(hasattr(window.chat_panel, "session_list"))
            self.assertFalse(hasattr(window.session_sidebar, "new_button"))
        finally:
            window.close()

    def test_session_sidebar_exposes_actions_in_context_menu(self):
        store = SessionStore(self.database_path)
        window = MainWindow(session_store=store)
        try:
            menu = window.session_sidebar._create_context_menu()
            actions = {action.text(): action for action in menu.actions()}
            self.assertEqual(set(actions), {"新建对话", "重命名", "删除"})
            self.assertTrue(actions["新建对话"].isEnabled())
            self.assertFalse(actions["重命名"].isEnabled())
            self.assertFalse(actions["删除"].isEnabled())

            window.new_session()
            menu = window.session_sidebar._create_context_menu()
            actions = {action.text(): action for action in menu.actions()}
            self.assertTrue(actions["重命名"].isEnabled())
            self.assertTrue(actions["删除"].isEnabled())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
