from dataclasses import dataclass

from video2local.adapters.base import SourceDescriptor
from video2local.domain import SyncProgress
from video2local.domain import SourceType
from video2local.sync_engine import SyncSummary
from video2local.ui.controller import MainController


@dataclass
class FakeEngine:
    started: bool = False
    launched: bool = False

    def launch_chrome(self) -> None:
        self.launched = True

    def validate_current_page(self) -> SourceDescriptor:
        return SourceDescriptor(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            page_url="https://www.douyin.com/user/self?showTab=favorite_collection",
        )

    def start_sync(self) -> SyncSummary:
        self.started = True
        self.last_progress = SyncProgress(
            discovered_count=3,
            processed_count=3,
            downloaded_count=2,
            skipped_count=1,
            failed_count=0,
            current_video_id="735003",
            current_title="海边夜景",
            current_author_name="作者甲",
        )
        return SyncSummary(discovered_count=3, downloaded_count=2, skipped_count=1, failed_count=0)


def test_main_controller_updates_status_when_sync_starts() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.start_sync()

    assert engine.started is True
    assert controller.status_text == "同步完成: 发现 3，下载 2，跳过 1，失败 0"
    assert controller.detail_text == "最后处理: 作者甲 / 海边夜景"


def test_main_controller_updates_status_when_chrome_launches() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.launch_chrome()

    assert engine.launched is True
    assert controller.status_text == "Chrome 已启动"
    assert controller.detail_text == "请在专用 Chrome 中登录并打开抖音内容源页面"


def test_main_controller_updates_status_when_page_is_supported() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.validate_current_page()

    assert controller.status_text == "已识别 douyin / favorites"
    assert controller.detail_text == "https://www.douyin.com/user/self?showTab=favorite_collection"


def test_main_controller_shows_error_when_sync_start_fails() -> None:
    @dataclass
    class FailingEngine:
        def start_sync(self) -> None:
            raise RuntimeError("Unsupported source page")

    controller = MainController(engine=FailingEngine())

    controller.start_sync()

    assert controller.status_text == "错误: Unsupported source page"
    assert controller.detail_text == "请检查当前页面是否为受支持的内容源页面"
