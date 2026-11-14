# ui/detail_panel.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
import json
from typing import Any, List
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon,QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QTableWidget, QTableWidgetItem, QTextEdit, QSplitter, QHeaderView, QPushButton,QMessageBox
)
from core.parser import SBOMNode
from ui.dialogs import FullTextDialog

class DetailPanel(QWidget):
    """選択されたノードのプロパティ(Key-Value)と生JSONをオンデマンド表示するパネル"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_json_text = ""
        self.current_node_name = ""
        self.current_node = None  # 👈 保持しているノードを後から参照できるように保持すると便利です
        self.original_properties_backup = None  # 🔄 リセット用に元のプロパティのコピーを保持
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        inner_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(inner_splitter)

        # --- 上段：プロパティテーブル ---
        kv_container = QWidget()
        kv_layout = QVBoxLayout(kv_container)
        kv_layout.setContentsMargins(0, 5, 0, 0)

        # ▼ アイコン付きタイトルヘッダーの作成
        kv_header_layout = QHBoxLayout()
        kv_header_layout.setContentsMargins(2, 0, 0, 0)
        kv_header_layout.setSpacing(6)

        icon_label = QLabel()
        icon_path = os.path.join("icons", "table-2.svg")
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(16, 16))
        kv_header_layout.addWidget(icon_label)

        title_label = QLabel("プロパティ (Key-Value)")
        title_label.setStyleSheet("font-weight: bold;")

        kv_header_layout.addWidget(title_label)
#        kv_header_layout.addStretch()
        # スペーサー
        kv_header_layout.addStretch()

        # ▼ アクションボタン群の配置
        self.btn_edit = QPushButton("✏️ 編集")
        self.btn_edit.clicked.connect(self.start_edit_mode)
        kv_header_layout.addWidget(self.btn_edit)

        self.btn_reset = QPushButton("🔄 リセット")
        self.btn_reset.clicked.connect(self.reset_edits)
        self.btn_reset.setVisible(False)  # 初期状態は非表示
        kv_header_layout.addWidget(self.btn_reset)

        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self.save_edits)
        self.btn_save.setVisible(False)  # 初期状態は非表示
        kv_header_layout.addWidget(self.btn_save)

        kv_layout.addLayout(kv_header_layout)
        
        self.table_widget = QTableWidget(0, 2)
        self.table_widget.setHorizontalHeaderLabels(["キー (Key)", "値 (Value)"])
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        kv_layout.addWidget(self.table_widget)
        inner_splitter.addWidget(kv_container)

        # --- 下段：生JSON ---
        json_container = QWidget()
        json_layout = QVBoxLayout(json_container)
        json_layout.setContentsMargins(0, 2, 0, 0)
        
        json_header_layout = QHBoxLayout()
        json_header_layout.setContentsMargins(2, 0, 0, 0)
        json_header_layout.setSpacing(6)

        # 1. アイコンの追加
        json_icon_label = QLabel()
        json_icon_path = os.path.join("icons", "file-braces.svg")
        if os.path.exists(json_icon_path):
            json_icon_label.setPixmap(QIcon(json_icon_path).pixmap(16, 16))
        json_header_layout.addWidget(json_icon_label)

        # 2. タイトルテキスト
        json_title_label = QLabel("該当箇所の生 JSON (オンデマンド生成)")
        json_title_label.setStyleSheet("font-weight: bold;")
        json_header_layout.addWidget(json_title_label)

        # スペーサーで左側と右側を分離
        json_header_layout.addStretch()
        
        # 3. 全文表示ボタン
        self.btn_full_text = QPushButton("🔍 全文を別窓で表示")
        self.btn_full_text.setEnabled(False)
        self.btn_full_text.clicked.connect(self.show_full_text_dialog)
        json_header_layout.addWidget(self.btn_full_text)
        
        json_layout.addLayout(json_header_layout)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        font = self.text_edit.font()
        font.setFamily("Courier New")
        self.text_edit.setFont(font)
        json_layout.addWidget(self.text_edit)
        inner_splitter.addWidget(json_container)

        inner_splitter.setSizes([360, 240])

    def _flatten_properties(self, data: Any, depth: int = 0) -> List[tuple]:
        rows = []
        indent = "    " * depth

        if isinstance(data, dict):
            # ▼ ルート階層（depth == 0）の場合、表示順の優先リストを適用する
            if depth == 0:
                priority_keys = [
                     "SPDXID", "name", "versionInfo", "supplier", 
                    "originator", "downloadLocation", "filesAnalyzed", "licenseConcluded", "licenseDeclared"
                ]
                # 優先リストにあるキーを順番通りに、リストにない残りのキーは後ろにアルファベット順で配置
                keys = sorted(
                    data.keys(), 
                    key=lambda k: (priority_keys.index(k) if k in priority_keys else 999, k)
                )
            else:
                keys = data.keys()

            for key in keys:
                val = data[key]
                display_key = f"{indent}{key}"
                if isinstance(val, (dict, list)):
                    rows.append((display_key, ""))
                    rows.extend(self._flatten_properties(val, depth=depth + 1))
                else:
                    rows.append((display_key, str(val)))
                    
        elif isinstance(data, list):
            for idx, val in enumerate(data):
                display_key = f"{indent}[{idx}]"
                if isinstance(val, (dict, list)):
                    rows.append((display_key, ""))
                    rows.extend(self._flatten_properties(val, depth=depth + 1))
                else:
                    rows.append((display_key, str(val)))
        
        return rows

    def update_display(self, node: SBOMNode):
        self.current_node = node
        # 編集キャンセルやリセット用にディープコピーを保持しておく
        import copy
        self.original_properties_backup = copy.deepcopy(node.properties)
        
        self._load_table_data(node.properties)

    def _load_table_data(self, properties: dict):
        self.table_widget.setRowCount(0)
        self.current_node_name = self.current_node.name if self.current_node else ""
        
        if properties:
            flattened_rows = self._flatten_properties(properties)
            self.table_widget.setRowCount(len(flattened_rows))
            for row_idx, (key, value) in enumerate(flattened_rows):
                key_item = QTableWidgetItem(key)
                val_item = QTableWidgetItem(value)
                # 🔒 キー列（列0）は、どの状態でも絶対に編集不可にする
                key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                
                # キー部分の色を少し変えるなどして「ここは編集できない」感を出すと親切です
                key_item.setForeground(Qt.GlobalColor.darkGray)

                # ▼【新規】インデント等を除いた純粋なキー名を取得
                clean_key = key.strip()

                # 🔒【新規】「SPDXID」の行、または値が空（コンテナ行など）の場合は、Value列も編集不可にする
                if clean_key == "SPDXID" or value == "":
                    val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    # SPDXIDであることが一目でわかるように少し文字色を薄くする（お好みで）
#                    if clean_key == "SPDXID":
#                        val_item.setForeground(Qt.GlobalColor.darkGray)
                self.table_widget.setItem(row_idx, 0, key_item)
                self.table_widget.setItem(row_idx, 1, val_item)
        
            self.current_json_text = json.dumps(properties, indent=2, ensure_ascii=False)
            self.text_edit.setPlainText(self.current_json_text)
            self.btn_full_text.setEnabled(True)
        else:
            self.text_edit.setPlainText("{}")
            self.current_json_text = "{}"
            self.btn_full_text.setEnabled(False)

    def start_edit_mode(self):
        """編集モードを開始する"""
        if not self.current_node:
            return
        
        # ボタンの表示切り替え
        self.btn_edit.setVisible(False)
        self.btn_reset.setVisible(True)
        self.btn_save.setVisible(True)

        # テーブルを編集可能にする（値列のみ、あるいはダブルクリック編集）
        self.table_widget.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | 
            QTableWidget.EditTrigger.EditKeyPressed
        )
        # ▼【新規】編集モード中であることをわかりやすくするため、Value列（列1）の背景色を変更する
        edit_bg_color = QColor("#fffdf0")  # 薄い黄色
        for row in range(self.table_widget.rowCount()):
            val_item = self.table_widget.item(row, 1)
            if val_item:
                # フラグが編集可能（ItemIsEditable）なセルだけ背景色を変える
                if val_item.flags() & Qt.ItemFlag.ItemIsEditable:
                    val_item.setBackground(edit_bg_color)

    def reset_edits(self):
        """変更を破棄して元の状態に戻す"""
        if self.original_properties_backup:
            self._load_table_data(self.original_properties_backup)
        self.end_edit_mode()

    def save_edits(self):
        """テーブルの編集内容をノードの properties に反映し、生JSONを更新する"""
        if not self.current_node:
            return

        try:
            # 1. テーブルの全行を走査して、現在の表示・編集状態から一時的なフラットマップを作成
            # キーのインデントを取り除く
            updated_data = {}
            
            # 簡易的に現在のテーブル行を上から順に読み込む仕組み、
            # または元のプロパティ構造をベースに値を上書きしていくアプローチが安全です。
            # ここではシンプルに、現在保持している properties のコピーをベースに、
            # 編集された値をマッピングし直すか、あるいは直接書き戻します。

            # 今回のシンプルな実装アプローチ：
            # テーブルの行数分ループし、各行のキーパスを特定して current_node.properties を更新する
            for row in range(self.table_widget.rowCount()):
                key_item = self.table_widget.item(row, 0)
                val_item = self.table_widget.item(row, 1)
                
                if not key_item or not val_item:
                    continue
                
                # インデント（4スペース単位）を取り除いた純粋なキー名を取得
                display_key = key_item.text()
                actual_key = display_key.strip()
                
                # 値を取得（数値や真偽値っぽいものは適宜型変換するとより綺麗ですが、まず文字列として代入）
                new_val = val_item.text()
                
                # ▼ トップレベルのプロパティの場合の更新処理
                # （※ ネストが浅い一般的なSBOMプロパティであればこれで直接更新できます）
                if actual_key in self.current_node.properties:
                    # 元の型（boolやintなど）を維持したい場合の簡易型推測
                    old_val = self.current_node.properties[actual_key]
                    if isinstance(old_val, bool):
                        new_val = (new_val.lower() == "true")
                    elif isinstance(old_val, int):
                        try:
                            new_val = int(new_val)
                        except ValueError:
                            pass
                    elif isinstance(old_val, float):
                        try:
                            new_val = float(new_val)
                        except ValueError:
                            pass
                    
                    self.current_node.properties[actual_key] = new_val

            # 2. 下段の生 JSON 表示（self.text_edit）を最新の node.properties から再生成して更新する
            self.current_json_text = json.dumps(self.current_node.properties, indent=2, ensure_ascii=False)
            self.text_edit.setPlainText(self.current_json_text)
            
            # 3. バックアップ（リセット用）も最新の状態に更新
            import copy
            self.original_properties_backup = copy.deepcopy(self.current_node.properties)

            QMessageBox.information(self, "完了", "プロパティの変更を反映しました。\n（※別のノードを選択しても値が維持されます）")
            self.end_edit_mode()

        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存中にエラーが発生しました:\n{str(e)}")


    def end_edit_mode(self):
        """編集モードを終了して通常表示に戻す"""
        self.btn_edit.setVisible(True)
        self.btn_reset.setVisible(False)
        self.btn_save.setVisible(False)

        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # ▼【新規】Value列（列1）の背景色をデフォルト（透明/白）に戻す
        for row in range(self.table_widget.rowCount()):
            val_item = self.table_widget.item(row, 1)
            if val_item:
                val_item.setBackground(QColor(0, 0, 0, 0))  # 背景色をリセット（透明）

    def clear_display(self):
        self.table_widget.setRowCount(0)
        self.text_edit.clear()
        self.current_json_text = ""
        self.btn_full_text.setEnabled(False)

    def show_full_text_dialog(self):
        if not self.current_json_text:
            return
        
        dialog = FullTextDialog(
            title=f"詳細データ全文: {self.current_node_name}",
            text=self.current_json_text,
            parent=self
        )
        dialog.exec()