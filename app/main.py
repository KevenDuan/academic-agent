from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from PyQt6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description="AcademicAgent PDF reader")
    parser.add_argument("pdf", nargs="?", help="optional PDF path")
    args = parser.parse_args()

    application = QApplication(sys.argv)
    application.setApplicationName("AcademicAgent")
    window = MainWindow(args.pdf)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
