from pathlib import Path
from unittest.mock import patch

from video2local.app_runtime import AppRuntime
from video2local.domain import SourceType, SyncProgress, VideoMetadata
from video2local.browser import ChromeLaunchSpec
from video2local.config import AppSettings
from video2local.sync_engine import SyncSummary


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
            assert str(exc) == "请先在专用 Chrome 中打开抖音收藏页或作者作品页"
        else:
            raise AssertionError("Expected RuntimeError for chrome internal page")


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

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=html_snapshots):
            with patch.object(runtime.downloader, "probe_metadata", return_value=metadata) as probe_mock:
                with patch.object(runtime.sync_engine, "sync_items", return_value=summary) as sync_mock:
                    result = runtime.start_sync()

    assert result == summary
    assert probe_mock.call_count == 2
    sync_mock.assert_called_once()
    assert sync_mock.call_args.args[0] == [metadata]
    assert sync_mock.call_args.kwargs["progress_callback"] == runtime._store_progress


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

    def fake_sync_items(items, progress_callback=None):
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

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=favorite_collection"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/735001">video</a>']):
            with patch.object(runtime.downloader, "probe_metadata", return_value=metadata):
                with patch.object(runtime.sync_engine, "sync_items", side_effect=fake_sync_items):
                    runtime.start_sync()

    assert runtime.last_progress is not None
    assert runtime.last_progress.current_video_id == "735001"
    assert runtime.last_progress.downloaded_count == 1
