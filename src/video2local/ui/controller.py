from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from threading import Lock, Thread

from video2local.domain import SampleDownloadResult
from video2local.sync_engine import SyncSummary


@dataclass
class MainController:
    engine: object
    status_text: str = "待命"
    source_text: str = "解析来源: -"
    detail_text: str = "未开始同步"
    summary_text: str = "暂无最近一次同步摘要"
    share_parse_result: object | None = None
    share_variants: list[object] = field(default_factory=list)
    sync_preview_items: list[object] = field(default_factory=list)
    results_mode: str = "sync_preview"
    results_revision: int = 0
    output_dir_text: str = ""
    sync_limit_text: str = ""
    retry_count_text: str = "1"
    flat_output_enabled: bool = False
    resolver_sources: tuple[str, ...] = ("native", "kukutool")
    platform_mode: str = "douyin"

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._worker: Thread | None = None
        configured_sources = getattr(self.engine, "resolver_sources", None)
        if configured_sources:
            self.resolver_sources = tuple(configured_sources)
        if hasattr(self.engine, "set_active_platform"):
            self.engine.set_active_platform(self.platform_mode)

    def launch_chrome(self) -> None:
        if hasattr(self.engine, "launch_chrome"):
            self.engine.launch_chrome()
        self.status_text = "Chrome 已启动"
        self.detail_text = "请在专用 Chrome 中登录并打开受支持的平台内容页"

    def validate_current_page(self) -> None:
        try:
            source = self.engine.validate_current_page()
        except Exception as exc:
            self.status_text = f"错误: {exc}"
            self.detail_text = "当前页面不是受支持的内容源页面"
            return
        self.status_text = f"已识别 {source.platform} / {source.source_type.value}"
        self.detail_text = source.page_url

    def start_sync(self) -> None:
        worker = self._worker
        if worker is not None and worker.is_alive():
            self.status_text = "同步进行中"
            self.detail_text = "当前任务尚未结束"
            return
        self.status_text = "同步进行中"
        self.detail_text = "正在准备同步任务"
        self._worker = Thread(target=self._run_sync, daemon=True)
        self._worker.start()

    def preview_sync(self) -> None:
        worker = self._worker
        if worker is not None and worker.is_alive():
            self.status_text = "同步进行中"
            self.detail_text = "请等待当前任务结束后再预览"
            return
        self.status_text = "正在生成预览"
        self.detail_text = "正在扫描页面并解析预计下载版本"
        self._worker = Thread(target=self._run_sync_preview, daemon=True)
        self._worker.start()

    def stop_sync(self) -> None:
        if hasattr(self.engine, "stop_sync"):
            self.engine.stop_sync()
        self.status_text = "正在停止同步"
        self.detail_text = "将在当前视频处理完成后停止"

    def open_downloads_dir(self) -> None:
        if hasattr(self.engine, "open_downloads_dir"):
            self.engine.open_downloads_dir()
        self.status_text = "已打开下载目录"
        self.detail_text = "可以查看当前归档输出"

    def download_first_visible_sample(self) -> None:
        worker = self._worker
        if worker is not None and worker.is_alive():
            self.status_text = "同步进行中"
            self.detail_text = "请等待当前任务结束后再执行样本下载"
            return
        self.status_text = "正在下载样本"
        self.detail_text = "将下载当前页面首个可见视频到 _smoke_test 目录"
        self._worker = Thread(target=self._run_sample_download, daemon=True)
        self._worker.start()

    def parse_share_text(self, raw_text: str) -> None:
        worker = self._worker
        if worker is not None and worker.is_alive():
            self.status_text = "同步进行中"
            self.detail_text = "请等待当前任务结束后再解析分享链接"
            return
        detected_platform = self._share_platform(raw_text)
        if detected_platform is not None and detected_platform != self.platform_mode:
            selected_name = "抖音" if detected_platform == "douyin" else "Bilibili"
            self.status_text = f"错误: 当前为{self._platform_name()}工作台"
            self.detail_text = f"该链接属于 {selected_name}，请先切换平台工作台"
            return
        self.status_text = "正在解析分享链接"
        self.detail_text = "正在提取链接并加载可用清晰度版本"
        self._worker = Thread(target=self._run_share_parse, args=(raw_text,), daemon=True)
        self._worker.start()

    def download_share_variant(self, variant_id: str) -> None:
        worker = self._worker
        if worker is not None and worker.is_alive():
            self.status_text = "同步进行中"
            self.detail_text = "请等待当前任务结束后再下载分享视频"
            return
        if self.share_parse_result is None:
            self.status_text = "错误: 尚未解析分享链接"
            self.detail_text = "请先解析分享链接并选择清晰度版本"
            return
        self.status_text = "正在下载分享视频"
        self.detail_text = f"正在下载所选版本: {variant_id}"
        self._worker = Thread(target=self._run_share_variant_download, args=(variant_id,), daemon=True)
        self._worker.start()

    def show_latest_summary(self) -> None:
        if not hasattr(self.engine, "get_latest_sync_run"):
            self.summary_text = "当前运行时未提供同步摘要"
            return
        row = self.engine.get_latest_sync_run()
        if row is None:
            self.summary_text = "暂无最近一次同步摘要"
            return
        self.summary_text = (
            f"最近一次同步: {row['status']}，发现 {row['discovered_count']}，下载 {row['downloaded_count']}，"
            f"跳过 {row['skipped_count']}，失败 {row['failed_count']}"
        )

    def set_output_dir(self, raw_path: str) -> None:
        text = raw_path.strip()
        if not text:
            raise ValueError("请先选择下载输出目录")
        target = Path(text).expanduser()
        if not target.is_dir():
            raise ValueError("输出目录不存在或不可用，请重新选择")
        if hasattr(self.engine, "set_output_root"):
            self.engine.set_output_root(target)
        self.output_dir_text = str(target)
        self.status_text = "输出目录已更新"
        self.detail_text = str(target)

    def set_sync_limit(self, raw_value: str) -> None:
        text = raw_value.strip()
        if not text:
            limit = None
            self.sync_limit_text = ""
        else:
            limit = int(text)
            if limit <= 0:
                raise ValueError("前 N 个视频必须是正整数")
            self.sync_limit_text = text
        if hasattr(self.engine, "set_sync_limit"):
            self.engine.set_sync_limit(limit)

    def set_retry_count(self, raw_value: str) -> None:
        text = raw_value.strip()
        retry_count = 1 if not text else int(text)
        if retry_count < 0:
            raise ValueError("失败重试次数不能小于 0")
        self.retry_count_text = str(retry_count)
        if hasattr(self.engine, "set_retry_count"):
            self.engine.set_retry_count(retry_count)

    def set_flat_output(self, enabled: bool) -> None:
        self.flat_output_enabled = enabled
        if hasattr(self.engine, "set_flat_output"):
            self.engine.set_flat_output(enabled)

    def set_resolver_sources(self, sources: tuple[str, ...]) -> None:
        normalized = tuple(dict.fromkeys(item for item in sources if item))
        if not normalized:
            raise ValueError("至少保留一个解析来源")
        self.resolver_sources = normalized
        if hasattr(self.engine, "set_resolver_sources"):
            self.engine.set_resolver_sources(normalized)

    def set_platform_mode(self, platform: str) -> None:
        if platform not in {"douyin", "bilibili"}:
            raise ValueError("不支持的平台工作台")
        if platform == self.platform_mode:
            return
        self.platform_mode = platform
        if hasattr(self.engine, "set_active_platform"):
            self.engine.set_active_platform(platform)
        self.share_parse_result = None
        self.share_variants = []
        self.sync_preview_items = []
        self.results_mode = "sync_preview"
        self.results_revision += 1
        self.status_text = f"已切换到{self._platform_name()}工作台"
        self.source_text = "解析来源: -"
        self.detail_text = "请选择对应平台的页面或分享链接"
        self.summary_text = "结果表已清空，避免跨平台内容混淆"

    def _share_platform(self, raw_text: str) -> str | None:
        lowered = raw_text.lower()
        if "bilibili.com" in lowered or "b23.tv" in lowered:
            return "bilibili"
        if "douyin.com" in lowered or "iesdouyin.com" in lowered:
            return "douyin"
        return None

    def _platform_name(self) -> str:
        return {"douyin": "抖音", "bilibili": "Bilibili"}[self.platform_mode]

    def wait_for_sync(self, timeout: float | None = None) -> None:
        worker = self._worker
        if worker is None:
            return
        worker.join(timeout=timeout)

    def poll_runtime_state(self) -> None:
        worker = self._worker
        if worker is None or not worker.is_alive():
            return
        progress = getattr(self.engine, "last_progress", None)
        if progress is None:
            return
        with self._lock:
            self.status_text = (
                f"同步进行中: 已处理 {progress.processed_count}/{progress.discovered_count}，"
                f"下载 {progress.downloaded_count}，跳过 {progress.skipped_count}，失败 {progress.failed_count}"
            )
            self.detail_text = (
                f"进行中: {progress.current_author_name} / "
                f"{progress.current_title or progress.current_video_id} "
                f"({progress.processed_count}/{progress.discovered_count})"
            )

    def _run_sync(self) -> None:
        try:
            summary = self.engine.start_sync()
        except Exception as exc:
            with self._lock:
                self.status_text = f"错误: {exc}"
                self.detail_text = "请检查当前页面是否为受支持的内容源页面"
            return
        self._apply_summary(summary)
        self.show_latest_summary()

    def _run_sync_preview(self) -> None:
        try:
            result = self.engine.preview_sync()
        except Exception as exc:
            with self._lock:
                self.status_text = f"错误: {exc}"
                self.detail_text = "同步预览失败，请检查当前页面和登录态"
            return
        self._apply_sync_preview(result)

    def _run_sample_download(self) -> None:
        try:
            result = self.engine.download_first_visible_sample()
        except Exception as exc:
            with self._lock:
                self.status_text = f"错误: {exc}"
                self.detail_text = "样本下载失败，请先检查页面和登录态"
            return
        self._apply_sample_result(result)

    def _run_share_parse(self, raw_text: str) -> None:
        try:
            result = self.engine.parse_share_text(raw_text)
        except Exception as exc:
            with self._lock:
                self.status_text = f"错误: {exc}"
                self.detail_text = "分享链接解析失败，请检查文案或链接是否有效"
            return
        self._apply_share_parse_result(result)

    def _run_share_variant_download(self, variant_id: str) -> None:
        try:
            result = self.engine.download_share_variant(self.share_parse_result, variant_id)
        except Exception as exc:
            with self._lock:
                self.status_text = f"错误: {exc}"
                self.detail_text = "分享视频下载失败，请重新解析或更换清晰度版本"
            return
        self._apply_share_variant_download_result(result)

    def _apply_sample_result(self, result: SampleDownloadResult) -> None:
        metadata = getattr(result, "metadata", result)
        title = getattr(metadata, "title", None) or getattr(metadata, "video_id")
        author_name = getattr(metadata, "author_name")
        local_path = getattr(result, "local_path")
        with self._lock:
            self.status_text = "样本下载完成"
            self.detail_text = f"{author_name} / {title}"
            self.summary_text = f"样本文件: {local_path}"

    def _apply_share_parse_result(self, result: object) -> None:
        metadata = getattr(result, "metadata")
        variants = list(getattr(result, "variants"))
        provider_id = getattr(result, "provider_id", "-")
        with self._lock:
            self.share_parse_result = result
            self.share_variants = variants
            self.results_mode = "share_parse"
            self.results_revision += 1
            self.status_text = "分享链接解析完成"
            self.source_text = f"解析来源: {provider_id}"
            self.detail_text = f"{metadata.author_name} / {metadata.title or metadata.video_id}"
            self.summary_text = f"{metadata.author_name} / {metadata.title or metadata.video_id}，已解析 {len(variants)} 个清晰度版本"

    def _apply_share_variant_download_result(self, result: object) -> None:
        with self._lock:
            self.status_text = "分享视频下载完成"
            self.detail_text = getattr(result, "local_path")
            self.summary_text = getattr(result, "local_path")

    def _apply_summary(self, summary: SyncSummary) -> None:
        with self._lock:
            prefix = "同步已停止" if summary.status == "stopped" else "同步完成"
            self.status_text = (
                f"{prefix}: 发现 {summary.discovered_count}，下载 {summary.downloaded_count}，"
                f"跳过 {summary.skipped_count}，失败 {summary.failed_count}"
            )
            progress = getattr(self.engine, "last_progress", None)
            if progress is None:
                self.detail_text = "未提供视频级进度详情"
            else:
                title = progress.current_title or progress.current_video_id
                self.detail_text = f"最后处理: {progress.current_author_name} / {title}"
            if summary.report_path:
                self.summary_text = f"结果清单: {summary.report_path}"

    def _apply_sync_preview(self, result: object) -> None:
        items = list(getattr(result, "items", []))
        skipped_items = list(getattr(result, "skipped_items", []) or [])
        source = getattr(result, "source")
        with self._lock:
            self.sync_preview_items = items
            self.results_mode = "sync_preview"
            self.results_revision += 1
            self.status_text = "预览完成"
            self.detail_text = (
                f"{source.platform} / {source.source_type.value}，共预览 {len(items)} 条，"
                f"跳过 {len(skipped_items)} 条"
            )
            if items:
                first_item = items[0]
                metadata = getattr(first_item, "metadata")
                quality_label = getattr(first_item, "selected_quality_label", None) or "未知"
                provider_summary = getattr(first_item, "provider_summary", "-")
                self.summary_text = f"首条预览: {metadata.author_name} / {metadata.title or metadata.video_id} / {provider_summary} / {quality_label}"
            else:
                self.summary_text = "当前预览为空"
            report_path = getattr(result, "report_path", None)
            if report_path:
                self.summary_text += f"；跳过明细: {report_path}"
