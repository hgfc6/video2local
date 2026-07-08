from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from video2local.archive import ArchiveManager
from video2local.domain import SyncProgress, SyncRunStatus, VideoMetadata


@dataclass(frozen=True)
class SyncSummary:
    discovered_count: int = 0
    downloaded_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    status: str = SyncRunStatus.COMPLETED.value


class SyncEngine:
    def __init__(self, repository, downloader, archive_manager: ArchiveManager) -> None:
        self.repository = repository
        self.downloader = downloader
        self.archive_manager = archive_manager
        self._stop_event = Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def sync_items(
        self,
        items: Iterable[VideoMetadata],
        progress_callback: Callable[[SyncProgress], None] | None = None,
        cookies_file: Path | None = None,
    ) -> SyncSummary:
        self._stop_event.clear()
        items = list(items)
        downloaded_count = 0
        skipped_count = 0
        failed_count = 0
        status = SyncRunStatus.COMPLETED.value

        for index, metadata in enumerate(items, start=1):
            if self._stop_event.is_set():
                status = SyncRunStatus.STOPPED.value
                break
            if self.repository.has_downloaded_video(metadata.platform, metadata.video_id):
                skipped_count += 1
                self.repository.record_skipped_video(metadata)
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
                file_ext, local_path = self.downloader.download(
                    metadata,
                    target_path.parent,
                    cookies_file=cookies_file,
                )
                self.repository.upsert_downloaded_video(
                    metadata,
                    local_path=local_path,
                    file_ext=file_ext,
                    file_size=self._safe_file_size(local_path),
                )
                downloaded_count += 1
            except Exception as exc:
                self.repository.record_failed_video(metadata, error_message=str(exc))
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
            status=status,
        )

    def _safe_file_size(self, local_path: str) -> int | None:
        try:
            return Path(local_path).stat().st_size
        except OSError:
            return None
