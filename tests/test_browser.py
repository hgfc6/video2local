from pathlib import Path
from unittest.mock import patch

from video2local.browser import ChromeLaunchSpec


def test_chrome_launch_args_use_dedicated_profile_and_remote_debugging_port(tmp_path: Path) -> None:
    spec = ChromeLaunchSpec(
        executable_path=Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        user_data_dir=tmp_path / "chrome-profile",
        remote_debugging_port=9222,
    )

    args = spec.to_argv()

    assert args == [
        str(spec.executable_path),
        f"--user-data-dir={spec.user_data_dir}",
        "--remote-debugging-port=9222",
        "--new-window",
        "about:blank",
    ]


def test_detect_finds_chrome_on_path(tmp_path: Path) -> None:
    with patch("video2local.browser.shutil.which", return_value="C:/Chrome/chrome.exe"):
        spec = ChromeLaunchSpec.detect(user_data_dir=tmp_path / "chrome-profile")

    assert spec.executable_path == Path("C:/Chrome/chrome.exe")
    assert spec.user_data_dir == tmp_path / "chrome-profile"
    assert spec.remote_debugging_port == 9222
