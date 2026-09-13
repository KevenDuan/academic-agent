from __future__ import annotations

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QStyle

import qtawesome as qta


def app_icon(name: str, color: str = "#c9d1cd") -> QIcon:
    try:
        return qta.icon(name, color=color)
    except Exception:
        application = QApplication.instance()
        if application is None:
            return QIcon()
        fallbacks = {
            "fa5s.folder-open": QStyle.StandardPixmap.SP_DialogOpenButton,
            "fa5s.bookmark": QStyle.StandardPixmap.SP_DialogSaveButton,
            "fa5s.book": QStyle.StandardPixmap.SP_FileDialogListView,
            "fa5s.cog": QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "fa5s.columns": QStyle.StandardPixmap.SP_FileDialogListView,
            "fa5s.chevron-left": QStyle.StandardPixmap.SP_ArrowLeft,
            "fa5s.chevron-right": QStyle.StandardPixmap.SP_ArrowRight,
            "fa5s.search-minus": QStyle.StandardPixmap.SP_ArrowDown,
            "fa5s.search-plus": QStyle.StandardPixmap.SP_ArrowUp,
            "fa5s.expand": QStyle.StandardPixmap.SP_TitleBarMaxButton,
            "fa5s.language": QStyle.StandardPixmap.SP_FileDialogContentsView,
            "fa5s.comment-alt": QStyle.StandardPixmap.SP_MessageBoxInformation,
            "fa5s.paper-plane": QStyle.StandardPixmap.SP_ArrowForward,
            "fa5s.times": QStyle.StandardPixmap.SP_DialogCloseButton,
            "fa5s.eye": QStyle.StandardPixmap.SP_FileDialogInfoView,
            "fa5s.eye-slash": QStyle.StandardPixmap.SP_FileDialogInfoView,
            "fa5s.trash-alt": QStyle.StandardPixmap.SP_TrashIcon,
        }
        standard_icon = fallbacks.get(name, QStyle.StandardPixmap.SP_FileIcon)
        return application.style().standardIcon(standard_icon)
