from dataclasses import dataclass
import subprocess

from video2local.archive import ArchiveManager
from video2local.adapters.base import SourceDescriptor
from video2local.adapters.douyin import DouyinAdapter
from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession
from video2local.config import AppSettings
from video2local.downloader import YtDlpService
from video2local.storage import VideoRepository
from video2local.sync_engine import SyncEngine, SyncSummary


@dataclass
class AppRuntime:
    settings: AppSettings

    def __post_init__(self) -> None:
        self.adapter = DouyinAdapter()
        self.browser_session = ChromeRemoteSession()
        self.repository = VideoRepository(self.settings.paths.database_path)
        self.archive_manager = ArchiveManager(self.settings.paths.downloads_dir)
        self.downloader = YtDlpService()
        self.sync_engine = SyncEngine(
            repository=self.repository,
            downloader=self.downloader,
            archive_manager=self.archive_manager,
        )

    def ensure_directories(self) -> None:
        self.settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.repository.initialize()

    def launch_chrome(self) -> None:
        self.ensure_directories()
        launch_spec = ChromeLaunchSpec.detect(self.settings.paths.chrome_profile_dir)
        subprocess.Popen(launch_spec.to_argv())

    def get_current_source(self) -> SourceDescriptor:
        self.ensure_directories()
        page_url = self.browser_session.get_active_page_url()
        source = self.adapter.detect_source(page_url)
        if source is None:
            raise RuntimeError(f"Unsupported source page: {page_url}")
        return source

    def start_sync(self) -> SyncSummary:
        source = self.get_current_source()
        html = self.browser_session.fetch_active_page_html()
        candidate_urls = self.adapter.collect_candidate_urls(html)
        items = [
            self.downloader.probe_metadata(
                url=url,
                platform=source.platform,
                source_type=source.source_type,
                cookies_from_browser="chrome",
            )
            for url in candidate_urls
        ]
        return self.sync_engine.sync_items(items)
