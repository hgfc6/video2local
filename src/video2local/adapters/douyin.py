import re
from urllib.parse import parse_qs, urlparse

from video2local.adapters.base import SourceDescriptor
from video2local.domain import SourceType, VideoMetadata

VIDEO_URL_RE = re.compile(r'https://www\.douyin\.com/video/\d+|/video/\d+')


class DouyinAdapter:
    platform_name = "douyin"

    def detect_source(self, page_url: str) -> SourceDescriptor | None:
        if "douyin.com" not in page_url:
            return None
        parsed = urlparse(page_url)
        show_tab = parse_qs(parsed.query).get("showTab", [None])[0]
        if show_tab and "favorite" in show_tab:
            return SourceDescriptor(
                platform=self.platform_name,
                source_type=SourceType.FAVORITES,
                page_url=page_url,
            )
        if parsed.path.startswith("/user/") and show_tab in (None, "", "post"):
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

    def parse_aweme_detail(
        self,
        payload: dict,
        *,
        source_type: SourceType,
        page_url: str,
    ) -> VideoMetadata:
        detail = payload["aweme_detail"]
        author = detail.get("author") or {}
        video = detail.get("video") or {}
        video_id = str(detail["aweme_id"])
        title = detail.get("desc") or video_id
        author_name = (
            author.get("nickname")
            or author.get("unique_id")
            or author.get("short_id")
            or "unknown"
        )
        duration_ms = detail.get("duration")
        duration_seconds = None
        if isinstance(duration_ms, int):
            duration_seconds = duration_ms // 1000
        return VideoMetadata(
            platform=self.platform_name,
            source_type=source_type,
            video_id=video_id,
            title=title,
            author_name=author_name,
            page_url=page_url,
            download_url=self._select_best_media_url(video),
            duration_seconds=duration_seconds,
        )

    def _select_best_media_url(self, video: dict) -> str:
        bit_rates = video.get("bit_rate") or []
        if bit_rates:
            best_variant = max(
                bit_rates,
                key=lambda item: int(item.get("bit_rate") or 0),
            )
            best_urls = ((best_variant.get("play_addr") or {}).get("url_list")) or []
            if best_urls:
                return best_urls[0]

        for field_name in ("play_addr_h264", "play_addr", "download_addr"):
            urls = ((video.get(field_name) or {}).get("url_list")) or []
            if urls:
                return urls[0]

        raise RuntimeError("抖音视频详情中未找到可下载的视频地址")
