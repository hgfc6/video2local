from pathlib import Path
import json
from unittest.mock import patch

from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession


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


def test_remote_session_returns_first_http_page_url() -> None:
    payload = json.dumps(
        [
            {"id": "1", "type": "service_worker", "url": "chrome-extension://abc"},
            {"id": "2", "type": "page", "url": "https://www.douyin.com/user/self?showTab=favorite_collection"},
        ]
    ).encode("utf-8")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return payload

    with patch("video2local.browser.urlopen", return_value=FakeResponse()):
        session = ChromeRemoteSession()

        assert session.get_active_page_url() == "https://www.douyin.com/user/self?showTab=favorite_collection"
