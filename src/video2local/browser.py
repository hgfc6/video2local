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
        await self._wait_for_user_to_clear_kukutool_gate(page, base_url=base_url)
        clear_button = page.get_by_role("button", name="清除内容")
        if await clear_button.count():
            await clear_button.click()
        text_box = page.get_by_role("textbox", name="粘贴带链接的文本")
        await text_box.fill(share_url)
        await page.get_by_role("button", name="开始解析").click()
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
            for index, button_text in enumerate(button_texts):
                variant = self._parse_download_button_text(button_text)
                if variant is None:
                    continue
                quality_label = self._next_media_label(variant, media_counts)
                variant = {**variant, "type": quality_label}
                copy_button_text = "复制" if "size" in variant else "复制无水印链接"
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
                capture_index = await self._clipboard_capture_length(page) if capture_enabled else 0
                await copy_button.click()
                download_url = await self._wait_for_captured_url(page, capture_index) if capture_enabled else ""
                if not download_url:
                    download_url = await evaluate_with_navigation_retry(page, "navigator.clipboard.readText()")
                if not isinstance(download_url, str) or not download_url.startswith(("http://", "https://")):
                    download_url = self._read_windows_clipboard()
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
        return {
            "url": entries[-1]["url"],
            "videos": [{"url": entries[-1]["url"], "video_fullinfo": entries}],
        }

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
    def _next_media_label(variant: dict, media_counts: dict[str, int]) -> str:
        media_type = str(variant["type"])
        media_counts[media_type] = media_counts.get(media_type, 0) + 1
        ordinal = media_counts[media_type]
        if ordinal == 1:
            return media_type
        return f"{media_type} {ordinal}"

    @staticmethod
    def _keep_best_video_and_all_images(entries: list[dict]) -> list[dict]:
        images = [entry for entry in entries if "图片" in str(entry.get("type", "")) or "实况图" in str(entry.get("type", ""))]
        videos = [entry for entry in entries if entry not in images]
        best_video = max(videos, key=lambda entry: int(entry.get("size") or 0), default=None)
        return ([best_video] if best_video is not None else []) + images

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
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
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
                    raise RuntimeError("请先在专用 Chrome 中打开 Kukutool 首页，并保持“粘贴带链接的文本”和“开始解析”控件可见")
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
        """Return the already-open Kukutool page that has its parse form rendered."""
        host = urlparse(base_url).netloc
        for context in browser.contexts:
            for page in context.pages:
                if urlparse(page.url).netloc != host:
                    continue
                try:
                    text_box = page.get_by_role("textbox", name="粘贴带链接的文本")
                    parse_button = page.get_by_role("button", name="开始解析")
                    if await text_box.count() == 1 and await parse_button.count() == 1:
                        return page
                except PlaywrightError:
                    continue
        return None

    @staticmethod
    def _is_kukutool_page(page_url: str, base_url: str) -> bool:
        return urlparse(page_url).netloc == urlparse(base_url).netloc

    async def _wait_for_kukutool_page(self, page, *, base_url: str, timeout_seconds: int = 600) -> None:
        for _ in range(timeout_seconds):
            if self._is_kukutool_page(page.url, base_url):
                return
            await page.wait_for_timeout(1000)
        raise RuntimeError("Kukutool 页面仍停留在广告或验证页，请关闭该页面并回到 https://dy.kukutool.com 后重试")

    async def _wait_for_quality_results(self, page, *, base_url: str, timeout_seconds: int = 120) -> None:
        for _ in range(timeout_seconds):
            await self._wait_for_kukutool_page(page, base_url=base_url)
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

    async def _wait_for_user_to_clear_kukutool_gate(
        self,
        page,
        *,
        base_url: str,
        timeout_seconds: int = 600,
    ) -> None:
        for _ in range(timeout_seconds):
            await self._wait_for_kukutool_page(page, base_url=base_url)
            has_gate = await evaluate_with_navigation_retry(
                page,
                "() => Boolean(document.querySelector('.fc-dialog-overlay, .fc-message-root'))"
            )
            if not has_gate:
                return
            await page.wait_for_timeout(1000)
        raise RuntimeError("Kukutool 的广告或验证窗口仍未处理，请完成后重新解析")

    async def _parse_share_url_async(self, share_url: str, *, base_url: str) -> dict:
        result = (await self._parse_share_urls_async([share_url], base_url=base_url))[0]
        if isinstance(result, Exception):
            raise result
        return result

    def parse_share_url(self, share_url: str, *, base_url: str) -> dict:
        return asyncio.run(self._parse_share_url_async(share_url, base_url=base_url))

    def parse_share_urls(self, share_urls: list[str], *, base_url: str) -> list[dict | Exception]:
        return asyncio.run(self._parse_share_urls_async(share_urls, base_url=base_url))
