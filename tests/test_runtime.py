from pathlib import Path
from unittest.mock import patch
import os

from video2local.app_runtime import AppRuntime
from video2local.domain import ShareParseResult, SourceType, SyncProgress, VideoMetadata, VideoVariant
from video2local.browser import ChromeLaunchSpec
from video2local.config import AppSettings, ShareResolverSettings
from video2local.resolvers import KukutoolResolver, NativeDouyinResolver
from video2local.sync_engine import SyncSummary


def kukutool_resolver_for(runtime: AppRuntime) -> KukutoolResolver:
    return next(item for item in runtime.share_resolver.resolvers if isinstance(item, KukutoolResolver))


def test_launch_chrome_creates_directories_and_starts_process(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    launch_spec = ChromeLaunchSpec(
        executable_path=Path("C:/Chrome/chrome.exe"),
        user_data_dir=settings.paths.chrome_profile_dir,
        remote_debugging_port=9222,
    )

    with patch("video2local.app_runtime.ChromeLaunchSpec.detect", return_value=launch_spec) as detect_mock:
        with patch("video2local.app_runtime.subprocess.Popen") as popen_mock:
            runtime.launch_chrome()

    assert settings.paths.data_dir.exists()
    assert settings.paths.chrome_profile_dir.exists()
    assert settings.paths.downloads_dir.exists()
    detect_mock.assert_called_once_with(settings.paths.chrome_profile_dir)
    popen_mock.assert_called_once_with(launch_spec.to_argv())


def test_runtime_configures_native_share_resolver_only_by_default(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)

    assert [type(item) for item in runtime.share_resolver.resolvers] == [NativeDouyinResolver]


def test_runtime_prefers_kukutool_resolver_when_enabled(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
        ),
    )

    runtime = AppRuntime(settings=settings)

    assert [type(item) for item in runtime.share_resolver.resolvers] == [KukutoolResolver, NativeDouyinResolver]


def test_runtime_can_use_native_resolver_only_when_configured(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
            enabled_sources=("native",),
        ),
    )

    runtime = AppRuntime(settings=settings)

    assert [type(item) for item in runtime.share_resolver.resolvers] == [NativeDouyinResolver]


def test_runtime_can_switch_to_kukutool_only_at_runtime(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
            enabled_sources=("native", "kukutool"),
        ),
    )
    runtime = AppRuntime(settings=settings)
    cookies_path = tmp_path / "yt-dlp-cookies.txt"

    runtime.set_resolver_sources(("kukutool",))

    assert [type(item) for item in runtime.share_resolver.resolvers] == [KukutoolResolver]


def test_parse_share_text_prefers_kukutool_variants_when_enabled(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
        ),
    )
    runtime = AppRuntime(settings=settings)
    native_detail_payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "duration": 8467,
            "author": {"nickname": "香菜严选"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "1080_1_1",
                        "bit_rate": 3524000,
                        "is_h265": 0,
                        "play_addr": {
                            "data_size": 3819934,
                            "width": 1080,
                            "height": 1920,
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
                    {"type": "1080p", "size": 3819934, "url": "https://cdn.example.com/native-1080.mp4"},
                    {"type": "超高清", "size": 67819321, "url": "https://cdn.example.com/ultra.mp4"},
                ],
            }
        ],
    }

    with patch("video2local.app_runtime.KukutoolSession.parse_share_url", return_value=kukutool_payload) as kukutool_parse_mock:
        with patch(
            "video2local.app_runtime.DouyinSignedSession.fetch_share_aweme_detail",
            return_value=("https://www.douyin.com/video/7651428709099242127", native_detail_payload),
        ) as signed_fetch_mock:
            result = runtime.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")

    kukutool_parse_mock.assert_called_once()
    signed_fetch_mock.assert_called_once()
    assert result.metadata.video_id == "7651428709099242127"
    assert result.provider_id == "kukutool"
    assert result.variants[0].quality_label == "超高清"
    assert result.variants[0].provider_id == "kukutool"
    assert result.variants[0].file_size == 67819321
    assert result.variants[0].download_url == "https://cdn.example.com/ultra.mp4"


def test_start_sync_detects_supported_douyin_source(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        source = runtime.get_current_source()

    assert source is not None
    assert source.platform == "douyin"
    assert source.source_type == SourceType.FAVORITES


def test_validate_current_page_returns_supported_source(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        source = runtime.validate_current_page()

    assert source.platform == "douyin"
    assert source.source_type == SourceType.FAVORITES


def test_validate_current_page_returns_friendly_error_for_chrome_internal_page(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="chrome://intro/"):
        try:
            runtime.validate_current_page()
        except RuntimeError as exc:
            assert str(exc) == "请先在专用 Chrome 中打开受支持平台的收藏页或作者作品页"
        else:
            raise AssertionError("Expected RuntimeError for chrome internal page")


def test_validate_current_page_returns_friendly_error_for_unsupported_douyin_page(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/jingxuan"):
        try:
            runtime.validate_current_page()
        except RuntimeError as exc:
            assert str(exc) == "当前抖音页面不受支持，请先打开“我”的作品页或收藏页后再开始。当前页面: https://www.douyin.com/jingxuan"
        else:
            raise AssertionError("Expected RuntimeError for unsupported douyin page")


def test_start_sync_collects_candidates_probes_metadata_and_runs_engine(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    summary = SyncSummary(discovered_count=1, downloaded_count=1, skipped_count=0, failed_count=0)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title="演示视频",
        author_name="作者A",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://www.douyin.com/video/735001",
    )

    html_snapshots = [
        '<a href="/video/735001">video</a>',
        '<a href="/video/735001">video</a><a href="/video/735002">video2</a>',
    ]
    cookies_path = tmp_path / "cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=html_snapshots):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                    with patch.object(runtime.downloader, "probe_metadata", return_value=metadata) as probe_mock:
                        def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
                            collected = list(items)
                            assert collected == [metadata]
                            return summary

                        with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items) as sync_mock:
                            result = runtime.start_sync()

    assert result == summary
    assert probe_mock.call_count == 2
    sync_mock.assert_called_once()
    assert sync_mock.call_args.kwargs["progress_callback"] == runtime._store_progress


def test_start_sync_respects_configured_item_limit(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    runtime.set_sync_limit(1)
    summary = SyncSummary(discovered_count=1, downloaded_count=1, skipped_count=0, failed_count=0)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title="演示视频",
        author_name="作者A",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://www.douyin.com/video/735001",
    )
    html_snapshots = [
        '<a href="/video/735001">video</a><a href="/video/735002">video2</a>',
    ]
    cookies_path = tmp_path / "cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=html_snapshots):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(runtime.downloader, "probe_metadata", return_value=metadata) as probe_mock:
                    def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
                        collected = list(items)
                        assert collected == [metadata]
                        return summary

                    with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items) as sync_mock:
                        runtime.start_sync()

    probe_mock.assert_called_once()


def test_start_sync_uses_kukutool_share_resolver_sequentially_when_enabled(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
        ),
    )
    runtime = AppRuntime(settings=settings)
    summary = SyncSummary(discovered_count=2, downloaded_count=2, skipped_count=0, failed_count=0)
    html_snapshots = [
        '<a href="/video/735001">video</a><a href="/video/735002">video2</a>',
    ]
    cookies_path = tmp_path / "cookies.txt"
    resolved_urls: list[str] = []
    captured_items: list[VideoMetadata] = []
    native_payload_1 = {
        "aweme_detail": {
            "aweme_id": "735001",
            "desc": "title-735001",
            "author": {"nickname": "author-735001"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "2160_1_1",
                        "bit_rate": 5135000,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 5409478,
                            "width": 2160,
                            "height": 3840,
                            "url_list": ["https://cdn.example.com/735001-2160.mp4"],
                        },
                    }
                ]
            },
        }
    }
    native_payload_2 = {
        "aweme_detail": {
            "aweme_id": "735002",
            "desc": "title-735002",
            "author": {"nickname": "author-735002"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "2160_1_1",
                        "bit_rate": 5135000,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 5409478,
                            "width": 2160,
                            "height": 3840,
                            "url_list": ["https://cdn.example.com/735002-2160.mp4"],
                        },
                    }
                ]
            },
        }
    }

    def fake_resolve(url: str):
        resolved_urls.append(url)
        video_id = url.rsplit("/", 1)[-1]
        return type("Resolution", (), {
            "provider_id": "kukutool",
            "source_url": url,
            "canonical_url": url,
            "payload": {
                "aweme_detail": {
                    "aweme_id": video_id,
                    "desc": f"title-{video_id}",
                    "author": {"nickname": f"author-{video_id}"},
                    "video": {
                        "video_fullinfo": [
                            {
                                "type": "1080p",
                                "size": 3819934,
                                "url": f"https://cdn.example.com/{video_id}-1080.mp4",
                            },
                            {
                                "type": "超高清",
                                "size": 67819321,
                                "url": f"https://cdn.example.com/{video_id}-ultra.mp4",
                            },
                        ],
                        "play_addr": {"url_list": [f"https://cdn.example.com/{video_id}-ultra.mp4"]},
                    },
                }
            },
        })()

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=html_snapshots):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(kukutool_resolver_for(runtime), "resolve_variants_only", side_effect=fake_resolve) as resolve_mock:
                    with patch(
                        "video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail",
                        side_effect=[native_payload_1, native_payload_2],
                    ) as detail_mock:
                        with patch.object(runtime.downloader, "probe_metadata") as probe_mock:
                            def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
                                captured_items.extend(list(items))
                                return summary

                            with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items) as sync_mock:
                                runtime.start_sync()

    assert resolve_mock.call_count == 2
    assert resolved_urls == [
        "https://www.douyin.com/video/735001",
        "https://www.douyin.com/video/735002",
    ]
    assert detail_mock.call_count == 2
    probe_mock.assert_not_called()
    assert [item.video_id for item in captured_items] == ["735001", "735002"]
    assert captured_items[0].download_url == "https://cdn.example.com/735001-ultra.mp4"
    assert captured_items[1].download_url == "https://cdn.example.com/735002-ultra.mp4"


def test_start_sync_uses_merged_best_variant_without_quality_strategy_override(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
        ),
    )
    runtime = AppRuntime(settings=settings)
    summary = SyncSummary(discovered_count=1, downloaded_count=1, skipped_count=0, failed_count=0)
    cookies_path = tmp_path / "cookies.txt"
    captured_items: list[VideoMetadata] = []

    def fake_resolve(url: str):
        return type("Resolution", (), {
            "provider_id": "kukutool",
            "source_url": url,
            "canonical_url": url,
            "payload": {
                "aweme_detail": {
                    "aweme_id": "735001",
                    "desc": "title-735001",
                    "author": {"nickname": "author-735001"},
                    "video": {
                        "video_fullinfo": [
                            {"type": "1080p", "size": 3819934, "url": "https://cdn.example.com/735001-1080.mp4"},
                            {"type": "超高清", "size": 67819321, "url": "https://cdn.example.com/735001-ultra.mp4"},
                        ],
                        "bit_rate": [
                            {
                                "gear_name": "2160_1_1",
                                "bit_rate": 5135000,
                                "is_h265": 1,
                                "play_addr": {
                                    "data_size": 5409478,
                                    "width": 2160,
                                    "height": 3840,
                                    "url_list": ["https://cdn.example.com/735001-2160.mp4"],
                                },
                            }
                        ],
                        "play_addr": {"url_list": ["https://cdn.example.com/735001-ultra.mp4"]},
                    },
                }
            },
        })()

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a>']):
                with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                    with patch.object(kukutool_resolver_for(runtime), "resolve_variants_only", side_effect=fake_resolve):
                        def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
                            captured_items.extend(list(items))
                            return summary

                        with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items):
                            runtime.start_sync()

    assert captured_items[0].download_url == "https://cdn.example.com/735001-ultra.mp4"


def test_preview_sync_returns_merged_variant_summary(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
        ),
    )
    runtime = AppRuntime(settings=settings)
    cookies_path = tmp_path / "cookies.txt"
    native_payload_1 = {
        "aweme_detail": {
            "aweme_id": "735001",
            "desc": "title-735001",
            "author": {"nickname": "author-735001"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "2160_1_1",
                        "bit_rate": 5135000,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 5409478,
                            "width": 2160,
                            "height": 3840,
                            "url_list": ["https://cdn.example.com/735001-2160.mp4"],
                        },
                    }
                ]
            },
        }
    }
    native_payload_2 = {
        "aweme_detail": {
            "aweme_id": "735002",
            "desc": "title-735002",
            "author": {"nickname": "author-735002"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "2160_1_1",
                        "bit_rate": 5135000,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 5409478,
                            "width": 2160,
                            "height": 3840,
                            "url_list": ["https://cdn.example.com/735002-2160.mp4"],
                        },
                    }
                ]
            },
        }
    }

    def fake_resolve(url: str):
        video_id = url.rsplit("/", 1)[-1]
        return type("Resolution", (), {
            "provider_id": "kukutool",
            "source_url": url,
            "canonical_url": url,
            "payload": {
                "aweme_detail": {
                    "aweme_id": video_id,
                    "desc": f"title-{video_id}",
                    "author": {"nickname": f"author-{video_id}"},
                    "video": {
                        "video_fullinfo": [
                            {"type": "超高清", "size": 67819321, "url": f"https://cdn.example.com/{video_id}-ultra.mp4"},
                        ],
                        "play_addr": {"url_list": [f"https://cdn.example.com/{video_id}-ultra.mp4"]},
                        "bit_rate": [
                            {
                                "gear_name": "2160_1_1",
                                "bit_rate": 5135000,
                                "is_h265": 1,
                                "play_addr": {
                                    "data_size": 5409478,
                                    "width": 2160,
                                    "height": 3840,
                                    "url_list": [f"https://cdn.example.com/{video_id}-2160.mp4"],
                                },
                            }
                        ],
                        "play_addr": {"url_list": [f"https://cdn.example.com/{video_id}-ultra.mp4"]},
                    },
                }
            },
        })()

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a><a href="/video/735002">video2</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(
                    kukutool_resolver_for(runtime),
                    "resolve_variants_only_many",
                    side_effect=lambda urls: {url: fake_resolve(url) for url in urls},
                ):
                    with patch(
                        "video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail",
                        side_effect=[native_payload_1, native_payload_2],
                    ):
                        preview = runtime.preview_sync()

    assert preview.source.platform == "douyin"
    assert len(preview.items) == 2
    assert preview.items[0].provider_summary == "kukutool + native"
    assert "超高清" in preview.items[0].variant_summary
    assert "2160p" in preview.items[0].variant_summary
    assert preview.items[0].selected_quality_label == "超高清"
    assert preview.items[0].selected_file_size == 67819321
    assert preview.items[0].metadata.author_name == "author-735001"


def test_preview_sync_resolves_every_video_with_kukutool_directly(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
            enabled_sources=("kukutool",),
        ),
    )
    runtime = AppRuntime(settings=settings)
    cookies_path = tmp_path / "cookies.txt"
    resolved_urls: list[str] = []

    def fake_kukutool_resolve(url: str):
        resolved_urls.append(url)
        video_id = url.rsplit("/", 1)[-1]
        return type("Resolution", (), {
            "provider_id": "kukutool",
            "canonical_url": url,
            "payload": {
                "aweme_detail": {
                    "aweme_id": video_id,
                    "desc": f"title-{video_id}",
                    "author": {"nickname": f"author-{video_id}"},
                    "video": {
                        "video_fullinfo": [
                            {"type": "超高清", "size": 67819321, "url": f"https://cdn.example.com/{video_id}-ultra.mp4"},
                        ],
                        "play_addr": {"url_list": [f"https://cdn.example.com/{video_id}-ultra.mp4"]},
                    },
                },
            },
        })()

    kukutool_resolver = next(item for item in runtime.share_resolver.resolvers if isinstance(item, KukutoolResolver))
    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">one</a><a href="/video/735002">two</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(
                    kukutool_resolver,
                    "resolve_variants_only_many",
                    side_effect=lambda urls: {url: fake_kukutool_resolve(url) for url in urls},
                ) as resolve_many_mock:
                    with patch("video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail") as native_mock:
                        preview = runtime.preview_sync()

    assert resolved_urls == [
        "https://www.douyin.com/video/735001",
        "https://www.douyin.com/video/735002",
    ]
    resolve_many_mock.assert_called_once()
    assert [item.provider_summary for item in preview.items] == ["kukutool", "kukutool"]
    assert all(item.selected_quality_label == "超高清" for item in preview.items)
    native_mock.assert_not_called()


def test_preview_sync_kukutool_only_does_not_silently_fall_back_to_native(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
            enabled_sources=("kukutool",),
        ),
    )
    runtime = AppRuntime(settings=settings)
    cookies_path = tmp_path / "cookies.txt"
    kukutool_resolver = next(item for item in runtime.share_resolver.resolvers if isinstance(item, KukutoolResolver))

    with patch.object(kukutool_resolver, "resolve_variants_only", side_effect=RuntimeError("Kukutool limited")):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail") as native_mock:
            try:
                runtime._resolve_douyin_sync_metadata(
                    page_url="https://www.douyin.com/video/735001",
                    source_type=SourceType.FAVORITES,
                    cookies_path=cookies_path,
                )
            except RuntimeError as exc:
                assert "Kukutool" in str(exc)
            else:
                raise AssertionError("Kukutool-only failure must be reported")

    native_mock.assert_not_called()


def test_start_sync_passes_retry_and_report_dir_to_sync_engine(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    runtime.set_retry_count(2)
    summary = SyncSummary(discovered_count=1, downloaded_count=1, skipped_count=0, failed_count=0)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title="演示视频",
        author_name="作者A",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://www.douyin.com/video/735001",
    )
    cookies_path = tmp_path / "cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(runtime.downloader, "probe_metadata", return_value=metadata):
                    with patch.object(runtime.sync_engine, "sync_items", return_value=summary) as sync_mock:
                        runtime.start_sync()

    assert sync_mock.call_args.kwargs["retry_count"] == 2
    assert sync_mock.call_args.kwargs["report_dir"] == runtime.output_root


def test_start_sync_streams_douyin_items_without_pre_resolving_everything(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
        ),
    )
    runtime = AppRuntime(settings=settings)
    cookies_path = tmp_path / "cookies.txt"
    resolve_calls: list[str] = []
    download_calls: list[str] = []

    def fake_resolve(url: str):
        resolve_calls.append(url)
        video_id = url.rsplit("/", 1)[-1]
        return type("Resolution", (), {
            "provider_id": "kukutool",
            "source_url": url,
            "canonical_url": url,
            "payload": {
                "aweme_detail": {
                    "aweme_id": video_id,
                    "desc": f"title-{video_id}",
                    "author": {"nickname": f"author-{video_id}"},
                    "video": {
                        "video_fullinfo": [
                            {"type": "超高清", "size": 67819321, "url": f"https://cdn.example.com/{video_id}-ultra.mp4"},
                        ],
                        "play_addr": {"url_list": [f"https://cdn.example.com/{video_id}-ultra.mp4"]},
                    },
                }
            },
        })()

    def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
        iterator = iter(items)
        first_item = next(iterator)
        assert resolve_calls == ["https://www.douyin.com/video/735001"]
        rest_items = list(iterator)
        collected = [first_item, *rest_items]
        download_calls.extend([item.video_id for item in collected])
        assert resolve_calls == [
            "https://www.douyin.com/video/735001",
            "https://www.douyin.com/video/735002",
        ]
        return SyncSummary(discovered_count=2, downloaded_count=2, skipped_count=0, failed_count=0)

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a><a href="/video/735002">video2</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(kukutool_resolver_for(runtime), "resolve_variants_only", side_effect=fake_resolve):
                    with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items):
                        runtime.start_sync()

    assert download_calls == ["735001", "735002"]


def test_start_sync_falls_back_to_existing_browser_pipeline_when_kukutool_resolution_fails(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    settings = AppSettings(
        platform_name=settings.platform_name,
        supported_source_types=settings.supported_source_types,
        paths=settings.paths,
        share_resolvers=settings.share_resolvers.__class__(
            enable_kukutool_fallback=True,
            kukutool_base_url=settings.share_resolvers.kukutool_base_url,
        ),
    )
    runtime = AppRuntime(settings=settings)
    summary = SyncSummary(discovered_count=1, downloaded_count=1, skipped_count=0, failed_count=0)
    detail_payload = {
        "aweme_detail": {
            "aweme_id": "735001",
            "desc": "native-title",
            "author": {"nickname": "native-author"},
            "video": {
                "bit_rate": [
                    {
                        "bit_rate": 1347641,
                        "play_addr": {"url_list": ["https://cdn.example.com/native.mp4"]},
                    }
                ]
            },
        }
    }
    cookies_path = tmp_path / "cookies.txt"
    captured_items: list[VideoMetadata] = []

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(kukutool_resolver_for(runtime), "resolve_variants_only", side_effect=RuntimeError("kukutool limited")) as resolve_mock:
                    with patch("video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail", return_value=detail_payload) as detail_mock:
                        def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
                            captured_items.extend(list(items))
                            return summary

                        with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items):
                            runtime.start_sync()

    assert resolve_mock.call_count == 1
    resolve_mock.assert_called_with("https://www.douyin.com/video/735001")
    detail_mock.assert_called_once_with("https://www.douyin.com/video/735001")
    assert len(captured_items) == 1
    assert captured_items[0].download_url == "https://cdn.example.com/native.mp4"


def test_start_sync_uses_browser_aweme_detail_pipeline_for_douyin(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    summary = SyncSummary(discovered_count=1, downloaded_count=1, skipped_count=0, failed_count=0)
    detail_payload = {
        "aweme_detail": {
            "aweme_id": "7062344670323526953",
            "desc": "#情绪 #成长",
            "duration": 6826,
            "author": {"nickname": "h6ii"},
            "video": {
                "bit_rate": [
                    {
                        "bit_rate": 1347641,
                        "play_addr": {"url_list": ["https://cdn.example.com/high.mp4"]},
                    }
                ]
            },
        }
    }
    captured_items: list[VideoMetadata] = []

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=post"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/7062344670323526953">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=tmp_path / "cookies.txt"):
                with patch("video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail", return_value=detail_payload) as detail_mock:
                    with patch.object(runtime.downloader, "probe_metadata") as probe_mock:
                        def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
                            captured_items.extend(list(items))
                            return summary

                        with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items):
                            runtime.start_sync()

    detail_mock.assert_called_once_with("https://www.douyin.com/video/7062344670323526953")
    probe_mock.assert_not_called()
    assert len(captured_items) == 1
    assert captured_items[0].video_id == "7062344670323526953"
    assert captured_items[0].download_url == "https://cdn.example.com/high.mp4"
def test_start_sync_stores_last_progress_from_engine_callback(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title="演示视频",
        author_name="作者A",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://www.douyin.com/video/735001",
    )

    def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
        list(items)
        progress_callback(
            SyncProgress(
                discovered_count=1,
                processed_count=1,
                downloaded_count=1,
                skipped_count=0,
                failed_count=0,
                current_video_id="735001",
                current_title="演示视频",
                current_author_name="作者A",
            )
        )
        return SyncSummary(discovered_count=1, downloaded_count=1, skipped_count=0, failed_count=0)
    cookies_path = tmp_path / "cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(runtime.downloader, "probe_metadata", return_value=metadata):
                    with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items):
                        runtime.start_sync()

    assert runtime.last_progress is not None
    assert runtime.last_progress.current_video_id == "735001"
    assert runtime.last_progress.downloaded_count == 1


def test_start_sync_records_latest_sync_run_summary_in_memory(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    summary = SyncSummary(
        discovered_count=2,
        downloaded_count=1,
        skipped_count=1,
        failed_count=0,
        status="completed",
    )
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title="演示视频",
        author_name="作者A",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://www.douyin.com/video/735001",
    )
    cookies_path = tmp_path / "cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(runtime.downloader, "probe_metadata", return_value=metadata):
                    with patch.object(runtime.sync_engine, "sync_items", return_value=summary):
                        runtime.start_sync()

    row = runtime.get_latest_sync_run()

    assert row is not None
    assert row["status"] == "completed"
    assert row["discovered_count"] == 2
    assert row["downloaded_count"] == 1
    assert row["skipped_count"] == 1
    assert row["failed_count"] == 0


def test_start_sync_raises_friendly_error_when_no_candidates_are_visible(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    cookies_path = tmp_path / "cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=post"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=["<html></html>"]):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                try:
                    runtime.start_sync()
                except RuntimeError as exc:
                    assert str(exc) == "当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。"
                else:
                    raise AssertionError("Expected RuntimeError when no candidates are visible")


def test_start_sync_exports_cookie_file_and_reuses_it_for_download_pipeline(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    summary = SyncSummary(
        discovered_count=1,
        downloaded_count=1,
        skipped_count=0,
        failed_count=0,
        status="completed",
    )
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.FAVORITES,
        video_id="735001",
        title="演示视频",
        author_name="作者A",
        page_url="https://www.douyin.com/video/735001",
        download_url="https://www.douyin.com/video/735001",
    )
    cookies_path = tmp_path / "cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path) as export_mock:
                    with patch.object(runtime.downloader, "probe_metadata", return_value=metadata) as probe_mock:
                        def fake_sync_items(items, progress_callback=None, cookies_file=None, retry_count=0, report_dir=None, discovered_count=None):
                            list(items)
                            return summary

                        with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items) as sync_mock:
                            runtime.start_sync()

    export_mock.assert_called_once()
    assert probe_mock.call_args.kwargs["cookies_file"] == cookies_path
    assert sync_mock.call_args.kwargs["cookies_file"] == cookies_path


def test_get_latest_sync_run_returns_latest_in_memory_summary(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    runtime._latest_sync_run = {
        "status": "completed",
        "discovered_count": 1,
        "downloaded_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
    }

    row = runtime.get_latest_sync_run()

    assert row is not None
    assert row["status"] == "completed"


def test_open_downloads_dir_uses_windows_shell(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    custom_dir = tmp_path / "custom-downloads"
    runtime.set_output_root(custom_dir)

    with patch.object(os, "startfile", create=True) as startfile_mock:
        runtime.open_downloads_dir()

    startfile_mock.assert_called_once_with(str(custom_dir))


def test_download_first_visible_sample_writes_first_visible_video_to_smoke_test_dir(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.AUTHOR_VIDEOS,
        video_id="7062344670323526953",
        title="#情绪 #成长",
        author_name="h6ii",
        page_url="https://www.douyin.com/video/7062344670323526953",
        download_url="https://cdn.example.com/high.mp4",
    )
    detail_payload = {
        "aweme_detail": {
            "aweme_id": metadata.video_id,
            "desc": metadata.title,
            "duration": 6826,
            "author": {"nickname": metadata.author_name},
            "video": {
                "bit_rate": [
                    {
                        "bit_rate": 1347641,
                        "play_addr": {"url_list": [metadata.download_url]},
                    }
                ]
            },
        }
    }

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=post"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/7062344670323526953">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail", return_value=detail_payload):
                with patch.object(runtime.downloader, "download", return_value=("mp4", str(tmp_path / "downloads" / "_smoke_test" / "sample.mp4"))) as download_mock:
                    result = runtime.download_first_visible_sample()

    assert result.metadata.video_id == "7062344670323526953"
    assert result.local_path.endswith("sample.mp4")
    assert download_mock.call_args.args[0].video_id == "7062344670323526953"
    assert download_mock.call_args.args[1] == settings.paths.downloads_dir / "_smoke_test"


def test_parse_share_text_returns_metadata_and_variants_without_login(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "duration": 8467,
            "author": {"nickname": "香菜严选"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "720_1_1",
                        "bit_rate": 1971327,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 2086404,
                            "width": 720,
                            "height": 1280,
                            "url_list": ["https://cdn.example.com/720.mp4"],
                        },
                    }
                ]
            },
        }
    }

    with patch("video2local.app_runtime.DouyinPublicSession.fetch_share_aweme_detail", return_value=("https://www.douyin.com/video/7651428709099242127", payload)) as fetch_mock:
        with patch("video2local.app_runtime.DouyinPublicSession.probe_content_length", return_value=2086404):
            result = runtime.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")

    fetch_mock.assert_called_once()
    assert result.metadata.video_id == "7651428709099242127"
    assert result.canonical_url == "https://www.douyin.com/video/7651428709099242127"
    assert result.provider_id == "native"
    assert len(result.variants) == 1
    assert result.variants[0].quality_label == "720p"
    assert result.variants[0].file_size == 2086404


def test_parse_share_text_prefers_signed_web_api_variants_when_available(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    signed_payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "duration": 8467,
            "author": {"nickname": "香菜严选"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "720_1_1",
                        "bit_rate": 1971327,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 2086404,
                            "width": 720,
                            "height": 1280,
                            "url_list": ["https://cdn.example.com/720.mp4"],
                        },
                    },
                    {
                        "gear_name": "1080_1_1",
                        "bit_rate": 9900000,
                        "is_h265": 0,
                        "play_addr": {
                            "data_size": 64700000,
                            "width": 1080,
                            "height": 1920,
                            "url_list": ["https://cdn.example.com/1080-ultra.mp4"],
                        },
                    },
                ]
            },
        }
    }

    with patch(
        "video2local.app_runtime.DouyinSignedSession.fetch_share_aweme_detail",
        return_value=("https://www.douyin.com/video/7651428709099242127", signed_payload),
    ) as signed_fetch_mock:
        with patch("video2local.app_runtime.DouyinPublicSession.fetch_share_aweme_detail") as public_fetch_mock:
            result = runtime.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")

    signed_fetch_mock.assert_called_once()
    public_fetch_mock.assert_not_called()
    assert result.metadata.video_id == "7651428709099242127"
    assert result.provider_id == "native"
    assert result.variants[0].quality_label == "1080p"
    assert result.variants[0].file_size == 64700000
    assert result.variants[0].download_url == "https://cdn.example.com/1080-ultra.mp4"


def test_parse_share_text_falls_back_to_public_session_when_signed_web_api_fails(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    public_payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "duration": 8467,
            "author": {"nickname": "香菜严选"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "720_1_1",
                        "bit_rate": 1971327,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 2086404,
                            "width": 720,
                            "height": 1280,
                            "url_list": ["https://cdn.example.com/720.mp4"],
                        },
                    }
                ]
            },
        }
    }

    with patch(
        "video2local.app_runtime.DouyinSignedSession.fetch_share_aweme_detail",
        side_effect=RuntimeError("signed api unavailable"),
    ) as signed_fetch_mock:
        with patch(
            "video2local.app_runtime.DouyinPublicSession.fetch_share_aweme_detail",
            return_value=("https://www.douyin.com/video/7651428709099242127", public_payload),
        ) as public_fetch_mock:
            with patch("video2local.app_runtime.DouyinPublicSession.probe_content_length", return_value=2086404):
                result = runtime.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")

    assert signed_fetch_mock.call_count == 2
    public_fetch_mock.assert_called_once()
    assert result.variants[0].quality_label == "720p"
    assert result.variants[0].file_size == 2086404


def test_parse_share_text_retries_signed_web_api_before_public_fallback(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    signed_payload = {
        "aweme_detail": {
            "aweme_id": "7651428709099242127",
            "desc": "分享视频",
            "duration": 8467,
            "author": {"nickname": "香菜严选"},
            "video": {
                "bit_rate": [
                    {
                        "gear_name": "2160_1_1",
                        "bit_rate": 5134767,
                        "is_h265": 1,
                        "play_addr": {
                            "data_size": 5409478,
                            "width": 2160,
                            "height": 3840,
                            "url_list": ["https://cdn.example.com/2160.mp4"],
                        },
                    }
                ]
            },
        }
    }

    with patch(
        "video2local.app_runtime.DouyinSignedSession.fetch_share_aweme_detail",
        side_effect=[
            RuntimeError("signed api timeout"),
            ("https://www.douyin.com/video/7651428709099242127", signed_payload),
        ],
    ) as signed_fetch_mock:
        with patch("video2local.app_runtime.DouyinPublicSession.fetch_share_aweme_detail") as public_fetch_mock:
            result = runtime.parse_share_text("https://v.douyin.com/5MF6Y_tP8nk/")

    assert signed_fetch_mock.call_count == 2
    public_fetch_mock.assert_not_called()
    assert result.variants[0].quality_label == "2160p"


def test_download_share_variant_saves_selected_quality_with_quality_suffix(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    custom_dir = tmp_path / "custom-downloads"
    runtime.set_output_root(custom_dir)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.SHARE_LINK,
        video_id="7651428709099242127",
        title="分享视频",
        author_name="香菜严选",
        page_url="https://www.douyin.com/video/7651428709099242127",
        download_url="https://cdn.example.com/original.mp4",
    )
    variant = VideoVariant(
        variant_id="720_1_1",
        quality_label="720p",
        codec_label="H.265",
        bit_rate=1971327,
        file_size=2086404,
        width=720,
        height=1280,
        download_url="https://cdn.example.com/720.mp4",
        is_recommended=True,
    )
    parse_result = ShareParseResult(
        provider_id="native",
        source_url="https://v.douyin.com/5MF6Y_tP8nk/",
        canonical_url="https://www.douyin.com/video/7651428709099242127",
        metadata=metadata,
        variants=[variant],
    )

    with patch.object(runtime.downloader, "download", return_value=("mp4", str(tmp_path / "downloads" / "douyin" / "香菜严选" / "分享视频-7651428709099242127-720p.mp4"))) as download_mock:
        result = runtime.download_share_variant(parse_result, "720_1_1")

    assert result.local_path.endswith("-720p.mp4")
    assert download_mock.call_args.args[0].download_url == "https://cdn.example.com/720.mp4"
    assert download_mock.call_args.kwargs["filename_stem"] == "分享视频-7651428709099242127-720p"
    assert download_mock.call_args.args[1] == custom_dir / "douyin" / "香菜严选"


def test_download_share_variant_can_write_directly_into_output_root(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    custom_dir = tmp_path / "custom-downloads"
    runtime.set_output_root(custom_dir)
    runtime.set_flat_output(True)
    metadata = VideoMetadata(
        platform="douyin",
        source_type=SourceType.SHARE_LINK,
        video_id="7651428709099242127",
        title="分享视频",
        author_name="香菜严选",
        page_url="https://www.douyin.com/video/7651428709099242127",
        download_url="https://cdn.example.com/original.mp4",
    )
    variant = VideoVariant(
        variant_id="720_1_1",
        quality_label="720p",
        codec_label="H.265",
        bit_rate=1971327,
        file_size=2086404,
        width=720,
        height=1280,
        download_url="https://cdn.example.com/720.mp4",
        is_recommended=True,
    )
    parse_result = ShareParseResult(
        provider_id="native",
        source_url="https://v.douyin.com/5MF6Y_tP8nk/",
        canonical_url="https://www.douyin.com/video/7651428709099242127",
        metadata=metadata,
        variants=[variant],
    )

    with patch.object(runtime.downloader, "download", return_value=("mp4", str(custom_dir / "分享视频-7651428709099242127-720p.mp4"))) as download_mock:
        runtime.download_share_variant(parse_result, "720_1_1")

    assert download_mock.call_args.args[1] == custom_dir


def test_parse_bilibili_share_text_uses_native_formats_without_kukutool(tmp_path: Path) -> None:
    settings = AppSettings.for_root(
        tmp_path,
        platform_name="douyin",
        supported_source_types=("favorites", "author_videos"),
        share_resolvers=ShareResolverSettings(enable_kukutool_fallback=True, enabled_sources=("native", "kukutool")),
    )
    runtime = AppRuntime(settings=settings)
    cookies_path = tmp_path / "yt-dlp-cookies.txt"
    payload = {
        "id": "BV1xx411c7mD",
        "title": "B站测试视频",
        "uploader": "测试UP",
        "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "formats": [
            {"format_id": "80", "height": 1080, "vcodec": "avc1", "acodec": "none", "tbr": 3600, "filesize": 30_000_000},
            {"format_id": "30280", "vcodec": "none", "acodec": "mp4a", "abr": 192, "filesize": 2_000_000},
        ],
    }

    with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path) as export_mock:
        with patch.object(runtime.downloader, "probe_video_info", return_value=payload) as probe_mock:
            with patch.object(runtime.share_resolver, "resolve") as resolve_mock:
                result = runtime.parse_share_text("【B站测试视频】https://b23.tv/AbCdEfG")

    export_mock.assert_called_once_with(settings.paths.data_dir / "yt-dlp-cookies.txt")
    probe_mock.assert_called_once_with(url="https://b23.tv/AbCdEfG", cookies_file=cookies_path)
    resolve_mock.assert_not_called()
    assert result.provider_id == "native"
    assert result.metadata.platform == "bilibili"
    assert result.variants[0].format_selector == "80+30280"


def test_download_bilibili_variant_passes_selected_format_to_downloader(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    metadata = VideoMetadata(
        platform="bilibili",
        source_type=SourceType.SHARE_LINK,
        video_id="BV1xx411c7mD",
        title="B站测试视频",
        author_name="测试UP",
        page_url="https://www.bilibili.com/video/BV1xx411c7mD",
        download_url="https://www.bilibili.com/video/BV1xx411c7mD",
    )
    variant = VideoVariant(
        variant_id="bilibili:80+30280",
        quality_label="1080p",
        codec_label="H.264",
        bit_rate=3600000,
        file_size=32000000,
        width=1920,
        height=1080,
        download_url=metadata.page_url,
        format_selector="80+30280",
        is_recommended=True,
    )
    parse_result = ShareParseResult(
        provider_id="native",
        source_url=metadata.page_url,
        canonical_url=metadata.page_url,
        metadata=metadata,
        variants=[variant],
    )

    cookies_path = tmp_path / "yt-dlp-cookies.txt"
    with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
        with patch.object(runtime.downloader, "download", return_value=("mp4", str(tmp_path / "B站测试视频-BV1xx411c7mD-1080p.mp4"))) as download_mock:
            runtime.download_share_variant(parse_result, variant.variant_id)

    assert download_mock.call_args.kwargs["format_selector"] == "80+30280"
    assert download_mock.call_args.kwargs["cookies_file"] == cookies_path


def test_parse_bilibili_share_text_falls_back_to_anonymous_when_chrome_is_unavailable(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    payload = {
        "id": "BV1xx411c7mD",
        "title": "B站测试视频",
        "uploader": "测试UP",
        "formats": [{"format_id": "80", "height": 1080, "vcodec": "avc1", "acodec": "mp4a", "tbr": 3600}],
    }

    with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", side_effect=RuntimeError("Chrome is not running")):
        with patch.object(runtime.downloader, "probe_video_info", return_value=payload) as probe_mock:
            result = runtime.parse_share_text("https://www.bilibili.com/video/BV1xx411c7mD")

    assert result.metadata.platform == "bilibili"
    assert probe_mock.call_args.kwargs["cookies_file"] is None


def test_parse_youtube_share_text_uses_native_formats_and_browser_cookies(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    cookies_path = tmp_path / "yt-dlp-cookies.txt"
    payload = {
        "id": "abcDEF12345",
        "title": "YouTube 测试视频",
        "uploader": "测试频道",
        "webpage_url": "https://www.youtube.com/watch?v=abcDEF12345",
        "formats": [
            {"format_id": "248", "height": 1080, "vcodec": "vp9", "acodec": "none", "tbr": 4500},
            {"format_id": "251", "vcodec": "none", "acodec": "opus", "abr": 160},
        ],
    }

    with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
        with patch.object(runtime.downloader, "probe_video_info", return_value=payload) as probe_mock:
            result = runtime.parse_share_text("分享 https://youtu.be/abcDEF12345")

    assert result.metadata.platform == "youtube"
    assert result.variants[0].format_selector == "248+251"
    assert probe_mock.call_args.kwargs["cookies_file"] == cookies_path


def test_download_youtube_share_variant_passes_selected_format_and_cookies(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    parse_result = ShareParseResult(
        provider_id="native",
        source_url="https://youtu.be/abcDEF12345",
        canonical_url="https://www.youtube.com/watch?v=abcDEF12345",
        metadata=VideoMetadata(
            platform="youtube",
            source_type=SourceType.SHARE_LINK,
            video_id="abcDEF12345",
            title="YouTube 测试视频",
            author_name="测试频道",
            page_url="https://www.youtube.com/watch?v=abcDEF12345",
            download_url="https://www.youtube.com/watch?v=abcDEF12345",
        ),
        variants=[
            VideoVariant(
                variant_id="youtube:248+251",
                quality_label="1080p",
                codec_label="VP9",
                bit_rate=4500000,
                file_size=None,
                width=1920,
                height=1080,
                download_url="https://www.youtube.com/watch?v=abcDEF12345",
                format_selector="248+251",
            )
        ],
    )
    cookies_path = tmp_path / "yt-dlp-cookies.txt"

    with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
        with patch.object(runtime.downloader, "download", return_value=("mp4", str(tmp_path / "YouTube 测试视频-abcDEF12345-1080p.mp4"))) as download_mock:
            runtime.download_share_variant(parse_result, "youtube:248+251")

    assert download_mock.call_args.kwargs["cookies_file"] == cookies_path
    assert download_mock.call_args.kwargs["format_selector"] == "248+251"


def test_preview_bilibili_author_page_uses_login_cookies_and_shows_selected_quality(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    cookies_path = tmp_path / "yt-dlp-cookies.txt"
    payload = {
        "id": "BV1xx411c7mD",
        "title": "B站测试视频",
        "uploader": "测试UP",
        "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "formats": [
            {"format_id": "80", "height": 1080, "vcodec": "avc1", "acodec": "none", "tbr": 3600, "filesize": 30_000_000},
            {"format_id": "30280", "vcodec": "none", "acodec": "mp4a", "abr": 192, "filesize": 2_000_000},
        ],
    }

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://space.bilibili.com/123456/video"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/BV1xx411c7mD">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(runtime.downloader, "probe_video_info", return_value=payload) as probe_mock:
                    with patch.object(runtime, "_resolve_kukutool_preview_candidates") as kukutool_preview_mock:
                        preview = runtime.preview_sync()

    assert preview.source.platform == "bilibili"
    assert preview.items[0].selected_quality_label == "1080p"
    assert preview.items[0].metadata.format_selector == "80+30280"
    assert probe_mock.call_args.kwargs["cookies_file"] == cookies_path
    kukutool_preview_mock.assert_not_called()


def test_preview_bilibili_skips_expired_video_and_writes_details_to_output_root(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    cookies_path = tmp_path / "yt-dlp-cookies.txt"
    working_payload = {
        "id": "BV1ok411c7mD",
        "title": "正常视频",
        "uploader": "测试UP",
        "webpage_url": "https://www.bilibili.com/video/BV1ok411c7mD",
        "formats": [{"format_id": "80", "height": 1080, "vcodec": "avc1", "acodec": "mp4a", "tbr": 3600}],
    }

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://space.bilibili.com/123456/favlist?fid=987654"):
        with patch(
            "video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots",
            return_value=[
                '<a href="/video/BV1bad411c7mD">expired</a>'
                '<a href="/video/BV1ok411c7mD">working</a>'
            ],
        ):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(
                    runtime.downloader,
                    "probe_video_info",
                    side_effect=[RuntimeError("ERROR: [BiliBili] video is not available"), working_payload],
                ):
                    preview = runtime.preview_sync()

    assert [item.metadata.video_id for item in preview.items] == ["BV1ok411c7mD"]
    assert preview.skipped_items is not None
    assert len(preview.skipped_items) == 1
    assert preview.report_path is not None
    report_text = Path(preview.report_path).read_text(encoding="utf-8")
    assert "BV1bad411c7mD" in report_text
    assert "视频已失效、删除或当前账号无权访问" in report_text


def test_start_sync_bilibili_skips_expired_video_and_continues_next_item(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    cookies_path = tmp_path / "yt-dlp-cookies.txt"
    working_payload = {
        "id": "BV1ok411c7mD",
        "title": "正常视频",
        "uploader": "测试UP",
        "webpage_url": "https://www.bilibili.com/video/BV1ok411c7mD",
        "formats": [{"format_id": "80", "height": 1080, "vcodec": "avc1", "acodec": "mp4a", "tbr": 3600}],
    }

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://space.bilibili.com/123456/favlist?fid=987654"):
        with patch(
            "video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots",
            return_value=[
                '<a href="/video/BV1bad411c7mD">expired</a>'
                '<a href="/video/BV1ok411c7mD">working</a>'
            ],
        ):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(
                    runtime.downloader,
                    "probe_video_info",
                    side_effect=[RuntimeError("ERROR: [BiliBili] video is not available"), working_payload],
                ):
                    with patch.object(
                        runtime.downloader,
                        "download",
                        return_value=("mp4", str(tmp_path / "正常视频-BV1ok411c7mD.mp4")),
                    ) as download_mock:
                        summary = runtime.start_sync()

    assert summary.skipped_count == 1
    assert summary.downloaded_count == 1
    assert download_mock.call_args.args[0].video_id == "BV1ok411c7mD"
    assert summary.report_path is not None
    assert "BV1bad411c7mD" in Path(summary.report_path).read_text(encoding="utf-8")


def test_start_sync_bilibili_page_passes_selected_format_and_cookies_to_queue(tmp_path: Path) -> None:
    runtime = AppRuntime(settings=AppSettings.default_for_root(tmp_path))
    cookies_path = tmp_path / "yt-dlp-cookies.txt"
    payload = {
        "id": "BV1xx411c7mD",
        "title": "B站测试视频",
        "uploader": "测试UP",
        "webpage_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "formats": [
            {"format_id": "80", "height": 1080, "vcodec": "avc1", "acodec": "none", "tbr": 3600, "filesize": 30_000_000},
            {"format_id": "30280", "vcodec": "none", "acodec": "mp4a", "abr": 192, "filesize": 2_000_000},
        ],
    }
    captured_items: list[VideoMetadata] = []

    def fake_sync_items(items, **kwargs):
        captured_items.extend(items)
        return SyncSummary(discovered_count=1, downloaded_count=1, status="completed")

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://space.bilibili.com/123456/favlist?fid=987654"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/BV1xx411c7mD">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=cookies_path):
                with patch.object(runtime.downloader, "probe_video_info", return_value=payload):
                    with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items) as sync_mock:
                        runtime.start_sync()

    assert captured_items[0].platform == "bilibili"
    assert captured_items[0].format_selector == "80+30280"
    assert sync_mock.call_args.kwargs["cookies_file"] == cookies_path
