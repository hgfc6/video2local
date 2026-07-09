from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QScrollArea, QSplitter, QTableWidget

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
    group_titles = [group.title() for group in window.findChildren(QGroupBox)]
    assert "批量同步" in group_titles
    assert "单链接解析" in group_titles
    assert "结果预览" in group_titles
    assert "运行状态" in group_titles
    assert len(window.findChildren(QTableWidget)) == 1
    assert len(window.findChildren(QSplitter)) == 0
    assert window.height() <= 820
    scroll_areas = window.findChildren(QScrollArea)
    assert len(scroll_areas) == 1
    assert scroll_areas[0].widgetResizable() is True

    window.close()
    app.quit()


def test_main_window_keeps_sync_preview_table_scrollable() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(MainController(engine=FakeEngine()))

    assert window.results_table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.results_table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
    assert window.results_table.minimumHeight() >= 220
    assert window.results_table.wordWrap() is False

    window.close()
    app.quit()


def test_main_window_uses_shared_results_table_for_share_parse() -> None:
    app = QApplication.instance() or QApplication([])

    class ShareEngine(FakeEngine):
        def parse_share_text(self, raw_text: str):
            return type("ParseResult", (), {
                "provider_id": "kukutool",
                "metadata": type("Metadata", (), {
                    "video_id": "7651428709099242127",
                    "title": "分享视频",
                    "author_name": "香菜严选",
                })(),
                "variants": [
                    type("Variant", (), {
                        "variant_id": "ultra_1",
                        "quality_label": "超高清",
                        "codec_label": "H.265",
                        "bit_rate": 9900000,
                        "file_size": 64700000,
                        "is_recommended": True,
                    })()
                ],
            })()

    controller = MainController(engine=ShareEngine())
    window = MainWindow(controller)

    controller.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")
    controller.wait_for_sync(timeout=1.0)
    window.refresh_labels()

    headers = [window.results_table.horizontalHeaderItem(index).text() for index in range(window.results_table.columnCount())]
    assert headers == ["选择", "清晰度", "编码", "码率", "大小", "推荐"]
    assert window.results_table.rowCount() == 1
    assert window.results_table.item(0, 0).flags() & Qt.ItemIsUserCheckable
    assert window.results_table.item(0, 0).checkState() == Qt.Unchecked
    assert window.results_table.item(0, 1).text() == "超高清"

    window.close()
    app.quit()


def test_main_window_downloads_checked_share_variant() -> None:
    app = QApplication.instance() or QApplication([])

    class ShareEngine(FakeEngine):
        downloaded_variant_id: str | None = None

        def parse_share_text(self, raw_text: str):
            return type("ParseResult", (), {
                "provider_id": "kukutool",
                "metadata": type("Metadata", (), {
                    "video_id": "7651428709099242127",
                    "title": "分享视频",
                    "author_name": "香菜严选",
                })(),
                "variants": [
                    type("Variant", (), {
                        "variant_id": "1080_1",
                        "quality_label": "1080p",
                        "codec_label": "H.264",
                        "bit_rate": 3609000,
                        "file_size": 3640000,
                        "is_recommended": False,
                    })(),
                    type("Variant", (), {
                        "variant_id": "ultra_1",
                        "quality_label": "超高清",
                        "codec_label": "H.265",
                        "bit_rate": 9900000,
                        "file_size": 64700000,
                        "is_recommended": True,
                    })(),
                ],
            })()

        def download_share_variant(self, parse_result, variant_id: str):
            self.downloaded_variant_id = variant_id
            return type("DownloadResult", (), {"local_path": "downloads/分享视频-7651428709099242127-超高清.mp4"})()

    engine = ShareEngine()
    controller = MainController(engine=engine)
    window = MainWindow(controller)

    controller.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")
    controller.wait_for_sync(timeout=1.0)
    window.refresh_labels()
    window.results_table.item(1, 0).setCheckState(Qt.Checked)

    window.handle_download_share()
    controller.wait_for_sync(timeout=1.0)

    assert engine.downloaded_variant_id == "ultra_1"

    window.close()
    app.quit()
