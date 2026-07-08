from dataclasses import dataclass


@dataclass
class MainController:
    engine: object
    status_text: str = "待命"

    def launch_chrome(self) -> None:
        if hasattr(self.engine, "launch_chrome"):
            self.engine.launch_chrome()
        self.status_text = "Chrome 已启动"

    def start_sync(self) -> None:
        try:
            source = self.engine.start_sync()
        except Exception as exc:
            self.status_text = f"错误: {exc}"
            return
        self.status_text = f"已识别 {source.platform} / {source.source_type.value}"
