from dataclasses import dataclass
from typing import Protocol

from video2local.domain import SourceType, VideoMetadata


@dataclass(frozen=True)
class SourceDescriptor:
    platform: str
    source_type: SourceType
    page_url: str


class SiteAdapter(Protocol):
    def detect_source(self, page_url: str) -> SourceDescriptor | None:
        ...

    def parse_candidate(self, raw_item: dict[str, str], source_type: SourceType) -> VideoMetadata:
        ...
