from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.paper_repo import PaperRecord


class PaperLibraryDialog(QDialog):
    openPaperRequested = pyqtSignal(str)
    removePaperRequested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("论文库")
        self.resize(720, 480)
        self.paper_list = QListWidget()
        self.paper_list.setAlternatingRowColors(True)
        self.summary_label = QLabel("共 0 篇论文")
        self.open_button = QPushButton("打开论文")
        self.remove_button = QPushButton("移出论文库")
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)

        actions = QHBoxLayout()
        actions.addWidget(self.summary_label)
        actions.addStretch()
        actions.addWidget(self.open_button)
        actions.addWidget(self.remove_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.paper_list, 1)
        layout.addLayout(actions)
        layout.addWidget(close_buttons)

        self.paper_list.currentItemChanged.connect(self._selection_changed)
        self.paper_list.itemDoubleClicked.connect(lambda _item: self._open_selected())
        self.open_button.clicked.connect(self._open_selected)
        self.remove_button.clicked.connect(self._remove_selected)
        self._selection_changed(None, None)

    def set_papers(self, papers: list[PaperRecord]) -> None:
        selected_id = self.current_paper_id()
        self.paper_list.clear()
        selected_row = -1
        for row, paper in enumerate(papers):
            item = QListWidgetItem(
                f"{paper.title}\n{paper.block_count} 个文本块  |  {paper.file_path}"
            )
            item.setData(Qt.ItemDataRole.UserRole, paper.paper_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, paper.file_path)
            item.setToolTip(paper.file_path)
            self.paper_list.addItem(item)
            if paper.paper_id == selected_id:
                selected_row = row
        self.paper_list.setCurrentRow(selected_row)
        self.summary_label.setText(f"共 {len(papers)} 篇论文")
        self._selection_changed(self.paper_list.currentItem(), None)

    def current_paper_id(self) -> str | None:
        item = self.paper_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self, current, _previous) -> None:
        enabled = current is not None
        self.open_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)

    def _open_selected(self) -> None:
        item = self.paper_list.currentItem()
        if item:
            self.openPaperRequested.emit(item.data(Qt.ItemDataRole.UserRole + 1))

    def _remove_selected(self) -> None:
        paper_id = self.current_paper_id()
        if paper_id:
            self.removePaperRequested.emit(paper_id)

