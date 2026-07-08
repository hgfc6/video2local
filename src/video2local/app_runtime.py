from dataclasses import dataclass
import subprocess

from video2local.adapters.base import SourceDescriptor
from video2local.adapters.douyin import DouyinAdapter
from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession
from video2local.config import AppSettings


@dataclass
class AppRuntime:
    settings: AppSettings

    def __post_init__(self) -> None:
        self.adapter = DouyinAdapter()
        self.browser_session = ChromeRemoteSession()

    def ensure_directories(self) -> None:
        self.settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.downloads_dir.mkdir(parents=True, exist_ok=True)

    def launch_chrome(self) -> None:
        self.ensure_directories()
        launch_spec = ChromeLaunchSpec.detect(self.settings.paths.chrome_profile_dir)
        subprocess.Popen(launch_spec.to_argv())

    def start_sync(self) -> SourceDescriptor:
        self.ensure_directories()
        page_url = self.browser_session.get_active_page_url()
        source = self.adapter.detect_source(page_url)
        if source is None:
            raise RuntimeError(f"Unsupported source page: {page_url}")
        return source
