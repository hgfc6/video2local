from dataclasses import dataclass
import asyncio
import json
from pathlib import Path
import shutil
from urllib.request import urlopen

from playwright.async_api import async_playwright


@dataclass(frozen=True)
class ChromeLaunchSpec:
    executable_path: Path
    user_data_dir: Path
    remote_debugging_port: int

    @classmethod
    def detect(cls, user_data_dir: Path, remote_debugging_port: int = 9222) -> "ChromeLaunchSpec":
        chrome_path = shutil.which("chrome") or shutil.which("chrome.exe")
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
