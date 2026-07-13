from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QHeaderView,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from video2local.ui.controller import MainController


class MainWindow(QMainWindow):
    def __init__(self, controller: MainController) -> None:
        super().__init__()
        self.controller = controller
        self._rendered_results_revision = -1
        self.setWindowTitle("Video2Local")
        self.resize(1240, 780)
        self.setStyleSheet(
            """
            QMainWindow { background: #f7f5ef; }
            QWidget { color: #1f2937; font-size: 13px; }
            QGroupBox {
                background: rgba(255, 255, 252, 0.97);
                border: 1px solid #ddd4c1;
                border-radius: 18px;
                margin-top: 16px;
                padding-top: 14px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
                color: #7b6248;
            }
            QLabel#heroTitle { font-size: 26px; font-weight: 700; color: #25403b; }
            QLabel#heroBody { color: #5f6b68; line-height: 1.5; }
            QLabel#sectionHint { color: #667085; padding-bottom: 6px; }
            QLabel#statusChip {
                background: #fcfbf7;
                border: 1px solid #e5ddcd;
                border-radius: 14px;
                padding: 9px 12px;
            }
            QLineEdit {
                background: white;
                border: 1px solid #d8d0bf;
                border-radius: 12px;
                padding: 9px 12px;
                min-height: 18px;
            }
            QTableWidget {
                background: white;
                border: 1px solid #d8d0bf;
                border-radius: 14px;
                gridline-color: #ece4d3;
            }
            QTableWidget QScrollBar:vertical {
                background: #ece3d1;
                width: 16px;
                margin: 2px;
                border-radius: 8px;
            }
            QTableWidget QScrollBar::handle:vertical {
                background: #aa8f6d;
                min-height: 28px;
                border-radius: 8px;
            }
            QTableWidget QScrollBar:horizontal {
                background: #ece3d1;
                height: 16px;
                margin: 2px;
                border-radius: 8px;
            }
            QTableWidget QScrollBar::handle:horizontal {
                background: #aa8f6d;
                min-width: 28px;
                border-radius: 8px;
            }
            QTableWidget QScrollBar::add-line,
            QTableWidget QScrollBar::sub-line,
            QTableWidget QScrollBar::add-page,
            QTableWidget QScrollBar::sub-page {
                background: transparent;
                border: none;
            }
            QHeaderView::section {
                background: #f7f3ea;
                border: none;
                border-bottom: 1px solid #e7decc;
                padding: 10px 8px;
                font-weight: 600;
            }
            QPushButton {
                background: #d57a4a;
                color: white;
                border: none;
                border-radius: 12px;
                padding: 9px 14px;
                font-weight: 600;
                min-height: 18px;
            }
            QPushButton:hover { background: #c86b3e; }
            QPushButton#secondaryButton { background: #eef1e8; color: #41544a; }
            QPushButton#secondaryButton:hover { background: #e2e8dc; }
            QPushButton#accentButton { background: #2f6c5d; }
            QPushButton#accentButton:hover { background: #285b4f; }
            QPushButton#platformButton { background: #ece8dc; color: #58645d; min-width: 104px; }
            QPushButton#platformButton:checked { background: #254f45; color: white; }
            QFrame#panelCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fffdf8, stop:1 #f4efe4);
                border: 1px solid #ddd4c1;
                border-radius: 20px;
            }
            QCheckBox {
                spacing: 8px;
                color: #425466;
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
        self.douyin_platform_button = QPushButton("抖音工作台")
        self.bilibili_platform_button = QPushButton("Bilibili 工作台")
        for button in (self.douyin_platform_button, self.bilibili_platform_button):
            button.setObjectName("platformButton")
            button.setCheckable(True)
        self.douyin_platform_button.setChecked(True)
        self.platform_buttons = QButtonGroup(self)
        self.platform_buttons.addButton(self.douyin_platform_button)
        self.platform_buttons.addButton(self.bilibili_platform_button)
        self.douyin_platform_button.clicked.connect(lambda: self.handle_platform_switch("douyin"))
        self.bilibili_platform_button.clicked.connect(lambda: self.handle_platform_switch("bilibili"))
        self.output_dir_input = QLineEdit(self.controller.output_dir_text)
        self.output_dir_input.setReadOnly(True)
        self.output_dir_button = QPushButton("选择目录")
        self.output_dir_button.setObjectName("secondaryButton")
        self.output_dir_button.clicked.connect(self.handle_choose_output_dir)
        self.flat_output_checkbox = QCheckBox("直接下载到所选目录，不再分平台/作者子目录")
        self.flat_output_checkbox.setChecked(self.controller.flat_output_enabled)
        self.limit_input = QLineEdit(self.controller.sync_limit_text)
        self.limit_input.setPlaceholderText("全部")
        self.retry_input = QLineEdit(self.controller.retry_count_text)
        self.retry_input.setPlaceholderText("1")
        self.native_resolver_checkbox = QCheckBox("原生解析")
        self.native_resolver_checkbox.setChecked("native" in self.controller.resolver_sources)
        self.kukutool_resolver_checkbox = QCheckBox("Kukutool")
        self.kukutool_resolver_checkbox.setChecked("kukutool" in self.controller.resolver_sources)
        self.share_input = QLineEdit()
        self.share_input.setPlaceholderText("粘贴抖音或哔哩哔哩分享文案、短链或视频链接")
        self.parse_share_button = QPushButton("解析分享链接")
        self.parse_share_button.setObjectName("accentButton")
        self.parse_share_button.clicked.connect(self.handle_parse_share)
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
        self.preview_button = QPushButton("同步前预览")
        self.preview_button.setObjectName("secondaryButton")
        self.preview_button.clicked.connect(self.handle_preview_sync)
        self.results_table = QTableWidget(0, 6)
        self.results_table.setMinimumHeight(220)
        self.results_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_table.setWordWrap(False)
        self.results_table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.results_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.results_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.results_table.horizontalHeader().setStretchLastSection(False)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.results_table.horizontalHeader().setMinimumSectionSize(120)
        self.results_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.results_table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self._configure_results_table_for_sync_preview()

        self.status_label.setObjectName("statusChip")
        self.source_label.setObjectName("statusChip")
        self.detail_label.setObjectName("statusChip")
        self.summary_label.setObjectName("statusChip")
        for label in (self.status_label, self.source_label, self.detail_label, self.summary_label):
            label.setWordWrap(True)

        hero_layout = QVBoxLayout()
        hero_layout.setContentsMargins(18, 14, 18, 14)
        hero_layout.setSpacing(4)
        hero_layout.addWidget(self.hero_title)
        platform_row = QHBoxLayout()
        platform_row.setSpacing(8)
        platform_row.addWidget(self.douyin_platform_button)
        platform_row.addWidget(self.bilibili_platform_button)
        platform_row.addStretch(1)
        hero_layout.addLayout(platform_row)
        hero_layout.addWidget(self.guide_label)
        hero_card = QFrame()
        hero_card.setObjectName("panelCard")
        hero_card.setLayout(hero_layout)

        settings_group = QGroupBox("下载设置")
        settings_layout = QGridLayout()
        settings_layout.setContentsMargins(14, 16, 14, 14)
        settings_layout.setHorizontalSpacing(10)
        settings_layout.setVerticalSpacing(8)
        settings_layout.addWidget(QLabel("输出目录"), 0, 0)
        settings_layout.addWidget(self.output_dir_input, 0, 1)
        settings_layout.addWidget(self.output_dir_button, 0, 2)
        settings_layout.addWidget(self.flat_output_checkbox, 1, 0, 1, 3)
        settings_layout.addWidget(QLabel("前 N 个视频"), 2, 0)
        settings_layout.addWidget(self.limit_input, 2, 1)
        settings_layout.addWidget(QLabel("留空表示下载当前页面全部可见视频"), 2, 2)
        self.resolver_label = QLabel("抖音解析来源")
        settings_layout.addWidget(self.resolver_label, 3, 0)
        resolver_row = QHBoxLayout()
        resolver_row.setSpacing(12)
        resolver_row.addWidget(self.native_resolver_checkbox)
        resolver_row.addWidget(self.kukutool_resolver_checkbox)
        resolver_row.addStretch(1)
        self.resolver_widget = QWidget()
        self.resolver_widget.setLayout(resolver_row)
        settings_layout.addWidget(self.resolver_widget, 3, 1, 1, 2)
        self.bilibili_resolver_hint = QLabel("Bilibili 固定使用原生解析和登录 cookies")
        self.bilibili_resolver_hint.setObjectName("sectionHint")
        self.bilibili_resolver_hint.setVisible(False)
        settings_layout.addWidget(self.bilibili_resolver_hint, 4, 1, 1, 2)
        settings_layout.addWidget(QLabel("失败重试"), 5, 0)
        settings_layout.addWidget(self.retry_input, 5, 1)
        settings_layout.addWidget(QLabel("串行重试次数，建议 0-2"), 5, 2)
        settings_group.setLayout(settings_layout)

        self.status_group = QGroupBox("运行状态")
        status_layout = QGridLayout()
        status_layout.setContentsMargins(14, 16, 14, 14)
        status_layout.setHorizontalSpacing(12)
        status_layout.setVerticalSpacing(8)
        status_layout.addWidget(QLabel("当前状态"), 0, 0)
        status_layout.addWidget(self.status_label, 0, 1)
        status_layout.addWidget(QLabel("解析来源"), 1, 0)
        status_layout.addWidget(self.source_label, 1, 1)
        status_layout.addWidget(QLabel("当前详情"), 2, 0)
        status_layout.addWidget(self.detail_label, 2, 1)
        status_layout.addWidget(QLabel("本次摘要"), 3, 0)
        status_layout.addWidget(self.summary_label, 3, 1)
        self.status_group.setLayout(status_layout)

        self.sync_group = QGroupBox("批量同步")
        sync_layout = QVBoxLayout()
        sync_layout.setContentsMargins(14, 16, 14, 14)
        sync_layout.setSpacing(10)
        self.sync_hint = QLabel("打开抖音收藏页或作者作品页。先检查当前页面，再下载首个样本确认链路。")
        self.sync_hint.setObjectName("sectionHint")
        sync_layout.addWidget(self.sync_hint)
        sync_buttons_row1 = QHBoxLayout()
        sync_buttons_row1.setSpacing(8)
        sync_buttons_row1.addWidget(self.launch_button)
        sync_buttons_row1.addWidget(self.validate_button)
        sync_layout.addLayout(sync_buttons_row1)
        sync_buttons_row2 = QHBoxLayout()
        sync_buttons_row2.setSpacing(8)
        sync_buttons_row2.addWidget(self.sample_button)
        sync_buttons_row2.addWidget(self.preview_button)
        sync_buttons_row2.addWidget(self.start_button)
        sync_buttons_row2.addWidget(self.stop_button)
        sync_layout.addLayout(sync_buttons_row2)
        sync_buttons_row3 = QHBoxLayout()
        sync_buttons_row3.setSpacing(8)
        sync_buttons_row3.addWidget(self.open_downloads_button)
        sync_buttons_row3.addWidget(self.summary_button)
        sync_layout.addLayout(sync_buttons_row3)
        self.sync_group.setLayout(sync_layout)

        self.share_group = QGroupBox("单链接解析")
        share_layout = QVBoxLayout()
        share_layout.setContentsMargins(14, 16, 14, 14)
        share_layout.setSpacing(10)
        self.share_hint = QLabel("粘贴抖音分享文案或短链，查看各来源的清晰度后下载所选版本。")
        self.share_hint.setObjectName("sectionHint")
        share_layout.addWidget(self.share_hint)
        share_layout.addWidget(self.share_input)
        share_actions = QHBoxLayout()
        share_actions.setSpacing(8)
        share_actions.addWidget(self.parse_share_button)
        share_actions.addWidget(self.download_share_button)
        share_layout.addLayout(share_actions)
        self.share_group.setLayout(share_layout)

        self.results_group = QGroupBox("结果预览")
        results_layout = QVBoxLayout()
        results_layout.setContentsMargins(14, 16, 14, 14)
        results_layout.setSpacing(8)
        results_hint = QLabel("批量预览和单链接解析共用这一张表；每个清晰度版本都会标记解析来源。")
        results_hint.setObjectName("sectionHint")
        results_layout.addWidget(results_hint)
        results_layout.addWidget(self.results_table)
        self.results_group.setLayout(results_layout)

        right_column = QVBoxLayout()
        right_column.setSpacing(12)
        right_column.addWidget(self.share_group)
        right_column.addWidget(self.status_group)
        right_column.addStretch(1)

        operations_layout = QHBoxLayout()
        operations_layout.setSpacing(12)
        operations_layout.addWidget(self.sync_group, 1)
        operations_layout.addLayout(right_column, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(hero_card)
        layout.addWidget(settings_group)
        layout.addLayout(operations_layout)
        layout.addWidget(self.results_group, 1)

        container = QWidget()
        container.setLayout(layout)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setWidget(container)
        self.setCentralWidget(scroll_area)
        self._apply_platform_mode(self.controller.platform_mode)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(200)
        self.refresh_timer.timeout.connect(self.refresh_labels)
        self.refresh_timer.start()

    def handle_platform_switch(self, platform: str) -> None:
        self.controller.set_platform_mode(platform)
        self._apply_platform_mode(platform)
        self.refresh_labels()

    def _apply_platform_mode(self, platform: str) -> None:
        is_douyin = platform == "douyin"
        self.douyin_platform_button.setChecked(is_douyin)
        self.bilibili_platform_button.setChecked(not is_douyin)
        self.resolver_label.setVisible(is_douyin)
        self.resolver_widget.setVisible(is_douyin)
        self.bilibili_resolver_hint.setVisible(not is_douyin)
        if is_douyin:
            self.sync_hint.setText("打开抖音收藏页或作者作品页。先检查当前页面，再下载首个样本确认链路。")
            self.share_hint.setText("粘贴抖音分享文案或短链，查看各来源的清晰度后下载所选版本。")
            self.share_input.setPlaceholderText("粘贴抖音分享文案、短链或视频链接")
        else:
            self.sync_hint.setText("打开 Bilibili 收藏夹或 UP 主投稿页。程序使用登录 cookies 获取可用画质。")
            self.share_hint.setText("粘贴 Bilibili 视频链接、b23 短链或分享文案，原生解析后下载所选版本。")
            self.share_input.setPlaceholderText("粘贴 Bilibili 视频链接、b23 短链或分享文案")

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

    def handle_preview_sync(self) -> None:
        if not self.apply_download_options():
            return
        self.controller.preview_sync()
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
        row = self._checked_share_variant_row()
        if row < 0 or row >= len(self.controller.share_variants):
            self.controller.status_text = "错误: 未选择清晰度版本"
            self.controller.detail_text = "请先勾选一个清晰度版本，再开始下载"
            self.refresh_labels()
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
            self.controller.set_flat_output(self.flat_output_checkbox.isChecked())
            self.controller.set_sync_limit(self.limit_input.text())
            self.controller.set_retry_count(self.retry_input.text())
            if self.controller.platform_mode == "douyin":
                resolver_sources: list[str] = []
                if self.native_resolver_checkbox.isChecked():
                    resolver_sources.append("native")
                if self.kukutool_resolver_checkbox.isChecked():
                    resolver_sources.append("kukutool")
                self.controller.set_resolver_sources(tuple(resolver_sources))
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
        self.refresh_results_table()

    def refresh_results_table(self) -> None:
        if self._rendered_results_revision != self.controller.results_revision:
            self.results_table.clearContents()
            self.results_table.setRowCount(0)
            self._rendered_results_revision = self.controller.results_revision
        if self.controller.results_mode == "share_parse":
            self._configure_results_table_for_share_variants()
            self._refresh_share_results_rows()
            return
        self._configure_results_table_for_sync_preview()
        self._refresh_sync_preview_rows()

    def _configure_results_table_for_share_variants(self) -> None:
        self.results_table.setColumnCount(7)
        self.results_table.setHorizontalHeaderLabels(["选择", "清晰度", "来源", "编码", "码率", "大小", "推荐"])
        self.results_table.setColumnWidth(0, 80)
        self.results_table.setColumnWidth(1, 140)
        self.results_table.setColumnWidth(2, 120)
        self.results_table.setColumnWidth(3, 140)
        self.results_table.setColumnWidth(4, 140)
        self.results_table.setColumnWidth(5, 140)
        self.results_table.setColumnWidth(6, 100)

    def _configure_results_table_for_sync_preview(self) -> None:
        self.results_table.setColumnCount(6)
        self.results_table.setHorizontalHeaderLabels(["作者", "标题", "视频ID", "解析来源", "可用版本", "默认下载"])
        self.results_table.setColumnWidth(0, 140)
        self.results_table.setColumnWidth(1, 280)
        self.results_table.setColumnWidth(2, 180)
        self.results_table.setColumnWidth(3, 140)
        self.results_table.setColumnWidth(4, 380)
        self.results_table.setColumnWidth(5, 140)

    def _refresh_share_results_rows(self) -> None:
        variants = self.controller.share_variants
        self.results_table.setRowCount(len(variants))
        for row, variant in enumerate(variants):
            check_item = self.results_table.item(row, 0)
            if check_item is None:
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                check_item.setCheckState(Qt.Unchecked)
                self.results_table.setItem(row, 0, check_item)
            bit_rate = getattr(variant, "bit_rate", None)
            file_size = getattr(variant, "file_size", None)
            self.results_table.setItem(row, 1, QTableWidgetItem(getattr(variant, "quality_label", "")))
            self.results_table.setItem(row, 2, QTableWidgetItem(getattr(variant, "provider_id", "native")))
            self.results_table.setItem(row, 3, QTableWidgetItem(getattr(variant, "codec_label", "")))
            self.results_table.setItem(row, 4, QTableWidgetItem("" if bit_rate is None else f"{bit_rate / 1000:.0f} kbps"))
            self.results_table.setItem(row, 5, QTableWidgetItem("" if file_size is None else f"{file_size / 1024 / 1024:.2f} MB"))
            self.results_table.setItem(row, 6, QTableWidgetItem("是" if getattr(variant, "is_recommended", False) else ""))

    def _refresh_sync_preview_rows(self) -> None:
        items = self.controller.sync_preview_items
        self.results_table.setRowCount(len(items))
        for row, item in enumerate(items):
            metadata = getattr(item, "metadata")
            self.results_table.setItem(row, 0, QTableWidgetItem(getattr(metadata, "author_name", "")))
            self.results_table.setItem(row, 1, QTableWidgetItem(getattr(metadata, "title", "") or getattr(metadata, "video_id", "")))
            self.results_table.setItem(row, 2, QTableWidgetItem(getattr(metadata, "video_id", "")))
            self.results_table.setItem(row, 3, QTableWidgetItem(getattr(item, "provider_summary", "")))
            self.results_table.setItem(row, 4, QTableWidgetItem(getattr(item, "variant_summary", "")))
            self.results_table.setItem(row, 5, QTableWidgetItem(getattr(item, "selected_quality_label", "") or ""))

    def _checked_share_variant_row(self) -> int:
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                return row
        return -1
