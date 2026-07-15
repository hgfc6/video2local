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
    previewed: bool = False
    flat_output: bool = False
    resolver_sources: tuple[str, ...] = ("native", "kukutool")
    active_platform: str | None = None

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

    def preview_sync(self):
        self.previewed = True
        return type("PreviewResult", (), {
            "source": SourceDescriptor(
                platform="douyin",
                source_type=SourceType.FAVORITES,
                page_url="https://www.douyin.com/user/self?showTab=favorite_collection",
            ),
            "items": [
                type("PreviewItem", (), {
                    "metadata": type("Metadata", (), {
                        "video_id": "735001",
                        "title": "海边夜景",
                        "author_name": "作者甲",
                    })(),
                    "provider_summary": "kukutool + native",
                    "variant_summary": "超高清(64.67 MB), 2160p(5.16 MB), 1080p(3.64 MB)",
                    "selected_quality_label": "超高清",
                    "selected_file_size": 67819321,
                })()
            ],
        })()

    def set_flat_output(self, enabled: bool) -> None:
        self.flat_output = enabled

    def set_resolver_sources(self, sources: tuple[str, ...]) -> None:
        self.resolver_sources = sources

    def set_active_platform(self, platform: str) -> None:
        self.active_platform = platform


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
    assert controller.detail_text == "请在专用 Chrome 中登录并打开受支持的平台内容页"


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


def test_main_controller_can_toggle_flat_output_mode() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.set_flat_output(True)

    assert engine.flat_output is True
    assert controller.flat_output_enabled is True


def test_main_controller_can_set_resolver_sources() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.set_resolver_sources(("native",))

    assert engine.resolver_sources == ("native",)
    assert controller.resolver_sources == ("native",)


def test_main_controller_switches_platform_and_clears_previous_results() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)
    controller.share_variants = [object()]
    controller.results_revision = 3

    controller.set_platform_mode("bilibili")

    assert engine.active_platform == "bilibili"
    assert controller.platform_mode == "bilibili"
    assert controller.share_variants == []
    assert controller.results_revision == 4
    assert "结果表已清空" in controller.summary_text


def test_main_controller_rejects_share_link_from_other_platform_workbench() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.parse_share_text("https://www.bilibili.com/video/BV1xx411c7mD")

    assert controller.status_text == "错误: 当前为抖音工作台"
    assert "切换平台工作台" in controller.detail_text


def test_main_controller_reports_preview_table_summary_after_preview() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.preview_sync()
    controller.wait_for_sync(timeout=1.0)

    assert controller.status_text == "预览完成"
    assert controller.detail_text.endswith("共预览 1 条，跳过 0 条")


def test_main_controller_can_preview_sync_items() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.preview_sync()
    controller.wait_for_sync(timeout=1.0)

    assert engine.previewed is True
    assert controller.status_text == "预览完成"
    assert "海边夜景" in controller.summary_text
    assert len(controller.sync_preview_items) == 1


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


def test_main_controller_can_parse_share_link_and_store_variants() -> None:
    @dataclass
    class Variant:
        variant_id: str
        quality_label: str
        codec_label: str
        bit_rate: int | None
        file_size: int | None

    @dataclass
    class Metadata:
        video_id: str
        title: str
        author_name: str

    @dataclass
    class ParseResult:
        provider_id: str
        source_url: str
        canonical_url: str
        metadata: Metadata
        variants: list[Variant]

    @dataclass
    class ShareEngine:
        def parse_share_text(self, raw_text: str):
            assert "v.douyin.com" in raw_text
            return ParseResult(
                provider_id="kukutool",
                source_url="https://v.douyin.com/5MF6Y_tP8nk/",
                canonical_url="https://www.douyin.com/video/7651428709099242127",
                metadata=Metadata(
                    video_id="7651428709099242127",
                    title="分享视频",
                    author_name="香菜严选",
                ),
                variants=[
                    Variant(
                        variant_id="720_1_1",
                        quality_label="720p",
                        codec_label="H.265",
                        bit_rate=1971327,
                        file_size=2086404,
                    )
                ],
            )

    controller = MainController(engine=ShareEngine())

    controller.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")
    controller.wait_for_sync(timeout=1.0)

    assert controller.status_text == "分享链接解析完成"
    assert controller.source_text == "解析来源: kukutool"
    assert controller.detail_text == "香菜严选 / 分享视频"
    assert controller.summary_text == "香菜严选 / 分享视频，已解析 1 个清晰度版本"
    assert len(controller.share_variants) == 1


def test_main_controller_can_download_selected_share_variant() -> None:
    @dataclass
    class DownloadResult:
        local_path: str

    @dataclass
    class Variant:
        variant_id: str
        quality_label: str
        codec_label: str
        bit_rate: int | None
        file_size: int | None

    @dataclass
    class Metadata:
        video_id: str
        title: str
        author_name: str

    @dataclass
    class ParseResult:
        source_url: str
        canonical_url: str
        metadata: Metadata
        variants: list[Variant]

    @dataclass
    class ShareEngine:
        downloaded_variant_id: str | None = None

        def download_share_variant(self, parse_result, variant_id: str):
            self.downloaded_variant_id = variant_id
            return DownloadResult(local_path="downloads/douyin/香菜严选/分享视频 [7651428709099242127] [720p].mp4")

    engine = ShareEngine()
    controller = MainController(engine=engine)
    controller.share_parse_result = ParseResult(
        source_url="https://v.douyin.com/5MF6Y_tP8nk/",
        canonical_url="https://www.douyin.com/video/7651428709099242127",
        metadata=Metadata(video_id="7651428709099242127", title="分享视频", author_name="香菜严选"),
        variants=[Variant(variant_id="720_1_1", quality_label="720p", codec_label="H.265", bit_rate=1971327, file_size=2086404)],
    )
    controller.share_variants = controller.share_parse_result.variants

    controller.download_share_variant("720_1_1")
    controller.wait_for_sync(timeout=1.0)

    assert engine.downloaded_variant_id == "720_1_1"
    assert controller.status_text == "分享视频下载完成"
    assert controller.summary_text.endswith("[720p].mp4")
