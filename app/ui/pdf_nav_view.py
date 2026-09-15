from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QCursor, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.icons import app_icon
from app.ui.pdf_viewer import PDFPageView


class _NavButton(QPushButton):
    """不遮挡额外阅读区域的圆形翻页按钮。"""

    def __init__(
        self,
        icon_name: str,
        tooltip: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self.setMouseTracking(True)
        self.setIcon(app_icon(icon_name, "#eef0ee"))
        self.setIconSize(QSize(22, 22))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(42, 45, 48, 236);
                border: 1px solid rgba(226, 232, 228, 0.30);
                border-radius: 28px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(61, 81, 70, 246);
                border-color: rgba(142, 211, 166, 0.82);
            }
            QPushButton:pressed {
                background-color: rgba(74, 104, 87, 250);
            }
            """
        )

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)

        self._visible = False
        self.hide()

    def set_faded_visible(self, visible: bool) -> None:
        if visible == self._visible:
            return
        self._visible = visible
        self._fade.stop()
        current_opacity = self._opacity.opacity()
        if visible:
            self.show()
            self.raise_()
            self._fade.setStartValue(current_opacity)
            self._fade.setEndValue(1.0)
        else:
            self._fade.setStartValue(current_opacity)
            self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if not self._visible:
            self.hide()


class PDFNavigationView(QWidget):
    """包裹 PDF 阅读区，在左右边缘悬浮圆形上/下页按钮。

    鼠标停留在滚动区域左/右边缘（含滚动条上方）时按钮保持显示，移出区域
    即淡出。顶部工具栏的翻页按钮保持不变，这里的按钮通过 previousRequested
    / nextRequested 信号触发同一套翻页逻辑。
    """

    previousRequested = pyqtSignal()
    nextRequested = pyqtSignal()

    EDGE_ZONE = 110  # 距可见阅读区左右边缘多少像素内触发按钮显示（滚动条上方也算）

    def __init__(
        self,
        pdf_view: PDFPageView,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pdf_view = pdf_view
        self._nav_enabled = False
        self._previous_available = False
        self._next_available = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.pdf_view, 1)

        self.prev_button = _NavButton("fa5s.chevron-left", "上一页", self)
        self.next_button = _NavButton("fa5s.chevron-right", "下一页", self)
        self.prev_button.clicked.connect(self.previousRequested.emit)
        self.next_button.clicked.connect(self.nextRequested.emit)

        viewport = self.pdf_view.viewport()
        viewport.setMouseTracking(True)
        self.pdf_view.setMouseTracking(True)
        self.setMouseTracking(True)
        for scrollbar in (
            self.pdf_view.verticalScrollBar(),
            self.pdf_view.horizontalScrollBar(),
        ):
            scrollbar.setMouseTracking(True)
        for target in (
            self,
            self.pdf_view,
            viewport,
            self.pdf_view.canvas,
            self.pdf_view.verticalScrollBar(),
            self.pdf_view.horizontalScrollBar(),
            self.prev_button,
            self.next_button,
        ):
            target.installEventFilter(self)

    def set_nav_enabled(self, enabled: bool) -> None:
        self._nav_enabled = enabled
        self._previous_available = enabled
        self._next_available = enabled
        self.prev_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)
        if enabled:
            self._update_from_cursor()
        else:
            self.prev_button.set_faded_visible(False)
            self.next_button.set_faded_visible(False)

    def set_page_state(self, current_page: int, page_count: int) -> None:
        self._nav_enabled = page_count > 0
        self._previous_available = self._nav_enabled and current_page > 0
        self._next_available = self._nav_enabled and current_page < page_count - 1
        self.prev_button.setEnabled(self._previous_available)
        self.next_button.setEnabled(self._next_available)
        self._update_from_cursor()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        event_type = event.type()
        if event_type == QEvent.Type.Wheel and obj in (
            self.prev_button,
            self.next_button,
        ):
            self._forward_wheel_event(event)
            return True
        if event_type in (
            QEvent.Type.MouseMove,
            QEvent.Type.Enter,
            QEvent.Type.Leave,
            QEvent.Type.Wheel,
        ):
            self._update_from_cursor()
        elif event_type == QEvent.Type.Resize and obj is self.pdf_view.viewport():
            self._reposition_buttons()
            self._update_from_cursor()
        return super().eventFilter(obj, event)

    def _forward_wheel_event(self, event: QWheelEvent) -> None:
        viewport = self.pdf_view.viewport()
        local_position = viewport.mapFromGlobal(event.globalPosition().toPoint())
        forwarded = QWheelEvent(
            QPointF(local_position),
            event.globalPosition(),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
        )
        QApplication.sendEvent(viewport, forwarded)
        event.accept()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._reposition_buttons()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._reposition_buttons()

    def _update_from_cursor(self) -> None:
        if not self._nav_enabled:
            self._set_visibility(False, False)
            return
        zone = self._zone_rect_in_container()
        cursor = self._cursor_pos_in_container()
        if not zone.contains(cursor):
            self._set_visibility(False, False)
            return
        viewport_rect = self._viewport_rect_in_container()
        in_left = (
            (cursor.x() - viewport_rect.left()) < self.EDGE_ZONE
            or self._over_button(self.prev_button, cursor)
        )
        in_right = (
            (viewport_rect.right() - cursor.x()) < self.EDGE_ZONE
            or self._over_button(self.next_button, cursor)
        )
        self._set_visibility(in_left, in_right)

    def _over_button(self, button: _NavButton, cursor: QPoint) -> bool:
        """光标是否停在按钮附近（含周围留白），保证瞄准/点击时按钮不会消失。"""
        return button.geometry().adjusted(-16, -16, 16, 16).contains(cursor)

    def _cursor_pos_in_container(self) -> QPoint:
        return self.mapFromGlobal(QCursor.pos())

    def _set_visibility(self, show_prev: bool, show_next: bool) -> None:
        self.prev_button.set_faded_visible(show_prev and self._previous_available)
        self.next_button.set_faded_visible(show_next and self._next_available)

    def _viewport_rect_in_container(self) -> QRect:
        viewport = self.pdf_view.viewport()
        return QRect(viewport.mapTo(self, QPoint(0, 0)), viewport.size())

    def _zone_rect_in_container(self) -> QRect:
        """整个滚动区域的几何范围（含滚动条），触发区据此计算。"""
        return QRect(self.pdf_view.mapTo(self, QPoint(0, 0)), self.pdf_view.size())

    def _reposition_buttons(self) -> None:
        viewport_rect = self._viewport_rect_in_container()
        margin = 24
        y = viewport_rect.top() + (viewport_rect.height() - self.prev_button.height()) // 2
        self.prev_button.move(viewport_rect.left() + margin, y)
        self.next_button.move(
            viewport_rect.right() - margin - self.next_button.width() + 1,
            y,
        )
