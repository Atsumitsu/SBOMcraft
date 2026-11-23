# ui/settings_dialog.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
    QWidget, QLabel, QPushButton, QMessageBox, QGroupBox, QFormLayout
)

from core.i18n import t
from core.license_manager import SPDXLicenseManager
from ui import theme


class SettingsDialog(QDialog):
    """将来の設定拡張を見据えたタブ形式の設定画面"""
    def __init__(self, license_manager: SPDXLicenseManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self.resize(560, 420)
        self.license_manager = license_manager

        self.init_ui()
        self.update_license_metadata_display()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget()

        # --- タブ1: SPDX ライセンス管理 ---
        self.license_tab = QWidget()
        self.init_license_tab_ui()
        self.tab_widget.addTab(self.license_tab, t("settings.tab_license"))

        main_layout.addWidget(self.tab_widget)

        # --- 下部共通ボタン ---
        btn_layout = QHBoxLayout()
        btn_close = QPushButton(t("settings.close"))
        btn_close.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)

        main_layout.addLayout(btn_layout)

    def init_license_tab_ui(self):
        layout = QVBoxLayout(self.license_tab)

        desc_label = QLabel(t("settings.desc"))
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # ステータス表示グループボックス
        group_box = QGroupBox(t("settings.group"))
        form_layout = QFormLayout(group_box)

        self.lbl_status = QLabel(t("settings.status_checking"))
        self.lbl_version = QLabel("-")
        self.lbl_date = QLabel("-")
        self.lbl_count = QLabel("-")
        self.lbl_exc_count = QLabel("-")

        form_layout.addRow(t("settings.row_status"), self.lbl_status)
        form_layout.addRow(t("settings.row_version"), self.lbl_version)
        form_layout.addRow(t("settings.row_date"), self.lbl_date)
        form_layout.addRow(t("settings.row_count"), self.lbl_count)
        form_layout.addRow(t("settings.row_exc_count"), self.lbl_exc_count)

        layout.addWidget(group_box)

        # ダウンロードボタン
        btn_download_layout = QHBoxLayout()
        self.btn_download = QPushButton(t("settings.btn_download"))
        self.btn_download.clicked.connect(self.on_download_clicked)
        btn_download_layout.addStretch()
        btn_download_layout.addWidget(self.btn_download)
        btn_download_layout.addStretch()

        layout.addLayout(btn_download_layout)
        layout.addStretch()

    def update_license_metadata_display(self):
        """ローカルキャッシュのメタデータを取得して画面に反映する"""
        tok = theme.tokens()     # ※ 変数名を t にすると翻訳関数 t() を隠してしまうため tok とする
        meta = self.license_manager.get_metadata()
        if meta["exists"]:
            self.lbl_status.setText(
                f"<font color='{tok.success_fg}'><b>{html.escape(t('settings.status_ok'))}</b></font>")
            self.lbl_version.setText(str(meta["version"]))
            self.lbl_date.setText(meta["released_date"])
            self.lbl_count.setText(t("settings.count", n=f"{meta['count']:,}"))
            self.lbl_exc_count.setText(t("settings.count", n=f"{meta.get('exc_count', 0):,}"))
        else:
            self.lbl_status.setText(
                f"<font color='{tok.danger_fg}'><b>{html.escape(t('settings.status_none'))}</b></font>")
            self.lbl_version.setText(t("settings.not_installed"))
            self.lbl_date.setText("-")
            self.lbl_count.setText(t("settings.count", n="0"))
            self.lbl_exc_count.setText(t("settings.count", n="0"))

    def on_download_clicked(self):
        """ダウンロードボタン押下時の処理"""
        self.btn_download.setEnabled(False)
        self.btn_download.setText(t("settings.downloading"))
        self.setCursor(Qt.CursorShape.WaitCursor)

        try:
            success, message = self.license_manager.download_latest_list()
            if success:
                QMessageBox.information(self, t("settings.success"), message)
                self.update_license_metadata_display()
            else:
                QMessageBox.warning(self, t("settings.failure"), message)
        except Exception as e:
            QMessageBox.critical(self, t("settings.error"), t("settings.unexpected", error=e))
        finally:
            self.btn_download.setEnabled(True)
            self.btn_download.setText(t("settings.btn_download"))
            self.unsetCursor()
