import sqlite3
from pathlib import Path

from video2local.domain import SourceType, SyncRunStatus, VideoMetadata

ALLOWED_SOURCE_TYPES = tuple(source_type.value for source_type in SourceType)
DOWNLOADED_STATUS = "downloaded"
SKIPPED_STATUS = "skipped_existing"
FAILED_STATUS = "failed"
ALLOWED_DOWNLOAD_STATUSES = (DOWNLOADED_STATUS, SKIPPED_STATUS, FAILED_STATUS)
ALLOWED_SOURCE_TYPES_SQL = ", ".join(f"'{source_type}'" for source_type in ALLOWED_SOURCE_TYPES)
ALLOWED_DOWNLOAD_STATUSES_SQL = ", ".join(f"'{status}'" for status in ALLOWED_DOWNLOAD_STATUSES)
ALLOWED_SYNC_STATUSES = tuple(status.value for status in SyncRunStatus)
ALLOWED_SYNC_STATUSES_SQL = ", ".join(f"'{status}'" for status in ALLOWED_SYNC_STATUSES)
VIDEO_COLUMNS = (
    ("source_type", f"text not null default '{SourceType.FAVORITES.value}' check(source_type in ({ALLOWED_SOURCE_TYPES_SQL}))"),
    ("downloaded_at", "text"),
    ("file_size", "integer"),
    ("duration_seconds", "integer"),
    ("error_message", "text"),
)
SYNC_RUN_COLUMNS = (
    ("discovered_count", "integer not null default 0"),
    ("downloaded_count", "integer not null default 0"),
    ("skipped_count", "integer not null default 0"),
    ("failed_count", "integer not null default 0"),
    ("error_message", "text"),
    ("started_at", "text not null default current_timestamp"),
    ("ended_at", "text"),
)


class VideoRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                f"""
                create table if not exists videos (
                    id integer primary key,
                    platform text not null,
                    video_id text not null,
                    source_type text not null check(source_type in ({ALLOWED_SOURCE_TYPES_SQL})),
                    author_name text not null,
                    title text,
                    page_url text not null,
                    download_url text not null,
                    local_path text,
                    file_ext text,
                    downloaded_at text,
                    file_size integer,
                    duration_seconds integer,
                    error_message text,
                    download_status text not null check(download_status in ({ALLOWED_DOWNLOAD_STATUSES_SQL})),
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp,
                    unique(platform, video_id)
                )
                """
            )
            conn.execute(
                f"""
                create table if not exists sync_runs (
                    id integer primary key,
                    platform text not null,
                    status text not null check(status in ({ALLOWED_SYNC_STATUSES_SQL})),
                    discovered_count integer not null default 0,
                    downloaded_count integer not null default 0,
                    skipped_count integer not null default 0,
                    failed_count integer not null default 0,
                    error_message text,
                    started_at text not null default current_timestamp,
                    ended_at text
                )
                """
            )
            self._ensure_columns(conn, "videos", VIDEO_COLUMNS)
            self._ensure_columns(conn, "sync_runs", SYNC_RUN_COLUMNS)

    def _ensure_columns(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        expected_columns: tuple[tuple[str, str], ...],
    ) -> None:
        existing_columns = {
            row[1]
            for row in conn.execute(f"pragma table_info({table_name})").fetchall()
        }
        for column_name, column_sql in expected_columns:
            if column_name in existing_columns:
                continue
            conn.execute(f"alter table {table_name} add column {column_name} {column_sql}")

    def upsert_downloaded_video(
        self,
        metadata: VideoMetadata,
        local_path: str,
        file_ext: str,
        file_size: int | None = None,
    ) -> None:
        self._upsert_video_status(
            metadata=metadata,
            local_path=local_path,
            file_ext=file_ext,
            downloaded_at="current_timestamp",
            file_size=file_size,
            duration_seconds=metadata.duration_seconds,
            download_status=DOWNLOADED_STATUS,
            error_message=None,
        )

    def record_skipped_video(self, metadata: VideoMetadata) -> None:
        self._upsert_video_status(
            metadata=metadata,
            local_path=None,
            file_ext=None,
            downloaded_at=None,
            file_size=None,
            duration_seconds=metadata.duration_seconds,
            download_status=SKIPPED_STATUS,
            error_message=None,
        )

    def record_failed_video(self, metadata: VideoMetadata, error_message: str) -> None:
        self._upsert_video_status(
            metadata=metadata,
            local_path=None,
            file_ext=None,
            downloaded_at=None,
            file_size=None,
            duration_seconds=metadata.duration_seconds,
            download_status=FAILED_STATUS,
            error_message=error_message,
        )

    def _upsert_video_status(
        self,
        *,
        metadata: VideoMetadata,
        local_path: str | None,
        file_ext: str | None,
        downloaded_at: str | None,
        file_size: int | None,
        duration_seconds: int | None,
        download_status: str,
        error_message: str | None,
    ) -> None:
        with sqlite3.connect(self.database_path) as conn:
            if downloaded_at == "current_timestamp":
                conn.execute(
                    """
                insert into videos (
                    platform,
                    video_id,
                    source_type,
                    author_name,
                    title,
                    page_url,
                    download_url,
                    local_path,
                    file_ext,
                    downloaded_at,
                    file_size,
                    duration_seconds,
                    error_message,
                    download_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp, ?, ?, ?, ?)
                on conflict(platform, video_id) do update set
                    source_type = excluded.source_type,
                    author_name = excluded.author_name,
                    title = excluded.title,
                    page_url = excluded.page_url,
                    download_url = excluded.download_url,
                    local_path = excluded.local_path,
                    file_ext = excluded.file_ext,
                    downloaded_at = excluded.downloaded_at,
                    file_size = excluded.file_size,
                    duration_seconds = excluded.duration_seconds,
                    error_message = excluded.error_message,
                    download_status = excluded.download_status,
                    updated_at = current_timestamp
                """,
                    (
                        metadata.platform,
                        metadata.video_id,
                        metadata.source_type.value,
                        metadata.author_name,
                        metadata.title,
                        metadata.page_url,
                        metadata.download_url,
                        local_path,
                        file_ext,
                        file_size,
                        duration_seconds,
                        error_message,
                        download_status,
                    ),
                )
                return
            conn.execute(
                """
                insert into videos (
                    platform,
                    video_id,
                    source_type,
                    author_name,
                    title,
                    page_url,
                    download_url,
                    local_path,
                    file_ext,
                    downloaded_at,
                    file_size,
                    duration_seconds,
                    error_message,
                    download_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(platform, video_id) do update set
                    source_type = excluded.source_type,
                    author_name = excluded.author_name,
                    title = excluded.title,
                    page_url = excluded.page_url,
                    download_url = excluded.download_url,
                    local_path = excluded.local_path,
                    file_ext = excluded.file_ext,
                    downloaded_at = excluded.downloaded_at,
                    file_size = excluded.file_size,
                    duration_seconds = excluded.duration_seconds,
                    error_message = excluded.error_message,
                    download_status = excluded.download_status,
                    updated_at = current_timestamp
                """,
                (
                    metadata.platform,
                    metadata.video_id,
                    metadata.source_type.value,
                    metadata.author_name,
                    metadata.title,
                    metadata.page_url,
                    metadata.download_url,
                    local_path,
                    file_ext,
                    downloaded_at,
                    file_size,
                    duration_seconds,
                    error_message,
                    download_status,
                ),
            )

    def get_video(self, platform: str, video_id: str) -> sqlite3.Row | None:
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                "select * from videos where platform = ? and video_id = ?",
                (platform, video_id),
            ).fetchone()

    def has_downloaded_video(self, platform: str, video_id: str) -> bool:
        row = self.get_video(platform, video_id)
        return row is not None and row["download_status"] == DOWNLOADED_STATUS

    def create_sync_run(self, platform: str) -> int:
        with sqlite3.connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                insert into sync_runs (
                    platform,
                    status
                ) values (?, ?)
                """,
                (platform, SyncRunStatus.RUNNING.value),
            )
            return int(cursor.lastrowid)

    def finish_sync_run(
        self,
        *,
        run_id: int,
        status: str,
        discovered_count: int,
        downloaded_count: int,
        skipped_count: int,
        failed_count: int,
        error_message: str | None = None,
    ) -> None:
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                """
                update sync_runs
                set status = ?,
                    discovered_count = ?,
                    downloaded_count = ?,
                    skipped_count = ?,
                    failed_count = ?,
                    error_message = ?,
                    ended_at = current_timestamp
                where id = ?
                """,
                (
                    status,
                    discovered_count,
                    downloaded_count,
                    skipped_count,
                    failed_count,
                    error_message,
                    run_id,
                ),
            )

    def get_latest_sync_run(self) -> sqlite3.Row | None:
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                "select * from sync_runs order by id desc limit 1"
            ).fetchone()
