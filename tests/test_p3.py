from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core.paper_repo import PaperRepository
from app.core.pdf_parser import Block, PageData
from app.core.rag_engine import RagEngine
from app.core.session_store import SessionStore
from app.ui.main_window import MainWindow


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeEmbedder:
    model_name = "test-embedding"
    dimension = 4

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "segmentation" in lowered or "医学图像" in text:
                vector = [1.0, 0.0, 0.0, 0.0]
            elif "attention" in lowered or "注意力" in text:
                vector = [0.0, 1.0, 0.0, 0.0]
            else:
                vector = [0.0, 0.0, 1.0, 0.0]
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)


class CapturingChatService:
    def __init__(self):
        self.context = None

    def answer(self, messages, paper_context):
        self.context = paper_context
        return "跨论文回答 [来源1]"


class P3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database_path = self.root / "papers.db"
        self.index_path = self.root / "papers.faiss"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _engine(self, embedder=None):
        return RagEngine(
            repository=PaperRepository(self.database_path),
            embedder=embedder or FakeEmbedder(),
            index_path=self.index_path,
        )

    def _document(self, filename: str, title: str, body: str):
        path = self.root / filename
        path.write_bytes((title + body).encode("utf-8"))
        return SimpleNamespace(
            path=path.resolve(),
            pages=[
                PageData(
                    number=0,
                    width=600,
                    height=800,
                    blocks=[
                        Block(
                            page=0,
                            bbox=(20, 20, 580, 60),
                            text=title,
                            kind="title",
                            order=0,
                        ),
                        Block(
                            page=0,
                            bbox=(20, 80, 580, 180),
                            text=body,
                            kind="text",
                            order=1,
                        ),
                    ],
                )
            ],
        )

    def test_cross_paper_search_returns_cited_block(self):
        engine = self._engine()
        try:
            engine.add_document(
                self._document(
                    "unet.pdf",
                    "U-Net for Biomedical Images",
                    "A convolutional network for biomedical image segmentation.",
                )
            )
            engine.add_document(
                self._document(
                    "transformer.pdf",
                    "Attention Is All You Need",
                    "The Transformer architecture relies on self-attention mechanisms.",
                )
            )
            results = engine.search("医学图像分割方法", top_k=2)
            self.assertEqual(results[0].block.paper_title, "U-Net for Biomedical Images")
            self.assertEqual(results[0].block.page, 0)
            context = engine.format_context(results)
            self.assertIn("[来源1：U-Net for Biomedical Images，第 1 页]", context)
            self.assertIn("image segmentation", context)
        finally:
            engine.close()

    def test_duplicate_paper_is_not_embedded_twice(self):
        embedder = FakeEmbedder()
        engine = self._engine(embedder)
        try:
            document = self._document(
                "paper.pdf", "Paper Title Here", "A biomedical image segmentation method."
            )
            first, first_created = engine.add_document(document)
            second, second_created = engine.add_document(document)
            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertEqual(first.paper_id, second.paper_id)
            self.assertEqual(embedder.calls, 1)
            self.assertEqual(len(engine.list_papers()), 1)
        finally:
            engine.close()

    def test_persisted_index_reopens_and_corruption_rebuilds(self):
        engine = self._engine()
        document = self._document(
            "paper.pdf", "Persistent Paper", "A biomedical image segmentation method."
        )
        paper, _created = engine.add_document(document)
        block_count = paper.block_count
        engine.close()
        self.assertTrue(self.index_path.exists())

        self.index_path.write_bytes(b"not a faiss index")
        reopened = self._engine()
        try:
            results = reopened.search("医学图像分割")
            self.assertTrue(results)
            self.assertEqual(results[0].block.paper_id, paper.paper_id)
            self.assertEqual(reopened._index.ntotal, block_count)
        finally:
            reopened.close()

    def test_removing_paper_removes_vectors(self):
        engine = self._engine()
        try:
            paper, _created = engine.add_document(
                self._document(
                    "paper.pdf", "Disposable Paper", "A biomedical segmentation method."
                )
            )
            engine.remove_paper(paper.paper_id)
            self.assertEqual(engine.list_papers(), [])
            self.assertEqual(engine.search("医学图像"), [])
            self.assertEqual(engine._index.ntotal, 0)
        finally:
            engine.close()

    def test_main_window_indexes_current_pdf_in_background(self):
        engine = self._engine()
        store = SessionStore(self.root / "sessions.db")
        window = MainWindow(session_store=store, rag_engine=engine)
        window.load_pdf(PROJECT_ROOT / "data" / "Unet.pdf")
        window.add_current_to_library()
        for _ in range(300):
            self.qt_app.processEvents()
            if engine.list_papers():
                break
            QTest.qWait(10)
        for _ in range(100):
            self.qt_app.processEvents()
            if window._index_thread is None:
                break
            QTest.qWait(10)
        try:
            papers = engine.list_papers()
            self.assertEqual(len(papers), 1)
            self.assertGreater(papers[0].block_count, 0)
            self.assertTrue(window.add_to_library_action.isEnabled())
            self.assertIn("已加入论文库", window.statusBar().currentMessage())
        finally:
            window.close()

    def test_chat_sends_at_most_five_retrieved_sources(self):
        engine = self._engine()
        for number in range(6):
            engine.add_document(
                self._document(
                    f"paper-{number}.pdf",
                    f"Segmentation Paper {number}",
                    f"Biomedical image segmentation study number {number}.",
                )
            )
        store = SessionStore(self.root / "sessions.db")
        window = MainWindow(session_store=store, rag_engine=engine)
        chat_service = CapturingChatService()
        window.chat_service = chat_service
        window.send_chat_message("医学图像分割有哪些方法？")
        for _ in range(300):
            self.qt_app.processEvents()
            if window.current_session_id:
                messages = store.get_messages(window.current_session_id)
                if len(messages) == 2:
                    break
            QTest.qWait(10)
        try:
            self.assertIsNotNone(chat_service.context)
            self.assertEqual(chat_service.context.count("[来源"), 5)
            self.assertIn("[来源5：", chat_service.context)
            self.assertNotIn("[来源6：", chat_service.context)
            messages = store.get_messages(window.current_session_id)
            self.assertEqual(messages[-1].content, "跨论文回答 [来源1]")
        finally:
            window.close()

    def test_chat_caps_combined_retrieval_and_current_paper_context(self):
        engine = self._engine()
        engine.add_document(
            self._document(
                "library.pdf",
                "Library Segmentation Paper",
                "Biomedical image segmentation evidence from the paper library.",
            )
        )
        current_document = self._document(
            "current.pdf",
            "Current Unindexed Paper",
            "Current paper evidence. " * 3000,
        )
        store = SessionStore(self.root / "sessions.db")
        window = MainWindow(session_store=store, rag_engine=engine)
        window.document = current_document
        chat_service = CapturingChatService()
        window.chat_service = chat_service
        window.send_chat_message("医学图像分割有哪些方法？")
        for _ in range(300):
            self.qt_app.processEvents()
            if chat_service.context is not None:
                break
            QTest.qWait(10)
        try:
            self.assertIsNotNone(chat_service.context)
            self.assertLessEqual(len(chat_service.context), 32000)
            self.assertTrue(chat_service.context.startswith("[来源1："))
        finally:
            window.document = None
            window.close()


if __name__ == "__main__":
    unittest.main()
