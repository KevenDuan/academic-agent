from __future__ import annotations

import json
from pathlib import Path

from platformdirs import user_data_path

from app.config import AppSettings


class SettingsStore:
    """Persist application settings in the local AcademicAgent data directory."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = user_data_path("AcademicAgent", appauthor=False, ensure_exists=True) / "settings.json"
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings.from_environment()
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                raise ValueError("settings root must be an object")
            return AppSettings.from_dict(values)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppSettings.from_environment()

    def save(self, settings: AppSettings) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
