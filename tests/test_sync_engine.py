from dataclasses import dataclass
from pathlib import Path

from video2local.archive import ArchiveManager
from video2local.domain import SourceType, VideoMetadata
from video2local.sync_engine import SyncEngine


@dataclass
class FakeRepository:
    existing: set[tuple[str, str]]
    saved: list[tuple[str, str]]

    def has_downloaded_video(self, platform: str, video_id: str) -> bool:
        return (platform, video_id) in self.existing

    def upsert_downloaded_video(self, metadata: VideoMetadata, local_path: str, file_ext: str) -> None:
        self.saved.append((metadata.video_id, local_path))


@dataclass
class FakeDownloader:
    downloads: list[str]

    def download(self, metadata: VideoMetadata, target_dir: Path) -> tuple[str, str]:
        self.downloads.append(metadata.video_id)
        return ("mp4", str(target_dir / f"{metadata.title} [{metadata.video_id}].mp4"))


def test_sync_engine_skips_existing_video_and_downloads_new_one(tmp_path: Path) -> None:
    repo = FakeRepository(existing={("douyin", "735001")}, saved=[])
    downloader = FakeDownloader(downloads=[])
    archive = ArchiveManager(download_root=tmp_path)
    engine = SyncEngine(repository=repo, downloader=downloader, archive_manager=archive)
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

    summary = engine.sync_items(videos)

    assert summary.skipped_count == 1
    assert summary.downloaded_count == 1
    assert downloader.downloads == ["735002"]
    assert repo.saved[0][0] == "735002"
