from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from video2local.ui.controller import MainController


class MainWindow(QMainWindow):
    def __init__(self, controller: MainController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Video2Local")
        self.resize(1180, 760)
        self.setStyleSheet(
            """
            QMainWindow { background: #f4efe6; }
            QWidget { color: #1f2937; font-size: 13px; }
            QGroupBox {
                background: rgba(255, 252, 247, 0.94);
                border: 1px solid #decfb5;
                border-radius: 16px;
                margin-top: 14px;
                padding-top: 12px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
                color: #7c4f2b;
            }
            QLabel#heroTitle { font-size: 24px; font-weight: 700; color: #6e4023; }
            QLabel#heroBody { color: #5b6472; line-height: 1.4; }
            QLabel#statusChip {
                background: #fffaf1;
                border: 1px solid #e7d5b5;
                border-radius: 12px;
                padding: 10px 12px;
            }
            QLineEdit {
                background: white;
                border: 1px solid #d8c7ab;
                border-radius: 10px;
                padding: 10px 12px;
            }
            QTableWidget {
                background: white;
                border: 1px solid #d8c7ab;
                border-radius: 12px;
                gridline-color: #eadfcb;
            }
            QHeaderView::section {
                background: #f7efe1;
                border: none;
                border-bottom: 1px solid #e4d3b8;
                padding: 8px;
                font-weight: 600;
            }
            QPushButton {
                background: #b85c38;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 10px 14px;
                font-weight: 600;
            }
            QPushButton:hover { background: #a65030; }
            QPushButton#secondaryButton { background: #efe2c8; color: #7a4d29; }
            QPushButton#secondaryButton:hover { background: #e6d4b2; }
            QPushButton#accentButton { background: #2f6c5d; }
            QPushButton#accentButton:hover { background: #275a4e; }
            QFrame#panelCard {
                background: rgba(255, 252, 247, 0.96);
                border: 1px solid #decfb5;
                border-radius: 18px;
            }
            """
        )

        self.hero_title = QLabel("Video2Local")
        self.hero_title.setObjectName("heroTitle")
        self.guide_label = QLabel(
            "浏览器页批量同步与分享链接单条下载共用一套目录设置。\n"
            "先选择输出目录，再决定同步前 N 个视频，最后开始批量或单条下载。"
        )
        self.guide_label.setObjectName("heroBody")
        self.guide_label.setWordWrap(True)
        self.output_dir_input = QLineEdit(self.controller.output_dir_text)
        self.output_dir_input.setReadOnly(True)
        self.output_dir_button = QPushButton("选择目录")
        self.output_dir_button.setObjectName("secondaryButton")
        self.output_dir_button.clicked.connect(self.handle_choose_output_dir)
        self.limit_input = QLineEdit(self.controller.sync_limit_text)
        self.limit_input.setPlaceholderText("全部")
        self.share_input = QLineEdit()
        self.share_input.setPlaceholderText("粘贴抖音分享文案或分享链接")
        self.parse_share_button = QPushButton("解析分享链接")
        self.parse_share_button.setObjectName("accentButton")
        self.parse_share_button.clicked.connect(self.handle_parse_share)
        self.share_table = QTableWidget(0, 5)
        self.share_table.setHorizontalHeaderLabels(["清晰度", "编码", "码率", "大小", "推荐"])
        self.download_share_button = QPushButton("下载所选版本")
        self.download_share_button.clicked.connect(self.handle_download_share)
        self.status_label = QLabel(self.controller.status_text)
        self.source_label = QLabel(self.controller.source_text)
        self.detail_label = QLabel(self.controller.detail_text)
        self.summary_label = QLabel(self.controller.summary_text)
        self.launch_button = QPushButton("启动 Chrome")
        self.launch_button.clicked.connect(self.handle_launch)
        self.validate_button = QPushButton("检查当前页面")
        self.validate_button.setObjectName("secondaryButton")
        self.validate_button.clicked.connect(self.handle_validate)
        self.sample_button = QPushButton("下载首个样本")
        self.sample_button.setObjectName("secondaryButton")
        self.sample_button.clicked.connect(self.handle_sample_download)
        self.start_button = QPushButton("开始同步")
        self.start_button.setObjectName("accentButton")
        self.start_button.clicked.connect(self.handle_start)
        self.stop_button = QPushButton("停止同步")
        self.stop_button.setObjectName("secondaryButton")
        self.stop_button.clicked.connect(self.handle_stop)
        self.open_downloads_button = QPushButton("打开下载目录")
        self.open_downloads_button.setObjectName("secondaryButton")
        self.open_downloads_button.clicked.connect(self.handle_open_downloads)
        self.summary_button = QPushButton("查看最近摘要")
        self.summary_button.setObjectName("secondaryButton")
        self.summary_button.clicked.connect(self.handle_summary)

        self.status_label.setObjectName("statusChip")
        self.source_label.setObjectName("statusChip")
        self.detail_label.setObjectName("statusChip")
        self.summary_label.setObjectName("statusChip")
        for label in (self.status_label, self.source_label, self.detail_label, self.summary_label):
            label.setWordWrap(True)

        hero_layout = QVBoxLayout()
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.guide_label)
        hero_card = QFrame()
        hero_card.setObjectName("panelCard")
        hero_card.setLayout(hero_layout)

        settings_group = QGroupBox("下载设置")
        settings_layout = QGridLayout()
        settings_layout.addWidget(QLabel("输出目录"), 0, 0)
        settings_layout.addWidget(self.output_dir_input, 0, 1)
        settings_layout.addWidget(self.output_dir_button, 0, 2)
        settings_layout.addWidget(QLabel("前 N 个视频"), 1, 0)
        settings_layout.addWidget(self.limit_input, 1, 1)
        settings_layout.addWidget(QLabel("留空表示下载当前页面全部可见视频"), 1, 2)
        settings_group.setLayout(settings_layout)

        status_group = QGroupBox("运行状态")
        status_layout = QGridLayout()
        status_layout.addWidget(QLabel("当前状态"), 0, 0)
        status_layout.addWidget(self.status_label, 0, 1)
        status_layout.addWidget(QLabel("解析来源"), 1, 0)
        status_layout.addWidget(self.source_label, 1, 1)
        status_layout.addWidget(QLabel("当前详情"), 2, 0)
        status_layout.addWidget(self.detail_label, 2, 1)
        status_layout.addWidget(QLabel("本次摘要"), 3, 0)
        status_layout.addWidget(self.summary_label, 3, 1)
        status_group.setLayout(status_layout)

        sync_group = QGroupBox("批量同步")
        sync_layout = QVBoxLayout()
        sync_layout.addWidget(QLabel("用于收藏页或作者作品页。先检查当前页面，再下载首个样本确认链路。"))
        sync_buttons_row1 = QHBoxLayout()
        sync_buttons_row1.addWidget(self.launch_button)
        sync_buttons_row1.addWidget(self.validate_button)
        sync_layout.addLayout(sync_buttons_row1)
        sync_buttons_row2 = QHBoxLayout()
        sync_buttons_row2.addWidget(self.sample_button)
        sync_buttons_row2.addWidget(self.start_button)
        sync_buttons_row2.addWidget(self.stop_button)
        sync_layout.addLayout(sync_buttons_row2)
        sync_buttons_row3 = QHBoxLayout()
        sync_buttons_row3.addWidget(self.open_downloads_button)
        sync_buttons_row3.addWidget(self.summary_button)
        sync_layout.addLayout(sync_buttons_row3)
        sync_group.setLayout(sync_layout)

        share_group = QGroupBox("单链接解析")
        share_layout = QVBoxLayout()
        share_layout.addWidget(QLabel("适合分享文案或短链，先看清晰度信息，再下载所选版本。"))
        share_layout.addWidget(self.share_input)
        share_actions = QHBoxLayout()
        share_actions.addWidget(self.parse_share_button)
        share_actions.addWidget(self.download_share_button)
        share_layout.addLayout(share_actions)
        share_layout.addWidget(self.share_table)
        share_group.setLayout(share_layout)

        left_column = QVBoxLayout()
        left_column.addWidget(sync_group)
        left_column.addWidget(status_group)
        right_column = QVBoxLayout()
        right_column.addWidget(share_group)

        main_columns = QHBoxLayout()
        main_columns.addLayout(left_column, 5)
        main_columns.addLayout(right_column, 7)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(hero_card)
        layout.addWidget(settings_group)
        layout.addLayout(main_columns)

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
        if not self.apply_download_options():
            return
        self.controller.start_sync()
        self.refresh_labels()

    def handle_sample_download(self) -> None:
        if not self.apply_download_options():
            return
        self.controller.download_first_visible_sample()
        self.refresh_labels()

    def handle_parse_share(self) -> None:
        if not self.apply_download_options():
            return
        self.controller.parse_share_text(self.share_input.text())
        self.refresh_labels()

    def handle_download_share(self) -> None:
        if not self.apply_download_options():
            return
        row = self.share_table.currentRow()
        if row < 0 or row >= len(self.controller.share_variants):
            return
        variant = self.controller.share_variants[row]
        self.controller.download_share_variant(getattr(variant, "variant_id"))
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

    def handle_choose_output_dir(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(self, "选择下载输出目录", self.output_dir_input.text())
        if not selected_dir:
            return
        self.output_dir_input.setText(selected_dir)
        self.apply_download_options()

    def apply_download_options(self) -> bool:
        try:
            self.controller.set_output_dir(self.output_dir_input.text())
            self.controller.set_sync_limit(self.limit_input.text())
        except ValueError as exc:
            self.controller.status_text = f"错误: {exc}"
            self.controller.detail_text = "请修正下载设置后重试"
            self.refresh_labels()
            return False
        return True

    def refresh_labels(self) -> None:
        self.controller.poll_runtime_state()
        self.status_label.setText(self.controller.status_text)
        self.source_label.setText(self.controller.source_text)
        self.detail_label.setText(self.controller.detail_text)
        self.summary_label.setText(self.controller.summary_text)
        self.refresh_share_table()

    def refresh_share_table(self) -> None:
        variants = self.controller.share_variants
        self.share_table.setRowCount(len(variants))
        for row, variant in enumerate(variants):
            bit_rate = getattr(variant, "bit_rate", None)
            file_size = getattr(variant, "file_size", None)
            self.share_table.setItem(row, 0, QTableWidgetItem(getattr(variant, "quality_label", "")))
            self.share_table.setItem(row, 1, QTableWidgetItem(getattr(variant, "codec_label", "")))
            self.share_table.setItem(row, 2, QTableWidgetItem("" if bit_rate is None else f"{bit_rate / 1000:.0f} kbps"))
            self.share_table.setItem(row, 3, QTableWidgetItem("" if file_size is None else f"{file_size / 1024 / 1024:.2f} MB"))
            self.share_table.setItem(row, 4, QTableWidgetItem("是" if getattr(variant, "is_recommended", False) else ""))
