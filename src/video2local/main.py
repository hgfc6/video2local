import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from video2local.app_runtime import AppRuntime
from video2local.config import AppSettings, ShareResolverSettings
from video2local.ui.controller import MainController
from video2local.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    settings = AppSettings.for_root(
        Path.cwd(),
        platform_name="douyin",
        supported_source_types=("favorites", "author_videos"),
        share_resolvers=ShareResolverSettings(
            enable_kukutool_fallback=True,
            enabled_sources=("native", "kukutool"),
        ),
    )
    controller = MainController(engine=AppRuntime(settings=settings))
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
