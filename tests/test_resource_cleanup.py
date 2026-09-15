from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import QCoreApplication, QEvent, QThread
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core.paper_repo import PaperRepository
from app.core.rag_engine import RagEngine
from app.core.session_store import SessionStore
from app.core.translator import Translator
from app.settings_store import SettingsStore
from app.ui.main_window import MainWindow


class FakeEmbedder:
    model_name = "test-embedder"
    dimension = 4

    def __init__(self) -> None:
        self.closed = False

    def encode(self, texts):
        vectors = np.ones((len(texts), self.dimension), dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    def close(self) -> None:
        self.closed = True


class NoopRagEngine:
    @staticmethod
    def search(_query, top_k=5):
        return []

    @staticmethod
    def format_context(_results):
        return ""

    @staticmethod
    def contains_document(_path):
        return False

    @staticmethod
    def list_papers():
        return []

    @staticmethod
    def close():
        pass


class LocalChatService:
    @staticmethod
    def answer(_messages, _paper_context):
        return "ok"


class SlowChatService:
    @staticmethod
    def answer(_messages, _paper_context):
        time.sleep(0.1)
        return "ok"


class ClosableClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ResourceCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _sqlite_storage(path: Path) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (path, Path(str(path) + "-wal"))
            if candidate.exists()
        )

    def test_deleting_session_reclaims_database_pages(self):
        path = self.root / "sessions.db"
        store = SessionStore(path)
        try:
            session = store.create_session()
            for _ in range(80):
                store.add_message(session.session_id, "user", "x" * 16000)
            size_before = self._sqlite_storage(path)

            store.delete_session(session.session_id)

            free_pages = store._connection.execute("PRAGMA freelist_count").fetchone()[0]
            self.assertEqual(free_pages, 0)
            self.assertLess(self._sqlite_storage(path), size_before)
        finally:
            store.close()

    def test_deleting_paper_reclaims_embedding_pages(self):
        path = self.root / "papers.db"
        repository = PaperRepository(path)
        try:
            blocks = [
                (0, index, (0.0, 0.0, 1.0, 1.0), "text", f"block {index}")
                for index in range(300)
            ]
            embeddings = np.ones((len(blocks), 1024), dtype=np.float32)
            repository.replace_paper(
                "paper-id",
                "paper.pdf",
                "Paper",
                "file-hash",
                "test-model",
                blocks,
                embeddings,
            )
            size_before = self._sqlite_storage(path)

            repository.delete_paper("paper-id")

            free_pages = repository._connection.execute("PRAGMA freelist_count").fetchone()[0]
            self.assertEqual(free_pages, 0)
            self.assertLess(self._sqlite_storage(path), size_before)
        finally:
            repository.close()

    def test_cached_search_does_not_reload_all_embedding_blobs(self):
        repository = PaperRepository(self.root / "papers.db")
        embedder = FakeEmbedder()
        repository.replace_paper(
            "paper-id",
            "paper.pdf",
            "Paper",
            "file-hash",
            embedder.model_name,
            [(0, 0, (0.0, 0.0, 1.0, 1.0), "text", "evidence")],
            embedder.encode(["evidence"]),
        )
        engine = RagEngine(repository, embedder, self.root / "papers.faiss")
        engine._rebuild_index()

        repository.load_embeddings = lambda: self.fail("loaded all embedding blobs")
        results = engine.search("question")

        self.assertEqual(len(results), 1)
        engine.close()
        self.assertTrue(embedder.closed)

    def test_translator_closes_http_client(self):
        client = ClosableClient()
        translator = Translator(client=client)
        translator.close()
        self.assertTrue(client.closed)
        self.assertIsNone(translator.client)

    def test_finished_chat_threads_are_deleted(self):
        window = MainWindow(
            session_store=SessionStore(self.root / "sessions.db"),
            rag_engine=NoopRagEngine(),
            settings_store=SettingsStore(self.root / "settings.json"),
        )
        window.chat_service = LocalChatService()
        try:
            for index in range(5):
                window.send_chat_message(f"question {index}")
                deadline = time.monotonic() + 2
                while window._chat_thread is not None and time.monotonic() < deadline:
                    self.qt_app.processEvents()
                    QTest.qWait(5)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.qt_app.processEvents()
            self.assertEqual(window.findChildren(QThread), [])
        finally:
            window.close()

    def test_close_waits_for_active_worker_then_releases_resources(self):
        window = MainWindow(
            session_store=SessionStore(self.root / "sessions.db"),
            rag_engine=NoopRagEngine(),
            settings_store=SettingsStore(self.root / "settings.json"),
        )
        window.chat_service = SlowChatService()
        window.show()
        window.send_chat_message("question")

        window.close()

        self.assertTrue(window._close_requested)
        self.assertFalse(window._resources_closed)
        deadline = time.monotonic() + 2
        while not window._resources_closed and time.monotonic() < deadline:
            self.qt_app.processEvents()
            QTest.qWait(5)
        self.assertTrue(window._resources_closed)
        self.assertFalse(window.isVisible())


if __name__ == "__main__":
    unittest.main()
