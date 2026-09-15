from __future__ import annotations

from enum import Enum
from math import sqrt

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QScrollArea, QWidget

from app.core.pdf_parser import Block


class PageViewMode(str, Enum):
    FIT_WIDTH = "fit_width"
    FIT_PAGE = "fit_page"
    ACTUAL_SIZE = "actual_size"


class PDFPageCanvas(QWidget):
    blockClicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = QImage()
        self._blocks: list[Block] = []
        self._selected = -1
        self._page_width = 1.0
        self._page_height = 1.0
        self._scale = 1.0
        self.setMouseTracking(True)

    def set_page(
        self,
        pixmap: QPixmap,
        page_width: float,
        page_height: float,
        blocks: list[Block],
        scale: float,
        selected: int = -1,
    ) -> None:
        self._image = pixmap.toImage()
        self._page_width = page_width
        self._page_height = page_height
        self._blocks = blocks
        self._scale = scale
        self._selected = selected
        self._resize_to_page()
        self.update()

    def set_image(self, image: QPixmap | QImage, scale: float) -> None:
        self._image = image.toImage() if isinstance(image, QPixmap) else image
        self._scale = scale
        self._resize_to_page()
        self.update()

    def set_selected(self, index: int) -> None:
        self._selected = index
        self.update()

    def _resize_to_page(self) -> None:
        self.resize(
            max(1, round(self._page_width * self._scale)),
            max(1, round(self._page_height * self._scale)),
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#252628"))
        if self._image.isNull():
            painter.setPen(QColor("#a8afab"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "打开 PDF 以开始阅读")
            return

        target = QRectF(0, 0, self._page_width * self._scale, self._page_height * self._scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, self._image)
        if 0 <= self._selected < len(self._blocks):
            x0, y0, x1, y1 = self._blocks[self._selected].bbox
            highlight = QRectF(
                x0 * self._scale,
                y0 * self._scale,
                (x1 - x0) * self._scale,
                (y1 - y0) * self._scale,
            )
            painter.setBrush(QColor(255, 213, 79, 75))
            painter.setPen(QPen(QColor("#f0b429"), 2))
            painter.drawRect(highlight)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton or self._image.isNull():
            return
        position = event.position()
        pdf_x = position.x() / self._scale
        pdf_y = position.y() / self._scale
        if not (0 <= pdf_x <= self._page_width and 0 <= pdf_y <= self._page_height):
            return
        for index, block in enumerate(self._blocks):
            x0, y0, x1, y1 = block.bbox
            if x0 <= pdf_x <= x1 and y0 <= pdf_y <= y1:
                self._selected = index
                self.blockClicked.emit(index)
                self.update()
                return


class PDFPageView(QScrollArea):
    PDF_DPI = 72.0
    RENDER_OVERSAMPLE = 1.5
    MIN_RENDER_DPI = 110
    MAX_RENDER_DPI = 600
    MAX_RENDER_PIXELS = 20_000_000

    blockClicked = pyqtSignal(int)
    zoomPercentChanged = pyqtSignal(int)
    renderRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = PDFPageCanvas()
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(420, 560)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._page_width = 1.0
        self._page_height = 1.0
        self._base_scale = 1.0
        self._zoom_factor = 1.0
        self._view_mode = PageViewMode.FIT_WIDTH
        self._updating_fit = False
        self.canvas.blockClicked.connect(self.blockClicked.emit)

    def sizeHint(self) -> QSize:
        return QSize(760, 900)

    @property
    def zoom_factor(self) -> float:
        return self._zoom_factor

    @property
    def view_mode(self) -> PageViewMode:
        return self._view_mode

    @property
    def current_scale(self) -> float:
        return self._current_scale()

    def prepare_page(self, page_width: float, page_height: float) -> None:
        self._page_width = max(1.0, page_width)
        self._page_height = max(1.0, page_height)
        self._zoom_factor = 1.0
        self._update_base_scale()

    def render_dpi(self, device_pixel_ratio: float | None = None) -> int:
        ratio = device_pixel_ratio or self.devicePixelRatioF()
        requested = (
            self.PDF_DPI
            * self._current_scale()
            * max(1.0, ratio)
            * self.RENDER_OVERSAMPLE
        )
        pixel_limited = self.PDF_DPI * sqrt(
            self.MAX_RENDER_PIXELS / (self._page_width * self._page_height)
        )
        return max(
            1,
            int(
                min(
                    max(self.MIN_RENDER_DPI, requested),
                    self.MAX_RENDER_DPI,
                    pixel_limited,
                )
            ),
        )

    def set_page(
        self,
        pixmap: QPixmap,
        page_width: float,
        page_height: float,
        blocks: list[Block],
        selected: int = -1,
    ) -> None:
        self.prepare_page(page_width, page_height)
        self.canvas.set_page(
            pixmap,
            page_width,
            page_height,
            blocks,
            self._current_scale(),
            selected,
        )
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.zoomPercentChanged.emit(100)

    def set_image(self, pixmap: QPixmap) -> None:
        self.canvas.set_image(pixmap, self._current_scale())

    def set_selected(self, index: int) -> None:
        self.canvas.set_selected(index)

    def zoom_in(self) -> None:
        self._zoom_at(1.2)

    def zoom_out(self) -> None:
        self._zoom_at(1 / 1.2)

    def reset_zoom(self) -> None:
        self.set_view_mode(self._view_mode)

    def fit_width(self) -> None:
        self.set_view_mode(PageViewMode.FIT_WIDTH)

    def fit_page(self) -> None:
        self.set_view_mode(PageViewMode.FIT_PAGE)

    def actual_size(self) -> None:
        self.set_view_mode(PageViewMode.ACTUAL_SIZE)

    def set_view_mode(self, mode: PageViewMode | str) -> None:
        self._view_mode = PageViewMode(mode)
        self._zoom_factor = 1.0
        self._update_base_scale()
        if not self.canvas._image.isNull():
            self.canvas.set_image(self.canvas._image, self._current_scale())
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.zoomPercentChanged.emit(100)
        if not self.canvas._image.isNull():
            self.renderRequested.emit()

    def _update_base_scale(self) -> None:
        viewport = self.viewport().size()
        margin = 18.0
        width_scale = max(1.0, viewport.width() - 2 * margin) / self._page_width
        if self._view_mode == PageViewMode.FIT_WIDTH:
            self._base_scale = width_scale
        elif self._view_mode == PageViewMode.FIT_PAGE:
            self._base_scale = min(
                width_scale,
                max(1.0, viewport.height() - 2 * margin) / self._page_height,
            )
        else:
            self._base_scale = max(1.0, float(self.logicalDpiX())) / self.PDF_DPI

    def _current_scale(self) -> float:
        return self._base_scale * self._zoom_factor

    def _zoom_at(self, multiplier: float, position: QPointF | None = None) -> None:
        if self.canvas._image.isNull():
            return
        position = position or QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        old_scale = self._current_scale()
        content_x = (
            self.horizontalScrollBar().value() + position.x() - self.canvas.pos().x()
        )
        content_y = self.verticalScrollBar().value() + position.y() - self.canvas.pos().y()
        page_x = content_x / old_scale
        page_y = content_y / old_scale
        self._zoom_factor = max(0.5, min(5.0, self._zoom_factor * multiplier))
        new_scale = self._current_scale()
        self.canvas.set_image(self.canvas._image, new_scale)
        self._set_scroll_anchor(page_x, page_y, position, new_scale)
        self.zoomPercentChanged.emit(round(self._zoom_factor * 100))
        self.renderRequested.emit()

    def _set_scroll_anchor(
        self, page_x: float, page_y: float, position: QPointF, scale: float
    ) -> None:
        self.horizontalScrollBar().setValue(
            round(page_x * scale + self.canvas.pos().x() - position.x())
        )
        self.verticalScrollBar().setValue(
            round(page_y * scale + self.canvas.pos().y() - position.y())
        )

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            self._zoom_at(1.2**steps, event.position())
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - event.angleDelta().y()
            )
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if (
            self._view_mode != PageViewMode.ACTUAL_SIZE
            and not self._updating_fit
        ):
            self._updating_fit = True
            old_scale = self._current_scale()
            self._update_base_scale()
            if (
                not self.canvas._image.isNull()
                and abs(self._current_scale() - old_scale) > 0.001
            ):
                self.canvas.set_image(self.canvas._image, self._current_scale())
                self.renderRequested.emit()
            self._updating_fit = False
