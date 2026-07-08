from dataclasses import dataclass
from enum import StrEnum


class SourceType(StrEnum):
    FAVORITES = "favorites"
    AUTHOR_VIDEOS = "author_videos"


@dataclass(frozen=True)
class VideoMetadata:
    platform: str
    source_type: SourceType
    video_id: str
    title: str | None
    author_name: str
    page_url: str
    download_url: str
