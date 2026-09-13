from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings
from app.ui.icons import app_icon


class SettingsDialog(QDialog):
    settingsSaved = pyqtSignal(AppSettings)

    PROVIDERS = (
        ("DeepSeek", "deepseek"),
        ("OpenAI", "openai"),
        ("自定义兼容服务", "custom"),
    )
    PRESETS = {
        "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
        "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    }

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("模型与服务设置")
        self.setModal(True)
        self.setMinimumWidth(540)

        title = QLabel("模型与服务")
        title.setObjectName("dialogTitle")
        description = QLabel("配置翻译、论文问答与联网搜索所使用的服务。保存后立即生效。")
        description.setObjectName("statusMuted")
        description.setWordWrap(True)

        self.provider_combo = QComboBox()
        for label, value in self.PROVIDERS:
            self.provider_combo.addItem(label, value)
        provider_index = self.provider_combo.findData(settings.provider)
        self.provider_combo.setCurrentIndex(max(0, provider_index))

        self.model_input = QLineEdit(settings.model)
        self.model_input.setPlaceholderText("例如 deepseek-chat")
        self.base_url_input = QLineEdit(settings.base_url)
        self.base_url_input.setPlaceholderText("https://api.example.com/v1")
        self.api_key_input = self._secret_input(settings.api_key, "模型 API Key")
        self.api_key_toggle = self._secret_toggle(self.api_key_input)
        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(5, 600)
        self.timeout_input.setSuffix(" 秒")
        self.timeout_input.setValue(settings.timeout)
        self.tavily_key_input = self._secret_input(settings.tavily_api_key, "Tavily API Key")
        self.tavily_key_toggle = self._secret_toggle(self.tavily_key_input)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.addRow("服务商", self.provider_combo)
        form.addRow("模型 ID", self.model_input)
        form.addRow("Base URL", self.base_url_input)
        form.addRow("API Key", self._with_toggle(self.api_key_input, self.api_key_toggle))
        form.addRow("请求超时", self.timeout_input)
        form.addRow("Tavily Key", self._with_toggle(self.tavily_key_input, self.tavily_key_toggle))

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        self.provider_combo.currentIndexChanged.connect(self._apply_provider_preset)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addSpacing(4)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(self.buttons)

    @staticmethod
    def _secret_input(value: str, placeholder: str) -> QLineEdit:
        field = QLineEdit(value)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText(placeholder)
        return field

    @staticmethod
    def _secret_toggle(field: QLineEdit) -> QPushButton:
        button = QPushButton()
        button.setObjectName("iconButton")
        button.setIcon(app_icon("fa5s.eye"))
        button.setFixedSize(34, 34)
        button.setCheckable(True)
        button.setToolTip("显示密钥")

        def toggle(checked: bool) -> None:
            field.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
            button.setIcon(app_icon("fa5s.eye-slash" if checked else "fa5s.eye"))
            button.setToolTip("隐藏密钥" if checked else "显示密钥")

        button.toggled.connect(toggle)
        return button

    @staticmethod
    def _with_toggle(field: QLineEdit, button: QPushButton) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(field, 1)
        layout.addWidget(button)
        return container

    def _apply_provider_preset(self) -> None:
        preset = self.PRESETS.get(str(self.provider_combo.currentData()))
        if preset is None:
            return
        base_url, model = preset
        self.base_url_input.setText(base_url)
        self.model_input.setText(model)

    def settings(self) -> AppSettings:
        return AppSettings(
            provider=str(self.provider_combo.currentData()),
            model=self.model_input.text().strip(),
            base_url=self.base_url_input.text().strip(),
            api_key=self.api_key_input.text().strip(),
            timeout=self.timeout_input.value(),
            tavily_api_key=self.tavily_key_input.text().strip(),
        )

    def _save(self) -> None:
        settings = self.settings()
        if not settings.model or not settings.base_url:
            QMessageBox.warning(self, "设置不完整", "模型 ID 和 Base URL 不能为空。")
            return
        self.settingsSaved.emit(settings)
        self.accept()
