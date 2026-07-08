import sqlite3
from pathlib import Path

from video2local.domain import SourceType, VideoMetadata

ALLOWED_SOURCE_TYPES = tuple(source_type.value for source_type in SourceType)
DOWNLOADED_STATUS = "downloaded"
ALLOWED_SOURCE_TYPES_SQL = ", ".join(f"'{source_type}'" for source_type in ALLOWED_SOURCE_TYPES)


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
                    download_status text not null check(download_status in ('{DOWNLOADED_STATUS}')),
                    created_at text not null default current_timestamp,
                    updated_at text not null default current_timestamp,
                    unique(platform, video_id)
                )
                """
            )

    def upsert_downloaded_video(self, metadata: VideoMetadata, local_path: str, file_ext: str) -> None:
        with sqlite3.connect(self.database_path) as conn:
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
                    download_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(platform, video_id) do update set
                    source_type = excluded.source_type,
                    author_name = excluded.author_name,
                    title = excluded.title,
                    page_url = excluded.page_url,
                    download_url = excluded.download_url,
                    local_path = excluded.local_path,
                    file_ext = excluded.file_ext,
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
                    DOWNLOADED_STATUS,
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
