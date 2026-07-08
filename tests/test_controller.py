from dataclasses import dataclass

from video2local.sync_engine import SyncSummary
from video2local.ui.controller import MainController


@dataclass
class FakeEngine:
    started: bool = False
    launched: bool = False

    def launch_chrome(self) -> None:
        self.launched = True

    def start_sync(self) -> SyncSummary:
        self.started = True
        return SyncSummary(downloaded_count=2, skipped_count=1, failed_count=0)


def test_main_controller_updates_status_when_sync_starts() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.start_sync()

    assert engine.started is True
    assert controller.status_text == "同步完成: 下载 2，跳过 1，失败 0"


def test_main_controller_updates_status_when_chrome_launches() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.launch_chrome()

    assert engine.launched is True
    assert controller.status_text == "Chrome 已启动"


def test_main_controller_shows_error_when_sync_start_fails() -> None:
    @dataclass
    class FailingEngine:
        def start_sync(self) -> None:
            raise RuntimeError("Unsupported source page")

    controller = MainController(engine=FailingEngine())

    controller.start_sync()

    assert controller.status_text == "错误: Unsupported source page"
