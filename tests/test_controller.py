from dataclasses import dataclass
from threading import Event

from video2local.adapters.base import SourceDescriptor
from video2local.domain import SyncProgress
from video2local.domain import SourceType
from video2local.sync_engine import SyncSummary
from video2local.ui.controller import MainController


@dataclass
class FakeEngine:
    started: bool = False
    launched: bool = False
    stopped: bool = False
    downloads_opened: bool = False

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
        return SyncSummary(discovered_count=3, downloaded_count=2, skipped_count=1, failed_count=0, status="completed")

    def stop_sync(self) -> None:
        self.stopped = True

    def open_downloads_dir(self) -> None:
        self.downloads_opened = True

    def get_latest_sync_run(self):
        return {
            "status": "completed",
            "discovered_count": 3,
            "downloaded_count": 2,
            "skipped_count": 1,
            "failed_count": 0,
        }


def test_main_controller_updates_status_when_sync_starts() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.start_sync()
    controller.wait_for_sync(timeout=1.0)

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
    controller.wait_for_sync(timeout=1.0)

    assert controller.status_text == "错误: Unsupported source page"
    assert controller.detail_text == "请检查当前页面是否为受支持的内容源页面"


def test_main_controller_requests_stop_without_interrupting_current_item() -> None:
    @dataclass
    class SlowEngine:
        entered: Event
        released: Event
        stopped: bool = False

        def start_sync(self) -> SyncSummary:
            self.entered.set()
            self.released.wait(timeout=1.0)
            return SyncSummary(discovered_count=1, downloaded_count=0, skipped_count=0, failed_count=0, status="stopped")

        def stop_sync(self) -> None:
            self.stopped = True

    engine = SlowEngine(entered=Event(), released=Event())
    controller = MainController(engine=engine)

    controller.start_sync()
    assert engine.entered.wait(timeout=1.0) is True

    controller.stop_sync()
    engine.released.set()
    controller.wait_for_sync(timeout=1.0)

    assert engine.stopped is True
    assert controller.status_text == "同步已停止: 发现 1，下载 0，跳过 0，失败 0"


def test_main_controller_can_open_downloads_directory() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.open_downloads_dir()

    assert engine.downloads_opened is True
    assert controller.status_text == "已打开下载目录"


def test_main_controller_can_show_latest_sync_summary() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.show_latest_summary()

    assert controller.summary_text == "最近一次同步: completed，发现 3，下载 2，跳过 1，失败 0"


def test_main_controller_polls_live_progress_while_running() -> None:
    @dataclass
    class AliveWorker:
        def is_alive(self) -> bool:
            return True

    engine = FakeEngine()
    engine.last_progress = SyncProgress(
        discovered_count=5,
        processed_count=2,
        downloaded_count=1,
        skipped_count=1,
        failed_count=0,
        current_video_id="735099",
        current_title="直播中条目",
        current_author_name="作者乙",
    )
    controller = MainController(engine=engine)
    controller._worker = AliveWorker()  # type: ignore[assignment]

    controller.poll_runtime_state()

    assert controller.status_text == "同步进行中: 已处理 2/5，下载 1，跳过 1，失败 0"
    assert controller.detail_text == "进行中: 作者乙 / 直播中条目 (2/5)"


def test_main_controller_can_run_sample_download() -> None:
    @dataclass
    class SampleResult:
        video_id: str
        title: str
        author_name: str
        local_path: str

    @dataclass
    class SampleEngine:
        sample_started: bool = False

        def download_first_visible_sample(self):
            self.sample_started = True
            return SampleResult(
                video_id="7062344670323526953",
                title="#情绪 #成长",
                author_name="h6ii",
                local_path="downloads/_smoke_test/sample.mp4",
            )

    engine = SampleEngine()
    controller = MainController(engine=engine)

    controller.download_first_visible_sample()
    controller.wait_for_sync(timeout=1.0)

    assert engine.sample_started is True
    assert controller.status_text == "样本下载完成"
    assert controller.detail_text == "h6ii / #情绪 #成长"
    assert controller.summary_text == "样本文件: downloads/_smoke_test/sample.mp4"
