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

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

COMMON_CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")),
)
VIDEO_ID_RE = re.compile(r"/video/(\d+)")
KUKUTOOL_QUALITY_BUTTON_RE = re.compile(
    r"^下载\s*(?P<quality>.+?)\s*\((?P<size>[\d.]+)\s*(?P<unit>KB|MB|GB)\)$"
)


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

    def to_argv(self) -> list[str]:
        return [
            str(self.executable_path),
            f"--user-data-dir={self.user_data_dir}",
            f"--remote-debugging-port={self.remote_debugging_port}",
            "--new-window",
            "about:blank",
        ]


@dataclass(frozen=True)
class ChromeRemoteSession:
    host: str = "127.0.0.1"
    port: int = 9222

    def list_targets_url(self) -> str:
        return f"http://{self.host}:{self.port}/json/list"

    def get_active_page_url(self) -> str:
        with urlopen(self.list_targets_url()) as response:
            payload = json.loads(response.read().decode("utf-8"))

        for item in payload:
            if item.get("type") == "page" and item.get("url") and item["url"] != "about:blank":
                return item["url"]

        raise RuntimeError("No active page target found in Chrome remote session")

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
        scroll_rounds: int = 3,
        pause_ms: int = 500,
    ) -> list[str]:
        target_url = self.get_active_page_url()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                page = self._find_target_page(browser, target_url)
                if page is not None:
                    snapshots = [await page.content()]
                    for _ in range(scroll_rounds):
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(pause_ms)
                        snapshots.append(await page.content())
                    return snapshots
            finally:
                await browser.close()
        raise RuntimeError("No active browser page found for HTML snapshot capture")

    async def _fetch_douyin_aweme_detail_async(self, video_page_url: str) -> dict:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            page = None
            try:
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await context.new_page()
                async with page.expect_response(
                    lambda response: "/aweme/v1/web/aweme/detail/" in response.url,
                    timeout=15000,
                ) as response_info:
                    await page.goto(video_page_url, wait_until="domcontentloaded")
                response = await response_info.value
                return await response.json()
            finally:
                if page is not None:
                    await page.close()
                await browser.close()

    def fetch_active_page_html_snapshots(
        self,
        *,
        scroll_rounds: int = 3,
        pause_ms: int = 500,
    ) -> list[str]:
        return asyncio.run(
            self._fetch_active_page_html_snapshots_async(
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

    async def _parse_loaded_page_async(self, page, share_url: str) -> dict:
        clear_button = page.get_by_role("button", name="清除内容")
        if await clear_button.count():
            await clear_button.click()
        text_box = page.get_by_role("textbox", name="粘贴带链接的文本")
        await text_box.fill(share_url)
        await page.get_by_role("button", name="开始解析").click()
        await page.wait_for_timeout(300)
        try:
            await page.wait_for_function(
                """() => [...document.querySelectorAll('button')]
                    .some((button) => button.innerText.trim() === '处理中...' || button.disabled)""",
                timeout=5000,
            )
            await page.wait_for_function(
                """() => [...document.querySelectorAll('button')]
                    .some((button) => button.innerText.trim() === '开始解析' && !button.disabled)""",
                timeout=60000,
            )
        except PlaywrightTimeoutError as exc:
            page_text = (await page.locator("body").inner_text()).strip()
            raise RuntimeError(f"Kukutool 网页解析未完成: {page_text[-300:]}") from exc

        quality_buttons = page.locator("button")
        button_texts = [" ".join(text.split()) for text in await quality_buttons.all_text_contents()]
        if not any(self._parse_quality_button_text(text) is not None for text in button_texts):
            raise RuntimeError("Kukutool 网页解析完成，但未返回可下载的清晰度")

        entries: list[dict] = []
        copied_values: list[str] = []
        seen_qualities: set[str] = set()
        button_texts = [" ".join(text.split()) for text in await quality_buttons.all_text_contents()]
        for index, button_text in enumerate(button_texts):
            variant = self._parse_quality_button_text(button_text)
            if variant is None:
                continue
            quality_label = variant["type"]
            if quality_label in seen_qualities:
                continue
            seen_qualities.add(quality_label)
            copy_button = next(
                (
                    quality_buttons.nth(next_index)
                    for next_index in range(index + 1, len(button_texts))
                    if button_texts[next_index] == "复制"
                ),
                None,
            )
            if copy_button is None:
                continue
            await copy_button.click()
            await page.wait_for_timeout(500)
            download_url = await page.evaluate("navigator.clipboard.readText()")
            if not isinstance(download_url, str) or not download_url.startswith(("http://", "https://")):
                download_url = self._read_windows_clipboard()
            copied_values.append(str(download_url))
            if not isinstance(download_url, str) or not download_url.startswith(("http://", "https://")):
                continue
            entries.append({**variant, "url": download_url})
        if not entries:
            raise RuntimeError(
                "Kukutool 网页未提供可复制的视频下载链接: "
                + ", ".join(repr(value[:120]) for value in copied_values)
            )
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
                page = self._find_kukutool_page(browser, base_url)
                if page is None:
                    raise RuntimeError("请先在专用 Chrome 中打开 https://dy.kukutool.com，并保持该页面打开")
                await self._wait_for_user_to_clear_kukutool_gate(page)
                await page.context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin=f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}",
                )
                results: list[dict | Exception] = []
                for share_url in share_urls:
                    try:
                        results.append(await self._parse_loaded_page_async(page, share_url))
                    except Exception as exc:
                        results.append(exc)
            finally:
                await browser.close()
        return results

    @staticmethod
    def _find_kukutool_page(browser, base_url: str):
        host = urlparse(base_url).netloc
        for context in browser.contexts:
            for page in context.pages:
                if urlparse(page.url).netloc == host:
                    return page
        return None

    @staticmethod
    async def _wait_for_user_to_clear_kukutool_gate(page, *, timeout_seconds: int = 600) -> None:
        for _ in range(timeout_seconds):
            has_gate = await page.evaluate(
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
