import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from video2local.app_runtime import AppRuntime
from video2local.config import AppSettings
from video2local.ui.controller import MainController
from video2local.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    settings = AppSettings.default_for_root(Path.cwd())
    controller = MainController(engine=AppRuntime(settings=settings))
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
