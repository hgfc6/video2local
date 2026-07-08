import sys

from PySide6.QtWidgets import QApplication

from video2local.ui.controller import MainController
from video2local.ui.main_window import MainWindow


class NullEngine:
    def start_sync(self) -> None:
        return None


def main() -> int:
    app = QApplication(sys.argv)
    controller = MainController(engine=NullEngine())
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
