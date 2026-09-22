from dataclasses import dataclass
import hashlib
from urllib.request import Request, urlopen

from video2local.browser import DouyinPublicSession, DouyinSignedSession, KukutoolSession
from video2local.config import AppSettings
from video2local.domain import VideoVariant


@dataclass(frozen=True)
class SharePayloadResolution:
    provider_id: str
    source_url: str
    canonical_url: str
    payload: dict


@dataclass
class NativeDouyinResolver:
    settings: AppSettings
    signed_session: DouyinSignedSession
    public_session: DouyinPublicSession
    provider_id: str = "native"
    signed_attempts: int = 2

    def resolve(self, share_url: str) -> SharePayloadResolution:
        signed_error: Exception | None = None
        for _ in range(self.signed_attempts):
            try:
                canonical_url, payload = self.signed_session.fetch_share_aweme_detail(share_url)
                return SharePayloadResolution(
                    provider_id=self.provider_id,
                    source_url=share_url,
                    canonical_url=canonical_url,
                    payload=payload,
                )
            except Exception as exc:
                signed_error = exc
        try:
            canonical_url, payload = self.public_session.fetch_share_aweme_detail(share_url)
            return SharePayloadResolution(
                provider_id=self.provider_id,
                source_url=share_url,
                canonical_url=canonical_url,
                payload=payload,
            )
        except Exception:
            if signed_error is not None:
                raise signed_error
            raise


@dataclass
class CdnDouyinResolver:
    """Resolve Douyin's original-quality CDN stream from native video metadata."""

    settings: AppSettings
    provider_id: str = "cdn"

    def resolve_variants_from_payload(self, payload: dict) -> list[VideoVariant]:
        detail = payload.get("aweme_detail") or {}
        video = detail.get("video") or {}
        play_addr = video.get("play_addr") or {}
        video_uri = play_addr.get("uri")
        if not video_uri or str(video_uri).startswith("http"):
            raise RuntimeError("抖音详情中未找到 CDN 原始视频 URI")

        play_url = (
            "https://aweme.snssdk.com/aweme/v1/play/"
            f"?video_id={video_uri}&ratio=default&line=0"
        )
        request = Request(
            play_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                    "Mobile/15E148 Safari/604.1"
                ),
                "Referer": "https://www.douyin.com/",
            },
            method="HEAD",
        )
        try:
            with urlopen(request, timeout=30) as response:
                file_size = self._parse_file_size(response.headers.get("Content-Length"))
                download_url = response.geturl()
        except Exception as exc:
            raise RuntimeError(f"CDN 原始高码率探测失败: {exc}") from exc

        if not download_url or "douyinvod.com" not in download_url:
            raise RuntimeError("CDN 原始高码率探测未返回 douyinvod.com 下载地址")
        if file_size is None:
            raise RuntimeError("CDN 原始高码率探测未返回文件大小")
        return [
            VideoVariant(
                variant_id="cdn_default",
                quality_label="原始高码率",
                codec_label="unknown",
                bit_rate=None,
                file_size=file_size,
                width=None,
                height=None,
                download_url=download_url,
                provider_id=self.provider_id,
            )
        ]

    @staticmethod
    def _parse_file_size(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            size = int(value)
        except ValueError:
            return None
        return size if size > 0 else None


@dataclass
class KukutoolResolver:
    settings: AppSettings
    kukutool_session: KukutoolSession
    provider_id: str = "kukutool"

    def resolve(self, share_url: str) -> SharePayloadResolution:
        """Resolve only through the already-open Kukutool page.

        Native metadata enrichment opens a separate temporary Chrome page and is
        intentionally excluded here so it cannot interrupt third-party parsing.
        """
        kukutool_payload = self.kukutool_session.parse_share_url(
            share_url,
            base_url=self.settings.share_resolvers.kukutool_base_url,
        )
        return self._build_variants_only_resolution(share_url, kukutool_payload)

    def resolve_variants_only(self, share_url: str) -> SharePayloadResolution:
        """Fetch third-party variants without duplicating native metadata requests."""
        kukutool_payload = self.kukutool_session.parse_share_url(
            share_url,
            base_url=self.settings.share_resolvers.kukutool_base_url,
        )
        return self._build_variants_only_resolution(share_url, kukutool_payload)

    def resolve_variants_only_many(
        self,
        share_urls: list[str],
    ) -> dict[str, SharePayloadResolution | Exception]:
        results: dict[str, SharePayloadResolution | Exception] = {}
        for share_url, payload in zip(
            share_urls,
            self.kukutool_session.parse_share_urls(
                share_urls,
                base_url=self.settings.share_resolvers.kukutool_base_url,
            ),
            strict=True,
        ):
            if isinstance(payload, Exception):
                results[share_url] = payload
                continue
            results[share_url] = self._build_variants_only_resolution(share_url, payload)
        return results

    def _build_variants_only_resolution(self, share_url: str, kukutool_payload: dict) -> SharePayloadResolution:
        payload = self._build_placeholder_payload(
            share_url=share_url,
            canonical_url=share_url,
            kukutool_payload=kukutool_payload,
        )
        return SharePayloadResolution(
            provider_id=self.provider_id,
            source_url=share_url,
            canonical_url=share_url,
            payload=payload,
        )

    def _build_placeholder_payload(
        self,
        *,
        share_url: str,
        canonical_url: str,
        kukutool_payload: dict,
    ) -> dict:
        best_url = kukutool_payload.get("url")
        video_entries = []
        videos = kukutool_payload.get("videos") or []
        if videos and isinstance(videos[0], dict):
            video_entries = list(videos[0].get("video_fullinfo") or [])
            if best_url is None:
                best_url = next((item.get("url") for item in video_entries if item.get("url")), None)
        stable_id = hashlib.sha1(share_url.encode("utf-8")).hexdigest()[:16]
        return {
            "aweme_detail": {
                "aweme_id": stable_id,
                "desc": stable_id,
                "author": {"nickname": "unknown"},
                "video": {
                    "video_fullinfo": video_entries,
                    "play_addr": {"url_list": [best_url]} if best_url else {"url_list": [canonical_url]},
                    "download_addr": {"url_list": [best_url]} if best_url else {"url_list": [canonical_url]},
                },
            }
        }


@dataclass
class ResolverChain:
    resolvers: list[object]

    def resolve(self, share_url: str) -> SharePayloadResolution:
        last_error: Exception | None = None
        errors: list[str] = []
        for resolver in self.resolvers:
            try:
                return resolver.resolve(share_url)
            except Exception as exc:
                last_error = exc
                provider_id = getattr(resolver, "provider_id", type(resolver).__name__)
                errors.append(f"{provider_id}: {exc}")
        if last_error is not None:
            raise RuntimeError("所有已选解析来源均失败: " + "；".join(errors)) from last_error
        raise RuntimeError("未配置可用的分享链接解析器")
