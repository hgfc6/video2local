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
        self.collision_policy = "skip"

    def set_collision_policy(self, policy: str) -> None:
        if policy not in {"skip", "overwrite", "timestamp"}:
            raise ValueError("不支持的同名文件处理方式")
        self.collision_policy = policy

    def request_stop(self) -> None:
        self._stop_event.set()
        request_stop = getattr(self.downloader, "request_stop", None)
        if request_stop is not None:
            request_stop()

    def sync_items(
        self,
        items: Iterable[VideoMetadata | SkippedSyncItem],
        progress_callback: Callable[[SyncProgress], None] | None = None,
        cookies_file: Path | None = None,
        retry_count: int = 0,
        report_dir: Path | None = None,
        discovered_count: int | None = None,
        collision_policy: str | None = None,
    ) -> SyncSummary:
        collision_policy = collision_policy or self.collision_policy
        if collision_policy not in {"skip", "overwrite", "timestamp"}:
            raise ValueError("不支持的同名文件处理方式")
        self._stop_event.clear()
        clear_stop_request = getattr(self.downloader, "clear_stop_request", None)
        if clear_stop_request is not None:
            clear_stop_request()
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
            expected_extension = "jpg" if metadata.media_type == "image" else "mp4"
            target_path = self.archive_manager.build_target_path(metadata, expected_extension)
            filename_stem = target_path.stem
            existing_paths = self.archive_manager.find_existing_paths(target_path.parent, filename_stem)
            if existing_paths and collision_policy == "skip":
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
                        **self._metadata_report_details(metadata, existing_paths[0]),
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

            if existing_paths and collision_policy == "overwrite":
                for existing_path in existing_paths:
                    existing_path.unlink()
            elif existing_paths and collision_policy == "timestamp":
                filename_stem = self.archive_manager.timestamped_filename_stem(filename_stem)

            target_path.parent.mkdir(parents=True, exist_ok=True)

            last_error = ""
            attempt_count = 0
            try:
                for attempt in range(retry_count + 1):
                    attempt_count = attempt + 1
                    try:
                        _, local_path = self.downloader.download(
                            metadata,
                            target_path.parent,
                            cookies_file=cookies_file,
                            **({"filename_stem": filename_stem} if collision_policy == "timestamp" else {}),
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
                                **self._metadata_report_details(metadata, Path(local_path)),
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
                if self._stop_event.is_set():
                    status = SyncRunStatus.STOPPED.value
                    break
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
                        **self._metadata_report_details(metadata),
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
        selected_provider: str = "",
        selected_quality: str = "",
        expected_file_size: str = "",
        selected_file_size: str = "",
        actual_file_size: str = "",
        download_url: str = "",
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
            "selected_provider": selected_provider,
            "selected_quality": selected_quality,
            "expected_file_size": expected_file_size,
            "selected_file_size": selected_file_size,
            "actual_file_size": actual_file_size,
            "download_url": download_url,
        }

    @staticmethod
    def _metadata_report_details(metadata: VideoMetadata, local_path: Path | None = None) -> dict[str, str]:
        actual_size = ""
        if local_path is not None and local_path.is_file():
            actual_size = str(local_path.stat().st_size)
        return {
            "selected_provider": metadata.selected_provider_id or "",
            "selected_quality": metadata.selected_quality_label or "",
            "expected_file_size": "" if metadata.expected_file_size is None else str(metadata.expected_file_size),
            "selected_file_size": "" if metadata.selected_file_size is None else str(metadata.selected_file_size),
            "actual_file_size": actual_size,
            "download_url": metadata.download_url,
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
                    f"最终解析来源: {row['selected_provider'] or '-'}",
                    f"最终清晰度: {row['selected_quality'] or '-'}",
                    f"解析版本大小: {row['selected_file_size'] or '-'}",
                    f"解析文件大小: {row['expected_file_size'] or '-'}",
                    f"实际文件大小: {row['actual_file_size'] or '-'}",
                    f"下载链接: {row['download_url'] or '-'}",
                    "",
                ]
            )
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return str(report_path)
