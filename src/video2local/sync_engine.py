from dataclasses import dataclass
from typing import Iterable

from video2local.archive import ArchiveManager
from video2local.domain import VideoMetadata


@dataclass(frozen=True)
class SyncSummary:
    downloaded_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


class SyncEngine:
    def __init__(self, repository, downloader, archive_manager: ArchiveManager) -> None:
        self.repository = repository
        self.downloader = downloader
        self.archive_manager = archive_manager

    def sync_items(self, items: Iterable[VideoMetadata]) -> SyncSummary:
        downloaded_count = 0
        skipped_count = 0
        failed_count = 0

        for metadata in items:
            if self.repository.has_downloaded_video(metadata.platform, metadata.video_id):
                skipped_count += 1
                continue

            target_path = self.archive_manager.build_target_path(metadata, "mp4")
            target_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                file_ext, local_path = self.downloader.download(metadata, target_path.parent)
                self.repository.upsert_downloaded_video(metadata, local_path=local_path, file_ext=file_ext)
                downloaded_count += 1
            except Exception:
                failed_count += 1

        return SyncSummary(
            downloaded_count=downloaded_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )
