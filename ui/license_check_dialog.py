# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
    QTableWidgetItem, QPushButton, QLabel, QHeaderView, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from core.parser import SBOMNode
from core.license_manager import SPDXLicenseManager
from core.license_validator import LicenseStringValidator

class LicenseCheckDialog(QDialog):
    """パッケージのライセンス情報を表形式で一覧表示し、検証結果をハイライトするダイアログ"""
    def __init__(self, root_node: SBOMNode, license_manager: SPDXLicenseManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("パッケージライセンス詳細チェック")
        self.resize(1000, 600)
        
        self.root_node = root_node
        self.license_manager = license_manager
        self.validator = LicenseStringValidator(license_manager)

        self.init_ui()
        self.load_package_licenses()

    def init_ui(self):
        layout = QVBoxLayout(self)

        info_label = QLabel(
            "SBOMに含まれる全パッケージのライセンス情報（Concluded / Declared）の検証結果一覧です。\n"
            "🟢 <font color='green'>薄い緑</font>: 未定義値（NOASSERTION等）  |  "
            "🔴 <font color='red'>薄い赤</font>: 未登録または無効なライセンス識別子"
        )
        layout.addWidget(info_label)

        # テーブルの定義（7列）
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "パッケージID", "パッケージ名", "バージョン", 
            "Concluded 記載", "Concluded 指摘事項", 
            "Declared 記載", "Declared 指摘事項"
        ])
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        # 下部ボタンレイアウト
        btn_layout = QHBoxLayout()
        
        # ▼ 追加: CSVエクスポートボタン
        self.btn_csv = QPushButton("📥 CSVエクスポート")
        self.btn_csv.clicked.connect(self.export_to_csv)
        btn_layout.addWidget(self.btn_csv)
        
        btn_layout.addStretch()
        
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)

    def load_package_licenses(self):
        """ツリーからパッケージを走査してテーブルにデータを流し込む"""
        packages_folder = self._find_packages_folder(self.root_node)
        if not packages_folder:
            return

        pkg_nodes = [c for c in packages_folder.children if c.node_type == "package"]
        self.table.setRowCount(len(pkg_nodes))

        green_color = QColor("#e8f8f5")  # 薄い緑（プレースホルダー用）
        red_color = QColor("#fadbd8")    # 薄い赤（エラー用）

        for row_idx, pkg_node in enumerate(pkg_nodes):
            props = pkg_node.properties
            pkg_id = pkg_node.spdx_id or props.get("SPDXID", "-")
            name = props.get("name", pkg_node.name or "Unknown")
            version = props.get("versionInfo", props.get("version", "-"))

            concluded_raw = props.get("licenseConcluded", "")
            declared_raw = props.get("licenseDeclared", "")

            conc_res = self.validator.validate_license_expression(concluded_raw)
            dec_res = self.validator.validate_license_expression(declared_raw)

            conc_msg = "" if conc_res["is_valid"] else conc_res["message"]
            dec_msg = "" if dec_res["is_valid"] else dec_res["message"]

            has_error = (not conc_res["is_valid"]) or (not dec_res["is_valid"])
            is_placeholder_only = (conc_res["status"] == "PLACEHOLDER" and dec_res["status"] == "PLACEHOLDER")

            row_bg = None
            if has_error:
                row_bg = red_color
            elif is_placeholder_only:
                row_bg = green_color

            items = [
                QTableWidgetItem(pkg_id),
                QTableWidgetItem(name),
                QTableWidgetItem(str(version)),
                QTableWidgetItem(str(concluded_raw)),
                QTableWidgetItem(conc_msg if conc_msg else "-"),
                QTableWidgetItem(str(declared_raw)),
                QTableWidgetItem(dec_msg if dec_msg else "-")
            ]

            for col_idx, item in enumerate(items):
                if row_bg:
                    item.setBackground(row_bg)
                if col_idx in (4, 6) and items[col_idx].text() != "-":
                    item.setForeground(QColor("#c0392b"))
                
                self.table.setItem(row_idx, col_idx, item)

    def export_to_csv(self):
        """テーブルのデータをカンマ区切り、全項目ダブルクォーテーション囲みでCSV出力する"""
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "Warning", "エクスポートするデータがありません。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "CSVエクスポート", "license_check_report.csv", "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                # 1. ヘッダー行の書き出し
                headers = []
                for col in range(self.table.columnCount()):
                    header_item = self.table.horizontalHeaderItem(col)
                    text = header_item.text() if header_item else ""
                    # ダブルクォーテーションのエスケープ（念のため内部の " を "" に置換）
                    escaped = text.replace('"', '""')
                    headers.append(f'"{escaped}"')
                f.write(",".join(headers) + "\n")

                # 2. データ行の書き出し
                for row in range(self.table.rowCount()):
                    row_data = []
                    for col in range(self.table.columnCount()):
                        item = self.table.item(row, col)
                        text = item.text() if item else ""
                        escaped = text.replace('"', '""')
                        row_data.append(f'"{escaped}"')
                    f.write(",".join(row_data) + "\n")

            QMessageBox.information(self, "完了", f"CSVファイルの出力が完了しました:\n{file_path}")

        except Exception as e:
            QMessageBox.critical(self, "エラー", f"CSVの出力中にエラーが発生しました:\n{str(e)}")

    def _find_packages_folder(self, node: SBOMNode) -> SBOMNode:
        if not node:
            return None
        if node.node_type == "packages_folder":
            return node
        for child in node.children:
            found = self._find_packages_folder(child)
            if found:
                return found
        return None
    