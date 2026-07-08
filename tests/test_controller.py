from dataclasses import dataclass

from video2local.ui.controller import MainController


@dataclass
class FakeEngine:
    started: bool = False

    def start_sync(self) -> None:
        self.started = True


def test_main_controller_updates_status_when_sync_starts() -> None:
    engine = FakeEngine()
    controller = MainController(engine=engine)

    controller.start_sync()

    assert engine.started is True
    assert controller.status_text == "同步进行中"
