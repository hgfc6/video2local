from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Callable, Iterable

from video2local.archive import ArchiveManager
from video2local.domain import SkippedSyncItem, SyncProgress, SyncRunStatus, VideoMetadata


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
        items: Iterable[VideoMetadata | SkippedSyncItem],
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
        report_rows: list[dict[str, str]] = []

        processed_count = 0
        for item in items:
            processed_count += 1
            if self._stop_event.is_set():
                status = SyncRunStatus.STOPPED.value
                break
            if isinstance(item, SkippedSyncItem):
                skipped_count += 1
                report_rows.append(
                    self._report_row(
                        platform=item.platform,
                        author_name=item.author_name,
                        video_id=item.video_id,
                        title=item.title or item.video_id,
                        page_url=item.page_url,
                        status="skipped",
                        stage=item.stage,
                        error_message=item.error_message,
                        attempts="0",
                    )
                )
                self._report_progress(
                    progress_callback,
                    known_discovered_count,
                    processed_count,
                    downloaded_count,
                    skipped_count,
                    failed_count,
                    item.video_id,
                    item.title,
                    item.author_name,
                )
                continue

            metadata = item
            target_path = self.archive_manager.build_target_path(metadata, "mp4")
            if target_path.exists():
                skipped_count += 1
                report_rows.append(
                    self._report_row(
                        platform=metadata.platform,
                        author_name=metadata.author_name,
                        video_id=metadata.video_id,
                        title=metadata.title or metadata.video_id,
                        page_url=metadata.page_url,
                        status="skipped",
                        stage="download",
                        local_path=str(target_path),
                        attempts="0",
                    )
                )
                self._report_progress(
                    progress_callback,
                    known_discovered_count,
                    processed_count,
                    downloaded_count,
                    skipped_count,
                    failed_count,
                    metadata.video_id,
                    metadata.title,
                    metadata.author_name,
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
                            self._report_row(
                                platform=metadata.platform,
                                author_name=metadata.author_name,
                                video_id=metadata.video_id,
                                title=metadata.title or metadata.video_id,
                                page_url=metadata.page_url,
                                status="downloaded",
                                stage="download",
                                local_path=local_path,
                                attempts=str(attempt_count),
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
                    self._report_row(
                        platform=metadata.platform,
                        author_name=metadata.author_name,
                        video_id=metadata.video_id,
                        title=metadata.title or metadata.video_id,
                        page_url=metadata.page_url,
                        status="failed",
                        stage="download",
                        error_message=str(exc),
                        attempts=str(attempt_count or 1),
                    )
                )
            self._report_progress(
                progress_callback,
                known_discovered_count,
                processed_count,
                downloaded_count,
                skipped_count,
                failed_count,
                metadata.video_id,
                metadata.title,
                metadata.author_name,
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

    def write_skipped_items_report(self, items: list[SkippedSyncItem], report_dir: Path) -> str | None:
        if not items:
            return None
        rows = [
            self._report_row(
                platform=item.platform,
                author_name=item.author_name,
                video_id=item.video_id,
                title=item.title or item.video_id,
                page_url=item.page_url,
                status="skipped",
                stage=item.stage,
                error_message=item.error_message,
                attempts="0",
            )
            for item in items
        ]
        return self._write_report(rows, report_dir, prefix="preview-skipped")

    def _report_progress(
        self,
        callback: Callable[[SyncProgress], None] | None,
        discovered_count: int,
        processed_count: int,
        downloaded_count: int,
        skipped_count: int,
        failed_count: int,
        video_id: str,
        title: str | None,
        author_name: str,
    ) -> None:
        if callback is not None:
            callback(
                SyncProgress(
                    discovered_count=max(discovered_count, processed_count),
                    processed_count=processed_count,
                    downloaded_count=downloaded_count,
                    skipped_count=skipped_count,
                    failed_count=failed_count,
                    current_video_id=video_id,
                    current_title=title,
                    current_author_name=author_name,
                )
            )

    def _report_row(
        self,
        *,
        platform: str,
        author_name: str,
        video_id: str,
        title: str,
        page_url: str,
        status: str,
        stage: str,
        local_path: str = "",
        error_message: str = "",
        attempts: str,
    ) -> dict[str, str]:
        return {
            "platform": platform,
            "author_name": author_name,
            "video_id": video_id,
            "title": title,
            "page_url": page_url,
            "status": status,
            "stage": stage,
            "local_path": local_path,
            "error_message": error_message,
            "attempts": attempts,
        }

    def _write_report(
        self,
        rows: list[dict[str, str]],
        report_dir: Path,
        *,
        prefix: str = "sync-report",
    ) -> str:
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        report_path = report_dir / f"{prefix}-{timestamp}.txt"
        lines = ["Video2Local 批量任务报告", f"生成时间: {datetime.now().isoformat(timespec='seconds')}", ""]
        for index, row in enumerate(rows, start=1):
            lines.extend(
                [
                    f"[{index}] 状态: {row['status']}",
                    f"平台: {row['platform']}",
                    f"阶段: {row['stage']}",
                    f"作者: {row['author_name']}",
                    f"视频ID: {row['video_id']}",
                    f"标题: {row['title']}",
                    f"页面链接: {row['page_url']}",
                    f"本地文件: {row['local_path'] or '-'}",
                    f"尝试次数: {row['attempts']}",
                    f"错误详情: {row['error_message'] or '-'}",
                    "",
                ]
            )
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return str(report_path)
