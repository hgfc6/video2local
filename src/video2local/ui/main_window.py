from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from video2local.ui.controller import MainController


class MainWindow(QMainWindow):
    def __init__(self, controller: MainController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Video2Local")

        self.guide_label = QLabel(
            "首次使用流程:\n"
            "1. 点击“启动 Chrome”打开专用浏览器\n"
            "2. 登录平台并打开收藏页或作者作品页\n"
            "3. 点击“检查当前页面”确认已识别来源\n"
            "4. 先点“下载首个样本”验证链路，再点“开始同步”"
        )
        self.status_label = QLabel(self.controller.status_text)
        self.detail_label = QLabel(self.controller.detail_text)
        self.summary_label = QLabel(self.controller.summary_text)
        self.launch_button = QPushButton("启动 Chrome")
        self.launch_button.clicked.connect(self.handle_launch)
        self.validate_button = QPushButton("检查当前页面")
        self.validate_button.clicked.connect(self.handle_validate)
        self.sample_button = QPushButton("下载首个样本")
        self.sample_button.clicked.connect(self.handle_sample_download)
        self.start_button = QPushButton("开始同步")
        self.start_button.clicked.connect(self.handle_start)
        self.stop_button = QPushButton("停止同步")
        self.stop_button.clicked.connect(self.handle_stop)
        self.open_downloads_button = QPushButton("打开下载目录")
        self.open_downloads_button.clicked.connect(self.handle_open_downloads)
        self.summary_button = QPushButton("查看最近摘要")
        self.summary_button.clicked.connect(self.handle_summary)

        layout = QVBoxLayout()
        layout.addWidget(self.guide_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.launch_button)
        layout.addWidget(self.validate_button)
        layout.addWidget(self.sample_button)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.open_downloads_button)
        layout.addWidget(self.summary_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(200)
        self.refresh_timer.timeout.connect(self.refresh_labels)
        self.refresh_timer.start()

    def handle_launch(self) -> None:
        self.controller.launch_chrome()
        self.status_label.setText(self.controller.status_text)
        self.detail_label.setText(self.controller.detail_text)

    def handle_validate(self) -> None:
        self.controller.validate_current_page()
        self.status_label.setText(self.controller.status_text)
        self.detail_label.setText(self.controller.detail_text)

    def handle_start(self) -> None:
        self.controller.start_sync()
        self.refresh_labels()

    def handle_sample_download(self) -> None:
        self.controller.download_first_visible_sample()
        self.refresh_labels()

    def handle_stop(self) -> None:
        self.controller.stop_sync()
        self.refresh_labels()

    def handle_open_downloads(self) -> None:
        self.controller.open_downloads_dir()
        self.refresh_labels()

    def handle_summary(self) -> None:
        self.controller.show_latest_summary()
        self.refresh_labels()

    def refresh_labels(self) -> None:
        self.controller.poll_runtime_state()
        self.status_label.setText(self.controller.status_text)
        self.detail_label.setText(self.controller.detail_text)
        self.summary_label.setText(self.controller.summary_text)
