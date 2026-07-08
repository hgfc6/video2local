from pathlib import Path
from unittest.mock import patch

from video2local.app_runtime import AppRuntime
from video2local.domain import SourceType
from video2local.browser import ChromeLaunchSpec
from video2local.config import AppSettings


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
        source = runtime.start_sync()

    assert source is not None
    assert source.platform == "douyin"
    assert source.source_type == SourceType.FAVORITES
