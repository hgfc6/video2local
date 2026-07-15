import re
from urllib.parse import urlparse

from video2local.domain import SourceType, VideoMetadata, VideoVariant


SHARE_URL_RE = re.compile(r"https?://[^\s]+")


class YouTubeAdapter:
    platform_name = "youtube"

    def extract_share_url(self, raw_text: str) -> str:
        for match in SHARE_URL_RE.findall(raw_text):
            cleaned = match.rstrip("，。！？!?,;:)\'\"")
            host = urlparse(cleaned).netloc.lower()
            if host in {"youtu.be", "www.youtu.be"} or host.endswith("youtube.com"):
                return cleaned
        raise RuntimeError("未在分享文案中找到可用的 YouTube 视频链接")

    def parse_video_info(
        self,
        payload: dict,
        *,
        source_url: str,
    ) -> tuple[VideoMetadata, list[VideoVariant]]:
        video_id = str(payload["id"])
        page_url = payload.get("webpage_url") or source_url
        metadata = VideoMetadata(
            platform=self.platform_name,
            source_type=SourceType.SHARE_LINK,
            video_id=video_id,
            title=payload.get("title") or video_id,
            author_name=payload.get("uploader") or payload.get("channel") or "unknown",
            page_url=page_url,
            download_url=page_url,
            duration_seconds=self._int_or_none(payload.get("duration")),
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
                    variant_id=f"youtube:{selector}",
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
            if existing is None or self._priority(variant) > self._priority(existing):
                deduped[variant.quality_label] = variant
        variants = sorted(deduped.values(), key=self._priority, reverse=True)
        if variants:
            best = variants[0]
            variants[0] = VideoVariant(**{**best.__dict__, "is_recommended": True})
        return variants

    def _has_video(self, item: dict) -> bool:
        return item.get("vcodec") not in (None, "none") and self._int_or_none(item.get("height")) is not None

    def _has_audio(self, item: dict) -> bool:
        return item.get("acodec") not in (None, "none")

    def _quality_label(self, item: dict) -> str:
        height = self._int_or_none(item.get("height"))
        fps = self._int_or_none(item.get("fps"))
        return f"{height}p{fps or ''}" if height else str(item.get("format_note") or "未知")

    def _codec_label(self, codec: str) -> str:
        normalized = codec.lower()
        if normalized.startswith(("avc", "h264")):
            return "H.264"
        if normalized.startswith(("hev", "hvc", "h265")):
            return "H.265"
        if normalized.startswith("av01"):
            return "AV1"
        if normalized.startswith("vp9"):
            return "VP9"
        return codec or "unknown"

    def _bit_rate(self, item: dict) -> int | None:
        value = item.get("tbr") or item.get("vbr") or item.get("abr")
        try:
            return round(float(value) * 1000) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _file_size(self, item: dict) -> int | None:
        return self._int_or_none(item.get("filesize") or item.get("filesize_approx"))

    def _audio_priority(self, item: dict) -> tuple[int, int]:
        return (self._bit_rate(item) or 0, self._file_size(item) or 0)

    def _priority(self, item: VideoVariant) -> tuple[int, int, int]:
        return (item.height or 0, item.bit_rate or 0, item.file_size or 0)

    def _sum_sizes(self, first: int | None, second: int | None) -> int | None:
        return first + second if first is not None and second is not None else first or second

    def _int_or_none(self, value: object) -> int | None:
        try:
            return round(float(value)) if value is not None else None
        except (TypeError, ValueError):
            return None
