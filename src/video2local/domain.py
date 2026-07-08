from dataclasses import dataclass
from enum import StrEnum


class SourceType(StrEnum):
    FAVORITES = "favorites"
    AUTHOR_VIDEOS = "author_videos"


class SyncRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class VideoMetadata:
    platform: str
    source_type: SourceType
    video_id: str
    title: str | None
    author_name: str
    page_url: str
    download_url: str
    duration_seconds: int | None = None


@dataclass(frozen=True)
class SyncProgress:
    discovered_count: int
    processed_count: int
    downloaded_count: int
    skipped_count: int
    failed_count: int
    current_video_id: str
    current_title: str | None
    current_author_name: str


@dataclass(frozen=True)
class SampleDownloadResult:
    metadata: VideoMetadata
    local_path: str
