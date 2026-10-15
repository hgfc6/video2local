from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from html import unescape
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable

from video2local.archive import ArchiveManager
from video2local.adapters.base import SourceDescriptor
from video2local.adapters.bilibili import BilibiliAdapter
from video2local.adapters.douyin import DouyinAdapter
from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession, DouyinPublicSession, DouyinSignedSession, KukutoolSession
from video2local.config import AppSettings
from video2local.downloader import YtDlpService
from video2local.domain import RuntimeActivity, SampleDownloadResult, ShareParseResult, ShareVariantDownloadResult, SkippedSyncItem, SourceType, SyncPreviewItem, SyncPreviewResult, SyncProgress, SyncRunStatus, VideoMetadata, VideoVariant
from video2local.resolvers import CdnDouyinResolver, KukutoolResolver, NativeDouyinResolver, ResolverChain
from video2local.sync_engine import SyncEngine, SyncSummary


@dataclass
class AppRuntime:
    settings: AppSettings

    def __post_init__(self) -> None:
        self.adapter = DouyinAdapter()
        self.bilibili_adapter = BilibiliAdapter()
        self.browser_session = ChromeRemoteSession()
        self.signed_session = DouyinSignedSession()
        self.public_session = DouyinPublicSession()
        self.resolver_sources = tuple(self.settings.share_resolvers.enabled_sources)
        self.share_resolver = self._build_share_resolver_chain()
        self.last_progress: SyncProgress | None = None
        self.last_activity: RuntimeActivity | None = None
        self.output_root = self.settings.paths.downloads_dir
        self.output_root_selected = False
        self.sync_limit: int | None = None
        self.active_platform: str | None = None
        self.retry_count: int = 1
        self.flat_output = False
        self._latest_sync_run: dict | None = None
        self._douyin_card_hints: dict[str, tuple[str, str]] = {}
        self.last_resolution_diagnostics: dict[str, object] = {}
        self.collision_policy = "skip"
        self.archive_manager = ArchiveManager(self.settings.paths.downloads_dir)
        self.downloader = YtDlpService()
        self.downloader.archive_manager = self.archive_manager
        self.sync_engine = SyncEngine(
            repository=None,
            downloader=self.downloader,
            archive_manager=self.archive_manager,
        )

    def ensure_directories(self) -> None:
        self.settings.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings.paths.chrome_profile_dir.mkdir(parents=True, exist_ok=True)

    def set_output_root(self, output_root: Path) -> None:
        self.output_root = output_root
        self.output_root_selected = True
        self.archive_manager.download_root = output_root

    def set_flat_output(self, enabled: bool) -> None:
        self.flat_output = enabled
        self.archive_manager.flatten_into_root = enabled

    def set_collision_policy(self, policy: str) -> None:
        if policy not in {"skip", "overwrite", "timestamp"}:
            raise ValueError("不支持的同名文件处理方式")
        self.collision_policy = policy
        self.sync_engine.set_collision_policy(policy)

    def set_sync_limit(self, limit: int | None) -> None:
        self.sync_limit = None if limit is None or limit <= 0 else limit

    def set_retry_count(self, retry_count: int | None) -> None:
        if retry_count is None or retry_count < 0:
            self.retry_count = 0
            return
        self.retry_count = retry_count

    def set_resolver_sources(self, sources: tuple[str, ...]) -> None:
        normalized = tuple(dict.fromkeys(item for item in sources if item))
        if not normalized:
            raise ValueError("至少保留一个解析来源")
        self.resolver_sources = normalized
        self.share_resolver = self._build_share_resolver_chain()

    def set_active_platform(self, platform: str) -> None:
        if platform not in {"douyin", "bilibili"}:
            raise ValueError(f"不支持的平台工作台: {platform}")
        self.active_platform = platform

    def launch_chrome(self) -> None:
        self.ensure_directories()
        launch_spec = ChromeLaunchSpec.detect(self.settings.paths.chrome_profile_dir)
        subprocess.Popen(
            launch_spec.to_argv(
                (
                    "https://www.douyin.com/user/self?from_tab_name=main&showSubTab=video&showTab=favorite_collection",
                    self.settings.share_resolvers.kukutool_base_url,
                )
            )
        )

    def get_current_source(self) -> SourceDescriptor:
        self.ensure_directories()
        try:
            fallback_page_url = self.browser_session.get_active_page_url()
            listed_page_urls = self.browser_session.list_page_urls()
            page_urls = listed_page_urls if fallback_page_url in listed_page_urls else [fallback_page_url]
        except Exception:
            # Keep test doubles and older Chrome sessions usable when the full target list is unavailable.
            page_urls = [self.browser_session.get_active_page_url()]
        all_sources = [
            source
            for page_url in page_urls
            for adapter in (self.adapter, self.bilibili_adapter)
            if (source := adapter.detect_source(page_url)) is not None
        ]
        sources = all_sources
        if self.active_platform is not None:
            sources = [source for source in sources if source.platform == self.active_platform]
        if len(sources) == 1:
            return sources[0]
        if len(sources) > 1:
            raise RuntimeError("检测到多个可同步内容页，请只保留当前工作台对应的一个收藏页或作品页后重试")
        active_platform_domain = {
            "douyin": "douyin.com",
            "bilibili": "bilibili.com",
        }.get(self.active_platform or "")
        if active_platform_domain and any(active_platform_domain in page_url for page_url in page_urls):
            platform_name = "抖音" if self.active_platform == "douyin" else "Bilibili"
            raise RuntimeError(f"当前 {platform_name} 页面不受支持，请打开收藏夹或 UP 主投稿页后再开始")
        if all_sources and self.active_platform is not None:
            platform_name = "抖音" if all_sources[0].platform == "douyin" else "Bilibili"
            raise RuntimeError(f"当前工作台为其他平台，请先切换到 {platform_name}")
        page_url = page_urls[0] if page_urls else ""
        if not page_url or page_url.startswith("chrome://"):
                raise RuntimeError("请先在专用 Chrome 中打开受支持平台的收藏页或作者作品页")
        if "douyin.com" in page_url:
            raise RuntimeError(
                f"当前抖音页面不受支持，请先打开“我”的作品页或收藏页后再开始。当前页面: {page_url}"
            )
        if "bilibili.com" in page_url:
            raise RuntimeError("当前 Bilibili 页面不受支持，请打开 UP 主投稿页或收藏夹后再开始")
        raise RuntimeError(f"Unsupported source page: {page_url}")

    def validate_current_page(self) -> SourceDescriptor:
        return self.get_current_source()

    def start_sync(self) -> SyncSummary:
        self._set_activity(operation="sync", stage="正在检查当前页面")
        source = self.get_current_source()
        try:
            self._set_activity(operation="sync", stage="正在导出浏览器登录信息")
            cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
            self._set_activity(operation="sync", stage="正在扫描页面作品")
            candidate_urls = self._collect_candidate_urls(source)
            self._set_activity(
                operation="sync",
                stage="已发现作品，准备逐条解析并下载",
                total_count=len(candidate_urls),
            )
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
                report_dir=self.output_root,
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
        self._set_activity(operation="preview", stage="正在检查当前页面")
        source = self.get_current_source()
        self._set_activity(operation="preview", stage="正在导出浏览器登录信息")
        cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
        self._set_activity(operation="preview", stage="正在扫描页面作品")
        candidate_urls = self._collect_candidate_urls(source)
        self._set_activity(
            operation="preview",
            stage="已发现作品，准备解析清晰度",
            total_count=len(candidate_urls),
        )
        kukutool_resolutions = (
            self._resolve_kukutool_preview_candidates(candidate_urls)
            if source.platform == "douyin"
            else {}
        )
        items: list[SyncPreviewItem] = []
        skipped_items: list[SkippedSyncItem] = []
        seen_video_keys: set[tuple[str, str]] = set()
        for index, url in enumerate(candidate_urls, start=1):
            self._set_activity(
                operation="preview",
                stage="正在解析作品元数据",
                completed_count=index - 1,
                total_count=len(candidate_urls),
                current_url=url,
            )
            try:
                preview_item = self._build_preview_item(
                    page_url=url,
                    source=source,
                    cookies_path=cookies_path,
                    kukutool_resolution=kukutool_resolutions.get(url),
                )
            except Exception as exc:
                skipped_items.append(self._build_skipped_item(source, url, exc, stage="preview_metadata"))
                continue
            video_key = (preview_item.metadata.platform, preview_item.metadata.video_id)
            if video_key in seen_video_keys:
                continue
            seen_video_keys.add(video_key)
            items.append(preview_item)
        if not items and not skipped_items:
            raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")
        report_path = (
            self.sync_engine.write_skipped_items_report(skipped_items, self.output_root)
            if self.output_root_selected
            else None
        )
        return SyncPreviewResult(
            source=source,
            items=items,
            skipped_items=skipped_items,
            report_path=report_path,
        )

    def clear_activity(self) -> None:
        self.last_activity = None

    def _resolve_kukutool_preview_candidates(self, candidate_urls: list[str]) -> dict[str, object]:
        if not self._is_kukutool_enabled():
            return {}
        resolver = next(
            (item for item in self.share_resolver.resolvers if isinstance(item, KukutoolResolver)),
            None,
        )
        if resolver is None:
            return {}
        # Native note metadata exposes the original image URLs directly. Avoid
        # third-party image parsing here: its copy controls can create popup
        # pages and return short-lived image URLs.
        video_urls = [url for url in candidate_urls if "/note/" not in url]
        if not video_urls:
            return {}
        return resolver.resolve_variants_only_many(
            video_urls,
            progress_callback=lambda completed, total, url: self._set_activity(
                operation="preview",
                stage="正在通过 Kukutool 解析清晰度",
                completed_count=completed,
                total_count=total,
                current_url=url,
            ),
        )

    def stop_sync(self) -> None:
        self.sync_engine.request_stop()

    def get_latest_sync_run(self):
        self.ensure_directories()
        return self._latest_sync_run

    def build_diagnostics(self) -> str:
        """Return shareable state only; do not include cookies or signed download URLs."""
        lines = [
            "Video2Local 诊断信息",
            f"生成时间: {datetime.now().isoformat(timespec='seconds')}",
            f"当前工作台: {self.active_platform or '-'}",
            f"输出目录: {self.output_root}",
            f"平铺输出: {'是' if self.flat_output else '否'}",
            f"同名文件处理: {self.collision_policy}",
            f"抖音解析来源: {', '.join(self.resolver_sources) or '-'}",
        ]
        if self.last_activity is not None:
            lines.append(f"当前活动: {self.last_activity.operation} / {self.last_activity.stage}")
            lines.append(f"当前链接: {self.last_activity.current_url or '-'}")
        if self.last_progress is not None:
            lines.append(
                "最近同步进度: "
                f"处理 {self.last_progress.processed_count}/{self.last_progress.discovered_count}，"
                f"下载 {self.last_progress.downloaded_count}，失败 {self.last_progress.failed_count}"
            )
        resolution = self.last_resolution_diagnostics
        if resolution:
            lines.append(f"最近解析页面: {resolution.get('page_url', '-')}")
            lines.append(f"最近解析来源: {' + '.join(resolution.get('sources', [])) or '-'}")
            lines.append(f"最近解析版本数: {resolution.get('variant_count', 0)}")
            errors = resolution.get("errors", [])
            lines.append(f"最近解析错误: {'；'.join(errors) if errors else '-'}")
        try:
            page_urls = self.browser_session.list_page_urls()
            lines.append(f"专用 Chrome 页面数: {len(page_urls)}")
            kukutool_host = self.settings.share_resolvers.kukutool_base_url.split("//", 1)[-1].split("/", 1)[0]
            lines.append(f"Kukutool 页面: {'已检测到' if any(kukutool_host in url for url in page_urls) else '未检测到'}")
        except Exception as exc:
            lines.append(f"专用 Chrome 状态: 未连接 ({exc})")
        return "\n".join(lines)

    def open_downloads_dir(self) -> None:
        self.ensure_directories()
        os.startfile(str(self.output_root))

    def download_first_visible_sample(self) -> SampleDownloadResult:
        self.ensure_directories()
        self._clear_download_stop_request()
        source = self.get_current_source()
        cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        for url in self._collect_candidate_urls(source):
            if url not in seen_urls:
                seen_urls.add(url)
                candidate_urls.append(url)
        if not candidate_urls:
            raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")

        first_url = candidate_urls[0]
        preview_item = self._build_preview_item(
            page_url=first_url,
            source=source,
            cookies_path=cookies_path,
        )
        selected_variants = self._select_sync_variants(
            preview_item.variants,
            page_url=preview_item.metadata.page_url,
        )
        selected_variant = selected_variants[0] if selected_variants else None
        metadata = (
            self._metadata_for_variant(preview_item.metadata, selected_variant)
            if selected_variant is not None
            else preview_item.metadata
        )

        target_dir = self.output_root / "_smoke_test"
        target_dir.mkdir(parents=True, exist_ok=True)
        _, local_path = self._download_with_collision(
            metadata,
            target_dir,
            cookies_file=cookies_path,
        )
        return SampleDownloadResult(metadata=metadata, local_path=local_path)

    def parse_share_text(self, raw_text: str) -> ShareParseResult:
        self.ensure_directories()
        if self._is_bilibili_share_text(raw_text):
            return self._parse_bilibili_share_text(raw_text)
        share_url = self.adapter.extract_share_url(raw_text)
        return self._parse_douyin_share_text(share_url)

    def _parse_douyin_share_text(self, share_url: str) -> ShareParseResult:
        canonical_url, metadata, provider_summary, variants = self._resolve_douyin_variants(
            page_url=share_url,
            source_type=SourceType.SHARE_LINK,
            native_detail_loader=lambda: self._load_native_douyin_share_detail(share_url),
        )
        return ShareParseResult(
            provider_id=provider_summary,
            source_url=share_url,
            canonical_url=canonical_url,
            metadata=metadata,
            variants=variants,
        )

    def download_share_variant(
        self,
        parse_result: ShareParseResult,
        variant_id: str,
    ) -> ShareVariantDownloadResult:
        self.ensure_directories()
        self._clear_download_stop_request()
        variant = next((item for item in parse_result.variants if item.variant_id == variant_id), None)
        if variant is None:
            raise RuntimeError(f"未找到要下载的清晰度版本: {variant_id}")
        metadata = self._metadata_for_variant(parse_result.metadata, variant)
        if self.flat_output:
            target_dir = self.output_root
        else:
            target_dir = (
                self.output_root
                / self.archive_manager.safe_name(metadata.platform)
                / self.archive_manager.build_author_directory_name(metadata)
            )
        target_dir.mkdir(parents=True, exist_ok=True)
        if self._is_image_variant(variant):
            image_variants = [item for item in parse_result.variants if self._is_image_variant(item)]
            local_paths: list[str] = []
            for index, image_variant in enumerate(image_variants, start=1):
                image_metadata = replace(
                    self._metadata_for_variant(metadata, image_variant),
                    video_id=f"{metadata.video_id}-{index:03d}",
                    media_type="live_photo" if "实况图" in image_variant.quality_label else "image",
                )
                _, local_path = self._download_with_collision(image_metadata, target_dir)
                local_paths.append(local_path)
            local_path = "; ".join(local_paths)
        else:
            filename_stem = self.archive_manager.build_filename_stem(
                video_id=metadata.video_id,
                title=metadata.title,
                author_name=metadata.author_name,
                suffix=variant.quality_label,
            )
            _, local_path = self._download_with_collision(
                metadata,
                target_dir,
                cookies_file=self._export_browser_cookies() if metadata.platform == "bilibili" else None,
                filename_stem=filename_stem,
                format_selector=variant.format_selector,
            )
        return ShareVariantDownloadResult(
            metadata=parse_result.metadata,
            variant=variant,
            local_path=local_path,
        )

    def _is_bilibili_share_text(self, raw_text: str) -> bool:
        lowered = raw_text.lower()
        return "bilibili.com" in lowered or "b23.tv" in lowered

    def _parse_bilibili_share_text(self, raw_text: str) -> ShareParseResult:
        share_url = self.bilibili_adapter.extract_share_url(raw_text)
        payload = self.downloader.probe_video_info(
            url=share_url,
            cookies_file=self._export_browser_cookies(),
        )
        metadata, variants = self.bilibili_adapter.parse_video_info(
            payload,
            source_type=SourceType.SHARE_LINK,
            source_url=share_url,
        )
        if not variants:
            raise RuntimeError("哔哩哔哩视频未返回可下载格式，请检查链接、登录态或权限限制")
        return ShareParseResult(
            provider_id="native",
            source_url=share_url,
            canonical_url=metadata.page_url,
            metadata=metadata,
            variants=variants,
        )

    def _export_browser_cookies(self) -> Path | None:
        """Use dedicated Chrome cookies when available, but keep public parsing usable."""
        try:
            return self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
        except Exception:
            return None

    def _clear_download_stop_request(self) -> None:
        clear_stop_request = getattr(self.downloader, "clear_stop_request", None)
        if clear_stop_request is not None:
            clear_stop_request()

    def _download_with_collision(
        self,
        metadata: VideoMetadata,
        target_dir: Path,
        *,
        cookies_file: Path | None = None,
        filename_stem: str | None = None,
        format_selector: str | None = None,
    ) -> tuple[str, str]:
        stem = filename_stem or self.archive_manager.build_filename_stem(
            video_id=metadata.video_id,
            title=metadata.title,
            author_name=metadata.author_name,
        )
        existing_paths = self.archive_manager.find_existing_paths(target_dir, stem)
        if existing_paths and self.collision_policy == "skip":
            existing_path = existing_paths[0]
            return existing_path.suffix.lstrip("."), str(existing_path)
        if existing_paths and self.collision_policy == "overwrite":
            for existing_path in existing_paths:
                existing_path.unlink()
        if existing_paths and self.collision_policy == "timestamp":
            stem = self.archive_manager.timestamped_filename_stem(stem)
        return self.downloader.download(
            metadata,
            target_dir,
            cookies_file=cookies_file,
            filename_stem=stem,
            format_selector=format_selector,
        )

    def _export_bilibili_cookies(self) -> Path | None:
        """Backward-compatible name retained for callers outside the runtime."""
        return self._export_browser_cookies()

    def _store_progress(self, progress: SyncProgress) -> None:
        self.last_progress = progress

    def _set_activity(
        self,
        *,
        operation: str,
        stage: str,
        completed_count: int = 0,
        total_count: int = 0,
        current_url: str = "",
        current_title: str | None = None,
        current_author_name: str = "",
    ) -> None:
        self.last_activity = RuntimeActivity(
            operation=operation,
            stage=stage,
            completed_count=completed_count,
            total_count=total_count,
            current_url=current_url,
            current_title=current_title,
            current_author_name=current_author_name,
        )

    def _iter_sync_items(
        self,
        *,
        source: SourceDescriptor,
        cookies_path: Path,
        candidate_urls: list[str],
    ):
        seen_media_keys: set[tuple[str, str, str]] = set()
        yielded = 0
        total_count = len(candidate_urls)
        for index, url in enumerate(candidate_urls, start=1):
            self._set_activity(
                operation="sync",
                stage="正在解析作品元数据",
                completed_count=index - 1,
                total_count=total_count,
                current_url=url,
            )
            try:
                preview_item = self._build_preview_item(
                    page_url=url,
                    source=source,
                    cookies_path=cookies_path,
                )
            except Exception as exc:
                yielded += 1
                yield self._build_skipped_item(source, url, exc, stage="sync_metadata")
                continue
            variants = self._select_sync_variants(
                preview_item.variants,
                page_url=preview_item.metadata.page_url,
            )
            if not variants:
                variants = [None]
            image_ordinal = 0
            for variant in variants:
                metadata = preview_item.metadata
                if variant is not None:
                    media_key = (metadata.platform, metadata.video_id, variant.download_url)
                    if media_key in seen_media_keys:
                        continue
                    seen_media_keys.add(media_key)
                    if self._is_image_variant(variant):
                        image_ordinal += 1
                        media_type = "live_photo" if "实况图" in variant.quality_label else "image"
                        metadata = replace(
                            self._metadata_for_variant(metadata, variant),
                            video_id=f"{metadata.video_id}-{image_ordinal:03d}",
                            media_type=media_type,
                        )
                    else:
                        metadata = self._metadata_for_variant(metadata, variant)
                else:
                    media_key = (metadata.platform, metadata.video_id, metadata.download_url)
                    if media_key in seen_media_keys:
                        continue
                    seen_media_keys.add(media_key)
                yielded += 1
                self._set_activity(
                    operation="sync",
                    stage="正在下载所选最大版本",
                    completed_count=index - 1,
                    total_count=total_count,
                    current_url=url,
                    current_title=metadata.title,
                    current_author_name=metadata.author_name,
                )
                yield metadata
        if yielded == 0:
            raise RuntimeError("当前页面未发现可下载视频，请确认已登录，并等待作品或收藏列表加载完成后再试。")

    def _collect_candidate_urls(self, source: SourceDescriptor) -> list[str]:
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        adapter = self.adapter if source.platform == "douyin" else self.bilibili_adapter
        snapshot_options = {"scroll_rounds": 8, "pause_ms": 700} if source.platform == "bilibili" else {}
        for html in self.browser_session.fetch_active_page_html_snapshots(
            target_url=source.page_url,
            **snapshot_options,
        ):
            card_hints: dict[str, tuple[str, str]] = {}
            card_urls: set[str] = set()
            if source.platform == "douyin":
                card_hints = self._extract_douyin_card_hints(html)
                card_urls = self._extract_douyin_card_urls(html)
                self._douyin_card_hints.update(card_hints)
            for url in adapter.collect_candidate_urls(html):
                # A Douyin page contains footer, recommendation and search links
                # that look exactly like work URLs. Once real collection/work
                # cards are present, only accept links from those cards.
                if source.platform == "douyin" and card_urls and url not in card_urls:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                candidate_urls.append(url)
        if self.sync_limit is not None:
            candidate_urls = candidate_urls[: self.sync_limit]
        return candidate_urls

    @staticmethod
    def _extract_douyin_card_hints(html: str) -> dict[str, tuple[str, str]]:
        """Read author/caption exposed on visible Douyin video and note cards.

        Kuku deliberately returns no author information for image downloads.  The
        source card remains a reliable fallback when Douyin detail lookup is
        unavailable or disabled.
        """
        hints: dict[str, tuple[str, str]] = {}
        pattern = re.compile(
            r'href=["\'][^"\']*/(?P<kind>video|note)/(?P<id>\d+)[^"\']*["\'][\s\S]{0,2000}?'
            r'<img[^>]*\balt=["\'](?P<alt>[^"\']+)',
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            alt = unescape(match.group("alt")).strip()
            separator = "：" if "：" in alt else ":"
            if separator not in alt:
                continue
            author_name, title = (part.strip() for part in alt.split(separator, 1))
            if not author_name or not title:
                continue
            page_url = f"https://www.douyin.com/{match.group('kind')}/{match.group('id')}"
            hints.setdefault(page_url, (author_name, title))
        return hints

    @staticmethod
    def _extract_douyin_card_urls(html: str) -> set[str]:
        """Identify visible work cards without requiring author/caption text."""
        pattern = re.compile(
            r'<a\b[^>]*\bhref=["\'][^"\']*/(?P<kind>video|note)/(?P<id>\d+)[^"\']*["\'][^>]*>'
            r'(?P<body>[\s\S]{0,2000}?)</a>',
            re.IGNORECASE,
        )
        return {
            f"https://www.douyin.com/{match.group('kind')}/{match.group('id')}"
            for match in pattern.finditer(html)
            if re.search(r"<img\b", match.group("body"), re.IGNORECASE)
        }

    def _apply_douyin_card_hint(self, metadata: VideoMetadata, page_url: str) -> VideoMetadata:
        hint = self._douyin_card_hints.get(page_url)
        if hint is None:
            return metadata
        author_name, title = hint
        return replace(
            metadata,
            author_name=author_name if metadata.author_name == "unknown" else metadata.author_name,
            title=title if not metadata.title or metadata.title == metadata.video_id else metadata.title,
        )

    def _build_skipped_item(
        self,
        source: SourceDescriptor,
        page_url: str,
        exc: Exception,
        *,
        stage: str,
    ) -> SkippedSyncItem:
        raw_message = str(exc).strip() or exc.__class__.__name__
        unavailable_markers = ("404", "not available", "已失效", "已删除", "不存在", "无权限", "需要登录")
        if source.platform == "bilibili" and any(marker.lower() in raw_message.lower() for marker in unavailable_markers):
            message = f"视频已失效、删除或当前账号无权访问。原始错误: {raw_message}"
        else:
            message = f"视频元数据解析失败。原始错误: {raw_message}"
        video_id = page_url.rstrip("/").rsplit("/", maxsplit=1)[-1] or "unknown"
        return SkippedSyncItem(
            platform=source.platform,
            source_type=source.source_type,
            video_id=video_id,
            page_url=page_url,
            error_message=message,
            stage=stage,
        )

    def _build_preview_item(
        self,
        *,
        page_url: str,
        source: SourceDescriptor,
        cookies_path: Path,
        kukutool_resolution: object | None = None,
        kukutool_variant_limit: int | None = None,
    ) -> SyncPreviewItem:
        if source.platform == "douyin":
            metadata, provider_summary, variant_summary, selected_variant, variants = self._resolve_douyin_sync_metadata(
                page_url=page_url,
                source_type=source.source_type,
                cookies_path=cookies_path,
                kukutool_resolution=kukutool_resolution,
                kukutool_variant_limit=kukutool_variant_limit,
                include_variants=True,
            )
            return SyncPreviewItem(
                metadata=metadata,
                provider_summary=provider_summary,
                variant_summary=variant_summary,
                selected_quality_label=None if selected_variant is None else selected_variant.quality_label,
                selected_file_size=None if selected_variant is None else selected_variant.file_size,
                variants=variants,
            )
        if source.platform == "bilibili":
            payload = self.downloader.probe_video_info(url=page_url, cookies_file=cookies_path)
            metadata, variants = self.bilibili_adapter.parse_video_info(
                payload,
                source_type=source.source_type,
                source_url=page_url,
            )
            selected_variant = self._select_sync_variant(variants)
            if selected_variant is not None:
                metadata = replace(metadata, format_selector=selected_variant.format_selector)
            return SyncPreviewItem(
                metadata=metadata,
                provider_summary="native",
                variant_summary=self._build_variant_summary(variants),
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
            metadata=metadata,
            provider_summary="native",
            variant_summary="",
            selected_quality_label=None,
            selected_file_size=None,
        )

    def _resolve_douyin_sync_metadata(
        self,
        *,
        page_url: str,
        source_type: SourceType,
        cookies_path: Path,
        kukutool_resolution: object | None = None,
        kukutool_variant_limit: int | None = None,
        include_variants: bool = False,
    ) -> tuple[VideoMetadata, str, str, VideoVariant | None] | tuple[VideoMetadata, str, str, VideoVariant | None, list[VideoVariant]]:
        canonical_url, metadata, provider_summary, merged_variants = self._resolve_douyin_variants(
            page_url=page_url,
            source_type=source_type,
            native_detail_loader=lambda: (
                page_url,
                self.browser_session.fetch_douyin_aweme_detail(page_url),
            ),
            fallback_metadata_loader=lambda: self.downloader.probe_metadata(
                url=page_url,
                platform="douyin",
                source_type=source_type,
                cookies_from_browser="chrome",
                cookies_file=cookies_path,
            ),
            kukutool_resolution=kukutool_resolution,
            kukutool_variant_limit=kukutool_variant_limit,
            allow_metadata_without_variants=True,
        )
        metadata = self._apply_douyin_card_hint(metadata, page_url)
        selected_variant = self._select_sync_variant(merged_variants)
        if selected_variant is not None:
            metadata = self._metadata_for_variant(metadata, selected_variant)
        variant_summary = self._build_variant_summary(merged_variants)
        if include_variants:
            return metadata, provider_summary, variant_summary, selected_variant, merged_variants
        return metadata, provider_summary, variant_summary, selected_variant

    def _load_native_douyin_share_detail(self, share_url: str) -> tuple[str, dict]:
        resolution = self._resolve_provider("native", share_url, attempts=1)
        return resolution.canonical_url, resolution.payload

    def _resolve_douyin_variants(
        self,
        *,
        page_url: str,
        source_type: SourceType,
        native_detail_loader: Callable[[], tuple[str, dict]] | None,
        fallback_metadata_loader: Callable[[], VideoMetadata] | None = None,
        kukutool_resolution: object | None = None,
        kukutool_variant_limit: int | None = None,
        allow_metadata_without_variants: bool = False,
    ) -> tuple[str, VideoMetadata, str, list[VideoVariant]]:
        """Resolve selected Douyin sources once for both share links and batch items."""
        metadata: VideoMetadata | None = None
        canonical_url = page_url
        provider_labels: list[str] = []
        merged_variants: list[VideoVariant] = []
        resolver_errors: list[Exception] = []
        native_detail_payload: dict | None = None
        native_is_image_post = False

        if self._requires_native_douyin_detail():
            try:
                if native_detail_loader is None:
                    raise RuntimeError("抖音原生详情加载器不可用")
                canonical_url, native_detail_payload = native_detail_loader()
                metadata = self.adapter.parse_aweme_detail(
                    native_detail_payload,
                    source_type=source_type,
                    page_url=canonical_url,
                )
                native_variants = self.adapter.parse_share_variants(native_detail_payload)
                native_is_image_post = self._contains_image_variants(native_variants)
                if "native" in self.resolver_sources or native_is_image_post:
                    merged_variants.extend(self._tag_variants(native_variants, "native"))
                    provider_labels.append("native" if "native" in self.resolver_sources else "native(图集回退)")
            except Exception as exc:
                resolver_errors.append(exc)
                if "native" in self.resolver_sources:
                    provider_labels.append("native(失败)")
                if metadata is None and fallback_metadata_loader is not None:
                    try:
                        metadata = fallback_metadata_loader()
                    except Exception as fallback_exc:
                        resolver_errors.append(fallback_exc)

        if "cdn" in self.resolver_sources and not native_is_image_post:
            try:
                if native_detail_payload is None:
                    raise RuntimeError("CDN 解析需要可用的抖音原生详情")
                merged_variants.extend(
                    self._tag_variants(
                        self._cdn_resolver().resolve_variants_from_payload(native_detail_payload),
                        "cdn",
                    )
                )
                provider_labels.append("cdn")
            except Exception as exc:
                resolver_errors.append(exc)
                provider_labels.append("cdn(失败)")

        if self._is_kukutool_enabled() and not native_is_image_post:
            try:
                if isinstance(kukutool_resolution, Exception):
                    raise kukutool_resolution
                resolution = kukutool_resolution or self._resolve_provider(
                    "kukutool", page_url, attempts=1, variants_only=True
                )
                if metadata is None:
                    canonical_url = resolution.canonical_url
                    metadata = self.adapter.parse_aweme_detail(
                        resolution.payload,
                        source_type=source_type,
                        page_url=canonical_url,
                    )
                kukutool_video = (resolution.payload.get("aweme_detail") or {}).get("video") or {}
                kukutool_variants = self._limit_kukutool_preview_variants(
                    self.adapter._build_kukutool_variants(kukutool_video),
                    kukutool_variant_limit,
                )
                merged_variants.extend(self._tag_variants(kukutool_variants, resolution.provider_id))
                provider_labels.append(resolution.provider_id)
            except Exception as exc:
                resolver_errors.append(exc)
                provider_labels.append("kukutool(失败)")
        if metadata is None:
            self._raise_douyin_resolution_error(resolver_errors)
        merged_variants = self._merge_sync_variants(merged_variants)
        if not merged_variants and not allow_metadata_without_variants:
            self._raise_douyin_resolution_error(resolver_errors, fallback="未解析到可下载版本")
        if merged_variants:
            merged_variants = self._merge_sync_variants(self._probe_missing_variant_sizes(merged_variants))
            merged_variants = self._mark_recommended_variant(merged_variants)
        provider_summary = " + ".join(provider_labels) if provider_labels else "native"
        self.last_resolution_diagnostics = {
            "page_url": page_url,
            "canonical_url": canonical_url,
            "sources": provider_labels,
            "errors": [str(error) for error in resolver_errors],
            "variant_count": len(merged_variants),
        }
        return canonical_url, metadata, provider_summary, merged_variants

    def _resolve_provider(
        self,
        provider_id: str,
        page_url: str,
        *,
        attempts: int,
        variants_only: bool = False,
    ) -> object:
        resolver = next(
            (
                item
                for item in self.share_resolver.resolvers
                if getattr(item, "provider_id", None) == provider_id
            ),
            None,
        )
        if resolver is None:
            raise RuntimeError(f"未启用解析来源: {provider_id}")

        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                if variants_only:
                    resolve_variants_only = getattr(resolver, "resolve_variants_only", None)
                    if resolve_variants_only is not None:
                        return resolve_variants_only(page_url)
                return resolver.resolve(page_url)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    # Keep third-party parsing serial and give transient service limits time to recover.
                    time.sleep(1)
        assert last_error is not None
        raise last_error

    def _is_kukutool_enabled(self) -> bool:
        return "kukutool" in self.resolver_sources and self.settings.share_resolvers.enable_kukutool_fallback

    def _requires_native_douyin_detail(self) -> bool:
        return "native" in self.resolver_sources or "cdn" in self.resolver_sources

    def _cdn_resolver(self) -> CdnDouyinResolver:
        resolver = next(
            (
                item
                for item in self.share_resolver.resolvers
                if isinstance(item, CdnDouyinResolver)
            ),
            None,
        )
        if resolver is None:
            raise RuntimeError("未启用解析来源: cdn")
        return resolver

    @staticmethod
    def _raise_douyin_resolution_error(
        resolver_errors: list[Exception],
        *,
        fallback: str = "已选解析来源未返回可用结果",
    ) -> None:
        if resolver_errors:
            raise RuntimeError(
                "已选解析来源未返回可用结果: " + "; ".join(str(error) for error in resolver_errors)
            ) from resolver_errors[-1]
        raise RuntimeError(fallback)

    def _probe_missing_variant_sizes(self, variants: list[VideoVariant]) -> list[VideoVariant]:
        return [
            replace(
                variant,
                file_size=variant.file_size or self.public_session.probe_content_length(variant.download_url),
            )
            if not self._is_image_variant(variant)
            else variant
            for variant in variants
        ]

    def _mark_recommended_variant(self, variants: list[VideoVariant]) -> list[VideoVariant]:
        selected = self._select_sync_variant(variants)
        if selected is None:
            return variants
        return [
            replace(variant, is_recommended=(variant.variant_id == selected.variant_id and variant.provider_id == selected.provider_id))
            for variant in variants
        ]

    def _build_share_resolver_chain(self) -> ResolverChain:
        resolvers: list[object] = []
        if "kukutool" in self.resolver_sources and self.settings.share_resolvers.enable_kukutool_fallback:
            resolvers.append(
                KukutoolResolver(
                    settings=self.settings,
                    kukutool_session=KukutoolSession(
                        host=self.browser_session.host,
                        port=self.browser_session.port,
                    ),
                )
            )
        if self._requires_native_douyin_detail():
            resolvers.append(
                NativeDouyinResolver(
                    settings=self.settings,
                    signed_session=self.signed_session,
                    public_session=self.public_session,
                )
            )
        if "cdn" in self.resolver_sources:
            resolvers.append(CdnDouyinResolver(settings=self.settings))
        return ResolverChain(resolvers)

    def _select_sync_variant(self, variants: list[VideoVariant]) -> VideoVariant | None:
        if not variants:
            return None
        return max(
            variants,
            key=lambda item: (
                item.file_size is not None,
                item.file_size or 0,
                item.bit_rate or 0,
                item.height or 0,
                item.width or 0,
            ),
        )

    @staticmethod
    def _metadata_for_variant(metadata: VideoMetadata, variant: VideoVariant) -> VideoMetadata:
        return replace(
            metadata,
            download_url=variant.download_url,
            format_selector=variant.format_selector,
            expected_file_size=variant.file_size if variant.provider_id == "cdn" else None,
            selected_provider_id=variant.provider_id,
            selected_quality_label=variant.quality_label,
            selected_file_size=variant.file_size,
        )

    @staticmethod
    def _is_image_variant(variant: VideoVariant) -> bool:
        return any(marker in variant.quality_label for marker in ("图片", "动图", "实况图"))

    def _contains_image_variants(self, variants: list[VideoVariant]) -> bool:
        return bool(variants) and all(self._is_image_variant(variant) for variant in variants)

    def _select_sync_variants(
        self,
        variants: list[VideoVariant],
        *,
        page_url: str | None = None,
    ) -> list[VideoVariant]:
        """Download the largest parsed video; only note posts retain image attachments."""
        image_variants = [variant for variant in variants if self._is_image_variant(variant)]
        video_variants = [variant for variant in variants if not self._is_image_variant(variant)]
        selected_video = self._select_sync_variant(video_variants)
        if page_url and "/video/" in page_url:
            return [selected_video] if selected_video is not None else []
        return ([selected_video] if selected_video is not None else []) + image_variants

    def _merge_sync_variants(self, variants: list[VideoVariant]) -> list[VideoVariant]:
        attachments: list[VideoVariant] = []
        attachment_urls: set[str] = set()
        deduped: dict[tuple[str, str], VideoVariant] = {}
        for variant in variants:
            if self._is_image_variant(variant):
                if variant.download_url not in attachment_urls:
                    attachment_urls.add(variant.download_url)
                    attachments.append(variant)
                continue
            key = (variant.provider_id or "native", variant.quality_label)
            existing = deduped.get(key)
            if existing is None or self.adapter._variant_priority(variant) > self.adapter._variant_priority(existing):
                deduped[key] = variant
        merged = list(deduped.values())
        merged.sort(
            key=lambda item: (
                item.file_size is not None,
                item.file_size or 0,
                item.bit_rate or 0,
                self.adapter._quality_rank(item.quality_label),
            ),
            reverse=True,
        )
        return merged + attachments

    def _limit_kukutool_preview_variants(
        self,
        variants: list[VideoVariant],
        limit: int | None,
    ) -> list[VideoVariant]:
        if limit is None:
            return variants
        attachments = [variant for variant in variants if self._is_image_variant(variant)]
        videos = [variant for variant in variants if not self._is_image_variant(variant)]
        videos.sort(key=lambda item: item.file_size or 0, reverse=True)
        return videos[:limit] + attachments

    def _tag_variants(self, variants: list[VideoVariant], provider_id: str) -> list[VideoVariant]:
        return [replace(variant, provider_id=provider_id) for variant in variants]

    def _build_variant_summary(self, variants: list[VideoVariant]) -> str:
        parts: list[str] = []
        for variant in sorted(
            variants,
            key=lambda item: (
                item.file_size is None,
                -(item.file_size or 0),
                item.quality_label,
                item.variant_id,
            ),
        ):
            details = variant.quality_label
            if variant.file_size is not None:
                details += f"({variant.file_size / 1024 / 1024:.2f} MB)"
            parts.append(f"{details}[{variant.provider_id}]")
        return ", ".join(parts)
