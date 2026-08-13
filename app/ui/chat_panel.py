from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.session_store import Message, Session


class SessionSidebar(QWidget):
    sessionSelected = pyqtSignal(str)
    newSessionRequested = pyqtSignal()
    renameSessionRequested = pyqtSignal()
    deleteSessionRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(190)
        self.setMaximumWidth(320)
        title = QLabel("对话")
        title.setObjectName("sidebarTitle")
        self.session_list = QListWidget()
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(title)
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


class ChatPanel(QWidget):
    messageSubmitted = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.messages = QTextBrowser()
        self.messages.setOpenExternalLinks(True)
        self.input = QTextEdit()
        self.input.setPlaceholderText("询问当前论文…")
        self.input.setFixedHeight(88)
        self.send_button = QPushButton("发送")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)

        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        compose = QHBoxLayout()
        compose.addWidget(self.input, 1)
        compose.addWidget(self.send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(compose)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._submit)

    def show_messages(self, messages: list[Message]) -> None:
        parts = []
        labels = {"user": "你", "assistant": "Academic Agent", "system": "系统"}
        for message in messages:
            if not message.content or message.role == "tool":
                continue
            label = labels.get(message.role, message.role)
            safe_content = message.content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            parts.append(f"<p><b>{label}</b><br>{safe_content.replace(chr(10), '<br>')}</p>")
        self.messages.setHtml("".join(parts))
        self.messages.verticalScrollBar().setValue(self.messages.verticalScrollBar().maximum())

    def set_busy(self, busy: bool, status: str = "") -> None:
        self.input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.status_label.setText(status)

    def clear_input(self) -> None:
        self.input.clear()

    def _submit(self) -> None:
        text = self.input.toPlainText().strip()
        if text:
            self.messageSubmitted.emit(text)
