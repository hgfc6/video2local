from pathlib import Path
from unittest.mock import patch
import os

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
                    with patch.object(runtime.sync_engine, "sync_items", return_value=summary) as sync_mock:
                        result = runtime.start_sync()

    assert result == summary
    assert probe_mock.call_count == 2
    sync_mock.assert_called_once()
    assert sync_mock.call_args.args[0] == [metadata]
    assert sync_mock.call_args.kwargs["progress_callback"] == runtime._store_progress


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

    with patch("video2local.app_runtime.ChromeRemoteSession.get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=post"):
        with patch("video2local.app_runtime.ChromeRemoteSession.fetch_active_page_html_snapshots", return_value=['<a href="/video/7062344670323526953">video</a>']):
            with patch("video2local.app_runtime.ChromeRemoteSession.export_cookies", return_value=tmp_path / "cookies.txt"):
                with patch("video2local.app_runtime.ChromeRemoteSession.fetch_douyin_aweme_detail", return_value=detail_payload) as detail_mock:
                    with patch.object(runtime.downloader, "probe_metadata") as probe_mock:
                        with patch.object(runtime.sync_engine, "sync_items", return_value=summary) as sync_mock:
                            runtime.start_sync()

    detail_mock.assert_called_once_with("https://www.douyin.com/video/7062344670323526953")
    probe_mock.assert_not_called()
    items = sync_mock.call_args.args[0]
    assert len(items) == 1
    assert items[0].video_id == "7062344670323526953"
    assert items[0].download_url == "https://cdn.example.com/high.mp4"
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

    def fake_sync_items(items, progress_callback=None, cookies_file=None):
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


def test_start_sync_records_latest_sync_run_summary(tmp_path: Path) -> None:
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

    row = runtime.repository.get_latest_sync_run()

    assert row is not None
    assert row["platform"] == "douyin"
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
                    with patch.object(runtime.sync_engine, "sync_items", return_value=summary) as sync_mock:
                        runtime.start_sync()

    export_mock.assert_called_once()
    assert probe_mock.call_args.kwargs["cookies_file"] == cookies_path
    assert sync_mock.call_args.kwargs["cookies_file"] == cookies_path


def test_get_latest_sync_run_returns_repository_row(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)
    runtime.ensure_directories()
    run_id = runtime.repository.create_sync_run(platform="douyin")
    runtime.repository.finish_sync_run(
        run_id=run_id,
        status="completed",
        discovered_count=1,
        downloaded_count=1,
        skipped_count=0,
        failed_count=0,
    )

    row = runtime.get_latest_sync_run()

    assert row is not None
    assert row["id"] == run_id
    assert row["status"] == "completed"


def test_open_downloads_dir_uses_windows_shell(tmp_path: Path) -> None:
    settings = AppSettings.default_for_root(tmp_path)
    runtime = AppRuntime(settings=settings)

    with patch.object(os, "startfile", create=True) as startfile_mock:
        runtime.open_downloads_dir()

    startfile_mock.assert_called_once_with(str(settings.paths.downloads_dir))


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
