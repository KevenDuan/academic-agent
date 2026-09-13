from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QSize, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QImage, QKeySequence, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QSpinBox,
    QSplitter,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.core.chat_service import ChatService
from app.config import AppSettings
from app.agent.agent_loop import AgentLoop
from app.agent.registry import SkillRegistry
from app.agent.skills import default_skills_dir
from app.core.pdf_parser import PDFParser, ParsedDocument
from app.core.rag_engine import RagEngine
from app.core.session_store import SessionStore, selected_passage_from_metadata
from app.core.translator import Translator
from app.resources import resource_path
from app.ui.chat_panel import ChatPanel, ElidedLabel, SessionSidebar
from app.ui.icons import app_icon
from app.ui.paper_library_dialog import PaperLibraryDialog
from app.ui.pdf_viewer import PDFPageView
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import codex_dark_stylesheet
from app.ui.translation_panel import TranslationPanel
from app.settings_store import SettingsStore


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
    toolsUsed = pyqtSignal(str, object)
    MAX_PAPER_CONTEXT_CHARS = 32000

    def __init__(
        self,
        chat_service: ChatService,
        rag_engine: RagEngine,
        session_id: str,
        messages,
        query: str,
        current_paper_path: str | None,
        fallback_context: str,
        agent_loop: AgentLoop | None = None,
        use_rag: bool = True,
    ) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.rag_engine = rag_engine
        self.session_id = session_id
        self.messages = messages
        self.query = query
        self.current_paper_path = current_paper_path
        self.fallback_context = fallback_context
        self.agent_loop = agent_loop
        self.use_rag = use_rag

    def run(self) -> None:
        try:
            selected_passage = (
                selected_passage_from_metadata(self.messages[-1].metadata)
                if self.messages
                else None
            )
            if self.agent_loop is not None:
                current_is_indexed = bool(
                    selected_passage is not None
                    or (
                        self.current_paper_path
                        and self.rag_engine.contains_document(self.current_paper_path)
                    )
                )
                context = "" if selected_passage is not None or current_is_indexed else self.fallback_context
            elif not self.use_rag:
                context = self.fallback_context
            else:
                results = (
                    []
                    if selected_passage is not None
                    else self.rag_engine.search(self.query, top_k=5)
                )
                context = self.rag_engine.format_context(results)
                current_is_indexed = bool(
                    selected_passage is None
                    and self.current_paper_path
                    and self.rag_engine.contains_document(self.current_paper_path)
                )
                if (
                    self.fallback_context
                    and selected_passage is None
                    and (not results or not current_is_indexed)
                ):
                    context = "\n\n".join(part for part in (context, self.fallback_context) if part)
            context = context[: self.MAX_PAPER_CONTEXT_CHARS]
            if self.agent_loop is not None:
                result = self.agent_loop.answer(self.messages, context)
                self.toolsUsed.emit(self.session_id, result.tool_traces)
                answer = result.answer
            else:
                answer = self.chat_service.answer(self.messages, context)
            self.finished.emit(self.session_id, answer)
        except Exception as exc:
            self.failed.emit(self.session_id, str(exc))


class IndexWorker(QObject):
    finished = pyqtSignal(str, str, bool, int)
    failed = pyqtSignal(str)

    def __init__(self, rag_engine: RagEngine, document: ParsedDocument) -> None:
        super().__init__()
        self.rag_engine = rag_engine
        self.document = document

    def run(self) -> None:
        try:
            paper, created = self.rag_engine.add_document(self.document)
            self.finished.emit(paper.paper_id, paper.title, created, paper.block_count)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    MAX_SELECTED_PASSAGE_CHARS = 12000

    def __init__(
        self,
        initial_pdf: str | None = None,
        session_store: SessionStore | None = None,
        rag_engine: RagEngine | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Academic Agent")
        self.setWindowIcon(QIcon(resource_path("logo.png")))
        self.resize(1440, 900)
        self.setMinimumSize(1040, 680)
        self.parser = PDFParser()
        self.document: ParsedDocument | None = None
        self._document_generation = 0
        self.current_page = 0
        self.settings_store = settings_store or SettingsStore()
        self.settings = self.settings_store.load()
        self.settings.apply_to_environment()
        self.translator = Translator(
            api_key=self.settings.api_key or None,
            base_url=self.settings.base_url or None,
            model=self.settings.model,
        )
        self.chat_service = ChatService(self.translator.client, self.translator.model)
        self.session_store = session_store or SessionStore()
        self._rag_engine_injected = rag_engine is not None
        self.rag_engine = rag_engine or RagEngine()
        self.skill_registry = SkillRegistry(default_skills_dir())
        self.agent_loop = AgentLoop(
            self.translator.client,
            self.translator.model,
            self.skill_registry,
            self.rag_engine,
            self.translator,
        )
        self.current_session_id: str | None = None
        self._selected_passage: dict[str, object] | None = None
        self._chat_thread: QThread | None = None
        self._chat_worker: ChatWorker | None = None
        self._index_thread: QThread | None = None
        self._index_worker: IndexWorker | None = None
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
        self.document_title = ElidedLabel()
        self.document_title.set_full_text("未打开论文")
        self.document_title.setObjectName("documentTitle")
        self.document_meta = QLabel("PDF")
        self.document_meta.setObjectName("documentMeta")
        self.page_label = QLabel("第 0 / 0 页")
        self.previous_button = QPushButton()
        self.next_button = QPushButton()
        self.zoom_out_button = QPushButton()
        self.zoom_reset_button = QPushButton("100%")
        self.zoom_in_button = QPushButton()
        self.fit_button = QPushButton()
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setFixedWidth(72)
        for button, icon, tooltip in (
            (self.previous_button, "fa5s.chevron-left", "上一页"),
            (self.next_button, "fa5s.chevron-right", "下一页"),
            (self.zoom_out_button, "fa5s.search-minus", "缩小"),
            (self.zoom_in_button, "fa5s.search-plus", "放大"),
            (self.fit_button, "fa5s.expand", "适应页面"),
        ):
            button.setIcon(app_icon(icon))
            button.setToolTip(tooltip)
            button.setObjectName("iconButton")
            button.setFixedSize(30, 28)
        for button in (
            self.zoom_out_button,
            self.zoom_reset_button,
            self.zoom_in_button,
            self.fit_button,
        ):
            button.setFixedHeight(28)
        self.zoom_reset_button.setFixedWidth(58)
        self.zoom_reset_button.setToolTip("重置缩放")

        self._build_ui()
        self._connect_signals()
        self._refresh_sessions()
        if initial_pdf:
            QTimer.singleShot(0, lambda: self.load_pdf(initial_pdf))

    def _build_ui(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        self.open_action = QAction(app_icon("fa5s.folder-open"), "打开 PDF", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.setToolTip("打开 PDF")
        self.open_action.triggered.connect(self.open_pdf)
        file_menu.addAction(self.open_action)
        self.add_to_library_action = QAction("将当前论文加入论文库", self)
        self.add_to_library_action.setIcon(app_icon("fa5s.bookmark"))
        self.add_to_library_action.setToolTip("将当前论文加入论文库")
        self.add_to_library_action.setEnabled(False)
        self.add_to_library_action.triggered.connect(self.add_current_to_library)
        file_menu.addAction(self.add_to_library_action)
        self.manage_library_action = QAction("管理论文库", self)
        self.manage_library_action.setIcon(app_icon("fa5s.book"))
        self.manage_library_action.setToolTip("管理论文库")
        self.manage_library_action.triggered.connect(self.show_paper_library)
        file_menu.addAction(self.manage_library_action)

        settings_menu = self.menuBar().addMenu("应用")
        self.settings_action = QAction(app_icon("fa5s.cog"), "设置", self)
        self.settings_action.setToolTip("模型与服务设置")
        self.settings_action.triggered.connect(self.show_settings)
        settings_menu.addAction(self.settings_action)

        view_menu = self.menuBar().addMenu("视图")
        self.sidebar_action = QAction(app_icon("fa5s.columns"), "显示最近对话", self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        self.sidebar_action.setToolTip("显示或隐藏最近对话")
        self.sidebar_action.triggered.connect(self.toggle_session_sidebar)
        view_menu.addAction(self.sidebar_action)

        toolbar = QToolBar("主工具栏", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.addAction(self.sidebar_action)
        toolbar.addSeparator()
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.add_to_library_action)
        toolbar.addAction(self.manage_library_action)
        toolbar.addSeparator()
        toolbar_spacer = QWidget()
        toolbar_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(toolbar_spacer)
        toolbar.addAction(self.settings_action)
        self.addToolBar(toolbar)
        self.main_toolbar = toolbar

        page_controls = QHBoxLayout()
        page_controls.setContentsMargins(0, 0, 0, 0)
        page_controls.addWidget(self.previous_button)
        page_controls.addWidget(self.next_button)
        page_controls.addSpacing(6)
        page_controls.addWidget(self.zoom_out_button)
        page_controls.addWidget(self.zoom_reset_button)
        page_controls.addWidget(self.zoom_in_button)
        page_controls.addWidget(self.fit_button)
        page_controls.addStretch()
        page_controls.addWidget(self.page_label)
        page_controls.addWidget(self.page_spin)

        document_heading = QVBoxLayout()
        document_heading.setContentsMargins(0, 0, 0, 0)
        document_heading.setSpacing(1)
        document_heading.addWidget(self.document_title)
        document_heading.addWidget(self.document_meta)
        document_header = QHBoxLayout()
        document_header.setContentsMargins(0, 0, 0, 0)
        document_header.addLayout(document_heading, 1)
        document_header.addLayout(page_controls)
        document_header_widget = QWidget()
        document_header_widget.setLayout(document_header)

        document_pane = QWidget()
        document_pane.setObjectName("documentPane")
        document_layout = QVBoxLayout(document_pane)
        document_layout.setContentsMargins(10, 8, 10, 10)
        document_layout.setSpacing(8)
        document_layout.addWidget(document_header_widget)
        document_layout.addWidget(self.pdf_view, 1)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.session_sidebar)
        self.workspace_splitter.addWidget(document_pane)
        self.right_tabs = QTabWidget()
        self.right_tabs.setObjectName("workspaceTabs")
        self.right_tabs.addTab(self.translation_panel, app_icon("fa5s.language"), "译文")
        self.right_tabs.addTab(self.chat_panel, app_icon("fa5s.comment-alt"), "对话")
        self.workspace_splitter.addWidget(self.right_tabs)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 1)
        self.workspace_splitter.setSizes([230, 760, 450])
        self.setCentralWidget(self.workspace_splitter)
        self.statusBar().showMessage("请选择一个 PDF 文件")
        self.setStyleSheet(codex_dark_stylesheet())

    def toggle_session_sidebar(self, visible: bool) -> None:
        self.session_sidebar.setVisible(visible)
        self.sidebar_action.setChecked(visible)

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
        self.chat_panel.selectedPassageCleared.connect(self.clear_selected_passage)

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
        self.clear_selected_passage()
        self._document_generation += 1
        self.document = parsed
        self.current_page = 0
        self.document_title.set_full_text(parsed.path.stem)
        self.document_title.setToolTip(str(parsed.path))
        self.document_meta.setText(f"PDF · {parsed.page_count} 页")
        self.add_to_library_action.setEnabled(True)
        if self.current_session_id:
            self.session_store.set_paper(self.current_session_id, str(parsed.path))
            self._refresh_sessions(self.current_session_id)
        self.page_spin.setMaximum(max(1, parsed.page_count))
        self.translation_panel.set_blocks(parsed.pages[0].blocks if parsed.pages else [])
        self.show_page(0)
        self.statusBar().showMessage(f"已打开：{parsed.path.name}")

    def add_current_to_library(self) -> None:
        if not self.document or (self._index_thread and self._index_thread.isRunning()):
            return
        if self._chat_thread and self._chat_thread.isRunning():
            self.statusBar().showMessage("请等待当前回答完成后再建立论文索引。")
            return
        thread = QThread(self)
        worker = IndexWorker(self.rag_engine, self.document)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._index_finished)
        worker.failed.connect(self._index_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._release_index_worker)
        self._index_thread = thread
        self._index_worker = worker
        self.add_to_library_action.setEnabled(False)
        self.chat_panel.set_busy(True, "正在建立论文索引，首次使用将下载 BGE-M3…")
        self.session_sidebar.set_busy(True)
        self.statusBar().showMessage("正在加载 BGE-M3 并建立论文索引…")
        thread.start()

    def _index_finished(
        self, _paper_id: str, title: str, created: bool, block_count: int
    ) -> None:
        self.add_to_library_action.setEnabled(self.document is not None)
        self.chat_panel.set_busy(False)
        self.session_sidebar.set_busy(False)
        if created:
            message = f"已加入论文库：{title}（{block_count} 个文本块）"
        else:
            message = f"论文已在库中：{title}"
        self.statusBar().showMessage(message)

    def _index_failed(self, message: str) -> None:
        self.add_to_library_action.setEnabled(self.document is not None)
        self.chat_panel.set_busy(False, message)
        self.session_sidebar.set_busy(False)
        self.statusBar().showMessage(f"论文入库失败：{message}")

    def _release_index_worker(self) -> None:
        self._index_worker = None
        self._index_thread = None

    def show_paper_library(self) -> None:
        dialog = PaperLibraryDialog(self)
        dialog.set_papers(self.rag_engine.list_papers())
        dialog.openPaperRequested.connect(lambda path: self._open_library_paper(dialog, path))
        dialog.removePaperRequested.connect(
            lambda paper_id: self._remove_library_paper(dialog, paper_id)
        )
        dialog.exec()

    def show_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = dialog.settings()
        try:
            self.settings_store.save(settings)
        except OSError as exc:
            QMessageBox.critical(self, "无法保存设置", str(exc))
            return
        self._apply_runtime_settings(settings)
        self.statusBar().showMessage("设置已保存并应用")

    def _apply_runtime_settings(self, settings: AppSettings) -> None:
        settings.apply_to_environment()
        translator = Translator(
            api_key=settings.api_key or None,
            base_url=settings.base_url or None,
            model=settings.model,
        )
        self.settings = settings
        self.translator = translator
        self.chat_service = ChatService(translator.client, translator.model)
        self.agent_loop = AgentLoop(
            translator.client,
            translator.model,
            self.skill_registry,
            self.rag_engine,
            translator,
        )

    def _open_library_paper(self, dialog: PaperLibraryDialog, path: str) -> None:
        paper_path = Path(path)
        if not paper_path.exists():
            QMessageBox.warning(self, "文件不存在", "论文文件已移动或删除。")
            return
        dialog.accept()
        self.load_pdf(paper_path)

    def _remove_library_paper(
        self, dialog: PaperLibraryDialog, paper_id: str
    ) -> None:
        answer = QMessageBox.question(
            self,
            "移出论文库",
            "确定从论文库移除该论文吗？原始 PDF 文件不会被删除。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.rag_engine.remove_paper(paper_id)
        dialog.set_papers(self.rag_engine.list_papers())
        self.statusBar().showMessage("论文已移出论文库")

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
        self._selected_passage = {
            "paper_path": str(self.document.path),
            "paper_title": self.document.path.stem,
            "page": self.current_page + 1,
            "block_index": index,
            "block_order": block.order,
            "bbox": list(block.bbox),
            "text": block.text.strip()[: self.MAX_SELECTED_PASSAGE_CHARS],
            "translation": block.translation,
        }
        self.chat_panel.set_selected_passage(self._selected_passage)
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
        if (
            self._selected_passage
            and self._selected_passage.get("paper_path") == str(self.document.path)
            and self._selected_passage.get("page") == page_number + 1
            and self._selected_passage.get("block_index") == index
        ):
            self._selected_passage["translation"] = translation
            self.chat_panel.set_selected_passage(self._selected_passage)
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
        if session_id != self.current_session_id:
            self.clear_selected_passage()
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
        if self._index_thread and self._index_thread.isRunning():
            self.statusBar().showMessage("请等待论文索引完成后再提问。")
            return
        if self._chat_thread and self._chat_thread.isRunning():
            return
        selected_passage = (
            dict(self._selected_passage) if self._selected_passage else None
        )
        if not self.current_session_id:
            self.new_session()
        if not self.current_session_id:
            return
        session_id = self.current_session_id
        existing_messages = self.session_store.get_messages(session_id)
        metadata = (
            {"selected_passage": selected_passage}
            if selected_passage
            else None
        )
        self.session_store.add_message(
            session_id,
            "user",
            text,
            metadata=metadata,
        )
        self.clear_selected_passage()
        if not existing_messages:
            self.session_store.rename_session(session_id, text[:40])
        messages = self.session_store.get_messages(session_id)
        self.chat_panel.clear_input()
        self.chat_panel.show_messages(messages)
        self.chat_panel.set_busy(True, "正在检索论文库并思考…")
        self.session_sidebar.set_busy(True)
        self._refresh_sessions(session_id)

        thread = QThread(self)
        worker = ChatWorker(
            self.chat_service,
            self.rag_engine,
            session_id,
            messages,
            text,
            str(self.document.path) if self.document else None,
            self._paper_context(),
            self.agent_loop if isinstance(self.chat_service, ChatService) else None,
            self._rag_engine_injected,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._chat_finished)
        worker.failed.connect(self._chat_failed)
        worker.toolsUsed.connect(self._chat_tools_used)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._release_chat_worker)
        self._chat_thread = thread
        self._chat_worker = worker
        thread.start()

    def _chat_tools_used(self, session_id: str, traces) -> None:
        for trace in traces:
            self.session_store.add_message(
                session_id,
                "tool",
                trace.result,
                tool_calls={
                    "name": trace.name,
                    "arguments": trace.arguments,
                    "tool_call_id": trace.tool_call_id,
                },
            )

    def clear_selected_passage(self) -> None:
        self._selected_passage = None
        self.chat_panel.set_selected_passage(None)

    def _paper_context(self, max_chars: int = 32000) -> str:
        if not self.document:
            return ""
        parts = []
        used_chars = 0
        for page in self.document.pages:
            page_text = "\n".join(
                block.text for block in page.blocks if block.kind != "formula"
            )
            chunk = f"[当前论文，第 {page.number + 1} 页]\n{page_text}\n"
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
        if self._index_thread and self._index_thread.isRunning():
            self.statusBar().showMessage("论文索引仍在进行，请等待完成后再关闭。")
            event.ignore()
            return
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
        self.rag_engine.close()
        event.accept()
