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
            if item.get("type") == "page" and item.get("url"):
                return item["url"]

        raise RuntimeError("No active page target found in Chrome remote session")

    async def _fetch_active_page_html_async(self) -> str:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                for context in browser.contexts:
                    for page in context.pages:
                        if page.url and page.url != "about:blank":
                            return await page.content()
            finally:
                await browser.close()
        raise RuntimeError("No active browser page found for HTML capture")

    def fetch_active_page_html(self) -> str:
        return asyncio.run(self._fetch_active_page_html_async())

    async def _fetch_active_page_html_snapshots_async(
        self,
        *,
        scroll_rounds: int = 3,
        pause_ms: int = 500,
    ) -> list[str]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")
            try:
                for context in browser.contexts:
                    for page in context.pages:
                        if not page.url or page.url == "about:blank":
                            continue
                        snapshots = [await page.content()]
                        for _ in range(scroll_rounds):
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            await page.wait_for_timeout(pause_ms)
                            snapshots.append(await page.content())
                        return snapshots
            finally:
                await browser.close()
        raise RuntimeError("No active browser page found for HTML snapshot capture")

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
