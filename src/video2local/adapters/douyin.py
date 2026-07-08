from video2local.adapters.base import SourceDescriptor
from video2local.domain import SourceType, VideoMetadata


class DouyinAdapter:
    platform_name = "douyin"

    def detect_source(self, page_url: str) -> SourceDescriptor | None:
        if "douyin.com" not in page_url:
            return None
        if "favorite" in page_url:
            return SourceDescriptor(
                platform=self.platform_name,
                source_type=SourceType.FAVORITES,
                page_url=page_url,
            )
        if "showTab=post" in page_url:
            return SourceDescriptor(
                platform=self.platform_name,
                source_type=SourceType.AUTHOR_VIDEOS,
                page_url=page_url,
            )
        return None

    def parse_candidate(self, raw_item: dict[str, str], source_type: SourceType) -> VideoMetadata:
        video_id = raw_item["video_id"]
        title = raw_item.get("title") or video_id
        author_name = raw_item["author_name"]
        page_url = raw_item["page_url"]
        return VideoMetadata(
            platform=self.platform_name,
            source_type=source_type,
            video_id=video_id,
            title=title,
            author_name=author_name,
            page_url=page_url,
            download_url=page_url,
        )
