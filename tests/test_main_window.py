from PySide6.QtWidgets import QApplication

from video2local.ui.controller import MainController
from video2local.ui.main_window import MainWindow


class FakeEngine:
    def launch_chrome(self) -> None:
        return None

    def stop_sync(self) -> None:
        return None

    def open_downloads_dir(self) -> None:
        return None

    def get_latest_sync_run(self):
        return None

    def start_sync(self):
        class Summary:
            discovered_count = 0
            downloaded_count = 0
            skipped_count = 0
            failed_count = 0
            status = "completed"

        return Summary()


def test_main_window_builds_buttons_and_status_label() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(MainController(engine=FakeEngine()))

    assert window.windowTitle() == "Video2Local"
    assert "输出目录" in window.guide_label.text()
    assert window.output_dir_input.text() != ""
    assert window.output_dir_button.text() == "选择目录"
    assert window.limit_input.placeholderText() == "全部"
    assert window.share_input.placeholderText() == "粘贴抖音分享文案或分享链接"
    assert window.parse_share_button.text() == "解析分享链接"
    assert window.download_share_button.text() == "下载所选版本"
    assert window.launch_button.text() == "启动 Chrome"
    assert window.validate_button.text() == "检查当前页面"
    assert window.sample_button.text() == "下载首个样本"
    assert window.start_button.text() == "开始同步"
    assert window.stop_button.text() == "停止同步"
    assert window.open_downloads_button.text() == "打开下载目录"
    assert window.summary_button.text() == "查看最近摘要"
    assert window.status_label.text() == "待命"
    assert window.detail_label.text() == "未开始同步"
    assert window.summary_label.text() == "暂无最近一次同步摘要"
    assert window.source_label.text() == "解析来源: -"

    window.close()
    app.quit()
