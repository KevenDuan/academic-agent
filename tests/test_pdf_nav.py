from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QApplication

from app.ui.pdf_nav_view import PDFNavigationView
from app.ui.pdf_viewer import PDFPageView


class StubCursorNav(PDFNavigationView):
    """允许测试注入鼠标位置，从而真实驱动 _update_from_cursor 的区域判定。"""

    def __init__(self, view: PDFPageView) -> None:
        super().__init__(view)
        self.stub = QPoint()

    def _cursor_pos_in_container(self) -> QPoint:
        return self.stub


class PdfNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def _window(self) -> StubCursorNav:
        view = PDFPageView()
        nav = StubCursorNav(view)
        nav.resize(900, 700)
        nav.show()
        self.qt_app.processEvents()
        return nav

    def _center(self, nav: StubCursorNav) -> QPoint:
        zone = nav._zone_rect_in_container()
        return QPoint(zone.left() + zone.width() // 2, zone.top() + zone.height() // 2)

    def test_buttons_hidden_by_default(self):
        nav = self._window()
        self.assertFalse(nav.prev_button.isVisible())
        self.assertFalse(nav.next_button.isVisible())
        nav.close()

    def test_disabled_nav_keeps_buttons_hidden(self):
        nav = self._window()
        nav.set_nav_enabled(False)
        nav._update_from_cursor()
        self.assertFalse(nav.prev_button.isVisible())
        self.assertFalse(nav.next_button.isVisible())
        nav.close()

    def test_cursor_in_left_zone_shows_prev(self):
        nav = self._window()
        zone = nav._zone_rect_in_container()
        nav.stub = QPoint(zone.left() + 5, zone.top() + zone.height() // 2)
        nav.set_nav_enabled(True)
        nav._update_from_cursor()
        self.qt_app.processEvents()
        self.assertTrue(nav.prev_button.isVisible())
        self.assertFalse(nav.next_button.isVisible())
        nav.close()

    def test_cursor_in_right_zone_shows_next_even_over_scrollbar(self):
        nav = self._window()
        zone = nav._zone_rect_in_container()
        viewport = nav._viewport_rect_in_container()
        # 鼠标停在滚动区域最右侧边缘——这个点可能在视口之外（滚动条/边框区域）。
        nav.stub = QPoint(zone.right() - 3, zone.top() + zone.height() // 2)
        nav.set_nav_enabled(True)
        nav._update_from_cursor()
        self.qt_app.processEvents()
        self.assertTrue(nav.next_button.isVisible())
        self.assertFalse(nav.prev_button.isVisible())
        self.assertGreater(zone.right(), viewport.right())
        nav.close()

    def test_leaving_zone_hides_immediately(self):
        nav = self._window()
        zone = nav._zone_rect_in_container()
        nav.stub = QPoint(zone.right() - 5, zone.top() + zone.height() // 2)
        nav.set_nav_enabled(True)
        nav._update_from_cursor()
        self.qt_app.processEvents()
        self.assertTrue(nav.next_button.isVisible())

        # 鼠标移到中部离开触发区：按钮应立即淡出隐藏。
        nav.stub = self._center(nav)
        nav._update_from_cursor()
        nav.next_button._on_fade_finished()
        nav.prev_button._on_fade_finished()
        self.assertFalse(nav.next_button.isVisible())
        nav.close()

    def test_staying_in_zone_keeps_button_visible(self):
        nav = self._window()
        nav.set_nav_enabled(True)
        zone = nav._zone_rect_in_container()
        for y in (zone.top() + 30, zone.top() + zone.height() // 2, zone.bottom() - 30):
            nav.stub = QPoint(zone.right() - 5, y)
            nav._update_from_cursor()
            self.qt_app.processEvents()
            self.assertTrue(nav.next_button.isVisible(), f"next should stay visible at y={y}")
        nav.close()

    def test_cursor_over_button_edge_keeps_button_visible(self):
        nav = self._window()
        nav.set_nav_enabled(True)
        vp = nav._viewport_rect_in_container()
        # 按钮左缘距可见区域右边缘约 99px——这正是之前触发区覆盖不到、导致按钮
        # 淡出的位置。光标停在这里按钮必须保持显示。
        nav.stub = QPoint(vp.right() - 99, vp.top() + vp.height() // 2)
        nav._update_from_cursor()
        self.qt_app.processEvents()
        self.assertTrue(nav.next_button.isVisible())
        nav.close()

    def test_cursor_far_from_zone_and_button_hides(self):
        nav = self._window()
        nav.set_nav_enabled(True)
        vp = nav._viewport_rect_in_container()
        nav.stub = QPoint(vp.left() + vp.width() // 2, vp.top() + vp.height() // 2)
        nav._update_from_cursor()
        nav.prev_button._on_fade_finished()
        nav.next_button._on_fade_finished()
        self.assertFalse(nav.prev_button.isVisible())
        self.assertFalse(nav.next_button.isVisible())
        nav.close()

    def test_mouse_over_scrollbar_triggers_button(self):
        nav = self._window()
        nav.set_nav_enabled(True)
        zone = nav._zone_rect_in_container()
        # 光标停在滚动条区域（滚动区域右缘、视口右缘之外），并直接向滚动条发送
        # 真实移动事件——这正是"在滚动条上滑动/拖动"时的真实路径，按钮必须出现。
        nav.stub = QPoint(zone.right() - 2, zone.top() + zone.height() // 2)
        scrollbar = nav.pdf_view.verticalScrollBar()
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(0, 0),
            QPointF(0, 0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(scrollbar, event)
        self.assertTrue(nav.next_button._visible)
        nav.close()

    def test_buttons_emit_page_requests(self):
        nav = self._window()
        requests = []
        nav.previousRequested.connect(lambda: requests.append("prev"))
        nav.nextRequested.connect(lambda: requests.append("next"))
        nav.next_button.click()
        nav.prev_button.click()
        self.assertEqual(requests, ["next", "prev"])
        nav.close()

    def test_page_boundaries_hide_unavailable_direction(self):
        nav = self._window()
        zone = nav._zone_rect_in_container()

        nav.stub = QPoint(zone.left() + 5, zone.center().y())
        nav.set_page_state(0, 3)
        self.qt_app.processEvents()
        self.assertFalse(nav.prev_button.isVisible())
        self.assertFalse(nav.prev_button.isEnabled())

        nav.stub = QPoint(zone.right() - 5, zone.center().y())
        nav.set_page_state(2, 3)
        self.qt_app.processEvents()
        self.assertFalse(nav.next_button.isVisible())
        self.assertFalse(nav.next_button.isEnabled())

        nav.set_page_state(0, 1)
        self.assertFalse(nav.prev_button.isEnabled())
        self.assertFalse(nav.next_button.isEnabled())
        nav.close()

    def test_wheel_over_button_scrolls_pdf(self):
        nav = self._window()
        nav.pdf_view.set_page(QPixmap(600, 1200), 600, 1200, [])
        self.qt_app.processEvents()
        scrollbar = nav.pdf_view.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(0)
        event = QWheelEvent(
            QPointF(nav.next_button.rect().center()),
            QPointF(nav.next_button.mapToGlobal(nav.next_button.rect().center())),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        QApplication.sendEvent(nav.next_button, event)

        self.assertGreater(scrollbar.value(), 0)
        nav.close()

    def test_reversing_fade_continues_from_current_opacity(self):
        nav = self._window()
        button = nav.next_button
        button.set_faded_visible(True)
        button._fade.setCurrentTime(80)
        button.set_faded_visible(False)
        button._fade.setCurrentTime(40)
        opacity_before_reentry = button._opacity.opacity()

        button.set_faded_visible(True)

        self.assertAlmostEqual(
            button._fade.startValue(),
            opacity_before_reentry,
            places=3,
        )
        self.assertAlmostEqual(button._opacity.opacity(), opacity_before_reentry, places=3)
        nav.close()

    def test_fade_toggles_visibility(self):
        nav = self._window()
        button = nav.next_button
        button.set_faded_visible(True)
        self.qt_app.processEvents()
        self.assertTrue(button.isVisible())
        button.set_faded_visible(False)
        button._on_fade_finished()
        self.assertFalse(button.isVisible())
        nav.close()

    def test_buttons_positioned_inside_viewport(self):
        nav = self._window()
        viewport = nav.pdf_view.viewport()
        prev_at = nav.prev_button.mapTo(viewport, QPoint(0, 0))
        next_at = nav.next_button.mapTo(viewport, QPoint(0, 0))
        for at, size in ((prev_at, nav.prev_button.size()), (next_at, nav.next_button.size())):
            self.assertGreaterEqual(at.x(), 0)
            self.assertGreaterEqual(at.y(), 0)
            self.assertLessEqual(at.x() + size.width(), viewport.width())
            self.assertLessEqual(at.y() + size.height(), viewport.height())
        nav.close()


if __name__ == "__main__":
    unittest.main()
