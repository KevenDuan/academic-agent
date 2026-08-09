from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QImage, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.pdf_parser import PDFParser, ParsedDocument
from app.core.translator import Translator
from app.ui.pdf_viewer import PDFPageView
from app.ui.translation_panel import TranslationPanel


class TranslationWorker(QObject):
    finished = pyqtSignal(int, int, int, str)
    failed = pyqtSignal(int, int, int, str)

    def __init__(
        self,
        translator: Translator,
        generation: int,
        page_number: int,
        index: int,
        text: str,
    ) -> None:
        super().__init__()
        self.translator = translator
        self.generation = generation
        self.page_number = page_number
        self.index = index
        self.text = text

    def run(self) -> None:
        try:
            self.finished.emit(
                self.generation,
                self.page_number,
                self.index,
                self.translator.translate_text(self.text),
            )
        except Exception as exc:  # surfaced in the status bar, never crashes the GUI
            self.failed.emit(self.generation, self.page_number, self.index, str(exc))


class MainWindow(QMainWindow):
    def __init__(self, initial_pdf: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("AcademicAgent")
        self.resize(1440, 900)
        self.parser = PDFParser()
        self.document: ParsedDocument | None = None
        self._document_generation = 0
        self.current_page = 0
        self.translator = Translator()
        self._translation_threads: dict[tuple[int, int, int], QThread] = {}
        self._translation_workers: dict[tuple[int, int, int], TranslationWorker] = {}
        self._inflight: set[tuple[int, int, int]] = set()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._rerender_current_page)

        self.pdf_view = PDFPageView()
        self.translation_panel = TranslationPanel()
        self.page_label = QLabel("第 0 / 0 页")
        self.previous_button = QPushButton("上一页")
        self.next_button = QPushButton("下一页")
        self.zoom_out_button = QPushButton("−")
        self.zoom_reset_button = QPushButton("100%")
        self.zoom_in_button = QPushButton("+")
        self.fit_button = QPushButton("适应")
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setFixedWidth(72)
        for button in (
            self.zoom_out_button,
            self.zoom_reset_button,
            self.zoom_in_button,
            self.fit_button,
        ):
            button.setFixedHeight(28)
        self.zoom_out_button.setFixedWidth(34)
        self.zoom_reset_button.setFixedWidth(58)
        self.zoom_in_button.setFixedWidth(34)
        self.fit_button.setFixedWidth(52)
        self.zoom_out_button.setToolTip("缩小")
        self.zoom_reset_button.setToolTip("重置缩放")
        self.zoom_in_button.setToolTip("放大")
        self.fit_button.setToolTip("适应页面")

        self._build_ui()
        self._connect_signals()
        if initial_pdf:
            QTimer.singleShot(0, lambda: self.load_pdf(initial_pdf))

    def _build_ui(self) -> None:
        open_action = QAction("打开 PDF", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_pdf)
        self.menuBar().addMenu("文件").addAction(open_action)

        page_controls = QHBoxLayout()
        page_controls.setContentsMargins(0, 0, 0, 0)
        page_controls.addWidget(self.previous_button)
        page_controls.addWidget(self.next_button)
        page_controls.addSpacing(12)
        page_controls.addWidget(self.zoom_out_button)
        page_controls.addWidget(self.zoom_reset_button)
        page_controls.addWidget(self.zoom_in_button)
        page_controls.addWidget(self.fit_button)
        page_controls.addStretch()
        page_controls.addWidget(self.page_label)
        page_controls.addWidget(self.page_spin)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.addLayout(page_controls)
        left_layout.addWidget(self.pdf_view, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.translation_panel)
        splitter.setSizes([900, 500])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("请选择一个 PDF 文件")
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #202328; color: #e6e9ef; }
            QListWidget, QSpinBox { background: #17191d; border: 1px solid #343a46; }
            QListWidget::item { padding: 0px; border-bottom: 1px solid #2d323c; }
            QListWidget::item:selected { background: #394455; }
            QPushButton { background: #303642; border: 1px solid #454e5e; padding: 6px 12px; }
            QPushButton:hover { background: #3d4758; }
            """
        )

    def _connect_signals(self) -> None:
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.zoom_out_button.clicked.connect(self.pdf_view.zoom_out)
        self.zoom_reset_button.clicked.connect(self.pdf_view.fit_page)
        self.zoom_in_button.clicked.connect(self.pdf_view.zoom_in)
        self.fit_button.clicked.connect(self.pdf_view.fit_page)
        self.pdf_view.zoomPercentChanged.connect(
            lambda value: self.zoom_reset_button.setText(f"{value}%")
        )
        self.pdf_view.renderRequested.connect(self._schedule_rerender)
        self.page_spin.valueChanged.connect(lambda value: self.show_page(value - 1))
        self.pdf_view.blockClicked.connect(self.select_block)
        self.translation_panel.blockSelected.connect(self.select_block)

    def open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开 PDF", "", "PDF 文件 (*.pdf)")
        if path:
            self.load_pdf(path)

    def load_pdf(self, path: str | Path) -> None:
        try:
            parsed = self.parser.parse(path)
        except Exception as exc:
            QMessageBox.critical(self, "无法打开 PDF", str(exc))
            return
        if self.document:
            self.document.close()
        self._document_generation += 1
        self.document = parsed
        self.current_page = 0
        self.page_spin.setMaximum(max(1, parsed.page_count))
        self.translation_panel.set_blocks(parsed.pages[0].blocks if parsed.pages else [])
        self.show_page(0)
        self.statusBar().showMessage(f"已打开：{parsed.path.name}")

    def show_page(self, page_number: int) -> None:
        if not self.document or not self.document.pages:
            return
        page_number = max(0, min(page_number, self.document.page_count - 1))
        self.current_page = page_number
        page = self.document.pages[page_number]
        pixmap = self.document.render_page(page_number, dpi=200)
        self.pdf_view.set_page(
            self._to_qpixmap(pixmap), page.width, page.height, page.blocks
        )
        self.translation_panel.set_blocks(page.blocks)
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(page_number + 1)
        self.page_spin.blockSignals(False)
        self.page_label.setText(f"第 {page_number + 1} / {self.document.page_count} 页")

    @staticmethod
    def _to_qpixmap(pixmap) -> QPixmap:
        image = QImage(
            pixmap.samples,
            pixmap.width,
            pixmap.height,
            pixmap.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(image)

    def _schedule_rerender(self) -> None:
        if self.document:
            self._render_timer.start()

    def _rerender_current_page(self) -> None:
        if not self.document or not self.document.pages:
            return
        dpi = max(200, min(600, round(200 * self.pdf_view.zoom_factor)))
        pixmap = self.document.render_page(self.current_page, dpi=dpi)
        self.pdf_view.set_image(self._to_qpixmap(pixmap))

    def previous_page(self) -> None:
        self.show_page(self.current_page - 1)

    def next_page(self) -> None:
        self.show_page(self.current_page + 1)

    def select_block(self, index: int) -> None:
        if not self.document or not self.document.pages:
            return
        blocks = self.document.pages[self.current_page].blocks
        if not 0 <= index < len(blocks):
            return
        self.pdf_view.set_selected(index)
        self.translation_panel.select_block(index)
        block = blocks[index]
        thread_key = (self._document_generation, self.current_page, index)
        if block.translation or block.kind == "formula" or thread_key in self._inflight:
            if block.kind == "formula" and not block.translation:
                block.translation = "公式（见原文）"
                self.translation_panel.update_block(index, block)
            return

        thread = QThread(self)
        self._inflight.add(thread_key)
        page_number = self.current_page
        worker = TranslationWorker(
            self.translator,
            self._document_generation,
            page_number,
            index,
            block.text,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._translation_finished)
        worker.failed.connect(self._translation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._release_translation(thread_key))
        self._translation_threads[thread_key] = thread
        self._translation_workers[thread_key] = worker
        self.translation_panel.set_pending(index, block)
        thread.start()

    def _release_translation(self, thread_key: tuple[int, int, int]) -> None:
        self._inflight.discard(thread_key)
        self._translation_workers.pop(thread_key, None)
        self._translation_threads.pop(thread_key, None)

    def _translation_finished(
        self, generation: int, page_number: int, index: int, translation: str
    ) -> None:
        if (
            generation != self._document_generation
            or not self.document
            or not 0 <= page_number < self.document.page_count
        ):
            return
        block = self.document.pages[page_number].blocks[index]
        block.translation = translation
        if page_number == self.current_page:
            self.translation_panel.update_block(index, block)
            self.statusBar().showMessage("翻译完成")

    def _translation_failed(
        self, generation: int, page_number: int, index: int, message: str
    ) -> None:
        if generation != self._document_generation:
            return
        if isinstance(self.translator, Translator) and not self.translator.client:
            message = "未配置 LLM_API_KEY，已保留原文。"
        self.statusBar().showMessage(message)
        if page_number == self.current_page:
            if self.document:
                block = self.document.pages[page_number].blocks[index]
                self.translation_panel.update_block(index, block)
            self.translation_panel.select_block(index)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        for thread in self._translation_threads.values():
            thread.quit()
            thread.wait(1000)
        if self.document:
            self.document.close()
        event.accept()
