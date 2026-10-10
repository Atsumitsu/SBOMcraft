# ui/settings_dialog.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, 
    QWidget, QLabel, QPushButton, QMessageBox, QGroupBox, QFormLayout
)
from core.license_manager import SPDXLicenseManager

class SettingsDialog(QDialog):
    """将来の設定拡張を見据えたタブ形式の設定画面"""
    def __init__(self, license_manager: SPDXLicenseManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定 (Settings)")
        self.resize(550, 420)
        self.license_manager = license_manager
        
        self.init_ui()
        self.update_license_metadata_display()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget()
        
        # --- タブ1: SPDX ライセンス管理 ---
        self.license_tab = QWidget()
        self.init_license_tab_ui()
        self.tab_widget.addTab(self.license_tab, "📜 SPDX ライセンス")

        main_layout.addWidget(self.tab_widget)

        # --- 下部共通ボタン ---
        btn_layout = QHBoxLayout()
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        
        main_layout.addLayout(btn_layout)

    def init_license_tab_ui(self):
        layout = QVBoxLayout(self.license_tab)

        desc_label = QLabel(
            "SBOMのライセンス検証に使用する公式 SPDX ライセンスリストおよび例外リストの管理を行います。\n"
            "インターネットから最新のリストをダウンロードして更新できます。"
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # ステータス表示グループボックス
        group_box = QGroupBox("ローカルキャッシュ情報")
        form_layout = QFormLayout(group_box)

        self.lbl_status = QLabel("確認中...")
        self.lbl_version = QLabel("-")
        self.lbl_date = QLabel("-")
        self.lbl_count = QLabel("-")
        self.lbl_exc_count = QLabel("-") # ← 追加

        form_layout.addRow("ステータス:", self.lbl_status)
        form_layout.addRow("リストバージョン:", self.lbl_version)
        form_layout.addRow("最終更新日時:", self.lbl_date)
        form_layout.addRow("登録ライセンス数:", self.lbl_count)
        form_layout.addRow("登録例外(Exceptions)数:", self.lbl_exc_count) # ← 追加

        layout.addWidget(group_box)

        # ダウンロードボタン
        btn_download_layout = QHBoxLayout()
        self.btn_download = QPushButton("🔄 最新の SPDX ライセンスリストをダウンロード / 更新")
        self.btn_download.clicked.connect(self.on_download_clicked)
        btn_download_layout.addStretch()
        btn_download_layout.addWidget(self.btn_download)
        btn_download_layout.addStretch()

        layout.addLayout(btn_download_layout)
        layout.addStretch()

    def update_license_metadata_display(self):
        """ローカルキャッシュのメタデータを取得して画面に反映する"""
        meta = self.license_manager.get_metadata()
        if meta["exists"]:
            self.lbl_status.setText("<font color='green'><b>利用可能 (キャッシュあり)</b></font>")
            self.lbl_version.setText(meta["version"])
            self.lbl_date.setText(meta["released_date"])
            self.lbl_count.setText(f"{meta['count']:,} 件")
            self.lbl_exc_count.setText(f"{meta.get('exc_count', 0):,}" + " 件")
        else:
            self.lbl_status.setText("<font color='red'><b>未ダウンロード (キャッシュなし)</b></font>")
            self.lbl_version.setText("未導入")
            self.lbl_date.setText("-")
            self.lbl_count.setText("0 件")
            self.lbl_exc_count.setText("0 件")

    def on_download_clicked(self):
        """ダウンロードボタン押下時の処理"""
        self.btn_download.setEnabled(False)
        self.btn_download.setText("ダウンロード中...")
        self.setCursor(Qt.CursorShape.WaitCursor)
        
        try:
            success, message = self.license_manager.download_latest_list()
            if success:
                QMessageBox.information(self, "成功", message)
                self.update_license_metadata_display()
            else:
                QMessageBox.warning(self, "失敗", message)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"予期せぬエラーが発生しました:\n{str(e)}")
        finally:
            self.btn_download.setEnabled(True)
            self.btn_download.setText("🔄 最新の SPDX ライセンスリストをダウンロード / 更新")
            self.unsetCursor()
            