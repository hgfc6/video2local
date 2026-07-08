from dataclasses import dataclass
from typing import Callable, Iterable

from video2local.archive import ArchiveManager
from video2local.domain import SyncProgress, VideoMetadata


@dataclass(frozen=True)
class SyncSummary:
    discovered_count: int = 0
    downloaded_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


class SyncEngine:
    def __init__(self, repository, downloader, archive_manager: ArchiveManager) -> None:
        self.repository = repository
        self.downloader = downloader
        self.archive_manager = archive_manager

    def sync_items(
        self,
        items: Iterable[VideoMetadata],
        progress_callback: Callable[[SyncProgress], None] | None = None,
    ) -> SyncSummary:
        items = list(items)
        downloaded_count = 0
        skipped_count = 0
        failed_count = 0

        for index, metadata in enumerate(items, start=1):
            if self.repository.has_downloaded_video(metadata.platform, metadata.video_id):
                skipped_count += 1
                if progress_callback is not None:
                    progress_callback(
                        SyncProgress(
                            discovered_count=len(items),
                            processed_count=index,
                            downloaded_count=downloaded_count,
                            skipped_count=skipped_count,
                            failed_count=failed_count,
                            current_video_id=metadata.video_id,
                            current_title=metadata.title,
                            current_author_name=metadata.author_name,
                        )
                    )
                continue

            target_path = self.archive_manager.build_target_path(metadata, "mp4")
            target_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                file_ext, local_path = self.downloader.download(metadata, target_path.parent)
                self.repository.upsert_downloaded_video(metadata, local_path=local_path, file_ext=file_ext)
                downloaded_count += 1
            except Exception:
                failed_count += 1
            if progress_callback is not None:
                progress_callback(
                    SyncProgress(
                        discovered_count=len(items),
                        processed_count=index,
                        downloaded_count=downloaded_count,
                        skipped_count=skipped_count,
                        failed_count=failed_count,
                        current_video_id=metadata.video_id,
                        current_title=metadata.title,
                        current_author_name=metadata.author_name,
                    )
                )

        return SyncSummary(
            discovered_count=len(items),
            downloaded_count=downloaded_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )
