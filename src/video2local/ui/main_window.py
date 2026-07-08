from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from video2local.ui.controller import MainController


class MainWindow(QMainWindow):
    def __init__(self, controller: MainController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Video2Local")

        self.status_label = QLabel(self.controller.status_text)
        self.start_button = QPushButton("开始同步")
        self.start_button.clicked.connect(self.handle_start)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.start_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def handle_start(self) -> None:
        self.controller.start_sync()
        self.status_label.setText(self.controller.status_text)
