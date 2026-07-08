from pathlib import Path
import json
from unittest.mock import patch
import asyncio

from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession, write_netscape_cookies


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


def test_detect_falls_back_to_common_install_path(tmp_path: Path) -> None:
    chrome_path = tmp_path / "chrome.exe"
    chrome_path.write_text("", encoding="utf-8")
    with patch("video2local.browser.shutil.which", return_value=None):
        with patch("video2local.browser.COMMON_CHROME_PATHS", (chrome_path,)):
            spec = ChromeLaunchSpec.detect(user_data_dir=tmp_path / "chrome-profile")

    assert spec.executable_path == chrome_path


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


def test_remote_session_ignores_about_blank_targets() -> None:
    payload = json.dumps(
        [
            {"id": "1", "type": "page", "url": "about:blank"},
            {"id": "2", "type": "page", "url": "https://www.douyin.com/user/self?showTab=post"},
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

        assert session.get_active_page_url() == "https://www.douyin.com/user/self?showTab=post"


def test_write_netscape_cookies_persists_compatible_cookie_file(tmp_path: Path) -> None:
    output_path = tmp_path / "cookies.txt"

    write_netscape_cookies(
        output_path,
        [
            {
                "domain": ".douyin.com",
                "path": "/",
                "secure": True,
                "expires": 1893456000,
                "name": "sessionid",
                "value": "abc123",
            }
        ],
    )

    contents = output_path.read_text(encoding="utf-8")

    assert contents.startswith("# Netscape HTTP Cookie File")
    assert ".douyin.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tabc123" in contents


def test_write_netscape_cookies_skips_nameless_entries_and_normalizes_session_expiry(tmp_path: Path) -> None:
    output_path = tmp_path / "cookies.txt"

    write_netscape_cookies(
        output_path,
        [
            {
                "domain": "www.douyin.com",
                "path": "/",
                "secure": False,
                "expires": -1,
                "name": "",
                "value": "ignored",
            },
            {
                "domain": "www.douyin.com",
                "path": "/",
                "secure": False,
                "expires": -1,
                "name": "session_cookie",
                "value": "value-1",
            },
        ],
    )

    contents = output_path.read_text(encoding="utf-8")

    assert "\t\tignored" not in contents
    assert "www.douyin.com\tFALSE\t/\tFALSE\t0\tsession_cookie\tvalue-1" in contents


def test_fetch_active_page_html_prefers_page_matching_active_target_url() -> None:
    class FakePage:
        def __init__(self, url: str, html: str) -> None:
            self.url = url
            self._html = html

        async def content(self) -> str:
            return self._html

    class FakeContext:
        def __init__(self, pages) -> None:
            self.pages = pages

    class FakeBrowser:
        def __init__(self, contexts) -> None:
            self.contexts = contexts

        async def close(self) -> None:
            return None

    class FakeChromium:
        async def connect_over_cdp(self, url: str):
            return FakeBrowser(
                [
                    FakeContext(
                        [
                            FakePage("https://www.douyin.com/jingxuan", "<html>discover</html>"),
                            FakePage("https://www.douyin.com/user/self?showTab=post", "<html>/video/7062344670323526953</html>"),
                        ]
                    )
                ]
            )

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeAsyncPlaywright:
        async def __aenter__(self):
            return FakePlaywright()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    session = ChromeRemoteSession()

    with patch.object(ChromeRemoteSession, "get_active_page_url", return_value="https://www.douyin.com/user/self?showTab=post"):
        with patch("video2local.browser.async_playwright", return_value=FakeAsyncPlaywright()):
            html = asyncio.run(session._fetch_active_page_html_async())

    assert html == "<html>/video/7062344670323526953</html>"
