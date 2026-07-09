from dataclasses import dataclass
from datetime import datetime
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
    report_path: str | None = None


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
        retry_count: int = 0,
        report_dir: Path | None = None,
        discovered_count: int | None = None,
    ) -> SyncSummary:
        self._stop_event.clear()
        known_discovered_count = 0 if discovered_count is None else discovered_count
        downloaded_count = 0
        skipped_count = 0
        failed_count = 0
        status = SyncRunStatus.COMPLETED.value
        report_rows: list[tuple[str, str, str, str, str, str, str, str]] = []

        processed_count = 0
        for metadata in items:
            processed_count += 1
            if self._stop_event.is_set():
                status = SyncRunStatus.STOPPED.value
                break
            target_path = self.archive_manager.build_target_path(metadata, "mp4")
            if target_path.exists():
                skipped_count += 1
                report_rows.append(
                    (
                        metadata.platform,
                        metadata.author_name,
                        metadata.video_id,
                        metadata.title or metadata.video_id,
                        "skipped",
                        str(target_path),
                        "",
                        "0",
                    )
                )
                if progress_callback is not None:
                    progress_callback(
                        SyncProgress(
                            discovered_count=max(known_discovered_count, processed_count),
                            processed_count=processed_count,
                            downloaded_count=downloaded_count,
                            skipped_count=skipped_count,
                            failed_count=failed_count,
                            current_video_id=metadata.video_id,
                            current_title=metadata.title,
                            current_author_name=metadata.author_name,
                        )
                    )
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)

            last_error = ""
            attempt_count = 0
            try:
                for attempt in range(retry_count + 1):
                    attempt_count = attempt + 1
                    try:
                        file_ext, local_path = self.downloader.download(
                            metadata,
                            target_path.parent,
                            cookies_file=cookies_file,
                        )
                        downloaded_count += 1
                        report_rows.append(
                            (
                                metadata.platform,
                                metadata.author_name,
                                metadata.video_id,
                                metadata.title or metadata.video_id,
                                "downloaded",
                                local_path,
                                "",
                                str(attempt_count),
                            )
                        )
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        if attempt >= retry_count:
                            raise
                else:
                    raise RuntimeError(last_error)
            except Exception as exc:
                failed_count += 1
                report_rows.append(
                    (
                        metadata.platform,
                        metadata.author_name,
                        metadata.video_id,
                        metadata.title or metadata.video_id,
                        "failed",
                        "",
                        str(exc),
                        str(attempt_count or 1),
                    )
                )
            if progress_callback is not None:
                    progress_callback(
                        SyncProgress(
                            discovered_count=max(known_discovered_count, processed_count),
                            processed_count=processed_count,
                            downloaded_count=downloaded_count,
                            skipped_count=skipped_count,
                            failed_count=failed_count,
                            current_video_id=metadata.video_id,
                            current_title=metadata.title,
                        current_author_name=metadata.author_name,
                        )
                )

        report_path = self._write_report(report_rows, report_dir) if report_dir is not None else None
        return SyncSummary(
            discovered_count=max(known_discovered_count, processed_count),
            downloaded_count=downloaded_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            status=status,
            report_path=report_path,
        )

    def _safe_file_size(self, local_path: str) -> int | None:
        try:
            return Path(local_path).stat().st_size
        except OSError:
            return None

    def _write_report(
        self,
        rows: list[tuple[str, str, str, str, str, str, str, str]],
        report_dir: Path,
    ) -> str:
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_path = report_dir / f"sync-report-{timestamp}.csv"
        lines = ["platform,author,video_id,title,status,local_path,error,attempts"]
        for row in rows:
            lines.append(",".join(self._csv_escape(value) for value in row))
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return str(report_path)

    def _csv_escape(self, value: str) -> str:
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
