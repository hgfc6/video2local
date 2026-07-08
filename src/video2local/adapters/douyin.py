import re

from video2local.adapters.base import SourceDescriptor
from video2local.domain import SourceType, VideoMetadata

VIDEO_URL_RE = re.compile(r'https://www\.douyin\.com/video/\d+|/video/\d+')


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

    def collect_candidate_urls(self, html: str) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for match in VIDEO_URL_RE.findall(html):
            url = match if match.startswith("http") else f"https://www.douyin.com{match}"
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

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
