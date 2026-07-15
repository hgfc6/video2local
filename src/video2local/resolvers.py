from dataclasses import dataclass
import hashlib

from video2local.browser import DouyinPublicSession, DouyinSignedSession, KukutoolSession
from video2local.config import AppSettings


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
