from dataclasses import dataclass
from dataclasses import replace
import os
from pathlib import Path
import subprocess

from video2local.archive import ArchiveManager
from video2local.adapters.base import SourceDescriptor
from video2local.adapters.douyin import DouyinAdapter
from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession, DouyinPublicSession, DouyinSignedSession, KukutoolSession
from video2local.config import AppSettings
from video2local.downloader import YtDlpService
from video2local.domain import SampleDownloadResult, ShareParseResult, ShareVariantDownloadResult, SourceType, SyncPreviewItem, SyncPreviewResult, SyncProgress, SyncQualityStrategy, SyncRunStatus, VideoMetadata, VideoVariant
from video2local.resolvers import KukutoolResolver, NativeDouyinResolver, ResolverChain
from video2local.sync_engine import SyncEngine, SyncSummary


@dataclass
class AppRuntime:
    settings: AppSettings

    def __post_init__(self) -> None:
        self.adapter = DouyinAdapter()
        self.browser_session = ChromeRemoteSession()
        self.signed_session = DouyinSignedSession()
        self.public_session = DouyinPublicSession()
        self.share_resolver = self._build_share_resolver_chain()
        self.last_progress: SyncProgress | None = None
        self.output_root = self.settings.paths.downloads_dir
        self.sync_limit: int | None = None
        self.retry_count: int = 1
        self.quality_strategy = SyncQualityStrategy.BEST_AVAILABLE
        self.flat_output = False
        self._latest_sync_run: dict | None = None
        self.archive_manager = ArchiveManager(self.settings.paths.downloads_dir)
        self.downloader = YtDlpService()
        self.sync_engine = SyncEngine(
            repository=None,
            downloader=self.downloader,
            archive_manager=self.archive_manager,
        )

    def ensure_directories(self) -> None:
        self.settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def set_output_root(self, output_root: Path) -> None:
        self.output_root = output_root
        self.archive_manager.download_root = output_root

    def set_flat_output(self, enabled: bool) -> None:
        self.flat_output = enabled
        self.archive_manager.flatten_into_root = enabled

    def set_sync_limit(self, limit: int | None) -> None:
        self.sync_limit = None if limit is None or limit <= 0 else limit

    def set_retry_count(self, retry_count: int | None) -> None:
        if retry_count is None or retry_count < 0:
            self.retry_count = 0
            return
        self.retry_count = retry_count

    def set_quality_strategy(self, strategy: str) -> None:
        self.quality_strategy = SyncQualityStrategy(strategy)

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
        try:
            cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
            candidate_urls = self._collect_candidate_urls()
            items = self._iter_sync_items(
                source=source,
                cookies_path=cookies_path,
                candidate_urls=candidate_urls,
            )
            summary = self.sync_engine.sync_items(
                items,
                progress_callback=self._store_progress,
                cookies_file=cookies_path,
                retry_count=self.retry_count,
                report_dir=self.output_root / "_sync_reports",
                discovered_count=len(candidate_urls),
            )
            self._latest_sync_run = {
                "status": summary.status,
                "discovered_count": summary.discovered_count,
                "downloaded_count": summary.downloaded_count,
                "skipped_count": summary.skipped_count,
                "failed_count": summary.failed_count,
                "report_path": summary.report_path,
            }
            return summary
        except Exception as exc:
            self._latest_sync_run = {
                "status": SyncRunStatus.FAILED.value,
                "discovered_count": 0,
                "downloaded_count": 0,
                "skipped_count": 0,
                "failed_count": 1,
                "error_message": str(exc),
            }
            raise

    def preview_sync(self) -> SyncPreviewResult:
        source = self.get_current_source()
        cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
        items: list[SyncPreviewItem] = []
        seen_video_keys: set[tuple[str, str]] = set()
        for url in self._collect_candidate_urls():
            preview_item = self._build_preview_item(
                page_url=url,
                source=source,
                cookies_path=cookies_path,
            )
            video_key = (preview_item.metadata.platform, preview_item.metadata.video_id)
            if video_key in seen_video_keys:
                continue
            seen_video_keys.add(video_key)
            items.append(preview_item)
        if not items:
            raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")
        return SyncPreviewResult(source=source, items=items)

    def stop_sync(self) -> None:
        self.sync_engine.request_stop()

    def get_latest_sync_run(self):
        self.ensure_directories()
        return self._latest_sync_run

    def open_downloads_dir(self) -> None:
        self.ensure_directories()
        os.startfile(str(self.output_root))

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

        target_dir = self.output_root / "_smoke_test"
        target_dir.mkdir(parents=True, exist_ok=True)
        _, local_path = self.downloader.download(metadata, target_dir)
        return SampleDownloadResult(metadata=metadata, local_path=local_path)

    def parse_share_text(self, raw_text: str) -> ShareParseResult:
        self.ensure_directories()
        share_url = self.adapter.extract_share_url(raw_text)
        resolution = self.share_resolver.resolve(share_url)
        metadata = self.adapter.parse_aweme_detail(
            resolution.payload,
            source_type=SourceType.SHARE_LINK,
            page_url=resolution.canonical_url,
        )
        variants = self.adapter.parse_share_variants(resolution.payload)
        if not variants:
            raise RuntimeError("未解析到可下载版本")
        variants = [
            replace(
                variant,
                file_size=variant.file_size or self.public_session.probe_content_length(variant.download_url),
            )
            for variant in variants
        ]
        return ShareParseResult(
            provider_id=resolution.provider_id,
            source_url=share_url,
            canonical_url=resolution.canonical_url,
            metadata=metadata,
            variants=variants,
        )

    def download_share_variant(
        self,
        parse_result: ShareParseResult,
        variant_id: str,
    ) -> ShareVariantDownloadResult:
        self.ensure_directories()
        variant = next((item for item in parse_result.variants if item.variant_id == variant_id), None)
        if variant is None:
            raise RuntimeError(f"未找到要下载的清晰度版本: {variant_id}")
        metadata = replace(parse_result.metadata, download_url=variant.download_url)
        if self.flat_output:
            target_dir = self.output_root
        else:
            target_dir = (
                self.output_root
                / self.archive_manager.safe_name(metadata.platform)
                / self.archive_manager.safe_name(metadata.author_name)
            )
        target_dir.mkdir(parents=True, exist_ok=True)
        filename_stem = self.archive_manager.build_filename_stem(
            video_id=metadata.video_id,
            title=metadata.title,
            suffix=variant.quality_label,
        )
        file_ext, local_path = self.downloader.download(
            metadata,
            target_dir,
            filename_stem=filename_stem,
        )
        return ShareVariantDownloadResult(
            metadata=parse_result.metadata,
            variant=variant,
            local_path=local_path,
        )

    def _store_progress(self, progress: SyncProgress) -> None:
        self.last_progress = progress

    def _build_sync_items(self, *, source: SourceDescriptor, cookies_path: Path) -> list[VideoMetadata]:
        items: list[VideoMetadata] = []
        seen_video_keys: set[tuple[str, str]] = set()
        for url in self._collect_candidate_urls():
            preview_item = self._build_preview_item(
                page_url=url,
                source=source,
                cookies_path=cookies_path,
            )
            video_key = (preview_item.metadata.platform, preview_item.metadata.video_id)
            if video_key in seen_video_keys:
                continue
            seen_video_keys.add(video_key)
            items.append(preview_item.metadata)
        if not items:
            raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")
        return items

    def _iter_sync_items(
        self,
        *,
        source: SourceDescriptor,
        cookies_path: Path,
        candidate_urls: list[str],
    ):
        seen_video_keys: set[tuple[str, str]] = set()
        yielded = 0
        for url in candidate_urls:
            preview_item = self._build_preview_item(
                page_url=url,
                source=source,
                cookies_path=cookies_path,
            )
            video_key = (preview_item.metadata.platform, preview_item.metadata.video_id)
            if video_key in seen_video_keys:
                continue
            seen_video_keys.add(video_key)
            yielded += 1
            yield preview_item.metadata
        if yielded == 0:
            raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")

    def _collect_candidate_urls(self) -> list[str]:
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        for html in self.browser_session.fetch_active_page_html_snapshots():
            for url in self.adapter.collect_candidate_urls(html):
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                candidate_urls.append(url)
        if self.sync_limit is not None:
            candidate_urls = candidate_urls[: self.sync_limit]
        return candidate_urls

    def _build_preview_item(
        self,
        *,
        page_url: str,
        source: SourceDescriptor,
        cookies_path: Path,
    ) -> SyncPreviewItem:
        if source.platform == "douyin":
            metadata, provider_id, selected_variant = self._resolve_douyin_sync_metadata(
                page_url=page_url,
                source_type=source.source_type,
                cookies_path=cookies_path,
            )
            return SyncPreviewItem(
                provider_id=provider_id,
                metadata=metadata,
                selected_quality_label=None if selected_variant is None else selected_variant.quality_label,
                selected_file_size=None if selected_variant is None else selected_variant.file_size,
            )
        metadata = self.downloader.probe_metadata(
            url=page_url,
            platform=source.platform,
            source_type=source.source_type,
            cookies_from_browser="chrome",
            cookies_file=cookies_path,
        )
        return SyncPreviewItem(
            provider_id="native",
            metadata=metadata,
            selected_quality_label=None,
            selected_file_size=None,
        )

    def _resolve_douyin_sync_metadata(
        self,
        *,
        page_url: str,
        source_type: SourceType,
        cookies_path: Path,
    ) -> tuple[VideoMetadata, str, VideoVariant | None]:
        if self.settings.share_resolvers.enable_kukutool_fallback:
            try:
                resolution = self.share_resolver.resolve(page_url)
                metadata = self.adapter.parse_aweme_detail(
                    resolution.payload,
                    source_type=source_type,
                    page_url=resolution.canonical_url,
                )
                variants = self.adapter.parse_share_variants(resolution.payload)
                selected_variant = self._select_sync_variant(variants)
                if selected_variant is not None:
                    metadata = replace(metadata, download_url=selected_variant.download_url)
                return metadata, resolution.provider_id, selected_variant
            except Exception:
                pass
        try:
            detail_payload = self.browser_session.fetch_douyin_aweme_detail(page_url)
            metadata = self.adapter.parse_aweme_detail(
                detail_payload,
                source_type=source_type,
                page_url=page_url,
            )
            variants = self.adapter.parse_share_variants(detail_payload)
            selected_variant = self._select_sync_variant(variants)
            if selected_variant is not None:
                metadata = replace(metadata, download_url=selected_variant.download_url)
            return metadata, "native", selected_variant
        except Exception:
            metadata = self.downloader.probe_metadata(
                url=page_url,
                platform="douyin",
                source_type=source_type,
                cookies_from_browser="chrome",
                cookies_file=cookies_path,
            )
            return metadata, "native", None

    def _build_share_resolver_chain(self) -> ResolverChain:
        if self.settings.share_resolvers.enable_kukutool_fallback:
            resolvers: list[object] = [
                KukutoolResolver(
                    settings=self.settings,
                    kukutool_session=KukutoolSession(
                        user_data_dir=self.settings.paths.chrome_profile_dir / "kukutool-profile",
                    ),
                    signed_session=self.signed_session,
                    public_session=self.public_session,
                ),
                NativeDouyinResolver(
                    settings=self.settings,
                    signed_session=self.signed_session,
                    public_session=self.public_session,
                ),
            ]
            return ResolverChain(resolvers)
        resolvers = [
            NativeDouyinResolver(
                settings=self.settings,
                signed_session=self.signed_session,
                public_session=self.public_session,
            )
        ]
        return ResolverChain(resolvers)

    def _safe_file_size(self, local_path: str) -> int | None:
        try:
            return Path(local_path).stat().st_size
        except OSError:
            return None

    def _select_sync_variant(self, variants: list[VideoVariant]) -> VideoVariant | None:
        if not variants:
            return None
        if self.quality_strategy == SyncQualityStrategy.BEST_AVAILABLE:
            return variants[0]
        if self.quality_strategy == SyncQualityStrategy.PREFER_ULTRA:
            for variant in variants:
                if variant.quality_label == "超高清":
                    return variant
            return variants[0]
        if self.quality_strategy == SyncQualityStrategy.PREFER_1080P:
            for variant in variants:
                if variant.quality_label == "1080p":
                    return variant
            return variants[0]
        return variants[0]
