from dataclasses import dataclass
from pathlib import Path

from video2local.archive import ArchiveManager
from video2local.domain import SourceType, SyncProgress, VideoMetadata
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
