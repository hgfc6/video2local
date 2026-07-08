from PySide6.QtWidgets import QApplication

from video2local.ui.controller import MainController
from video2local.ui.main_window import MainWindow


class FakeEngine:
    def launch_chrome(self) -> None:
        return None

    def start_sync(self):
        class Summary:
            downloaded_count = 0
            skipped_count = 0
            failed_count = 0

        return Summary()


def test_main_window_builds_buttons_and_status_label() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(MainController(engine=FakeEngine()))

    assert window.windowTitle() == "Video2Local"
    assert window.launch_button.text() == "启动 Chrome"
    assert window.validate_button.text() == "检查当前页面"
    assert window.start_button.text() == "开始同步"
    assert window.status_label.text() == "待命"
    assert window.detail_label.text() == "未开始同步"

    window.close()
    app.quit()
