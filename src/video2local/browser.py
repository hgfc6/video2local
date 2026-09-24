from dataclasses import dataclass
import asyncio
import inspect
import json
import random
from pathlib import Path
import re
import shutil
import os
import string
import subprocess
from urllib.parse import urlparse
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

COMMON_CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")),
)
VIDEO_ID_RE = re.compile(r"/(?:video|note)/(\d+)")
KUKUTOOL_QUALITY_BUTTON_RE = re.compile(
    r"^下载\s*(?P<quality>.+?)\s*\((?P<size>[\d.]+)\s*(?P<unit>KB|MB|GB)\)$"
)
KUKUTOOL_MEDIA_BUTTON_RE = re.compile(r"^下载无水印(?P<media>视频|图片|实况图)$")
KUKUTOOL_FILE_SIZE_RE = re.compile(
    r"(?:文件大小|File size)\s*[:：]\s*(?P<size>[\d.]+)\s*(?P<unit>KB|MB|GB)",
    re.IGNORECASE,
)
KUKUTOOL_FILE_SIZE_LABEL_RE = re.compile(r"文件大小|File size", re.IGNORECASE)
KUKUTOOL_BARE_FILE_SIZE_RE = re.compile(r"(?P<size>[\d.]+)\s*(?P<unit>KB|MB|GB)", re.IGNORECASE)
KUKUTOOL_RESOLUTION_RE = re.compile(r"(?P<width>\d{3,5})\s*[×xX]\s*(?P<height>\d{3,5})")
KUKUTOOL_MORE_SIZES_DIALOG_TITLE_RE = re.compile(r"更多大小|More sizes", re.IGNORECASE)
KUKUTOOL_PARSE_BUTTON_RE = re.compile(r"^(开始解析|Parse Video)$", re.IGNORECASE)
KUKUTOOL_CLEAR_BUTTON_RE = re.compile(r"^(清除内容|Clear)$", re.IGNORECASE)
KUKUTOOL_MORE_SIZES_BUTTON_RE = re.compile(r"^(更多大小|More sizes)(?:\s*\(.+\))?$", re.IGNORECASE)
KUKUTOOL_COPY_LINK_BUTTON_RE = re.compile(r"^(?:复制(?:下载)?链接|复制|Copy(?:\s+(?:link|URL))?)$", re.IGNORECASE)
KUKUTOOL_NOTICE_DISMISS_BUTTON_RE = re.compile(
    r"7天内不[在再]提示|Don't show again(?: for)? 7 days", re.IGNORECASE
)
KUKUTOOL_NOTICE_CONTINUE_BUTTON_RE = re.compile(r"^(继续处理|Continue)$", re.IGNORECASE)
KUKUTOOL_COOKIE_CONSENT_BUTTON_RE = re.compile(r"^(同意|Consent)$", re.IGNORECASE)
KUKUTOOL_CAPTCHA_TEXT_RE = re.compile(r"验证码|人机验证|captcha|recaptcha|hcaptcha", re.IGNORECASE)


async def evaluate_with_navigation_retry(page, expression: str, *, attempts: int = 4):
    """Retry page scripts briefly when a navigation replaces the execution context."""
    last_error: PlaywrightError | None = None
    for attempt in range(attempts):
        try:
            return await page.evaluate(expression)
        except PlaywrightError as exc:
            if "execution context was destroyed" not in str(exc).lower():
                raise
            last_error = exc
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except PlaywrightError:
                pass
            await page.wait_for_timeout(300 * (attempt + 1))
    assert last_error is not None
    raise last_error


async def wait_for_function_with_navigation_retry(
    page,
    expression: str,
    *,
    timeout: int,
    attempts: int = 4,
) -> None:
    """Keep waiting when Kukutool replaces the page during its parse flow."""
    last_error: PlaywrightError | None = None
    for attempt in range(attempts):
        try:
            await page.wait_for_function(expression, timeout=timeout)
            return
        except PlaywrightError as exc:
            if "execution context was destroyed" not in str(exc).lower():
                raise
            last_error = exc
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except PlaywrightError:
                pass
            await page.wait_for_timeout(300 * (attempt + 1))
    assert last_error is not None
    raise last_error


def write_netscape_cookies(output_path: Path, cookies: list[dict]) -> None:
    lines = ["# Netscape HTTP Cookie File", ""]
    for cookie in cookies:
        name = cookie.get("name", "")
        if not name:
            continue
        domain = cookie["domain"]
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = cookie.get("path", "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = int(cookie.get("expires") or 0)
        if expires < 0:
            expires = 0
        value = cookie["value"]
        lines.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ChromeLaunchSpec:
    executable_path: Path
    user_data_dir: Path
    remote_debugging_port: int

    @classmethod
    def detect(cls, user_data_dir: Path, remote_debugging_port: int = 9222) -> "ChromeLaunchSpec":
        chrome_path = shutil.which("chrome") or shutil.which("chrome.exe")
        if chrome_path is None:
            for candidate in COMMON_CHROME_PATHS:
                if candidate.exists():
                    chrome_path = str(candidate)
                    break
        if chrome_path is None:
            raise FileNotFoundError("Chrome executable not found in PATH")
        return cls(
            executable_path=Path(chrome_path),
            user_data_dir=user_data_dir,
            remote_debugging_port=remote_debugging_port,
        )

    def to_argv(self, start_urls: tuple[str, ...] = ("about:blank",)) -> list[str]:
        return [
            str(self.executable_path),
            f"--user-data-dir={self.user_data_dir}",
            f"--remote-debugging-port={self.remote_debugging_port}",
            "--new-window",
            *start_urls,
        ]


@dataclass(frozen=True)
class ChromeRemoteSession:
    host: str = "127.0.0.1"
    port: int = 9222

    def list_targets_url(self) -> str:
        return f"http://{self.host}:{self.port}/json/list"

    def list_page_urls(self) -> list[str]:
        with urlopen(self.list_targets_url(), timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [
            item["url"]
            for item in payload
            if item.get("type") == "page" and item.get("url") and item["url"] != "about:blank"
        ]

    def get_active_page_url(self) -> str:
        page_urls = self.list_page_urls()
        if page_urls:
            return page_urls[0]
        raise RuntimeError("No page target found in Chrome remote session")

    def _find_target_page(self, browser, target_url: str):
        fallback_page = None
        for context in browser.contexts:
            for page in context.pages:
                if not page.url or page.url == "about:blank":
                    continue
                if page.url == target_url:
                    return page
                if fallback_page is None:
                    fallback_page = page
        return fallback_page

    @staticmethod
    def _find_douyin_page(browser):
        for context in browser.contexts:
            for page in context.pages:
                host = urlparse(page.url).netloc.lower()
                if host in {"douyin.com", "www.douyin.com"}:
                    return page
        return None

    async def _fetch_active_page_html_async(self) -> str:
        target_url = self.get_active_page_url()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                page = self._find_target_page(browser, target_url)
                if page is not None:
                    return await page.content()
            finally:
                await browser.close()
        raise RuntimeError("No active browser page found for HTML capture")

    async def _export_cookies_async(self, output_path: Path) -> Path:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                cookies: list[dict] = []
                for context in browser.contexts:
                    cookies.extend(await context.cookies())
            finally:
                await browser.close()
        write_netscape_cookies(output_path, cookies)
        return output_path

    def fetch_active_page_html(self) -> str:
        return asyncio.run(self._fetch_active_page_html_async())

    async def _fetch_active_page_html_snapshots_async(
        self,
        *,
        target_url: str | None = None,
        scroll_rounds: int = 3,
        pause_ms: int = 500,
    ) -> list[str]:
        target_url = target_url or self.get_active_page_url()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                page = self._find_target_page(browser, target_url)
                if page is not None:
                    snapshots = [await page.content()]
                    for _ in range(scroll_rounds):
                        await evaluate_with_navigation_retry(page, "window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(pause_ms)
                        snapshots.append(await page.content())
                    return snapshots
            finally:
                await browser.close()
        raise RuntimeError("No active browser page found for HTML snapshot capture")

    async def _fetch_douyin_aweme_detail_async(self, video_page_url: str) -> dict:
        match = VIDEO_ID_RE.search(video_page_url)
        if match is None:
            raise RuntimeError(f"未能从作品链接提取作品 ID: {video_page_url}")
        aweme_id = match.group(1)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                page = self._find_douyin_page(browser)
                if page is None:
                    raise RuntimeError("请在专用 Chrome 中保持抖音收藏页或博主作品页打开")
                payload = await page.evaluate(
                    """async (id) => {
                        const response = await fetch(
                            `/aweme/v1/web/aweme/detail/?aweme_id=${encodeURIComponent(id)}`,
                            { credentials: 'include' },
                        );
                        if (!response.ok) {
                            throw new Error(`detail fetch failed: ${response.status}`);
                        }
                        return await response.json();
                    }""",
                    aweme_id,
                )
                if not isinstance(payload, dict) or not payload.get("aweme_detail"):
                    raise RuntimeError("抖音未返回作品详情")
                return payload
            finally:
                await browser.close()

    def fetch_active_page_html_snapshots(
        self,
        *,
        target_url: str | None = None,
        scroll_rounds: int = 3,
        pause_ms: int = 500,
    ) -> list[str]:
        return asyncio.run(
            self._fetch_active_page_html_snapshots_async(
                target_url=target_url,
                scroll_rounds=scroll_rounds,
                pause_ms=pause_ms,
            )
        )

    def export_cookies(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return asyncio.run(self._export_cookies_async(output_path))

    def fetch_douyin_aweme_detail(self, video_page_url: str) -> dict:
        return asyncio.run(self._fetch_douyin_aweme_detail_async(video_page_url))


@dataclass(frozen=True)
class DouyinPublicSession:
    chrome_executable_path: Path | None = None

    def _resolve_executable_path(self) -> Path:
        if self.chrome_executable_path is not None:
            return self.chrome_executable_path
        return ChromeLaunchSpec.detect(Path.cwd()).executable_path

    async def _fetch_share_aweme_detail_async(self, share_url: str) -> tuple[str, dict]:
        executable_path = self._resolve_executable_path()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path=str(executable_path),
                headless=True,
            )
            page = await browser.new_page()
            try:
                await page.goto(share_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(2000)
                canonical_url = page.url
                match = VIDEO_ID_RE.search(canonical_url)
                if match is None:
                    raise RuntimeError(f"未能从分享链接解析出视频页: {canonical_url}")
                aweme_id = match.group(1)
                api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}"
                raw_text = await page.evaluate(
                    """async (url) => {
                        const response = await fetch(url, { credentials: 'include' });
                        if (!response.ok) {
                            throw new Error(`detail fetch failed: ${response.status}`);
                        }
                        return await response.text();
                    }""",
                    api_url,
                )
                return canonical_url, json.loads(raw_text)
            finally:
                await browser.close()

    def fetch_share_aweme_detail(self, share_url: str) -> tuple[str, dict]:
        return asyncio.run(self._fetch_share_aweme_detail_async(share_url))

    def probe_content_length(self, url: str) -> int | None:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urlopen(request, timeout=60) as response:
                value = response.headers.get("Content-Length")
        except Exception:
            return None
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None


@dataclass(frozen=True)
class DouyinSignedSession(DouyinPublicSession):
    """Experimental signed-api entrypoint.

    The real signed request flow may evolve later. For now this class gives the
    runtime a dedicated higher-priority path and keeps public parsing as a
    fallback.
    """

    @staticmethod
    def _gen_false_ms_token(length: int = 182) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(random.choice(alphabet) for _ in range(length)) + "=="

    @staticmethod
    def _gen_verify_fp() -> str:
        alphabet = string.ascii_lowercase + string.digits
        timestamp = format(int(time.time() * 1000), "x")
        suffix = "".join(random.choice(alphabet) for _ in range(24))
        return f"verify_{timestamp}_{suffix}"

    def _generate_a_bogus(self, params: dict[str, str], user_agent: str) -> str | None:
        return None

    def _build_signed_detail_url(self, aweme_id: str, user_agent: str) -> str:
        params = {
            "aweme_id": aweme_id,
            "aid": "6383",
            "channel": "channel_pc_web",
            "device_platform": "webapp",
            "pc_client_type": "1",
            "pc_libra_divert": "Windows",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "100",
            "verifyFp": self._gen_verify_fp(),
            "msToken": self._gen_false_ms_token(),
        }
        query = urlencode(params)
        a_bogus = self._generate_a_bogus(params, user_agent)
        if a_bogus:
            query = f"{query}&a_bogus={a_bogus}"
        return f"https://www.douyin.com/aweme/v1/web/aweme/detail/?{query}"

    @staticmethod
    def _build_cookie_header(cookies: list[dict]) -> str:
        pairs = []
        for cookie in cookies:
            name = cookie.get("name")
            if not name:
                continue
            pairs.append(f"{name}={cookie.get('value', '')}")
        return "; ".join(pairs)

    def _fetch_detail_over_http(
        self,
        *,
        aweme_id: str,
        user_agent: str,
        cookies: list[dict],
        referer: str,
    ) -> dict:
        detail_url = self._build_signed_detail_url(aweme_id, user_agent)
        headers = {
            "User-Agent": user_agent,
            "Referer": referer,
        }
        cookie_header = self._build_cookie_header(cookies)
        if cookie_header:
            headers["Cookie"] = cookie_header
        request = Request(detail_url, headers=headers)
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _try_fetch_detail_over_http_async(
        self,
        page,
        *,
        aweme_id: str,
        referer: str,
    ) -> dict | None:
        try:
            user_agent = await page.evaluate("() => navigator.userAgent")
            cookies = await page.context.cookies()
        except Exception:
            return None
        try:
            payload = await asyncio.to_thread(
                self._fetch_detail_over_http,
                aweme_id=aweme_id,
                user_agent=user_agent,
                cookies=cookies,
                referer=referer,
            )
        except Exception:
            return None
        return payload if isinstance(payload, dict) and payload.get("aweme_detail") else None

    async def _goto_and_capture_detail_response_async(
        self,
        page,
        *,
        target_url: str,
        response_matcher,
    ) -> dict | None:
        try:
            async with page.expect_response(response_matcher, timeout=15000) as response_info:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            response = response_info.value
            if inspect.isawaitable(response):
                response = await response
            return await response.json()
        except PlaywrightTimeoutError:
            return None

    async def _fetch_share_aweme_detail_async(self, share_url: str) -> tuple[str, dict]:
        executable_path = self._resolve_executable_path()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path=str(executable_path),
                headless=True,
            )
            page = await browser.new_page()
            try:
                payload = await self._goto_and_capture_detail_response_async(
                    page,
                    target_url=share_url,
                    response_matcher=lambda response: "/aweme/v1/web/aweme/detail/" in response.url,
                )
                await page.wait_for_timeout(2000)
                canonical_url = page.url
                match = VIDEO_ID_RE.search(canonical_url)
                if match is None:
                    raise RuntimeError(f"未能从分享链接解析出视频页: {canonical_url}")
                aweme_id = match.group(1)
                http_payload = await self._try_fetch_detail_over_http_async(
                    page,
                    aweme_id=aweme_id,
                    referer=canonical_url,
                )
                if http_payload is not None:
                    return canonical_url, http_payload
                if payload is None:
                    payload = await self._goto_and_capture_detail_response_async(
                        page,
                        target_url=canonical_url,
                        response_matcher=lambda response: (
                            "/aweme/v1/web/aweme/detail/" in response.url
                            and f"aweme_id={aweme_id}" in response.url
                        ),
                    )
                if payload is None:
                    raise RuntimeError("未能捕获抖音详情接口响应")
                return canonical_url, payload
            finally:
                await browser.close()


@dataclass(frozen=True)
class KukutoolSession(DouyinPublicSession):
    host: str = "127.0.0.1"
    port: int = 9222

    async def _parse_loaded_page_async(self, page, share_url: str, *, base_url: str) -> dict:
        await self._dismiss_kukutool_ad_popup(page)
        await self._wait_for_user_to_clear_kukutool_gate(page, base_url=base_url)
        clear_button = page.get_by_role("button", name=KUKUTOOL_CLEAR_BUTTON_RE)
        if await clear_button.count():
            await clear_button.click()
            await self._wait_for_previous_results_to_clear(page, base_url=base_url)
        text_box = await self._wait_for_kukutool_input(page)
        await text_box.fill(share_url)
        await page.get_by_role("button", name=KUKUTOOL_PARSE_BUTTON_RE).click()
        await page.wait_for_timeout(300)
        await self._wait_for_user_to_clear_kukutool_gate(page, base_url=base_url)
        try:
            await self._wait_for_quality_results(page, base_url=base_url)
        except PlaywrightTimeoutError as exc:
            page_text = await evaluate_with_navigation_retry(page, "document.body.innerText")
            page_text = str(page_text).strip()
            raise RuntimeError(f"Kukutool 网页解析未完成: {page_text[-300:]}") from exc

        # A mixed post can render its video controls first and image controls a moment later.
        await page.wait_for_timeout(500)

        quality_buttons = page.locator("button")
        button_texts = [" ".join(text.split()) for text in await quality_buttons.all_text_contents()]
        if not any(self._parse_download_button_text(text) is not None for text in button_texts):
            raise RuntimeError("Kukutool 网页解析完成，但未返回可下载的清晰度")

        entries: list[dict] = []
        copied_values: list[str] = []
        media_counts: dict[str, int] = {}
        capture_enabled = await self._install_clipboard_capture(page)
        try:
            button_texts = [" ".join(text.split()) for text in await quality_buttons.all_text_contents()]
            more_sizes_entries = await self._read_more_sizes_entries(page, capture_enabled)
            if more_sizes_entries:
                # More sizes covers unrelated page controls. Its table already
                # contains every available video version, so do not inspect
                # lower-priority buttons behind the dialog.
                entries.extend(more_sizes_entries)
            else:
                fallback_video_index = self._select_standard_video_button(button_texts)
                for index, button_text in enumerate(button_texts):
                    variant = self._parse_download_button_text(button_text)
                    if variant is None:
                        continue
                    if not self._is_image_or_live_photo(variant):
                        if fallback_video_index is None or index != fallback_video_index:
                            continue
                    quality_label = self._next_media_label(variant, media_counts)
                    variant = {**variant, "type": quality_label}
                    copy_button_text = "复制" if "size" in variant else "复制无水印链接"
                    copy_button = await self._find_copy_button_for_download(
                        quality_buttons.nth(index),
                        copy_button_text=copy_button_text,
                    )
                    if copy_button is None:
                        copy_button = next(
                            (
                                quality_buttons.nth(next_index)
                                for next_index in range(index + 1, len(button_texts))
                                if button_texts[next_index] == copy_button_text
                            ),
                            None,
                        )
                    if copy_button is None:
                        continue
                    download_url = await self._copy_download_url(page, copy_button, capture_enabled)
                    copied_values.append(str(download_url))
                    if not isinstance(download_url, str) or not download_url.startswith(("http://", "https://")):
                        continue
                    entries.append({**variant, "url": download_url})
        finally:
            if capture_enabled:
                await self._restore_clipboard_capture(page)
        if not entries:
            raise RuntimeError(
                "Kukutool 网页未提供可复制的视频下载链接: "
                + ", ".join(repr(value[:120]) for value in copied_values)
            )
        entries = self._keep_best_video_and_all_images(entries)
        best_video_url = next(
            (entry["url"] for entry in entries if not self._is_image_or_live_photo(entry)),
            entries[0]["url"],
        )
        return {
            "url": best_video_url,
            "videos": [{"url": best_video_url, "video_fullinfo": entries}],
        }

    @staticmethod
    async def _find_copy_button_for_download(download_button, *, copy_button_text: str):
        """Find the copy action in the same Kukutool media card as its download action."""
        container = download_button
        for _ in range(7):
            container = container.locator("xpath=..")
            copy_buttons = container.get_by_role("button", name=copy_button_text)
            if await copy_buttons.count() == 1:
                return copy_buttons.first
        return None

    async def _read_more_sizes_entries(self, page, capture_enabled: bool) -> list[dict]:
        """Copy all video rows from the optional More sizes result dialog."""
        if not await self._click_more_sizes_button(page):
            return []
        dialog_text = await self._wait_for_more_sizes_dialog_or_notice(page)
        if self._is_usage_notice(dialog_text):
            if not await self._dismiss_usage_notice(page):
                return []
            await self._wait_for_usage_notice_to_clear(page)
            # The preference click starts the large-file request. The More sizes
            # button changes to "获取中…" for several seconds before the dialog appears.
            dialog_text = await self._wait_for_more_sizes_dialog_or_notice(page, timeout_seconds=45)
            if not await self._has_more_sizes_dialog(page):
                if not await self._click_more_sizes_button(page):
                    return []
                dialog_text = await self._wait_for_more_sizes_dialog_or_notice(page, timeout_seconds=45)
            if self._is_usage_notice(dialog_text):
                # The preference button can be delayed by a site animation. Continue is
                # only a fallback after the left-hand preference control was attempted.
                continue_button = page.get_by_role("button", name=KUKUTOOL_NOTICE_CONTINUE_BUTTON_RE)
                if await continue_button.count():
                    await continue_button.first.click()
                    await self._wait_for_usage_notice_to_clear(page)
                    dialog_text = await self._wait_for_more_sizes_dialog_or_notice(page, timeout_seconds=45)
                    if not await self._has_more_sizes_dialog(page):
                        if not await self._click_more_sizes_button(page):
                            return []
                        dialog_text = await self._wait_for_more_sizes_dialog_or_notice(page, timeout_seconds=45)
        dialog = await self._find_more_sizes_dialog(page)
        if dialog is None:
            return []
        copy_button = dialog.get_by_role("button", name=KUKUTOOL_COPY_LINK_BUTTON_RE)
        if not await copy_button.count():
            copy_button = dialog.locator("button").filter(has_text=KUKUTOOL_COPY_LINK_BUTTON_RE)
        if not await copy_button.count():
            return []
        entries: list[dict] = []
        for index in range(await copy_button.count()):
            current_copy_button = copy_button.nth(index)
            row_text = await self._more_sizes_row_text(current_copy_button)
            variant = self._parse_more_sizes_row(row_text, index=index)
            download_url = await self._copy_download_url(page, current_copy_button, capture_enabled)
            if not isinstance(download_url, str) or not download_url.startswith(("http://", "https://")):
                continue
            entries.append({**variant, "url": download_url})
        await self._close_more_sizes_dialog(page, dialog)
        return entries

    @staticmethod
    async def _close_more_sizes_dialog(page, dialog=None) -> None:
        """Release the modal so the next work can reach its More sizes button."""
        if dialog is None:
            dialog = await KukutoolSession._find_more_sizes_dialog(page)
        if dialog is None:
            return
        close = dialog.get_by_role("button", name=re.compile(r"^(关闭|Close)$", re.IGNORECASE))
        if not await close.count():
            close = dialog.locator("button").filter(has_text=re.compile(r"^(关闭|Close)$", re.IGNORECASE))
        if not await close.count():
            return
        try:
            await close.last.click(timeout=5000)
            await dialog.wait_for(state="hidden", timeout=5000)
        except PlaywrightError:
            # The copied URL is still valid; a later clear action can recover the page.
            return

    @staticmethod
    async def _find_more_sizes_dialog(page):
        """Find the visible result dialog by content, not a framework-specific class."""
        dialogs = page.locator(
            "[role='dialog'], [aria-modal='true'], div.fixed.inset-0, .modal, .dialog"
        ).filter(has_text=KUKUTOOL_MORE_SIZES_DIALOG_TITLE_RE)
        for index in range(await dialogs.count()):
            dialog = dialogs.nth(index)
            if await dialog.is_visible() and KukutoolSession._is_more_sizes_dialog(await dialog.inner_text()):
                return dialog

        # Kukutool has changed modal markup before. Start from the visible
        # title, then walk up its ancestors so this remains independent of the
        # current dialog framework and CSS class names.
        titles = page.get_by_text(KUKUTOOL_MORE_SIZES_DIALOG_TITLE_RE, exact=True)
        for index in range(await titles.count()):
            node = titles.nth(index)
            if not await node.is_visible():
                continue
            for _ in range(8):
                node = node.locator("xpath=..")
                try:
                    text = await node.inner_text(timeout=1000)
                except PlaywrightError:
                    break
                if KukutoolSession._is_more_sizes_dialog(text):
                    return node
        return None

    async def _has_more_sizes_dialog(self, page) -> bool:
        return await self._find_more_sizes_dialog(page) is not None

    async def _click_more_sizes_button(self, page) -> bool:
        await self._dismiss_kukutool_anchor_ad(page)
        more_sizes = page.get_by_role("button", name=KUKUTOOL_MORE_SIZES_BUTTON_RE)
        if not await more_sizes.count():
            more_sizes = page.locator("button").filter(has_text=KUKUTOOL_MORE_SIZES_BUTTON_RE)
        if not await more_sizes.count():
            return False
        await more_sizes.first.click(timeout=5000)
        return True

    @staticmethod
    async def _dismiss_usage_notice(page) -> bool:
        dismiss = page.get_by_role("button", name=KUKUTOOL_NOTICE_DISMISS_BUTTON_RE)
        if not await dismiss.count():
            dismiss = page.locator("button").filter(has_text=KUKUTOOL_NOTICE_DISMISS_BUTTON_RE)
        if not await dismiss.count():
            return False
        await dismiss.first.click(timeout=5000)
        return True

    async def _wait_for_usage_notice_to_clear(self, page, *, timeout_seconds: int = 10) -> None:
        for _ in range(timeout_seconds * 10):
            page_text = str(await evaluate_with_navigation_retry(page, "document.body.innerText"))
            if not self._is_usage_notice(page_text):
                return
            await page.wait_for_timeout(100)
        raise RuntimeError("Kukutool 使用提示未关闭，请手动关闭后重试")

    async def _copy_download_url(self, page, copy_button, capture_enabled: bool) -> str:
        capture_index = await self._clipboard_capture_length(page) if capture_enabled else 0
        existing_pages = tuple(page.context.pages)
        await copy_button.click()
        await self._close_copy_popups(page, existing_pages)
        download_url = await self._wait_for_captured_url(page, capture_index) if capture_enabled else ""
        if not download_url:
            download_url = await evaluate_with_navigation_retry(page, "navigator.clipboard.readText()")
        if not isinstance(download_url, str) or not download_url.startswith(("http://", "https://")):
            download_url = self._read_windows_clipboard()
        return str(download_url)

    @staticmethod
    async def _close_copy_popups(page, existing_pages: tuple) -> None:
        """Close pages opened by a copy control while preserving the user's work tabs."""
        existing_page_ids = {id(item) for item in existing_pages}
        for _ in range(4):
            popups_closed = False
            for candidate in list(page.context.pages):
                if candidate is page or id(candidate) in existing_page_ids:
                    continue
                try:
                    if await candidate.opener() is not page:
                        continue
                    await candidate.close()
                    popups_closed = True
                except PlaywrightError:
                    continue
            if not popups_closed:
                await page.wait_for_timeout(100)
                continue
            # A site can open a redirect page just after its first blank popup.
            await page.wait_for_timeout(100)

    @staticmethod
    def _parse_quality_button_text(button_text: str) -> dict | None:
        match = KUKUTOOL_QUALITY_BUTTON_RE.match(button_text.strip())
        if match is None:
            return None
        size = float(match.group("size"))
        unit = match.group("unit")
        multiplier = {"KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024}[unit]
        return {"type": match.group("quality"), "size": int(size * multiplier)}

    @classmethod
    def _parse_download_button_text(cls, button_text: str) -> dict | None:
        quality_variant = cls._parse_quality_button_text(button_text)
        if quality_variant is not None:
            return quality_variant
        match = KUKUTOOL_MEDIA_BUTTON_RE.match(button_text.strip())
        if match is None:
            return None
        return {"type": f"无水印{match.group('media')}"}

    @staticmethod
    def _parse_file_size(text: str) -> int | None:
        match = KUKUTOOL_FILE_SIZE_RE.search(text)
        if match is None:
            match = KUKUTOOL_BARE_FILE_SIZE_RE.search(text)
        if match is None:
            return None
        multiplier = {"KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024}
        return int(float(match.group("size")) * multiplier[match.group("unit").upper()])

    @staticmethod
    async def _more_sizes_row_text(copy_button) -> str:
        """Read the smallest ancestor that identifies the copy button's video row."""
        return str(
            await copy_button.evaluate(
                """button => {
                    const resolution = /\\d{3,5}\\s*[×xX]\\s*\\d{3,5}/;
                    const size = /\\d+(?:\\.\\d+)?\\s*(?:KB|MB|GB)/i;
                    let node = button.parentElement;
                    let fallback = '';
                    while (node && node.parentElement) {
                        const text = (node.innerText || '').trim();
                        if (text && !fallback) fallback = text;
                        if (resolution.test(text) && size.test(text)) return text;
                        node = node.parentElement;
                    }
                    return fallback;
                }"""
            )
        )

    @classmethod
    def _parse_more_sizes_row(cls, text: str, *, index: int) -> dict:
        size = cls._parse_file_size(text)
        resolution = KUKUTOOL_RESOLUTION_RE.search(text)
        if resolution is None:
            label = "更多大小" if index == 0 else f"更多大小 {index + 1}"
        else:
            label = f"{min(int(resolution.group('width')), int(resolution.group('height')))}p"
        entry = {"type": label}
        if size is not None:
            entry["size"] = size
        return entry

    @staticmethod
    def _next_media_label(variant: dict, media_counts: dict[str, int]) -> str:
        media_type = str(variant["type"])
        media_counts[media_type] = media_counts.get(media_type, 0) + 1
        ordinal = media_counts[media_type]
        if ordinal == 1:
            return media_type
        return f"{media_type} {ordinal}"

    @staticmethod
    def _keep_best_video_and_all_images(entries: list[dict]) -> list[dict]:
        images = [entry for entry in entries if KukutoolSession._is_image_or_live_photo(entry)]
        videos = [entry for entry in entries if entry not in images]
        best_video = max(videos, key=lambda entry: int(entry.get("size") or 0), default=None)
        return ([best_video] if best_video is not None else []) + images

    @staticmethod
    def _is_image_or_live_photo(entry: dict) -> bool:
        media_type = str(entry.get("type", ""))
        return "图片" in media_type or "实况图" in media_type

    @classmethod
    def _select_standard_video_button(cls, button_texts: list[str]) -> int | None:
        """Use 1080p then 720p only when More sizes did not return a link."""
        parsed = [cls._parse_download_button_text(text) for text in button_texts]
        for quality in ("1080p", "720p"):
            for index, variant in enumerate(parsed):
                if variant is not None and str(variant["type"]).lower() == quality:
                    return index
        candidates = [
            (index, variant)
            for index, variant in enumerate(parsed)
            if variant is not None and not cls._is_image_or_live_photo(variant)
        ]
        return max(candidates, key=lambda item: int(item[1].get("size") or 0), default=(None, None))[0]

    @staticmethod
    def _quality_result_wait_expression() -> str:
        return """() => [...document.querySelectorAll('button')]
            .some((button) => /^下载\\s*.+?\\s*\\([\\d.]+\\s*(KB|MB|GB)\\)$/.test(button.innerText.trim())
                || /^下载无水印(视频|图片|实况图)$/.test(button.innerText.trim()))"""

    @staticmethod
    async def _install_clipboard_capture(page) -> bool:
        return bool(
            await evaluate_with_navigation_retry(
                page,
                """() => {
                    const clipboard = navigator.clipboard;
                    if (!clipboard || typeof clipboard.writeText !== 'function') return false;
                    const key = '__video2localClipboardCapture';
                    const existing = window[key];
                    if (existing) existing.values.length = 0;
                    else {
                        const original = clipboard.writeText.bind(clipboard);
                        const state = { original, values: [] };
                        clipboard.writeText = async (value) => { state.values.push(String(value)); };
                        window[key] = state;
                    }
                    return true;
                }""",
            )
        )

    @staticmethod
    async def _clipboard_capture_length(page) -> int:
        value = await evaluate_with_navigation_retry(
            page,
            "() => window.__video2localClipboardCapture?.values.length || 0",
        )
        return int(value)

    @staticmethod
    async def _wait_for_captured_url(page, start_index: int, *, timeout_seconds: int = 3) -> str:
        for _ in range(timeout_seconds * 10):
            value = await evaluate_with_navigation_retry(
                page,
                f"""() => (window.__video2localClipboardCapture?.values || [])
                    .slice({start_index})
                    .find((value) => /^https?:\\/\\//.test(value)) || ''""",
            )
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
            await page.wait_for_timeout(100)
        return ""

    @staticmethod
    async def _restore_clipboard_capture(page) -> None:
        await evaluate_with_navigation_retry(
            page,
            """() => {
                const state = window.__video2localClipboardCapture;
                if (!state || !navigator.clipboard) return;
                navigator.clipboard.writeText = state.original;
                delete window.__video2localClipboardCapture;
            }""",
        )

    @staticmethod
    def _read_windows_clipboard() -> str:
        """Kukutool's copy button writes to the system clipboard on Windows."""
        try:
            process_kwargs = (
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                if os.name == "nt"
                else {}
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
                **process_kwargs,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    async def _parse_share_urls_async(self, share_urls: list[str], *, base_url: str) -> list[dict | Exception]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                page = await self._find_kukutool_page(browser, base_url)
                if page is None:
                    raise RuntimeError("请先在专用 Chrome 中打开 Kukutool 首页，并保持“开始解析”按钮可见")
                await self._wait_for_user_to_clear_kukutool_gate(page, base_url=base_url)
                await page.context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin=f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}",
                )
                results: list[dict | Exception] = []
                for share_url in share_urls:
                    try:
                        results.append(await self._parse_loaded_page_async(page, share_url, base_url=base_url))
                    except Exception as exc:
                        results.append(exc)
            finally:
                await browser.close()
        return results

    @staticmethod
    async def _find_kukutool_page(browser, base_url: str):
        """Return the existing Kukutool page, including a transient ad insert."""
        host = urlparse(base_url).netloc
        for context in browser.contexts:
            for page in context.pages:
                if urlparse(page.url).netloc != host:
                    continue
                # Google vignette keeps Kukutool's host but removes its document.
                # Return this page so the normal gate handler can navigate back.
                if KukutoolSession._is_google_vignette(page.url):
                    return page
                try:
                    parse_button = page.get_by_role("button", name=KUKUTOOL_PARSE_BUTTON_RE)
                    if await parse_button.count():
                        return page
                except PlaywrightError:
                    continue
        return None

    @staticmethod
    async def _wait_for_kukutool_input(page, *, timeout_seconds: int = 15):
        """Locate Kuku's dynamic input without relying on its changing ARIA name."""
        selector = "textarea, input:not([type]), input[type='text'], [contenteditable='true']"
        for _ in range(timeout_seconds * 10):
            text_boxes = page.locator(selector)
            if await text_boxes.count():
                return text_boxes.nth(0)
            await page.wait_for_timeout(100)
        raise RuntimeError("Kukutool 页面未加载链接输入框，请等待页面加载完成后重试")

    @staticmethod
    def _is_kukutool_page(page_url: str, base_url: str) -> bool:
        return urlparse(page_url).netloc == urlparse(base_url).netloc

    @staticmethod
    def _is_google_vignette(page_url: str) -> bool:
        return urlparse(page_url).fragment.lower() == "google_vignette"

    async def _wait_for_kukutool_page(self, page, *, base_url: str, timeout_seconds: int = 600) -> None:
        for _ in range(timeout_seconds):
            if self._is_google_vignette(page.url):
                await self._dismiss_kukutool_ad_popup(page)
                await page.wait_for_timeout(300)
                continue
            if self._is_kukutool_page(page.url, base_url):
                return
            await page.wait_for_timeout(1000)
        raise RuntimeError("Kukutool 页面仍停留在广告或验证页，请关闭该页面并回到 https://dy.kukutool.com 后重试")

    async def _wait_for_quality_results(self, page, *, base_url: str, timeout_seconds: int = 120) -> None:
        for _ in range(timeout_seconds):
            await self._wait_for_kukutool_page(page, base_url=base_url)
            if await self._dismiss_kukutool_ad_popup(page):
                await page.wait_for_timeout(300)
                continue
            try:
                await wait_for_function_with_navigation_retry(
                    page,
                    self._quality_result_wait_expression(),
                    timeout=1000,
                    attempts=2,
                )
                return
            except PlaywrightTimeoutError:
                continue
        raise PlaywrightTimeoutError("Kukutool quality results did not appear before timeout")

    async def _wait_for_previous_results_to_clear(
        self,
        page,
        *,
        base_url: str,
        timeout_seconds: int = 10,
    ) -> None:
        """Avoid treating the prior work's download buttons as the next result."""
        for _ in range(timeout_seconds * 10):
            await self._wait_for_kukutool_page(page, base_url=base_url)
            has_results = await evaluate_with_navigation_retry(
                page,
                self._quality_result_wait_expression(),
            )
            if not has_results:
                return
            await page.wait_for_timeout(100)
        raise RuntimeError("Kukutool 未清除上一条作品的解析结果，请点击“清除内容”后重试")

    async def _wait_for_user_to_clear_kukutool_gate(
        self,
        page,
        *,
        base_url: str,
        timeout_seconds: int = 600,
    ) -> None:
        for _ in range(timeout_seconds):
            await self._wait_for_kukutool_page(page, base_url=base_url)
            await self._dismiss_kukutool_ad_popup(page)
            has_gate = await evaluate_with_navigation_retry(
                page,
                "() => Boolean(document.querySelector('.fc-dialog-overlay, .fc-message-root'))"
            )
            if not has_gate:
                return
            await page.wait_for_timeout(1000)
        raise RuntimeError("Kukutool 的广告或验证窗口仍未处理，请完成后重新解析")

    async def _wait_for_more_sizes_dialog_or_notice(self, page, *, timeout_seconds: int = 20) -> str:
        for _ in range(timeout_seconds * 5):
            text = str(await evaluate_with_navigation_retry(page, "document.body.innerText"))
            if self._is_usage_notice(text) or await self._has_more_sizes_dialog(page):
                return text
            await page.wait_for_timeout(200)
        return ""

    @staticmethod
    def _is_usage_notice(text: str) -> bool:
        return "Usage notice" in text or "使用提示" in text

    @staticmethod
    def _is_more_sizes_dialog(text: str) -> bool:
        if KUKUTOOL_MORE_SIZES_DIALOG_TITLE_RE.search(text) is None:
            return False
        return KUKUTOOL_FILE_SIZE_RE.search(text) is not None or (
            KUKUTOOL_RESOLUTION_RE.search(text) is not None
            and KUKUTOOL_BARE_FILE_SIZE_RE.search(text) is not None
        )

    async def _dismiss_kukutool_ad_popup(self, page) -> bool:
        """Dismiss only generic first-page advertisements, never verification or size dialogs."""
        if self._is_google_vignette(page.url):
            try:
                await page.go_back(wait_until="domcontentloaded", timeout=5000)
                return True
            except PlaywrightError:
                return False
        page_text = str(await evaluate_with_navigation_retry(page, "document.body.innerText"))
        if self._is_usage_notice(page_text) or await self._has_more_sizes_dialog(page):
            return False
        if await self._has_visible_kukutool_captcha(page):
            return False
        consent = page.get_by_role("button", name=KUKUTOOL_COOKIE_CONSENT_BUTTON_RE)
        if await consent.count():
            try:
                await consent.first.click(timeout=1000)
                return True
            except PlaywrightError:
                return False
        try:
            await page.keyboard.press("Escape")
        except PlaywrightError:
            pass
        close_controls = page.locator(
            "button[aria-label*='close' i], [role='button'][aria-label*='close' i], "
            "button[aria-label*='关闭'], [role='button'][aria-label*='关闭'], "
            "button[aria-label*='collapse' i], [role='button'][aria-label*='collapse' i], "
            "button[aria-label*='收起'], [role='button'][aria-label*='收起'], "
            "[title*='close' i], [title*='关闭'], [title*='collapse' i], [title*='收起']"
        )
        if await close_controls.count():
            try:
                await close_controls.last.click(timeout=1000)
                return True
            except PlaywrightError:
                return False
        icon_close_controls = page.get_by_text(re.compile(r"^(×|✕)$"))
        if await icon_close_controls.count():
            try:
                await icon_close_controls.last.click(timeout=1000)
                return True
            except PlaywrightError:
                return False
        return await self._dismiss_kukutool_anchor_ad(page)

    @staticmethod
    async def _has_visible_kukutool_captcha(page) -> bool:
        """Do not mistake Kukutool's FAQ text for an active verification dialog."""
        dialog = page.locator(".fc-dialog-overlay, .fc-message-root").filter(
            has_text=KUKUTOOL_CAPTCHA_TEXT_RE
        )
        for index in range(await dialog.count()):
            if await dialog.nth(index).is_visible():
                return True
        return False

    @staticmethod
    async def _dismiss_kukutool_anchor_ad(page) -> bool:
        """Drag the visible Google anchor-ad handle down, as a user would."""
        handle = page.locator("ins[data-anchor-shown='true'] .grippy-host")
        if not await handle.count():
            return False
        box = await handle.first.bounding_box()
        viewport_height = await evaluate_with_navigation_retry(page, "window.innerHeight")
        if box is None or box["y"] >= float(viewport_height):
            return False
        center_x = box["x"] + box["width"] / 2
        center_y = box["y"] + box["height"] / 2
        try:
            await page.mouse.move(center_x, center_y)
            await page.mouse.down()
            await page.mouse.move(center_x, float(viewport_height) + 100, steps=12)
            await page.mouse.up()
            await page.wait_for_timeout(300)
            return True
        except PlaywrightError:
            try:
                await page.mouse.up()
            except PlaywrightError:
                pass
            return False

    async def _parse_share_url_async(self, share_url: str, *, base_url: str) -> dict:
        result = (await self._parse_share_urls_async([share_url], base_url=base_url))[0]
        if isinstance(result, Exception):
            raise result
        return result

    def parse_share_url(self, share_url: str, *, base_url: str) -> dict:
        return asyncio.run(self._parse_share_url_async(share_url, base_url=base_url))

    def parse_share_urls(self, share_urls: list[str], *, base_url: str) -> list[dict | Exception]:
        return asyncio.run(self._parse_share_urls_async(share_urls, base_url=base_url))
