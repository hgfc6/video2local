import re
from urllib.parse import urlparse, urlunparse

from video2local.adapters.base import SourceDescriptor
from video2local.domain import SourceType, VideoMetadata, VideoVariant


SHARE_URL_RE = re.compile(r"https?://[^\s]+")
BILIBILI_URL_RE = re.compile(r"(?:https?:)?//(?:www\.)?bilibili\.com/video/BV[\w-]+|/video/BV[\w-]+")


class BilibiliAdapter:
    platform_name = "bilibili"

    def detect_source(self, page_url: str) -> SourceDescriptor | None:
        parsed = urlparse(page_url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        if host == "space.bilibili.com":
            if path.endswith("/favlist"):
                return SourceDescriptor(self.platform_name, SourceType.FAVORITES, page_url)
            if path.endswith("/video"):
                return SourceDescriptor(self.platform_name, SourceType.AUTHOR_VIDEOS, page_url)
        if host in {"www.bilibili.com", "bilibili.com"} and path in {"/medialist/play/favlist", "/list/favorite"}:
            return SourceDescriptor(self.platform_name, SourceType.FAVORITES, page_url)
        return None

    def collect_candidate_urls(self, html: str) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for url in BILIBILI_URL_RE.findall(html):
            normalized = self.normalize_video_url(url)
            if normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)
        return urls

    def extract_share_url(self, raw_text: str) -> str:
        for match in SHARE_URL_RE.findall(raw_text):
            cleaned = match.rstrip("，。！？!?,;:)\'\"")
            host = urlparse(cleaned).netloc.lower()
            if host == "b23.tv" or host.endswith("bilibili.com"):
                return cleaned
        raise RuntimeError("未在分享文案中找到可用的哔哩哔哩链接")

    def normalize_video_url(self, url: str) -> str:
        if url.startswith("//"):
            url = f"https:{url}"
        elif url.startswith("/"):
            url = f"https://www.bilibili.com{url}"
        parsed = urlparse(url)
        if parsed.netloc.lower() == "b23.tv":
            return url
        return urlunparse(parsed._replace(query="", fragment=""))

    def parse_candidate(self, raw_item: dict[str, str], source_type: SourceType) -> VideoMetadata:
        return VideoMetadata(
            platform=self.platform_name,
            source_type=source_type,
            video_id=raw_item["video_id"],
            title=raw_item.get("title") or raw_item["video_id"],
            author_name=raw_item.get("author_name") or "unknown",
            page_url=raw_item["page_url"],
            download_url=raw_item["page_url"],
        )

    def parse_video_info(self, payload: dict, *, source_type: SourceType, source_url: str) -> tuple[VideoMetadata, list[VideoVariant]]:
        video_id = str(payload["id"])
        page_number = int(payload.get("playlist_index") or payload.get("chapter_number") or 1)
        if page_number > 1:
            video_id = f"{video_id}-p{page_number}"
        page_url = payload.get("webpage_url") or source_url
        metadata = VideoMetadata(
            platform=self.platform_name,
            source_type=source_type,
            video_id=video_id,
            title=payload.get("title") or video_id,
            author_name=payload.get("uploader") or payload.get("channel") or "unknown",
            page_url=page_url,
            download_url=page_url,
            duration_seconds=self._duration_seconds(payload.get("duration")),
        )
        return metadata, self.parse_variants(payload)

    def parse_variants(self, payload: dict) -> list[VideoVariant]:
        formats = [item for item in payload.get("formats") or [] if isinstance(item, dict)]
        audio_formats = [item for item in formats if self._has_audio(item) and not self._has_video(item)]
        best_audio = max(audio_formats, key=self._audio_priority, default=None)
        candidates: list[VideoVariant] = []
        for item in formats:
            if not self._has_video(item):
                continue
            format_id = str(item.get("format_id") or "")
            if not format_id:
                continue
            selector = format_id
            file_size = self._file_size(item)
            if not self._has_audio(item) and best_audio is not None:
                selector = f"{format_id}+{best_audio['format_id']}"
                file_size = self._sum_sizes(file_size, self._file_size(best_audio))
            candidates.append(
                VideoVariant(
                    variant_id=f"bilibili:{selector}",
                    quality_label=self._quality_label(item),
                    codec_label=self._codec_label(str(item.get("vcodec") or "")),
                    bit_rate=self._bit_rate(item),
                    file_size=file_size,
                    width=self._int_or_none(item.get("width")),
                    height=self._int_or_none(item.get("height")),
                    download_url=str(payload.get("webpage_url") or ""),
                    format_selector=selector,
                )
            )
        deduped: dict[str, VideoVariant] = {}
        for variant in candidates:
            existing = deduped.get(variant.quality_label)
            if existing is None or self._variant_priority(variant) > self._variant_priority(existing):
                deduped[variant.quality_label] = variant
        variants = sorted(deduped.values(), key=self._variant_priority, reverse=True)
        if variants:
            first = variants[0]
            variants[0] = VideoVariant(**{**first.__dict__, "is_recommended": True})
        return variants

    def _has_video(self, item: dict) -> bool:
        return item.get("vcodec") not in (None, "none") and self._int_or_none(item.get("height")) is not None

    def _has_audio(self, item: dict) -> bool:
        return item.get("acodec") not in (None, "none")

    def _quality_label(self, item: dict) -> str:
        height = self._int_or_none(item.get("height"))
        return f"{height}p" if height else (str(item.get("format_note") or "未知"))

    def _codec_label(self, codec: str) -> str:
        normalized = codec.lower()
        if normalized.startswith(("avc", "h264")):
            return "H.264"
        if normalized.startswith(("hev", "hvc", "h265")):
            return "H.265"
        if normalized.startswith("av01"):
            return "AV1"
        return codec or "unknown"

    def _bit_rate(self, item: dict) -> int | None:
        value = item.get("tbr") or item.get("vbr") or item.get("abr")
        try:
            return round(float(value) * 1000) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _file_size(self, item: dict) -> int | None:
        return self._int_or_none(item.get("filesize") or item.get("filesize_approx"))

    def _sum_sizes(self, first: int | None, second: int | None) -> int | None:
        return first + second if first is not None and second is not None else first or second

    def _audio_priority(self, item: dict) -> tuple[int, int]:
        return (self._bit_rate(item) or 0, self._file_size(item) or 0)

    def _variant_priority(self, item: VideoVariant) -> tuple[int, int, int]:
        return (item.height or 0, item.bit_rate or 0, item.file_size or 0)

    def _duration_seconds(self, value: object) -> int | None:
        try:
            return round(float(value)) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _int_or_none(self, value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
