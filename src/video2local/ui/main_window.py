from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from video2local.ui.controller import MainController


class MainWindow(QMainWindow):
    def __init__(self, controller: MainController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Video2Local")

        self.status_label = QLabel(self.controller.status_text)
        self.detail_label = QLabel(self.controller.detail_text)
        self.launch_button = QPushButton("启动 Chrome")
        self.launch_button.clicked.connect(self.handle_launch)
        self.validate_button = QPushButton("检查当前页面")
        self.validate_button.clicked.connect(self.handle_validate)
        self.start_button = QPushButton("开始同步")
        self.start_button.clicked.connect(self.handle_start)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.launch_button)
        layout.addWidget(self.validate_button)
        layout.addWidget(self.start_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

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
        self.status_label.setText(self.controller.status_text)
        self.detail_label.setText(self.controller.detail_text)
