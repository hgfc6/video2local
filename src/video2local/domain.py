from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video2local.adapters.base import SourceDescriptor


class SourceType(StrEnum):
    FAVORITES = "favorites"
    AUTHOR_VIDEOS = "author_videos"
    SHARE_LINK = "share_link"


class SyncRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class SyncQualityStrategy(StrEnum):
    BEST_AVAILABLE = "best_available"
    PREFER_ULTRA = "prefer_ultra"
    PREFER_1080P = "prefer_1080p"


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


@dataclass(frozen=True)
class VideoVariant:
    variant_id: str
    quality_label: str
    codec_label: str
    bit_rate: int | None
    file_size: int | None
    width: int | None
    height: int | None
    download_url: str
    is_recommended: bool = False


@dataclass(frozen=True)
class ShareParseResult:
    provider_id: str
    source_url: str
    canonical_url: str
    metadata: VideoMetadata
    variants: list[VideoVariant]


@dataclass(frozen=True)
class ShareVariantDownloadResult:
    metadata: VideoMetadata
    variant: VideoVariant
    local_path: str


@dataclass(frozen=True)
class SyncPreviewItem:
    provider_id: str
    metadata: VideoMetadata
    selected_quality_label: str | None
    selected_file_size: int | None


@dataclass(frozen=True)
class SyncPreviewResult:
    source: "SourceDescriptor"
    items: list[SyncPreviewItem]
