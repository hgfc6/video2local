from dataclasses import dataclass


@dataclass
class MainController:
    engine: object
    status_text: str = "待命"
    detail_text: str = "未开始同步"

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
        try:
            summary = self.engine.start_sync()
        except Exception as exc:
            self.status_text = f"错误: {exc}"
            self.detail_text = "请检查当前页面是否为受支持的内容源页面"
            return
        self.status_text = (
            f"同步完成: 发现 {summary.discovered_count}，下载 {summary.downloaded_count}，"
            f"跳过 {summary.skipped_count}，失败 {summary.failed_count}"
        )
        progress = getattr(self.engine, "last_progress", None)
        if progress is None:
            self.detail_text = "未提供视频级进度详情"
            return
        title = progress.current_title or progress.current_video_id
        self.detail_text = f"最后处理: {progress.current_author_name} / {title}"
