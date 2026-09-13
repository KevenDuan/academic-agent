from __future__ import annotations

import html

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
            "body { color: #eef0ee; }"
            ".role { color: #a8afab; font-size: 11px; font-weight: 600; margin-top: 14px; }"
            ".message { margin: 4px 0 18px 0; line-height: 1.5; }"
            ".passage { color: #c0d8ca; background: #35433b; border-left: 2px solid #8ed3a6; "
            "padding: 7px 9px; margin: 5px 0 8px 0; }"
            "</style>"
        ]
        labels = {"user": "你", "assistant": "Academic Agent", "system": "系统"}
        for message in messages:
            if not message.content or message.role == "tool":
                continue
            label = labels.get(message.role, message.role)
            passage = selected_passage_from_metadata(message.metadata)
            if passage is not None:
                title = html.escape(str(passage.get("paper_title") or "当前论文"))
                page = html.escape(str(passage.get("page") or "未知"))
                preview = self._preview(str(passage["text"]), 120)
                parts.append(
                    "<div class='passage'>"
                    f"<b>选中段落 · {title} · 第 {page} 页</b><br>"
                    f"{html.escape(preview)}</div>"
                )
            safe_content = html.escape(message.content)
            parts.append(
                f"<div class='role'>{label}</div>"
                f"<div class='message'>{safe_content.replace(chr(10), '<br>')}</div>"
            )
        self.messages.setHtml("".join(parts))
        self.messages.verticalScrollBar().setValue(self.messages.verticalScrollBar().maximum())

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
