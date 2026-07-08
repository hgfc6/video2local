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
        self.engine.start_sync()
        self.status_text = "同步进行中"
