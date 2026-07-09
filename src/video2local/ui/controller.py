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
    output_dir_text: str = ""
    sync_limit_text: str = ""

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._worker: Thread | None = None
        output_root = getattr(self.engine, "output_root", None)
        if output_root is not None:
            self.output_dir_text = str(output_root)
        else:
            self.output_dir_text = str(Path.cwd())

    def launch_chrome(self) -> None:
        if hasattr(self.engine, "launch_chrome"):
            self.engine.launch_chrome()
        self.status_text = "Chrome 已启动"
        self.detail_text = "请在专用 Chrome 中登录并打开抖音内容源页面"

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
        target = Path(raw_path).expanduser()
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
