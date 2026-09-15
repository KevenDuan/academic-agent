from __future__ import annotations

import html

from markdown_it import MarkdownIt
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.session_store import (
    Message,
    Session,
    selected_passage_from_metadata,
)
from app.ui.icons import app_icon


_MARKDOWN = MarkdownIt(
    "commonmark",
    {"html": False, "linkify": False, "typographer": False},
).enable(["table", "strikethrough"])


class SessionSidebar(QWidget):
    sessionSelected = pyqtSignal(str)
    newSessionRequested = pyqtSignal()
    renameSessionRequested = pyqtSignal()
    deleteSessionRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sessionSidebar")
        self.setMinimumWidth(190)
        self.setMaximumWidth(320)
        title = QLabel("Academic Agent")
        title.setObjectName("brandTitle")
        section = QLabel("最近对话")
        section.setObjectName("sectionLabel")
        self.session_list = QListWidget()
        self.session_list.setObjectName("sessionList")
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(title)
        layout.addWidget(section)
        layout.addWidget(self.session_list, 1)

        self.session_list.currentItemChanged.connect(self._session_changed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_sidebar_menu)
        self.session_list.customContextMenuRequested.connect(self._show_list_menu)

    def set_sessions(self, sessions: list[Session], selected_id: str | None = None) -> None:
        self.session_list.blockSignals(True)
        self.session_list.clear()
        selected_row = -1
        for row, session in enumerate(sessions):
            item = QListWidgetItem(session.title)
            item.setData(Qt.ItemDataRole.UserRole, session.session_id)
            item.setToolTip(session.paper_id or "未关联论文")
            self.session_list.addItem(item)
            if session.session_id == selected_id:
                selected_row = row
        self.session_list.setCurrentRow(selected_row)
        self.session_list.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.session_list.setEnabled(not busy)

    def _create_context_menu(self) -> QMenu:
        menu = QMenu(self)
        new_action = menu.addAction("新建对话")
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        has_session = self.session_list.currentItem() is not None
        new_action.setEnabled(not self._busy)
        rename_action.setEnabled(has_session and not self._busy)
        delete_action.setEnabled(has_session and not self._busy)
        new_action.triggered.connect(self.newSessionRequested.emit)
        rename_action.triggered.connect(self.renameSessionRequested.emit)
        delete_action.triggered.connect(self.deleteSessionRequested.emit)
        return menu

    def _show_sidebar_menu(self, position) -> None:
        self._create_context_menu().exec(self.mapToGlobal(position))

    def _show_list_menu(self, position) -> None:
        item = self.session_list.itemAt(position)
        if item is not None:
            self.session_list.setCurrentItem(item)
        self._create_context_menu().exec(self.session_list.mapToGlobal(position))

    def _session_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is not None:
            self.sessionSelected.emit(current.data(Qt.ItemDataRole.UserRole))


class ElidedLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setMinimumHeight(self.fontMetrics().height())
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        available_width = max(0, self.contentsRect().width())
        elided = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            available_width,
        )
        if elided != self.text():
            super().setText(elided)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._update_elided_text()


class ChatPanel(QWidget):
    messageSubmitted = pyqtSignal(str)
    selectedPassageCleared = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.messages = QTextBrowser()
        self.messages.setObjectName("chatMessages")
        self.messages.setOpenExternalLinks(True)
        self.input = QTextEdit()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("向 Academic Agent 提问…")
        self.input.setFixedHeight(82)
        self.send_button = QPushButton()
        self.send_button.setObjectName("sendButton")
        self.send_button.setIcon(app_icon("fa5s.paper-plane", "#07130d"))
        self.send_button.setFixedSize(36, 36)
        self.send_button.setToolTip("发送")
        self.status_label = QLabel()
        self.status_label.setObjectName("composerStatus")
        self.status_label.setWordWrap(True)
        self.composer = QFrame()
        self.composer.setObjectName("chatComposer")
        self.passage_attachment = QWidget()
        self.passage_attachment.setObjectName("passageAttachment")
        self.passage_title = ElidedLabel()
        self.passage_title.setObjectName("passageAttachmentTitle")
        self.passage_preview = ElidedLabel()
        self.passage_preview.setObjectName("passageAttachmentPreview")
        self.clear_passage_button = QPushButton()
        self.clear_passage_button.setObjectName("clearPassageButton")
        self.clear_passage_button.setIcon(app_icon("fa5s.times"))
        self.clear_passage_button.setFixedSize(28, 28)
        self.clear_passage_button.setToolTip("移除选中段落")

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        passage_text = QVBoxLayout()
        passage_text.setContentsMargins(0, 0, 0, 0)
        passage_text.setSpacing(2)
        passage_text.addWidget(self.passage_title)
        passage_text.addWidget(self.passage_preview)
        passage_layout = QHBoxLayout(self.passage_attachment)
        passage_layout.setContentsMargins(10, 7, 7, 7)
        passage_layout.addLayout(passage_text, 1)
        passage_layout.addWidget(self.clear_passage_button)
        self.passage_attachment.hide()

        composer_footer = QHBoxLayout()
        composer_footer.setContentsMargins(0, 0, 0, 0)
        composer_footer.addWidget(self.status_label, 1)
        composer_footer.addWidget(self.send_button)
        composer_layout = QVBoxLayout(self.composer)
        composer_layout.setContentsMargins(11, 8, 9, 9)
        composer_layout.setSpacing(4)
        composer_layout.addWidget(self.input)
        composer_layout.addLayout(composer_footer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.passage_attachment)
        layout.addWidget(self.composer)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._submit)
        self.clear_passage_button.clicked.connect(self.selectedPassageCleared.emit)

    def show_messages(self, messages: list[Message]) -> None:
        parts = [
            "<style>"
            "body { color: #eef0ee; margin: 0; }"
            "table.turn { margin: 6px 0 16px 0; }"
            "td.role { color: #a8afab; font-size: 11px; font-weight: 600; padding: 0 3px 5px 3px; }"
            "td.user-bubble { color: #f1f5f2; background: #405047; border: 1px solid #5d7366; "
            "padding: 10px 12px; }"
            "td.assistant-bubble { color: #eef0ee; background: #36383a; border: 1px solid #4c4f51; "
            "padding: 10px 12px; }"
            ".passage { color: #c9ddd1; background: #35433b; border-left: 2px solid #8ed3a6; "
            "padding: 7px 9px; margin: 0 0 9px 0; }"
            "p { margin: 0 0 8px 0; line-height: 1.5; }"
            "h1 { font-size: 18px; margin: 4px 0 9px 0; }"
            "h2 { font-size: 16px; margin: 4px 0 8px 0; }"
            "h3 { font-size: 14px; margin: 3px 0 7px 0; }"
            "pre { color: #e8ece9; background: #26282a; border: 1px solid #505355; "
            "padding: 8px; margin: 7px 0; white-space: pre-wrap; }"
            "code { color: #d7eadf; background: #2a2c2e; font-family: Consolas, monospace; }"
            "blockquote { color: #c2cac5; border-left: 3px solid #78837d; margin: 7px 0; padding-left: 9px; }"
            "th { background: #2a2c2e; padding: 5px; }"
            "td { padding: 5px; }"
            "a { color: #9bdcb1; }"
            "</style>"
        ]
        for message in messages:
            if not message.content or message.role == "tool":
                continue
            parts.append(self._render_turn(message))
        self.messages.setHtml("".join(parts))
        self.messages.verticalScrollBar().setValue(self.messages.verticalScrollBar().maximum())

    @classmethod
    def _render_turn(cls, message: Message) -> str:
        is_user = message.role == "user"
        label = "你" if is_user else "Academic Agent" if message.role == "assistant" else "系统"
        bubble_class = "user-bubble" if is_user else "assistant-bubble"
        content = cls._render_markdown(message.content or "")
        passage_html = cls._render_passage(message)
        bubble = f"<td class='{bubble_class}'>{passage_html}{content}</td>"
        if is_user:
            role_row = f"<tr><td width='16%'></td><td class='role' align='right'>{label}</td></tr>"
            bubble_row = f"<tr><td width='16%'></td>{bubble}</tr>"
        else:
            role_row = f"<tr><td class='role' align='left'>{label}</td><td width='8%'></td></tr>"
            bubble_row = f"<tr>{bubble}<td width='8%'></td></tr>"
        return (
            "<table class='turn' width='100%' cellspacing='0' cellpadding='0'>"
            f"{role_row}{bubble_row}</table>"
        )

    @staticmethod
    def _render_markdown(text: str) -> str:
        return _MARKDOWN.render(text)

    @classmethod
    def _render_passage(cls, message: Message) -> str:
        passage = selected_passage_from_metadata(message.metadata)
        if passage is None:
            return ""
        title = html.escape(str(passage.get("paper_title") or "当前论文"))
        page = html.escape(str(passage.get("page") or "未知"))
        preview = html.escape(cls._preview(str(passage["text"]), 120))
        return (
            "<div class='passage'>"
            f"<b>选中段落 · {title} · 第 {page} 页</b><br>"
            f"{preview}</div>"
        )

    def set_busy(self, busy: bool, status: str = "") -> None:
        self.input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.status_label.setText(status)

    def clear_input(self) -> None:
        self.input.clear()

    def set_selected_passage(self, passage: dict[str, object] | None) -> None:
        if passage is None:
            self.passage_attachment.hide()
            self.input.setPlaceholderText("向 Academic Agent 提问…")
            return
        title = str(passage.get("paper_title") or "当前论文")
        page = passage.get("page") or "未知"
        self.passage_title.set_full_text(f"选中段落 · {title} · 第 {page} 页")
        self.passage_title.setToolTip(title)
        passage_text = str(passage["text"])
        self.passage_preview.set_full_text(" ".join(passage_text.split()))
        self.passage_preview.setToolTip(passage_text)
        self.passage_attachment.show()
        self.input.setPlaceholderText("询问选中段落…")

    @staticmethod
    def _preview(text: str, limit: int) -> str:
        normalized = " ".join(text.split())
        return normalized if len(normalized) <= limit else normalized[:limit] + "..."

    def _submit(self) -> None:
        text = self.input.toPlainText().strip()
        if text:
            self.messageSubmitted.emit(text)
