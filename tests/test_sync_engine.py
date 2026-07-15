from dataclasses import dataclass
from pathlib import Path

from video2local.archive import ArchiveManager
from video2local.domain import SkippedSyncItem, SourceType, SyncProgress, VideoMetadata
from video2local.sync_engine import SyncEngine


@dataclass
class FakeDownloader:
    downloads: list[str]

    def download(
        self,
        metadata: VideoMetadata,
        target_dir: Path,
        cookies_file: Path | None = None,
    ) -> tuple[str, str]:
        self.downloads.append(metadata.video_id)
        return ("mp4", str(target_dir / f"{metadata.title} [{metadata.video_id}].mp4"))


def test_sync_engine_skips_existing_video_and_downloads_new_one(tmp_path: Path) -> None:
    downloader = FakeDownloader(downloads=[])
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=archive)
    videos = [
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735001",
            title="旧视频",
            author_name="张三",
            page_url="https://www.douyin.com/video/735001",
            download_url="https://www.douyin.com/video/735001",
        ),
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735002",
            title="新视频",
            author_name="张三",
            page_url="https://www.douyin.com/video/735002",
            download_url="https://www.douyin.com/video/735002",
        ),
    ]
    existing_path = archive.build_target_path(videos[0], "mp4")
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("existing", encoding="utf-8")

    summary = engine.sync_items(videos)

    assert summary.discovered_count == 2
    assert summary.skipped_count == 1
    assert summary.downloaded_count == 1
    assert downloader.downloads == ["735002"]


def test_sync_engine_reports_progress_for_each_processed_item(tmp_path: Path) -> None:
    downloader = FakeDownloader(downloads=[])
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=archive)
    events: list[SyncProgress] = []
    videos = [
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735001",
            title="旧视频",
            author_name="张三",
            page_url="https://www.douyin.com/video/735001",
            download_url="https://www.douyin.com/video/735001",
        ),
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735002",
            title="新视频",
            author_name="张三",
            page_url="https://www.douyin.com/video/735002",
            download_url="https://www.douyin.com/video/735002",
        ),
    ]
    existing_path = archive.build_target_path(videos[0], "mp4")
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("existing", encoding="utf-8")

    engine.sync_items(videos, progress_callback=events.append)

    assert len(events) == 2
    assert events[0].processed_count == 1
    assert events[0].skipped_count == 1
    assert events[0].current_video_id == "735001"
    assert events[1].processed_count == 2
    assert events[1].downloaded_count == 1
    assert events[1].current_video_id == "735002"


def test_sync_engine_stops_after_current_item_when_requested(tmp_path: Path) -> None:
    @dataclass
    class StoppableDownloader:
        downloads: list[str]
        engine: SyncEngine | None = None

        def download(
            self,
            metadata: VideoMetadata,
            target_dir: Path,
            cookies_file: Path | None = None,
        ) -> tuple[str, str]:
            self.downloads.append(metadata.video_id)
            if self.engine is not None:
                self.engine.request_stop()
            return ("mp4", str(target_dir / f"{metadata.title} [{metadata.video_id}].mp4"))

    downloader = StoppableDownloader(downloads=[])
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=archive)
    downloader.engine = engine
    videos = [
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735010",
            title="第一条",
            author_name="张三",
            page_url="https://www.douyin.com/video/735010",
            download_url="https://www.douyin.com/video/735010",
        ),
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735011",
            title="第二条",
            author_name="张三",
            page_url="https://www.douyin.com/video/735011",
            download_url="https://www.douyin.com/video/735011",
        ),
    ]

    summary = engine.sync_items(videos)

    assert summary.status == "stopped"
    assert summary.discovered_count == 2
    assert summary.downloaded_count == 1
    assert summary.skipped_count == 0
    assert summary.failed_count == 0
    assert downloader.downloads == ["735010"]


def test_sync_engine_forwards_stop_request_to_active_downloader(tmp_path: Path) -> None:
    @dataclass
    class CancellableDownloader:
        stop_requested: bool = False

        def request_stop(self) -> None:
            self.stop_requested = True

    downloader = CancellableDownloader()
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=ArchiveManager(download_root=tmp_path))

    engine.request_stop()

    assert downloader.stop_requested is True


def test_sync_engine_records_failed_video_and_continues(tmp_path: Path) -> None:
    @dataclass
    class FlakyDownloader:
        downloads: list[str]

        def download(
            self,
            metadata: VideoMetadata,
            target_dir: Path,
            cookies_file: Path | None = None,
        ) -> tuple[str, str]:
            self.downloads.append(metadata.video_id)
            if metadata.video_id == "735020":
                raise RuntimeError("network down")
            return ("mp4", str(target_dir / f"{metadata.title} [{metadata.video_id}].mp4"))

    downloader = FlakyDownloader(downloads=[])
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=archive)
    videos = [
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735020",
            title="失败条目",
            author_name="张三",
            page_url="https://www.douyin.com/video/735020",
            download_url="https://www.douyin.com/video/735020",
        ),
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735021",
            title="成功条目",
            author_name="张三",
            page_url="https://www.douyin.com/video/735021",
            download_url="https://www.douyin.com/video/735021",
        ),
    ]

    summary = engine.sync_items(videos)

    assert summary.failed_count == 1
    assert summary.downloaded_count == 1


def test_sync_engine_retries_failed_video_before_marking_success(tmp_path: Path) -> None:
    @dataclass
    class RetryDownloader:
        attempts: dict[str, int]

        def download(
            self,
            metadata: VideoMetadata,
            target_dir: Path,
            cookies_file: Path | None = None,
        ) -> tuple[str, str]:
            count = self.attempts.get(metadata.video_id, 0) + 1
            self.attempts[metadata.video_id] = count
            if metadata.video_id == "735030" and count < 3:
                raise RuntimeError("temporary error")
            return ("mp4", str(target_dir / f"{metadata.title}+{metadata.video_id}.mp4"))

    downloader = RetryDownloader(attempts={})
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=archive)
    videos = [
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735030",
            title="需要重试",
            author_name="张三",
            page_url="https://www.douyin.com/video/735030",
            download_url="https://www.douyin.com/video/735030",
        ),
    ]

    summary = engine.sync_items(videos, retry_count=2)

    assert summary.downloaded_count == 1
    assert summary.failed_count == 0
    assert downloader.attempts["735030"] == 3


def test_sync_engine_exports_result_report(tmp_path: Path) -> None:
    @dataclass
    class MixedDownloader:
        def download(
            self,
            metadata: VideoMetadata,
            target_dir: Path,
            cookies_file: Path | None = None,
        ) -> tuple[str, str]:
            if metadata.video_id == "735041":
                raise RuntimeError("network down")
            return ("mp4", str(target_dir / f"{metadata.title}+{metadata.video_id}.mp4"))

    downloader = MixedDownloader()
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=archive)
    videos = [
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735040",
            title="成功条目",
            author_name="张三",
            page_url="https://www.douyin.com/video/735040",
            download_url="https://www.douyin.com/video/735040",
        ),
        VideoMetadata(
            platform="douyin",
            source_type=SourceType.FAVORITES,
            video_id="735041",
            title="失败条目",
            author_name="张三",
            page_url="https://www.douyin.com/video/735041",
            download_url="https://www.douyin.com/video/735041",
        ),
    ]

    summary = engine.sync_items(videos, report_dir=tmp_path / "reports")

    assert summary.report_path is not None
    report_text = Path(summary.report_path).read_text(encoding="utf-8")
    assert "735040" in report_text
    assert "downloaded" in report_text
    assert "735041" in report_text
    assert "failed" in report_text


def test_sync_engine_skips_unavailable_item_and_records_its_page_url(tmp_path: Path) -> None:
    downloader = FakeDownloader(downloads=[])
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=None, downloader=downloader, archive_manager=archive)
    unavailable = SkippedSyncItem(
        platform="bilibili",
        source_type=SourceType.FAVORITES,
        video_id="BV1expired",
        page_url="https://www.bilibili.com/video/BV1expired",
        error_message="视频已失效、删除或当前账号无权访问。原始错误: HTTP Error 404",
        stage="sync_metadata",
    )
    normal = VideoMetadata(
        platform="bilibili",
        source_type=SourceType.FAVORITES,
        video_id="BV1normal",
        title="正常视频",
        author_name="测试UP",
        page_url="https://www.bilibili.com/video/BV1normal",
        download_url="https://www.bilibili.com/video/BV1normal",
    )

    summary = engine.sync_items([unavailable, normal], report_dir=tmp_path)

    assert summary.skipped_count == 1
    assert summary.downloaded_count == 1
    assert summary.report_path is not None
    report_text = Path(summary.report_path).read_text(encoding="utf-8")
    assert "BV1expired" in report_text
    assert "页面链接: https://www.bilibili.com/video/BV1expired" in report_text
    assert "错误详情: 视频已失效、删除或当前账号无权访问" in report_text
