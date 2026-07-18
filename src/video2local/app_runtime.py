from dataclasses import dataclass
from dataclasses import replace
from html import unescape
import os
from pathlib import Path
import re
import subprocess
import time

from video2local.archive import ArchiveManager
from video2local.adapters.base import SourceDescriptor
from video2local.adapters.bilibili import BilibiliAdapter
from video2local.adapters.douyin import DouyinAdapter
from video2local.browser import ChromeLaunchSpec, ChromeRemoteSession, DouyinPublicSession, DouyinSignedSession, KukutoolSession
from video2local.config import AppSettings
from video2local.downloader import YtDlpService
from video2local.domain import SampleDownloadResult, ShareParseResult, ShareVariantDownloadResult, SkippedSyncItem, SourceType, SyncPreviewItem, SyncPreviewResult, SyncProgress, SyncRunStatus, VideoMetadata, VideoVariant
from video2local.resolvers import KukutoolResolver, NativeDouyinResolver, ResolverChain
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
        self.output_root = self.settings.paths.downloads_dir
        self.output_root_selected = False
        self.sync_limit: int | None = None
        self.active_platform: str | None = None
        self.retry_count: int = 1
        self.flat_output = False
        self._latest_sync_run: dict | None = None
        self._douyin_card_hints: dict[str, tuple[str, str]] = {}
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

    def set_output_root(self, output_root: Path) -> None:
        self.output_root = output_root
        self.output_root_selected = True
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
        source = self.get_current_source()
        try:
            cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
            candidate_urls = self._collect_candidate_urls(source)
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
        source = self.get_current_source()
        cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
        candidate_urls = self._collect_candidate_urls(source)
        kukutool_resolutions = (
            self._resolve_kukutool_preview_candidates(candidate_urls)
            if source.platform == "douyin"
            else {}
        )
        items: list[SyncPreviewItem] = []
        skipped_items: list[SkippedSyncItem] = []
        seen_video_keys: set[tuple[str, str]] = set()
        for url in candidate_urls:
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

    def _resolve_kukutool_preview_candidates(self, candidate_urls: list[str]) -> dict[str, object]:
        if "kukutool" not in self.resolver_sources or not self.settings.share_resolvers.enable_kukutool_fallback:
            return {}
        resolver = next(
            (item for item in self.share_resolver.resolvers if isinstance(item, KukutoolResolver)),
            None,
        )
        if resolver is None:
            return {}
        return resolver.resolve_variants_only_many(candidate_urls)

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
        self._clear_download_stop_request()
        source = self.get_current_source()
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        for url in self._collect_candidate_urls(source):
            if url not in seen_urls:
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
            cookies_path = self.browser_session.export_cookies(self.settings.paths.data_dir / "yt-dlp-cookies.txt")
            metadata = self._build_preview_item(
                page_url=first_url,
                source=source,
                cookies_path=cookies_path,
            ).metadata

        target_dir = self.output_root / "_smoke_test"
        target_dir.mkdir(parents=True, exist_ok=True)
        _, local_path = self.downloader.download(metadata, target_dir, cookies_file=cookies_path if source.platform != "douyin" else None)
        return SampleDownloadResult(metadata=metadata, local_path=local_path)

    def parse_share_text(self, raw_text: str) -> ShareParseResult:
        self.ensure_directories()
        if self._is_bilibili_share_text(raw_text):
            return self._parse_bilibili_share_text(raw_text)
        share_url = self.adapter.extract_share_url(raw_text)
        resolution = self.share_resolver.resolve(share_url)
        metadata = self.adapter.parse_aweme_detail(
            resolution.payload,
            source_type=SourceType.SHARE_LINK,
            page_url=resolution.canonical_url,
        )
        variants = self._tag_variants(
            self.adapter.parse_share_variants(resolution.payload),
            resolution.provider_id,
        )
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
        self._clear_download_stop_request()
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
                / self.archive_manager.build_author_directory_name(metadata)
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

    def _export_bilibili_cookies(self) -> Path | None:
        """Backward-compatible name retained for callers outside the runtime."""
        return self._export_browser_cookies()

    def _store_progress(self, progress: SyncProgress) -> None:
        self.last_progress = progress

    def _build_sync_items(self, *, source: SourceDescriptor, cookies_path: Path) -> list[VideoMetadata]:
        items: list[VideoMetadata] = []
        seen_video_keys: set[tuple[str, str]] = set()
        for url in self._collect_candidate_urls(source):
            try:
                preview_item = self._build_preview_item(
                    page_url=url,
                    source=source,
                    cookies_path=cookies_path,
                )
            except Exception:
                continue
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
        seen_media_keys: set[tuple[str, str, str]] = set()
        yielded = 0
        for url in candidate_urls:
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
            variants = self._select_sync_variants(preview_item.variants)
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
                        metadata = replace(
                            metadata,
                            video_id=f"{metadata.video_id}-{image_ordinal:03d}",
                            download_url=variant.download_url,
                            format_selector=variant.format_selector,
                        )
                    else:
                        metadata = replace(
                            metadata,
                            download_url=variant.download_url,
                            format_selector=variant.format_selector,
                        )
                else:
                    media_key = (metadata.platform, metadata.video_id, metadata.download_url)
                    if media_key in seen_media_keys:
                        continue
                    seen_media_keys.add(media_key)
                yielded += 1
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
            if source.platform == "douyin":
                self._douyin_card_hints.update(self._extract_douyin_card_hints(html))
            for url in adapter.collect_candidate_urls(html):
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
    ) -> SyncPreviewItem:
        if source.platform == "douyin":
            metadata, provider_summary, variant_summary, selected_variant, variants = self._resolve_douyin_sync_metadata(
                page_url=page_url,
                source_type=source.source_type,
                cookies_path=cookies_path,
                kukutool_resolution=kukutool_resolution,
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
            selected_variant = variants[0] if variants else None
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
        include_variants: bool = False,
    ) -> tuple[VideoMetadata, str, str, VideoVariant | None] | tuple[VideoMetadata, str, str, VideoVariant | None, list[VideoVariant]]:
        metadata: VideoMetadata | None = None
        provider_labels: list[str] = []
        merged_variants: list[VideoVariant] = []
        resolver_errors: list[Exception] = []

        if "kukutool" in self.resolver_sources and self.settings.share_resolvers.enable_kukutool_fallback:
            try:
                if isinstance(kukutool_resolution, Exception):
                    raise kukutool_resolution
                resolution = kukutool_resolution or self._resolve_provider(
                    "kukutool", page_url, attempts=1, variants_only=True
                )
                metadata = self.adapter.parse_aweme_detail(
                    resolution.payload,
                    source_type=source_type,
                    page_url=resolution.canonical_url,
                )
                kukutool_video = (resolution.payload.get("aweme_detail") or {}).get("video") or {}
                merged_variants.extend(
                    self._tag_variants(self.adapter._build_kukutool_variants(kukutool_video), resolution.provider_id)
                )
                provider_labels.append(resolution.provider_id)
            except Exception as exc:
                resolver_errors.append(exc)
                provider_labels.append("kukutool(失败)")

        if "native" in self.resolver_sources:
            try:
                detail_payload = self.browser_session.fetch_douyin_aweme_detail(page_url)
                native_metadata = self.adapter.parse_aweme_detail(
                    detail_payload,
                    source_type=source_type,
                    page_url=page_url,
                )
                metadata = native_metadata
                # Kuku supplies the actual downloadable URLs.  Native detail is
                # still queried on the already open Douyin page for the real
                # author and caption, so image posts never fall into "unknown".
                if not merged_variants:
                    merged_variants.extend(self._tag_variants(self.adapter.parse_share_variants(detail_payload), "native"))
                if "native" not in provider_labels:
                    provider_labels.append("native")
            except Exception:
                if metadata is None:
                    metadata = self.downloader.probe_metadata(
                        url=page_url,
                        platform="douyin",
                        source_type=source_type,
                        cookies_from_browser="chrome",
                        cookies_file=cookies_path,
                    )
                    provider_labels.append("native")
        if metadata is None:
            if resolver_errors:
                raise RuntimeError(
                    "已选解析来源未返回可用结果: " + "; ".join(str(error) for error in resolver_errors)
                ) from resolver_errors[-1]
            raise RuntimeError("已选解析来源未返回可用结果")

        metadata = self._apply_douyin_card_hint(metadata, page_url)
        merged_variants = self._merge_sync_variants(merged_variants)
        selected_variant = self._select_sync_variant(merged_variants)
        if selected_variant is not None:
            metadata = replace(metadata, download_url=selected_variant.download_url)
        provider_summary = " + ".join(provider_labels) if provider_labels else "native"
        variant_summary = self._build_variant_summary(merged_variants)
        if include_variants:
            return metadata, provider_summary, variant_summary, selected_variant, merged_variants
        return metadata, provider_summary, variant_summary, selected_variant

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
        if "native" in self.resolver_sources:
            resolvers.append(
                NativeDouyinResolver(
                    settings=self.settings,
                    signed_session=self.signed_session,
                    public_session=self.public_session,
                )
            )
        return ResolverChain(resolvers)

    def _safe_file_size(self, local_path: str) -> int | None:
        try:
            return Path(local_path).stat().st_size
        except OSError:
            return None

    def _select_sync_variant(self, variants: list[VideoVariant]) -> VideoVariant | None:
        if not variants:
            return None
        return variants[0]

    @staticmethod
    def _is_image_variant(variant: VideoVariant) -> bool:
        return "图片" in variant.quality_label or "实况图" in variant.quality_label

    def _select_sync_variants(self, variants: list[VideoVariant]) -> list[VideoVariant]:
        """Download the best video plus every image/Live-photo attachment."""
        image_variants = [variant for variant in variants if self._is_image_variant(variant)]
        video_variants = [variant for variant in variants if not self._is_image_variant(variant)]
        selected_video = self._select_sync_variant(video_variants)
        return ([selected_video] if selected_video is not None else []) + image_variants

    def _merge_sync_variants(self, variants: list[VideoVariant]) -> list[VideoVariant]:
        deduped: dict[str, VideoVariant] = {}
        for variant in variants:
            existing = deduped.get(variant.quality_label)
            if existing is None or self.adapter._variant_priority(variant) > self.adapter._variant_priority(existing):
                deduped[variant.quality_label] = variant
        merged = list(deduped.values())
        merged.sort(
            key=lambda item: (
                self.adapter._quality_rank(item.quality_label),
                item.bit_rate or 0,
                item.file_size or 0,
            ),
            reverse=True,
        )
        return merged

    def _tag_variants(self, variants: list[VideoVariant], provider_id: str) -> list[VideoVariant]:
        return [replace(variant, provider_id=provider_id) for variant in variants]

    def _build_variant_summary(self, variants: list[VideoVariant]) -> str:
        parts: list[str] = []
        for variant in variants:
            details = variant.quality_label
            if variant.file_size is not None:
                details += f"({variant.file_size / 1024 / 1024:.2f} MB)"
            parts.append(f"{details}[{variant.provider_id}]")
        return ", ".join(parts)
