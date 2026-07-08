from dataclasses import dataclass

from video2local.adapters.base import SourceDescriptor
from video2local.domain import SourceType
from video2local.ui.controller import MainController


@dataclass
class FakeEngine:
    started: bool = False
    launched: bool = False

    def launch_chrome(self) -> None:
        self.launched = True

    def start_sync(self) -> SourceDescriptor:
        self.started = True
        return SourceDescriptor(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            page_url="https://www.douyin.com/user/self?showTab=favorite_collection",
        )


def test_main_controller_updates_status_when_sync_starts() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.start_sync()

    assert engine.started is True
    assert controller.status_text == "已识别 douyin / favorites"


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
