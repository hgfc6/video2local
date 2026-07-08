from dataclasses import dataclass
import asyncio
import json
from pathlib import Path
import shutil
import os
from urllib.request import urlopen

from playwright.async_api import async_playwright

COMMON_CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")),
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
