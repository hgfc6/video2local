from dataclasses import dataclass
import os
import subprocess

from video2local.archive import ArchiveManager
from video2local.adapters.base import SourceDescriptor
from video2local.adapters.douyin import DouyinAdapter
from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession
from video2local.config import AppSettings
from video2local.downloader import YtDlpService
from video2local.domain import SampleDownloadResult, SyncProgress, SyncRunStatus
from video2local.storage import VideoRepository
from video2local.sync_engine import SyncEngine, SyncSummary


@dataclass
class AppRuntime:
    settings: AppSettings

    def __post_init__(self) -> None:
        self.adapter = DouyinAdapter()
        self.browser_session = ChromeRemoteSession()
        self.last_progress: SyncProgress | None = None
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
            if page_url.startswith("chrome://"):
                raise RuntimeError("请先在专用 Chrome 中打开抖音收藏页或作者作品页")
            if "douyin.com" in page_url:
                raise RuntimeError(
                    f"当前抖音页面不受支持，请先打开“我”的作品页或收藏页后再开始。当前页面: {page_url}"
                )
            raise RuntimeError(f"Unsupported source page: {page_url}")
        return source

    def validate_current_page(self) -> SourceDescriptor:
        return self.get_current_source()

    def start_sync(self) -> SyncSummary:
        source = self.get_current_source()
        run_id = self.repository.create_sync_run(platform=source.platform)
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        try:
            cookies_path = self.browser_session.export_cookies(
                self.settings.paths.data_dir / "yt-dlp-cookies.txt"
            )
            for html in self.browser_session.fetch_active_page_html_snapshots():
                for url in self.adapter.collect_candidate_urls(html):
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    candidate_urls.append(url)
            if not candidate_urls:
                raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")
            items = []
            seen_video_keys: set[tuple[str, str]] = set()
            for url in candidate_urls:
                if source.platform == "douyin":
                    try:
                        detail_payload = self.browser_session.fetch_douyin_aweme_detail(url)
                        metadata = self.adapter.parse_aweme_detail(
                            detail_payload,
                            source_type=source.source_type,
                            page_url=url,
                        )
                    except Exception:
                        metadata = self.downloader.probe_metadata(
                            url=url,
                            platform=source.platform,
                            source_type=source.source_type,
                            cookies_from_browser="chrome",
                            cookies_file=cookies_path,
                        )
                else:
                    metadata = self.downloader.probe_metadata(
                        url=url,
                        platform=source.platform,
                        source_type=source.source_type,
                        cookies_from_browser="chrome",
                        cookies_file=cookies_path,
                    )
                video_key = (metadata.platform, metadata.video_id)
                if video_key in seen_video_keys:
                    continue
                seen_video_keys.add(video_key)
                items.append(metadata)
            if not items:
                raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")
            summary = self.sync_engine.sync_items(
                items,
                progress_callback=self._store_progress,
                cookies_file=cookies_path,
            )
            self.repository.finish_sync_run(
                run_id=run_id,
                status=summary.status,
                discovered_count=summary.discovered_count,
                downloaded_count=summary.downloaded_count,
                skipped_count=summary.skipped_count,
                failed_count=summary.failed_count,
            )
            return summary
        except Exception as exc:
            self.repository.finish_sync_run(
                run_id=run_id,
                status=SyncRunStatus.FAILED.value,
                discovered_count=0,
                downloaded_count=0,
                skipped_count=0,
                failed_count=1,
                error_message=str(exc),
            )
            raise

    def stop_sync(self) -> None:
        self.sync_engine.request_stop()

    def get_latest_sync_run(self):
        self.ensure_directories()
        return self.repository.get_latest_sync_run()

    def open_downloads_dir(self) -> None:
        self.ensure_directories()
        os.startfile(str(self.settings.paths.downloads_dir))

    def download_first_visible_sample(self) -> SampleDownloadResult:
        self.ensure_directories()
        source = self.get_current_source()
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        for html in self.browser_session.fetch_active_page_html_snapshots():
            for url in self.adapter.collect_candidate_urls(html):
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                candidate_urls.append(url)
        if not candidate_urls:
            raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")

        first_url = candidate_urls[0]
        if source.platform == "douyin":
            detail_payload = self.browser_session.fetch_douyin_aweme_detail(first_url)
            metadata = self.adapter.parse_aweme_detail(
                detail_payload,
                source_type=source.source_type,
                page_url=first_url,
            )
        else:
            metadata = self.downloader.probe_metadata(
                url=first_url,
                platform=source.platform,
                source_type=source.source_type,
                cookies_from_browser="chrome",
            )

        target_dir = self.settings.paths.downloads_dir / "_smoke_test"
        target_dir.mkdir(parents=True, exist_ok=True)
        _, local_path = self.downloader.download(metadata, target_dir)
        return SampleDownloadResult(metadata=metadata, local_path=local_path)

    def _store_progress(self, progress: SyncProgress) -> None:
        self.last_progress = progress
