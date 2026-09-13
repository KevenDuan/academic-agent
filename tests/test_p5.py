from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QFrame, QPushButton, QSplitter, QToolBar

from app.config import AppSettings
from app.core.session_store import SessionStore
from app.settings_store import SettingsStore
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog


class NoopRagEngine:
    @staticmethod
    def list_papers():
        return []

    @staticmethod
    def close():
        pass


class P5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_settings_store_roundtrip(self):
        store = SettingsStore(self.root / "settings.json")
        expected = AppSettings(
            provider="custom",
            model="research-model",
            base_url="https://llm.example/v1",
            api_key="secret",
            timeout=95,
            tavily_api_key="tavily-secret",
        )
        store.save(expected)
        self.assertEqual(store.load(), expected)

    def test_invalid_settings_file_falls_back_to_environment(self):
        path = self.root / "settings.json"
        path.write_text("not-json", encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "LLM_MODEL_ID": "environment-model",
                "LLM_BASE_URL": "https://api.openai.com/v1",
                "LLM_API_KEY": "environment-key",
                "LLM_TIMEOUT": "45",
            },
            clear=True,
        ):
            settings = SettingsStore(path).load()
        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.model, "environment-model")
        self.assertEqual(settings.timeout, 45)

    def test_settings_dialog_applies_provider_presets(self):
        dialog = SettingsDialog(
            AppSettings(provider="custom", model="local", base_url="https://local/v1")
        )
        try:
            dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("deepseek"))
            self.assertEqual(dialog.model_input.text(), "deepseek-chat")
            self.assertEqual(dialog.base_url_input.text(), "https://api.deepseek.com")
            dialog.provider_combo.setCurrentIndex(dialog.provider_combo.findData("openai"))
            self.assertEqual(dialog.model_input.text(), "gpt-4o-mini")
            self.assertEqual(dialog.base_url_input.text(), "https://api.openai.com/v1")
        finally:
            dialog.close()

    def test_runtime_settings_rebuild_llm_services(self):
        window = self._window()
        try:
            settings = AppSettings(
                provider="custom",
                model="new-model",
                base_url="https://llm.example/v1",
                api_key="test-key",
                timeout=70,
            )
            window._apply_runtime_settings(settings)
            self.assertEqual(window.translator.model, "new-model")
            self.assertEqual(window.chat_service.model, "new-model")
            self.assertEqual(window.agent_loop.model, "new-model")
            self.assertIs(window.chat_service.client, window.translator.client)
            self.assertIs(window.agent_loop.client, window.translator.client)
            self.assertIn("llm.example/v1", str(window.translator.client.base_url))
            self.assertIs(window.agent_loop.context.rag_engine, window.rag_engine)
        finally:
            window.close()

    def test_main_window_has_icon_toolbar_and_stable_three_columns(self):
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            self.assertIsInstance(window.main_toolbar, QToolBar)
            self.assertFalse(window.main_toolbar.isMovable())
            self.assertFalse(window.settings_action.icon().isNull())
            self.assertIsInstance(window.centralWidget(), QSplitter)
            self.assertEqual(window.workspace_splitter.count(), 3)
            self.assertIs(window.workspace_splitter.widget(0), window.session_sidebar)
            self.assertIs(window.workspace_splitter.widget(2), window.right_tabs)
        finally:
            window.close()

    def test_sidebar_keeps_entity_actions_in_context_menu_only(self):
        window = self._window()
        try:
            self.assertEqual(window.session_sidebar.findChildren(QPushButton), [])
            action_names = {
                action.text() for action in window.session_sidebar._create_context_menu().actions()
            }
            self.assertEqual(action_names, {"新建对话", "重命名", "删除"})
        finally:
            window.close()

    def test_sidebar_toolbar_action_collapses_and_restores_sidebar(self):
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            self.assertTrue(window.session_sidebar.isVisible())
            self.assertTrue(window.sidebar_action.isChecked())

            window.sidebar_action.trigger()
            self.qt_app.processEvents()
            self.assertTrue(window.session_sidebar.isHidden())
            self.assertFalse(window.sidebar_action.isChecked())

            window.sidebar_action.trigger()
            self.qt_app.processEvents()
            self.assertTrue(window.session_sidebar.isVisible())
            self.assertTrue(window.sidebar_action.isChecked())
            self.assertGreater(window.workspace_splitter.sizes()[0], 0)
        finally:
            window.close()

    def test_chat_uses_integrated_composer(self):
        window = self._window()
        try:
            self.assertIsInstance(window.chat_panel.composer, QFrame)
            self.assertIs(window.chat_panel.input.parentWidget(), window.chat_panel.composer)
            self.assertIs(window.chat_panel.send_button.parentWidget(), window.chat_panel.composer)
            self.assertEqual(window.chat_panel.send_button.text(), "")
            self.assertFalse(window.chat_panel.send_button.icon().isNull())
        finally:
            window.close()

    def test_minimum_window_preserves_visible_workspace_panes(self):
        window = self._window()
        try:
            window.resize(1040, 680)
            window.show()
            self.qt_app.processEvents()
            sizes = window.workspace_splitter.sizes()
            self.assertGreaterEqual(window.width(), 1040)
            self.assertEqual(len(sizes), 3)
            self.assertTrue(all(size > 0 for size in sizes))
            self.assertLessEqual(window.document_title.width(), window.workspace_splitter.widget(1).width())
        finally:
            window.close()

    def _window(self) -> MainWindow:
        session_store = SessionStore(self.root / f"sessions-{id(self)}.db")
        settings_store = SettingsStore(self.root / f"settings-{id(self)}.json")
        return MainWindow(
            session_store=session_store,
            rag_engine=NoopRagEngine(),
            settings_store=settings_store,
        )


if __name__ == "__main__":
    unittest.main()
