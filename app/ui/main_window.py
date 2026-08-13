from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QImage, QKeySequence, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.chat_service import ChatService
from app.core.pdf_parser import PDFParser, ParsedDocument
from app.core.session_store import SessionStore
from app.core.translator import Translator
from app.resources import resource_path
from app.ui.chat_panel import ChatPanel, SessionSidebar
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


class ChatWorker(QObject):
    finished = pyqtSignal(str, str)
    failed = pyqtSignal(str, str)

    def __init__(self, chat_service: ChatService, session_id: str, messages, context: str) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.session_id = session_id
        self.messages = messages
        self.context = context

    def run(self) -> None:
        try:
            self.finished.emit(
                self.session_id,
                self.chat_service.answer(self.messages, self.context),
            )
        except Exception as exc:
            self.failed.emit(self.session_id, str(exc))


class MainWindow(QMainWindow):
    def __init__(
        self,
        initial_pdf: str | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Academic Agent")
        self.setWindowIcon(QIcon(resource_path("logo.png")))
        self.resize(1440, 900)
        self.parser = PDFParser()
        self.document: ParsedDocument | None = None
        self._document_generation = 0
        self.current_page = 0
        self.translator = Translator()
        self.chat_service = ChatService(self.translator.client, self.translator.model)
        self.session_store = session_store or SessionStore()
        self.current_session_id: str | None = None
        self._chat_thread: QThread | None = None
        self._chat_worker: ChatWorker | None = None
        self._translation_threads: dict[tuple[int, int, int], QThread] = {}
        self._translation_workers: dict[tuple[int, int, int], TranslationWorker] = {}
        self._inflight: set[tuple[int, int, int]] = set()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(120)
        self._render_timer.timeout.connect(self._rerender_current_page)

        self.pdf_view = PDFPageView()
        self.translation_panel = TranslationPanel()
        self.chat_panel = ChatPanel()
        self.session_sidebar = SessionSidebar()
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
        self._refresh_sessions()
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
        splitter.addWidget(self.session_sidebar)
        splitter.addWidget(left)
        right_tabs = QTabWidget()
        right_tabs.addTab(self.translation_panel, "译文")
        right_tabs.addTab(self.chat_panel, "对话")
        splitter.addWidget(right_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([230, 760, 450])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("请选择一个 PDF 文件")
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #202328; color: #e6e9ef; }
            QListWidget, QSpinBox { background: #17191d; border: 1px solid #343a46; }
            QListWidget::item { padding: 0px; border-bottom: 1px solid #2d323c; }
            QListWidget::item:selected { background: #394455; }
            QLabel#sidebarTitle { font-size: 18px; font-weight: 600; padding: 4px 2px 8px 2px; }
            QTextBrowser, QTextEdit { background: #17191d; border: 1px solid #343a46; padding: 8px; }
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
        self.session_sidebar.sessionSelected.connect(self.activate_session)
        self.session_sidebar.newSessionRequested.connect(self.new_session)
        self.session_sidebar.renameSessionRequested.connect(self.rename_session)
        self.session_sidebar.deleteSessionRequested.connect(self.delete_session)
        self.chat_panel.messageSubmitted.connect(self.send_chat_message)

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
        if self.current_session_id:
            self.session_store.set_paper(self.current_session_id, str(parsed.path))
            self._refresh_sessions(self.current_session_id)
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

    def _refresh_sessions(self, selected_id: str | None = None) -> None:
        sessions = self.session_store.list_sessions()
        selected_id = selected_id or self.current_session_id
        if selected_id is None and sessions:
            selected_id = sessions[0].session_id
        self.session_sidebar.set_sessions(sessions, selected_id)
        if selected_id:
            self.activate_session(selected_id)
        else:
            self.current_session_id = None
            self.chat_panel.show_messages([])

    def new_session(self) -> None:
        paper_id = str(self.document.path) if self.document else None
        session = self.session_store.create_session(paper_id=paper_id)
        self._refresh_sessions(session.session_id)

    def activate_session(self, session_id: str) -> None:
        try:
            session = self.session_store.get_session(session_id)
        except KeyError:
            self._refresh_sessions()
            return
        self.current_session_id = session_id
        self.chat_panel.show_messages(self.session_store.get_messages(session_id))
        if session.paper_id:
            paper_path = Path(session.paper_id)
            current_path = self.document.path if self.document else None
            if paper_path.exists() and current_path != paper_path.resolve():
                self.load_pdf(paper_path)
            elif not paper_path.exists():
                self.chat_panel.set_busy(False, "关联的论文文件已移动，请重新打开 PDF。")

    def rename_session(self) -> None:
        if not self.current_session_id:
            return
        session = self.session_store.get_session(self.current_session_id)
        title, accepted = QInputDialog.getText(self, "重命名会话", "会话名称", text=session.title)
        if accepted and title.strip():
            self.session_store.rename_session(self.current_session_id, title)
            self._refresh_sessions(self.current_session_id)

    def delete_session(self) -> None:
        if not self.current_session_id:
            return
        answer = QMessageBox.question(
            self,
            "删除会话",
            "确定删除当前会话及其聊天记录吗？论文文件不会被删除。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        session_id = self.current_session_id
        self.current_session_id = None
        self.session_store.delete_session(session_id)
        self._refresh_sessions()

    def send_chat_message(self, text: str) -> None:
        if self._chat_thread and self._chat_thread.isRunning():
            return
        if not self.current_session_id:
            self.new_session()
        if not self.current_session_id:
            return
        session_id = self.current_session_id
        existing_messages = self.session_store.get_messages(session_id)
        self.session_store.add_message(session_id, "user", text)
        if not existing_messages:
            self.session_store.rename_session(session_id, text[:40])
        messages = self.session_store.get_messages(session_id)
        self.chat_panel.clear_input()
        self.chat_panel.show_messages(messages)
        self.chat_panel.set_busy(True, "正在思考…")
        self.session_sidebar.set_busy(True)
        self._refresh_sessions(session_id)

        thread = QThread(self)
        worker = ChatWorker(
            self.chat_service,
            session_id,
            messages,
            self._paper_context(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._chat_finished)
        worker.failed.connect(self._chat_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._release_chat_worker)
        self._chat_thread = thread
        self._chat_worker = worker
        thread.start()

    def _paper_context(self, max_chars: int = 32000) -> str:
        if not self.document:
            return ""
        parts = []
        used_chars = 0
        for page in self.document.pages:
            page_text = "\n".join(
                block.text for block in page.blocks if block.kind != "formula"
            )
            chunk = f"[第 {page.number + 1} 页]\n{page_text}\n"
            if parts and used_chars + len(chunk) > max_chars:
                break
            parts.append(chunk[: max_chars - used_chars])
            used_chars += len(parts[-1])
            if used_chars >= max_chars:
                break
        return "\n".join(parts)

    def _chat_finished(self, session_id: str, answer: str) -> None:
        self.session_store.add_message(session_id, "assistant", answer)
        self.chat_panel.set_busy(False)
        self.session_sidebar.set_busy(False)
        if session_id == self.current_session_id:
            self.chat_panel.show_messages(self.session_store.get_messages(session_id))
        self._refresh_sessions(self.current_session_id)
        self.statusBar().showMessage("回答完成")

    def _chat_failed(self, session_id: str, message: str) -> None:
        self.chat_panel.set_busy(False)
        self.session_sidebar.set_busy(False)
        if session_id == self.current_session_id:
            self.chat_panel.set_busy(False, message)
        self.statusBar().showMessage(message)

    def _release_chat_worker(self) -> None:
        self._chat_worker = None
        self._chat_thread = None

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._chat_thread and self._chat_thread.isRunning():
            self.chat_panel.set_busy(True, "模型仍在响应，请等待完成后再关闭。")
            self.session_sidebar.set_busy(True)
            event.ignore()
            return
        for thread in self._translation_threads.values():
            thread.quit()
            thread.wait(1000)
        if self.document:
            self.document.close()
        self.session_store.close()
        event.accept()
