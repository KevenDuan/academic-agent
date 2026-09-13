from __future__ import annotations

from pathlib import Path


def default_skills_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "skills"
