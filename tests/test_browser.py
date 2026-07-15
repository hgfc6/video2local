from pathlib import Path
import json
from unittest.mock import patch
import asyncio

from playwright.async_api import Error as PlaywrightError

from video2local.browser import (
    ChromeLaunchSpec,
    ChromeRemoteSession,
    DouyinSignedSession,
    KukutoolSession,
    evaluate_with_navigation_retry,
    wait_for_function_with_navigation_retry,
    write_netscape_cookies,
)


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


def test_kukutool_quality_button_parser_extracts_size_and_label() -> None:
    variant = KukutoolSession._parse_quality_button_text("下载 超高清 (64.7MB)")

    assert variant == {"type": "超高清", "size": int(64.7 * 1024 * 1024)}


def test_kukutool_result_wait_expression_matches_downloadable_quality_buttons() -> None:
    expression = KukutoolSession._quality_result_wait_expression()

    assert "下载" in expression
    assert "KB|MB|GB" in expression


def test_kukutool_clipboard_capture_script_intercepts_write_text() -> None:
    source = KukutoolSession._install_clipboard_capture.__code__.co_consts

    assert any("clipboard.writeText" in value for value in source if isinstance(value, str))


def test_kukutool_page_check_rejects_ad_navigation() -> None:
    base_url = "https://dy.kukutool.com/"

    assert KukutoolSession._is_kukutool_page(base_url, base_url) is True
    assert KukutoolSession._is_kukutool_page("https://googleads.g.doubleclick.net/pagead/ad", base_url) is False


def test_page_evaluate_retries_when_navigation_replaces_execution_context() -> None:
    class FakePage:
        calls = 0

        async def evaluate(self, expression: str):
            self.calls += 1
            if self.calls == 1:
                raise PlaywrightError("Execution context was destroyed, most likely because of a navigation")
            return "ready"

        async def wait_for_load_state(self, state: str, timeout: int) -> None:
            return None

        async def wait_for_timeout(self, timeout: int) -> None:
            return None

    page = FakePage()

    assert asyncio.run(evaluate_with_navigation_retry(page, "() => 'ready'")) == "ready"
    assert page.calls == 2


def test_page_wait_for_function_retries_when_navigation_replaces_execution_context() -> None:
    class FakePage:
        calls = 0

        async def wait_for_function(self, expression: str, timeout: int) -> None:
            self.calls += 1
            if self.calls == 1:
                raise PlaywrightError("Execution context was destroyed, most likely because of a navigation")

        async def wait_for_load_state(self, state: str, timeout: int) -> None:
            return None

        async def wait_for_timeout(self, timeout: int) -> None:
            return None

    page = FakePage()

    asyncio.run(wait_for_function_with_navigation_retry(page, "() => true", timeout=1000))

    assert page.calls == 2


def test_kukutool_quality_button_parser_accepts_kukutool_compact_button_text() -> None:
    variant = KukutoolSession._parse_quality_button_text("下载超高清 (7.0MB)")

    assert variant == {"type": "超高清", "size": 7 * 1024 * 1024}


def test_kukutool_quality_button_parser_ignores_unrelated_buttons() -> None:
    assert KukutoolSession._parse_quality_button_text("下载无水印视频") is None


def test_kukutool_quality_button_parser_accepts_button_text_with_line_breaks() -> None:
    variant = KukutoolSession._parse_quality_button_text("下载\n720p (2.6MB)".replace("\n", " "))

    assert variant == {"type": "720p", "size": int(2.6 * 1024 * 1024)}




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


def test_remote_session_lists_all_page_targets_for_runtime_source_selection() -> None:
    payload = json.dumps(
        [
            {"id": "1", "type": "page", "url": "https://dy.kukutool.com/"},
            {"id": "2", "type": "page", "url": "https://www.douyin.com/user/self?showTab=favorite_collection"},
            {"id": "3", "type": "page", "url": "about:blank"},
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
        assert ChromeRemoteSession().list_page_urls() == [
            "https://dy.kukutool.com/",
            "https://www.douyin.com/user/self?showTab=favorite_collection",
        ]


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


def test_signed_session_prefers_page_emitted_detail_response(tmp_path: Path) -> None:
    payload = {"aweme_detail": {"aweme_id": "7651428709099242127"}}

    class FakeResponse:
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=7651428709099242127&a_bogus=signed"

        async def json(self):
            return payload

    class FakeResponseInfo:
        def __init__(self, response) -> None:
            self.value = response

    class FakeExpectResponse:
        def __init__(self, response) -> None:
            self.response = response

        async def __aenter__(self):
            return FakeResponseInfo(self.response)

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePage:
        def __init__(self) -> None:
            self.url = "about:blank"

        def expect_response(self, predicate, timeout: int):
            response = FakeResponse()
            assert predicate(response) is True
            assert timeout == 15000
            return FakeExpectResponse(response)

        async def goto(self, url: str, wait_until: str, timeout: int):
            assert wait_until == "domcontentloaded"
            assert timeout == 60000
            if "v.douyin.com" in url:
                self.url = "https://www.douyin.com/video/7651428709099242127"
            else:
                self.url = url

        async def wait_for_timeout(self, timeout_ms: int):
            assert timeout_ms == 2000

    class FakeBrowser:
        def __init__(self) -> None:
            self.page = FakePage()

        async def new_page(self):
            return self.page

        async def close(self) -> None:
            return None

    class FakeChromium:
        async def launch(self, executable_path: str, headless: bool):
            assert executable_path.endswith("chrome.exe")
            assert headless is True
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeAsyncPlaywright:
        async def __aenter__(self):
            return FakePlaywright()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    session = DouyinSignedSession(chrome_executable_path=tmp_path / "chrome.exe")

    with patch("video2local.browser.async_playwright", return_value=FakeAsyncPlaywright()):
        canonical_url, result = asyncio.run(session._fetch_share_aweme_detail_async("https://v.douyin.com/5MF6Y_tP8nk/"))

    assert canonical_url == "https://www.douyin.com/video/7651428709099242127"
    assert result == payload


def test_signed_session_builds_web_detail_url_with_f2_style_query_params() -> None:
    session = DouyinSignedSession()

    with patch.object(DouyinSignedSession, "_gen_false_ms_token", return_value="ms-token-demo"):
        with patch.object(DouyinSignedSession, "_gen_verify_fp", return_value="verify-demo"):
            with patch.object(DouyinSignedSession, "_generate_a_bogus", return_value="bogus-demo"):
                url = session._build_signed_detail_url("7651428709099242127", "Mozilla/5.0 Demo")

    assert "https://www.douyin.com/aweme/v1/web/aweme/detail/?" in url
    assert "aweme_id=7651428709099242127" in url
    assert "aid=6383" in url
    assert "device_platform=webapp" in url
    assert "channel=channel_pc_web" in url
    assert "verifyFp=verify-demo" in url
    assert "msToken=ms-token-demo" in url
    assert "a_bogus=bogus-demo" in url


def test_signed_session_fetches_detail_over_http_with_cookie_headers() -> None:
    payload = {"aweme_detail": {"aweme_id": "7651428709099242127"}}
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout: int):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    session = DouyinSignedSession()
    cookies = [
        {"name": "ttwid", "value": "ttwid-demo"},
        {"name": "msToken", "value": "mstoken-demo"},
    ]

    with patch.object(DouyinSignedSession, "_build_signed_detail_url", return_value="https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=7651428709099242127"):
        with patch("video2local.browser.urlopen", side_effect=fake_urlopen):
            result = session._fetch_detail_over_http(
                aweme_id="7651428709099242127",
                user_agent="Mozilla/5.0 Demo",
                cookies=cookies,
                referer="https://www.douyin.com/video/7651428709099242127",
            )

    assert result == payload
    assert captured["url"].endswith("aweme_id=7651428709099242127")
    assert captured["timeout"] == 60
    assert captured["headers"]["User-agent"] == "Mozilla/5.0 Demo"
    assert captured["headers"]["Referer"] == "https://www.douyin.com/video/7651428709099242127"
    assert captured["headers"]["Cookie"] == "ttwid=ttwid-demo; msToken=mstoken-demo"
