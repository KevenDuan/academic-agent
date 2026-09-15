from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QPixmap, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractItemView, QApplication

from app.core.pdf_parser import Block, PDFParser
from app.core.translator import Translator
from app.ui.main_window import MainWindow
from app.ui.pdf_viewer import PDFPageView, PageViewMode
from app.ui.translation_panel import TranslationPanel


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="这是译文"))]
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class LocalTranslator:
    client = True

    def translate_text(self, text):
        return "本地测试译文"


class P0P1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_pdf_parser_extracts_blocks_and_coordinates(self):
        document = PDFParser().parse(PROJECT_ROOT / "data" / "Unet.pdf")
        try:
            self.assertGreater(document.page_count, 0)
            self.assertTrue(document.pages[0].blocks)
            block = document.pages[0].blocks[0]
            self.assertEqual(block.page, 0)
            self.assertEqual(len(block.bbox), 4)
            self.assertTrue(block.text.strip())
        finally:
            document.close()

    def test_short_prose_with_math_symbol_is_not_formula(self):
        block = Block(
            page=0,
            bbox=(0, 0, 1, 1),
            text="We set α = 0.01 for all experiments.",
            kind=PDFParser()._classify(
                "We set α = 0.01 for all experiments.", {"CMMI10", "CMR10"}
            ),
        )
        self.assertNotEqual(block.kind, "formula")

    def test_real_display_formula_is_formula(self):
        text = "E[∇L(w)] ≤ L(w*) + ε"
        kind = PDFParser()._classify(text, {"CMMI10"})
        self.assertEqual(kind, "formula")

    def test_long_prose_with_math_symbol_is_not_formula(self):
        text = "where wc : Ω→R is the weight map for the convolutional layer"
        kind = PDFParser()._classify(text, {"CMMI10", "CMR10"})
        self.assertNotEqual(kind, "formula")

    def test_short_prose_sentence_is_text_not_title(self):
        text = "We set α = 0.01 for all experiments."
        kind = PDFParser()._classify(text, {"CMMI10", "CMR10"})
        self.assertEqual(kind, "text")

    def test_translator_uses_openai_compatible_chat_api(self):
        client = FakeClient()
        translated = Translator(client=client, model="test-model").translate_text("Hello")
        self.assertEqual(translated, "这是译文")
        self.assertEqual(client.chat.completions.kwargs["model"], "test-model")

    def test_pdf_view_emits_clicked_block(self):
        view = PDFPageView()
        view.resize(800, 800)
        view.show()
        self.qt_app.processEvents()
        view.set_page(
            QPixmap(100, 100),
            100,
            100,
            [Block(page=0, bbox=(10, 10, 40, 30), text="block")],
        )
        self.qt_app.processEvents()
        click_x = round(20 * view.canvas._scale)
        click_y = round(20 * view.canvas._scale)
        selected = []
        view.blockClicked.connect(selected.append)
        QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=QPoint(click_x, click_y))
        self.assertEqual(selected, [0])
        self.assertEqual(view.canvas._selected, 0)
        view.close()

    def test_pdf_view_zoom_creates_scrollbars(self):
        view = PDFPageView()
        view.resize(800, 800)
        view.show()
        self.qt_app.processEvents()
        view.set_page(QPixmap(100, 100), 100, 100, [])
        self.qt_app.processEvents()
        self.assertEqual(view.zoom_factor, 1.0)
        view.zoom_in()
        self.assertGreater(view.zoom_factor, 1.0)
        self.qt_app.processEvents()
        self.assertGreater(view.horizontalScrollBar().maximum(), 0)
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        self.assertGreater(view.verticalScrollBar().value(), 0)
        view.fit_page()
        self.assertEqual(view.zoom_factor, 1.0)
        view.close()

    def test_pdf_view_supports_fit_width_page_and_actual_size(self):
        view = PDFPageView()
        view.resize(800, 800)
        view.show()
        self.qt_app.processEvents()
        view.set_page(QPixmap(612, 792), 612, 792, [])
        self.qt_app.processEvents()

        self.assertEqual(view.view_mode, PageViewMode.FIT_WIDTH)
        self.assertLessEqual(view.canvas.width(), view.viewport().width())
        self.assertGreater(view.verticalScrollBar().maximum(), 0)

        view.fit_page()
        self.qt_app.processEvents()
        self.assertEqual(view.view_mode, PageViewMode.FIT_PAGE)
        self.assertLessEqual(view.canvas.width(), view.viewport().width())
        self.assertLessEqual(view.canvas.height(), view.viewport().height())

        view.actual_size()
        self.qt_app.processEvents()
        self.assertEqual(view.view_mode, PageViewMode.ACTUAL_SIZE)
        self.assertAlmostEqual(
            view.current_scale,
            view.logicalDpiX() / view.PDF_DPI,
            places=3,
        )
        view.close()

    def test_dynamic_render_dpi_tracks_zoom_and_honors_pixel_limit(self):
        view = PDFPageView()
        view.resize(800, 800)
        view.show()
        self.qt_app.processEvents()
        view.set_page(QPixmap(612, 792), 612, 792, [])
        initial_dpi = view.render_dpi(device_pixel_ratio=1.0)

        for _ in range(20):
            view.zoom_in()
        zoomed_dpi = view.render_dpi(device_pixel_ratio=2.0)
        rendered_pixels = (
            612 * zoomed_dpi / view.PDF_DPI
            * 792 * zoomed_dpi / view.PDF_DPI
        )

        self.assertGreater(zoomed_dpi, initial_dpi)
        self.assertLessEqual(zoomed_dpi, view.MAX_RENDER_DPI)
        self.assertLessEqual(rendered_pixels, view.MAX_RENDER_PIXELS)
        view.close()

    def test_pdf_view_scrollbars_preserve_click_selection(self):
        view = PDFPageView()
        view.resize(800, 800)
        view.show()
        self.qt_app.processEvents()
        view.set_page(
            QPixmap(100, 100),
            100,
            100,
            [Block(page=0, bbox=(10, 10, 40, 30), text="block")],
        )
        self.qt_app.processEvents()
        view.zoom_in()
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        selected = []
        view.blockClicked.connect(selected.append)
        view.horizontalScrollBar().setValue(0)
        view.verticalScrollBar().setValue(0)
        click_x = round(20 * view.canvas._scale)
        click_y = round(20 * view.canvas._scale)
        QTest.mouseClick(view.canvas, Qt.MouseButton.LeftButton, pos=QPoint(click_x, click_y))
        self.assertEqual(selected, [0])
        view.close()

    def test_clicking_block_writes_translation_back(self):
        window = MainWindow()
        window.show()
        self.qt_app.processEvents()
        window.load_pdf(str(PROJECT_ROOT / "data" / "Unet.pdf"))
        window.translator = LocalTranslator()
        block_index = next(
            i for i, block in enumerate(window.document.pages[0].blocks) if block.kind != "formula"
        )
        window.select_block(block_index)
        for _ in range(100):
            self.qt_app.processEvents()
            if window.document.pages[0].blocks[block_index].translation:
                break
            QTest.qWait(10)
        block = window.document.pages[0].blocks[block_index]
        self.assertEqual(block.translation, "本地测试译文")
        self.assertIn("本地测试译文", window.translation_panel.list_widget.item(block_index).text())
        window.close()

    def test_long_translation_item_is_not_elided(self):
        panel = TranslationPanel()
        panel.resize(520, 640)
        panel.set_blocks([Block(page=0, bbox=(0, 0, 1, 1), text="long text " * 160)])
        panel.show()
        self.qt_app.processEvents()
        self.assertEqual(panel.list_widget.textElideMode(), Qt.TextElideMode.ElideNone)
        self.assertGreater(panel.list_widget.visualItemRect(panel.list_widget.item(0)).height(), 200)
        panel.close()

    def test_translation_panel_normalizes_pdf_line_breaks(self):
        panel = TranslationPanel()
        panel.set_blocks([Block(page=0, bbox=(0, 0, 1, 1), text="first line\nsecond line")])
        self.assertIn("first line second line", panel.list_widget.item(0).text())
        self.assertNotIn("first line\nsecond line", panel.list_widget.item(0).text())
        panel.close()

    def test_translation_panel_scrolls_by_pixel_with_mouse_wheel_easing(self):
        panel = TranslationPanel()
        panel.resize(440, 420)
        panel.set_blocks(
            [
                Block(page=0, bbox=(0, 0, 1, 1), text=f"paragraph {index} " * 25)
                for index in range(10)
            ]
        )
        panel.show()
        self.qt_app.processEvents()
        scrollbar = panel.list_widget.verticalScrollBar()
        self.assertEqual(
            panel.list_widget.verticalScrollMode(),
            QAbstractItemView.ScrollMode.ScrollPerPixel,
        )
        self.assertGreater(scrollbar.maximum(), 0)
        event = QWheelEvent(
            QPointF(20, 20),
            QPointF(panel.list_widget.mapToGlobal(QPoint(20, 20))),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        QApplication.sendEvent(panel.list_widget.viewport(), event)
        QTest.qWait(panel.list_widget.ANIMATION_DURATION_MS + 30)

        self.assertEqual(scrollbar.value(), panel.list_widget.WHEEL_DISTANCE)
        panel.close()

    def test_translation_scroll_animation_accumulates_and_stops_for_selection(self):
        panel = TranslationPanel()
        panel.resize(440, 420)
        panel.set_blocks(
            [
                Block(page=0, bbox=(0, 0, 1, 1), text=f"paragraph {index} " * 25)
                for index in range(10)
            ]
        )
        panel.show()
        self.qt_app.processEvents()

        for _ in range(2):
            event = QWheelEvent(
                QPointF(20, 20),
                QPointF(panel.list_widget.mapToGlobal(QPoint(20, 20))),
                QPoint(),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )
            QApplication.sendEvent(panel.list_widget.viewport(), event)
        self.assertEqual(
            panel.list_widget._scroll_target,
            panel.list_widget.WHEEL_DISTANCE * 2,
        )

        panel.select_block(0)

        self.assertEqual(
            panel.list_widget._scroll_animation.state(),
            panel.list_widget._scroll_animation.State.Stopped,
        )
        panel.close()


if __name__ == "__main__":
    unittest.main()
