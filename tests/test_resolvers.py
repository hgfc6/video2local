from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from video2local.browser import DouyinPublicSession, DouyinSignedSession, KukutoolSession
from video2local.config import AppSettings
from video2local.resolvers import KukutoolResolver, NativeDouyinResolver, ResolverChain, SharePayloadResolution


@dataclass
class FakeResolver:
    provider_id: str
    result: SharePayloadResolution | None = None
    error: Exception | None = None
    called: int = 0

    def resolve(self, share_url: str) -> SharePayloadResolution:
        self.called += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_resolver_chain_uses_next_resolver_after_failure() -> None:
    first = FakeResolver(provider_id="native", error=RuntimeError("native failed"))
    second = FakeResolver(
        provider_id="third_party",
        result=SharePayloadResolution(
            provider_id="third_party",
            source_url="https://v.douyin.com/5MF6Y_tP8nk/",
            canonical_url="https://www.douyin.com/video/7651428709099242127",
            payload={"aweme_detail": {"aweme_id": "7651428709099242127"}},
        ),
    )
    chain = ResolverChain([first, second])

    result = chain.resolve("https://v.douyin.com/5MF6Y_tP8nk/")

    assert first.called == 1
    assert second.called == 1
    assert result.provider_id == "third_party"


def test_native_douyin_resolver_prefers_signed_session_before_public_fallback(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    resolver = NativeDouyinResolver(
        settings=settings,
        signed_session=DouyinSignedSession(),
        public_session=DouyinPublicSession(),
    )
    signed_payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
        }
    }

    with patch(
        "video2local.resolvers.DouyinSignedSession.fetch_share_aweme_detail",
        return_value=("https://www.douyin.com/video/7651428709099242127", signed_payload),
    ) as signed_fetch_mock:
        with patch("video2local.resolvers.DouyinPublicSession.fetch_share_aweme_detail") as public_fetch_mock:
            result = resolver.resolve("https://v.douyin.com/5MF6Y_tP8nk/")

    signed_fetch_mock.assert_called_once()
    public_fetch_mock.assert_not_called()
    assert result.provider_id == "native"
    assert result.payload == signed_payload


def test_native_douyin_resolver_falls_back_to_public_after_signed_retries(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    resolver = NativeDouyinResolver(
        settings=settings,
        signed_session=DouyinSignedSession(),
        public_session=DouyinPublicSession(),
    )
    public_payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
        }
    }

    with patch(
        "video2local.resolvers.DouyinSignedSession.fetch_share_aweme_detail",
        side_effect=RuntimeError("signed unavailable"),
    ) as signed_fetch_mock:
        with patch(
            "video2local.resolvers.DouyinPublicSession.fetch_share_aweme_detail",
            return_value=("https://www.douyin.com/video/7651428709099242127", public_payload),
        ) as public_fetch_mock:
            result = resolver.resolve("https://v.douyin.com/5MF6Y_tP8nk/")

    assert signed_fetch_mock.call_count == 2
    public_fetch_mock.assert_called_once()
    assert result.provider_id == "native"
    assert result.payload == public_payload


def test_kukutool_resolver_merges_kukutool_variants_with_native_metadata(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    resolver = KukutoolResolver(
        settings=settings,
        kukutool_session=KukutoolSession(),
        signed_session=DouyinSignedSession(),
        public_session=DouyinPublicSession(),
    )
    detail_payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "author": {"nickname": "香菜严选"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "1080_1_1",
                        "bit_rate": 3524000,
                        "play_addr": {
                            "url_list": ["https://cdn.example.com/native-1080.mp4"],
                        },
                    }
                ]
            },
        }
    }
    kukutool_payload = {
        "title": "",
        "type": "video",
        "url": "https://cdn.example.com/native-1080.mp4",
        "videos": [
            {
                "url": "https://cdn.example.com/native-1080.mp4",
                "video_fullinfo": [
                    {"type": "540p", "size": 2430281, "url": "https://cdn.example.com/540.mp4"},
                    {"type": "超高清", "size": 67819321, "url": "https://cdn.example.com/ultra.mp4"},
                ],
            }
        ],
    }

    with patch(
        "video2local.resolvers.KukutoolSession.parse_share_url",
        return_value=kukutool_payload,
    ) as kukutool_parse_mock:
        with patch(
            "video2local.resolvers.DouyinSignedSession.fetch_share_aweme_detail",
            return_value=("https://www.douyin.com/video/7651428709099242127", detail_payload),
        ) as signed_fetch_mock:
            result = resolver.resolve("https://v.douyin.com/5MF6Y_tP8nk/")

    kukutool_parse_mock.assert_called_once_with(
        "https://v.douyin.com/5MF6Y_tP8nk/",
        base_url=settings.share_resolvers.kukutool_base_url,
    )
    signed_fetch_mock.assert_called_once()
    assert result.provider_id == "kukutool"
    assert result.canonical_url == "https://www.douyin.com/video/7651428709099242127"
    assert result.payload["aweme_detail"]["author"]["nickname"] == "香菜严选"
    assert result.payload["aweme_detail"]["video"]["video_fullinfo"][1]["type"] == "超高清"


def test_kukutool_variant_only_resolution_does_not_request_douyin_metadata(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    resolver = KukutoolResolver(
        settings=settings,
        kukutool_session=KukutoolSession(),
        signed_session=DouyinSignedSession(),
        public_session=DouyinPublicSession(),
    )
    kukutool_payload = {
        "url": "https://cdn.example.com/ultra.mp4",
        "videos": [{"video_fullinfo": [{"type": "超高清", "url": "https://cdn.example.com/ultra.mp4"}]}],
    }

    with patch("video2local.resolvers.KukutoolSession.parse_share_url", return_value=kukutool_payload):
        with patch("video2local.resolvers.DouyinSignedSession.fetch_share_aweme_detail") as signed_mock:
            with patch("video2local.resolvers.DouyinPublicSession.fetch_share_aweme_detail") as public_mock:
                result = resolver.resolve_variants_only("https://v.douyin.com/5MF6Y_tP8nk/")

    signed_mock.assert_not_called()
    public_mock.assert_not_called()
    assert result.payload["aweme_detail"]["video"]["video_fullinfo"][0]["type"] == "超高清"


def test_kukutool_resolver_uses_placeholder_metadata_when_native_enrichment_fails(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    resolver = KukutoolResolver(
        settings=settings,
        kukutool_session=KukutoolSession(),
        signed_session=DouyinSignedSession(),
        public_session=DouyinPublicSession(),
    )
    kukutool_payload = {
        "title": "",
        "type": "video",
        "url": "https://cdn.example.com/ultra.mp4",
        "videos": [
            {
                "url": "https://cdn.example.com/ultra.mp4",
                "video_fullinfo": [
                    {"type": "超高清", "size": 67819321, "url": "https://cdn.example.com/ultra.mp4"},
                ],
            }
        ],
    }

    with patch(
        "video2local.resolvers.KukutoolSession.parse_share_url",
        return_value=kukutool_payload,
    ):
        with patch(
            "video2local.resolvers.DouyinSignedSession.fetch_share_aweme_detail",
            side_effect=RuntimeError("signed unavailable"),
        ):
            with patch(
                "video2local.resolvers.DouyinPublicSession.fetch_share_aweme_detail",
                side_effect=RuntimeError("public unavailable"),
            ):
                result = resolver.resolve("https://v.douyin.com/5MF6Y_tP8nk/")

    assert result.provider_id == "kukutool"
    assert result.canonical_url == "https://v.douyin.com/5MF6Y_tP8nk/"
    assert result.payload["aweme_detail"]["author"]["nickname"] == "unknown"
    assert result.payload["aweme_detail"]["video"]["play_addr"]["url_list"] == ["https://cdn.example.com/ultra.mp4"]
