from dataclasses import dataclass


@dataclass
class MainController:
    engine: object
    status_text: str = "待命"

    def start_sync(self) -> None:
        self.engine.start_sync()
        self.status_text = "同步进行中"
