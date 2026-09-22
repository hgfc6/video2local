import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from video2local.adapters.base import SourceDescriptor
from video2local.domain import SourceType, VideoMetadata, VideoVariant

MEDIA_URL_RE = re.compile(r'https://www\.douyin\.com/(?:video|note)/\d+|/(?:video|note)/\d+')
SHARE_URL_RE = re.compile(r"https?://[^\s]+")


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
        for match in MEDIA_URL_RE.findall(html):
            url = match if match.startswith("http") else f"https://www.douyin.com{match}"
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def extract_share_url(self, raw_text: str) -> str:
        for match in SHARE_URL_RE.findall(raw_text):
            cleaned = match.rstrip("，。！？!?,;:)'\"")
            if "douyin.com" in cleaned or "iesdouyin.com" in cleaned:
                return cleaned
        raise RuntimeError("未在分享文案中找到可用的抖音链接")

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
        author_handle = author.get("unique_id") or author.get("short_id") or None
        duration_ms = detail.get("duration")
        duration_seconds = None
        if isinstance(duration_ms, int):
            duration_seconds = duration_ms // 1000
        download_url = self._select_best_media_url(video, required=False)
        if download_url is None:
            download_url = self._select_primary_image_url(detail)
        if download_url is None:
            raise RuntimeError("抖音作品详情中未找到可下载的媒体地址")
        return VideoMetadata(
            platform=self.platform_name,
            source_type=source_type,
            video_id=video_id,
            title=title,
            author_name=author_name,
            page_url=page_url,
            download_url=download_url,
            duration_seconds=duration_seconds,
            author_handle=str(author_handle) if author_handle else None,
        )

    def parse_share_variants(self, payload: dict) -> list[VideoVariant]:
        detail = payload.get("aweme_detail") or {}
        image_variants = self._build_image_variants(detail)
        if image_variants:
            image_variants[0] = VideoVariant(**{**image_variants[0].__dict__, "is_recommended": True})
            return image_variants

        video = detail.get("video") or {}
        variants: list[VideoVariant] = []
        variants.extend(self._build_kukutool_variants(video))
        variants.extend(self._build_public_download_variants(video))
        for item in video.get("bit_rate") or []:
            play_addr = item.get("play_addr") or {}
            urls = play_addr.get("url_list") or []
            if not urls:
                continue
            width = play_addr.get("width")
            height = play_addr.get("height")
            variants.append(
                VideoVariant(
                    variant_id=str(item.get("gear_name") or len(variants)),
                    quality_label=self._build_quality_label(width=width, height=height),
                    codec_label="H.265" if item.get("is_h265") else "H.264",
                    bit_rate=item.get("bit_rate"),
                    file_size=play_addr.get("data_size"),
                    width=width,
                    height=height,
                    download_url=urls[0],
                )
            )
        deduped: dict[str, VideoVariant] = {}
        for variant in variants:
            existing = deduped.get(variant.quality_label)
            if existing is None or self._variant_priority(variant) > self._variant_priority(existing):
                deduped[variant.quality_label] = variant
        variants = list(deduped.values())
        variants.sort(
            key=lambda item: (
                self._quality_rank(item.quality_label),
                item.bit_rate or 0,
                item.file_size or 0,
            ),
            reverse=True,
        )
        if variants:
            variants[0] = VideoVariant(**{**variants[0].__dict__, "is_recommended": True})
        return variants

    def _build_kukutool_variants(self, video: dict) -> list[VideoVariant]:
        variants: list[VideoVariant] = []
        for index, item in enumerate(video.get("video_fullinfo") or []):
            download_url = item.get("url")
            quality_label = item.get("type")
            if not download_url or not quality_label:
                continue
            variants.append(
                VideoVariant(
                    variant_id=f"kukutool_{index}",
                    quality_label=str(quality_label),
                    codec_label="unknown",
                    bit_rate=None,
                    file_size=item.get("size"),
                    width=None,
                    height=None,
                    download_url=download_url,
                )
            )
        return variants

    def _select_best_media_url(self, video: dict, *, required: bool = True) -> str | None:
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

        if required:
            raise RuntimeError("抖音视频详情中未找到可下载的视频地址")
        return None

    @classmethod
    def _build_image_variants(cls, detail: dict) -> list[VideoVariant]:
        """Return original image, animated-image, and Live Photo URLs from a note."""
        candidates: list[object] = []
        for field in ("images", "image_list", "no_watermark_image_list"):
            value = detail.get(field)
            if isinstance(value, list):
                candidates.extend(value)
        image_post_info = detail.get("image_post_info") or {}
        if isinstance(image_post_info, dict):
            for field in ("images", "image_list"):
                value = image_post_info.get(field)
                if isinstance(value, list):
                    candidates.extend(value)

        variants: list[VideoVariant] = []
        seen_urls: set[str] = set()
        label_counts: dict[str, int] = {}
        for item in candidates:
            media_urls: list[tuple[str, str]] = []
            static_url = cls._image_url(item)
            if static_url is not None:
                media_urls.append(("无水印动图" if cls._is_animated_image_url(static_url) else "无水印图片", static_url))
            motion = cls._motion_url(item)
            if motion is not None and motion[0] != static_url:
                motion_url, is_animated = motion
                motion_label = "无水印动图" if is_animated else "无水印实况图"
                media_urls.append((motion_label, motion_url))
            for base_label, url in media_urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                label_counts[base_label] = label_counts.get(base_label, 0) + 1
                label_ordinal = label_counts[base_label]
                label = base_label if label_ordinal == 1 else f"{base_label} {label_ordinal}"
                ordinal = len(variants) + 1
                variants.append(
                    VideoVariant(
                        variant_id=f"native_image_{ordinal}",
                        quality_label=label,
                        codec_label="原图" if base_label != "无水印实况图" else "原始动态视频",
                        bit_rate=None,
                        file_size=None,
                        width=None,
                        height=None,
                        download_url=url,
                    )
                )
        return variants

    @classmethod
    def _select_primary_image_url(cls, detail: dict) -> str | None:
        variants = cls._build_image_variants(detail)
        return variants[0].download_url if variants else None

    @staticmethod
    def _image_url(item: object) -> str | None:
        if isinstance(item, str):
            return item if item.startswith(("http://", "https://")) else None
        if not isinstance(item, dict):
            return None
        for field in ("url_list", "origin_url_list", "download_url_list"):
            urls = item.get(field)
            if isinstance(urls, list):
                url = next((value for value in urls if isinstance(value, str) and value.startswith(("http://", "https://"))), None)
                if url is not None:
                    return url
        for field in ("origin_image", "display_image", "image"):
            nested_url = DouyinAdapter._image_url(item.get(field))
            if nested_url is not None:
                return nested_url
        return None

    @staticmethod
    def _is_animated_image_url(url: str) -> bool:
        lowered = url.lower()
        return any(marker in lowered for marker in (".gif", ".webp", "format=gif", "format=webp", "animated"))

    @classmethod
    def _motion_url(cls, item: object) -> tuple[str, bool] | None:
        if not isinstance(item, dict):
            return None
        for field in (
            "animated_url_list",
            "animated_url",
            "gif_url_list",
            "gif_url",
            "live_url_list",
            "live_url",
            "motion_url_list",
            "motion_url",
        ):
            url = cls._media_url(item.get(field))
            if url is not None:
                return url, True
        video = item.get("video")
        if not isinstance(video, dict):
            return None
        for field in ("play_addr_h264", "play_addr", "download_addr"):
            url = cls._media_url(video.get(field))
            if url is not None:
                return url, False
        url = cls._media_url(video)
        return (url, False) if url is not None else None

    @classmethod
    def _media_url(cls, item: object) -> str | None:
        if isinstance(item, str):
            return item if item.startswith(("http://", "https://")) else None
        if isinstance(item, list):
            for value in item:
                url = cls._media_url(value)
                if url is not None:
                    return url
            return None
        if not isinstance(item, dict):
            return None
        return cls._image_url(item)

    def _build_quality_label(self, *, width: int | None, height: int | None) -> str:
        short_edge = min(width, height) if width and height else (height or width)
        if short_edge is None:
            return "unknown"
        if short_edge >= 2160:
            return "2160p"
        if short_edge >= 1440:
            return "1440p"
        if short_edge >= 1080:
            return "1080p"
        if short_edge >= 960:
            return "960p"
        if short_edge >= 720:
            return "720p"
        if short_edge >= 576:
            return "576p"
        if short_edge >= 540:
            return "540p"
        if short_edge >= 480:
            return "480p"
        if short_edge >= 360:
            return "360p"
        if short_edge > 0:
            return f"{short_edge}p"
        return "unknown"

    def _build_public_download_variants(self, video: dict) -> list[VideoVariant]:
        download_addr = video.get("download_addr") or {}
        template_url = next(
            (
                url
                for url in download_addr.get("url_list") or []
                if "aweme/v1/play/?" in url
            ),
            None,
        )
        if template_url is None:
            return []
        parsed = urlparse(template_url)
        base_query = dict(parse_qs(parsed.query))
        variants: list[VideoVariant] = []
        for quality in ("540p", "720p", "1080p"):
            query = {key: values[-1] for key, values in base_query.items()}
            query["ratio"] = quality
            query["watermark"] = "0"
            variant_url = urlunparse(parsed._replace(query=urlencode(query)))
            variants.append(
                VideoVariant(
                    variant_id=f"public_{quality}",
                    quality_label=quality,
                    codec_label="H.264",
                    bit_rate=None,
                    file_size=None,
                    width=None,
                    height=None,
                    download_url=variant_url,
                )
            )
        return variants

    def _quality_rank(self, quality_label: str) -> int:
        special_ranks = {
            "原画": 12000,
            "原始": 11900,
            "超高清": 11800,
            "高清": 11700,
        }
        if quality_label in special_ranks:
            return special_ranks[quality_label]
        match = re.search(r"(\d+)", quality_label)
        return int(match.group(1)) if match else 0

    def _variant_priority(self, variant: VideoVariant) -> tuple[int, int, int]:
        return (
            0 if variant.variant_id.startswith("public_") else 1,
            self._quality_rank(variant.quality_label),
            variant.bit_rate or 0,
            variant.file_size or 0,
        )
