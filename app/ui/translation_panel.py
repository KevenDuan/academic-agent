from __future__ import annotations

import math

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAbstractTextDocumentLayout, QPainter, QPalette, QTextDocument
from PyQt6.QtWidgets import (
    QApplication,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from app.core.pdf_parser import Block


class WrappedTextDelegate(QStyledItemDelegate):
    horizontal_padding = 32
    vertical_padding = 30

    def _document(self, option: QStyleOptionViewItem, text: str) -> QTextDocument:
        document = QTextDocument()
        document.setDocumentMargin(2)
        document.setDefaultFont(option.font)
        document.setPlainText(text)
        viewport = option.widget.viewport() if option.widget else None
        available_width = viewport.width() if viewport else option.rect.width()
        document.setTextWidth(max(180, available_width - self.horizontal_padding))
        return document

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt API
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        document = self._document(styled, styled.text)
        return QSize(
            math.ceil(document.textWidth()) + self.horizontal_padding,
            math.ceil(document.size().height()) + self.vertical_padding,
        )

    def paint(self, painter: QPainter, option, index) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        styled.text = ""
        style = styled.widget.style() if styled.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)

        document = self._document(styled, text)
        context = QAbstractTextDocumentLayout.PaintContext()
        if styled.state & QStyle.StateFlag.State_Selected:
            context.palette.setColor(
                QPalette.ColorRole.Text,
                styled.palette.color(QPalette.ColorRole.HighlightedText),
            )
        text_rect = styled.rect.adjusted(
            self.horizontal_padding // 2,
            self.vertical_padding // 2,
            -self.horizontal_padding // 2,
            -self.vertical_padding // 2,
        )
        painter.save()
        painter.translate(text_rect.topLeft())
        painter.setClipRect(0, 0, text_rect.width(), text_rect.height())
        document.documentLayout().draw(painter, context)
        painter.restore()


class TranslationPanel(QWidget):
    blockSelected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list_widget.setSpacing(8)
        self.list_widget.setItemDelegate(WrappedTextDelegate(self.list_widget))
        self.list_widget.currentRowChanged.connect(self.blockSelected.emit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.list_widget)

    def set_blocks(self, blocks: list[Block]) -> None:
        self.list_widget.clear()
        for block in blocks:
            self.list_widget.addItem(self._item_text(block))

    def update_block(self, index: int, block: Block) -> None:
        if 0 <= index < self.list_widget.count():
            item = self.list_widget.item(index)
            item.setText(self._item_text(block))
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.list_widget.doItemsLayout()

    def set_pending(self, index: int, block: Block) -> None:
        if 0 <= index < self.list_widget.count():
            self.list_widget.item(index).setText(self._item_text(block, "正在翻译…"))
            self.list_widget.doItemsLayout()

    def select_block(self, index: int) -> None:
        if 0 <= index < self.list_widget.count():
            self.list_widget.setCurrentRow(index)
            self.list_widget.scrollToItem(self.list_widget.item(index))

    @staticmethod
    def _item_text(block: Block, status: str | None = None) -> str:
        translation = block.translation or status or "译文尚未生成"
        display_source = " ".join(line.strip() for line in block.text.splitlines())
        return f"{block.order + 1}. {display_source}\n\n中文：{translation}"

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.list_widget.doItemsLayout()
