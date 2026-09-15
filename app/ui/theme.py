from __future__ import annotations


def codex_dark_stylesheet() -> str:
    return """
    * { font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; font-size: 13px; }
    QMainWindow, QDialog { background: #292a2c; color: #f0f1f0; }
    QWidget { color: #f0f1f0; background: #2e2f31; }
    QMenuBar { background: #292a2c; border-bottom: 1px solid #444648; padding: 2px; }
    QMenuBar::item { padding: 6px 10px; background: transparent; }
    QMenuBar::item:selected { background: #3a3b3d; border-radius: 4px; }
    QMenu { background: #333436; border: 1px solid #505254; padding: 5px; }
    QMenu::item { padding: 7px 28px 7px 10px; border-radius: 3px; }
    QMenu::item:selected { background: #3d5146; color: #f4fff8; }
    QToolBar#mainToolbar { background: #303133; border: none; border-bottom: 1px solid #46484a; spacing: 4px; padding: 5px 8px; }
    QToolBar#mainToolbar QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 6px; }
    QToolBar#mainToolbar QToolButton:hover { background: #414345; border-color: #55585a; }
    QToolBar#mainToolbar QToolButton:pressed, QToolBar#mainToolbar QToolButton:checked { background: #3d5146; }
    QWidget#sessionSidebar { background: #2a2b2d; border-right: 1px solid #454749; }
    QWidget#documentPane, QTabWidget#workspaceTabs { background: #2e2f31; }
    QLabel#brandTitle { font-size: 16px; font-weight: 650; color: #f5f7f6; padding: 5px 2px 1px 2px; }
    QLabel#dialogTitle { font-size: 18px; font-weight: 650; color: #f5f7f6; }
    QLabel#sectionLabel { color: #a5aca8; font-size: 11px; font-weight: 600; padding: 8px 2px 3px 2px; }
    QLabel#documentTitle { font-weight: 600; color: #e7ebe8; }
    QLabel#documentMeta, QLabel#statusMuted, QLabel#composerStatus { color: #a4aaa7; }
    QSplitter::handle { background: #454749; width: 1px; }
    QTabWidget::pane { border: none; border-left: 1px solid #454749; background: #2e2f31; }
    QTabBar { background: #2a2b2d; }
    QTabBar::tab { background: #2a2b2d; color: #a8aeab; border: none; border-bottom: 2px solid transparent; padding: 10px 16px; }
    QTabBar::tab:hover { color: #e1e4e2; background: #353638; }
    QTabBar::tab:selected { color: #f4f6f4; border-bottom-color: #8ed3a6; }
    QListWidget, QTextBrowser, QTextEdit { background: #303234; border: 1px solid #484b4d; border-radius: 5px; selection-background-color: #405a4b; }
    QListWidget { alternate-background-color: #333537; outline: none; }
    QListWidget::item { border-bottom: 1px solid #424446; padding: 0px; }
    QListWidget#sessionList::item { padding: 6px 8px; }
    QListWidget::item:hover { background: #3a3c3e; }
    QListWidget::item:selected { background: #3d5146; color: #f2fff7; }
    QTextBrowser#chatMessages { background: #2e2f31; border: none; padding: 8px 10px; }
    QTextEdit { padding: 8px; }
    QFrame#chatComposer { background: #383a3c; border: 1px solid #55585a; border-radius: 8px; }
    QFrame#chatComposer QTextEdit#chatInput { background: transparent; border: none; border-radius: 0px; padding: 3px; }
    QFrame#chatComposer QTextEdit#chatInput:focus { border: none; }
    QFrame#chatComposer QLabel { background: transparent; border: none; }
    QLineEdit, QComboBox, QSpinBox { background: #353739; border: 1px solid #505355; border-radius: 4px; padding: 7px 9px; min-height: 18px; }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus { border-color: #8ed3a6; }
    QComboBox::drop-down { border: none; width: 24px; }
    QPushButton { background: #3a3c3e; border: 1px solid #55585a; border-radius: 4px; padding: 7px 12px; }
    QPushButton:hover { background: #454749; border-color: #646769; }
    QPushButton:pressed { background: #3d5146; }
    QPushButton:disabled { color: #7d8380; background: #333537; border-color: #444648; }
    QPushButton#primaryButton, QPushButton#sendButton { background: #8ed3a6; color: #102016; border-color: #8ed3a6; font-weight: 650; }
    QPushButton#primaryButton:hover, QPushButton#sendButton:hover { background: #a0dfb5; }
    QPushButton#sendButton { padding: 0px; border-radius: 7px; }
    QPushButton#iconButton, QPushButton#clearPassageButton { padding: 0px; min-width: 28px; min-height: 28px; }
    QWidget#passageAttachment { background: #35423b; border: 1px solid #587363; border-radius: 5px; }
    QWidget#passageAttachment QLabel { background: transparent; border: none; }
    QLabel#passageAttachmentTitle { font-weight: 600; color: #dff7e9; }
    QLabel#passageAttachmentPreview { color: #b1c0b7; }
    QGroupBox { border: 1px solid #4b4e50; border-radius: 5px; margin-top: 12px; padding: 12px 10px 10px 10px; font-weight: 600; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #cdd4d0; }
    QDialogButtonBox { button-layout: 0; }
    QStatusBar { background: #292a2c; color: #a5aca8; border-top: 1px solid #444648; }
    QStatusBar::item { border: none; }
    QScrollBar:vertical { background: #2e2f31; width: 10px; margin: 0; }
    QScrollBar::handle:vertical { background: #5a5d5f; min-height: 28px; border-radius: 4px; margin: 2px; }
    QScrollBar::handle:vertical:hover { background: #707476; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal { background: #2e2f31; height: 10px; margin: 0; }
    QScrollBar::handle:horizontal { background: #5a5d5f; min-width: 28px; border-radius: 4px; margin: 2px; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QToolTip { background: #404244; color: #f0f1f0; border: 1px solid #626567; padding: 5px; }
    """
