# ui/detail_panel.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
import copy
import json
from typing import Any, List
from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QIcon,QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QTableWidget, QTableWidgetItem, QTextEdit, QSplitter, QHeaderView, QPushButton,QMessageBox
)
from core.parser import SBOMNode
from core.serializer import apply_flat_rows, json_default, PACKAGE_PRIORITY_KEYS
from ui.dialogs import FullTextDialog

class DetailPanel(QWidget):
    # ▼【新規】ノードのデータが更新されたことを親に知らせるシグナル
    node_updated = Signal(object)
    """選択されたノードのプロパティ(Key-Value)と生JSONをオンデマンド表示するパネル"""

    # 編集を許可するノード種別。対象を増やす場合はここに node_type を追加する
    # （例: {"package", "document_info"}）
    EDITABLE_NODE_TYPES = {"package"}
    NOT_EDITABLE_TOOLTIP = "編集できるのは Packages 配下のパッケージのみです"
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_json_text = ""
        self.current_node_name = ""
        self.current_node = None  # 👈 保持しているノードを後から参照できるように保持すると便利です
        self.original_properties_backup = None  # 🔄 リセット用に元のプロパティのコピーを保持
        self.is_editing = False  # 👈 【追加】編集中フラグ
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
        self.btn_edit.setEnabled(False)  # ノード選択後、編集可能な種別のときだけ有効化
        self.btn_edit.setToolTip(self.NOT_EDITABLE_TOOLTIP)
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
                priority_keys = PACKAGE_PRIORITY_KEYS
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

    def _is_editable(self, node) -> bool:
        """このノードが編集対象か（Packages 配下のパッケージのみ）"""
        return node is not None and node.node_type in self.EDITABLE_NODE_TYPES

    def _update_edit_button_state(self):
        """現在のノードに応じて「編集」ボタンの有効/無効とツールチップを切り替える"""
        editable = self._is_editable(self.current_node)
        self.btn_edit.setEnabled(editable)
        self.btn_edit.setToolTip("" if editable else self.NOT_EDITABLE_TOOLTIP)

    def update_display(self, node: SBOMNode):
        self.current_node = node
        self._update_edit_button_state()
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

                # 🔒【新規】「SPDXID」の行などの場合は、Value列も編集不可にする
                if clean_key.lower() in {"spdxid", "checksums", "externalrefs"}:
                    val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                # elif value == "" and clean_key in ("[","]"):
                #    val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                self.table_widget.setItem(row_idx, 0, key_item)
                self.table_widget.setItem(row_idx, 1, val_item)
        
            self.current_json_text = json.dumps(properties, indent=2, ensure_ascii=False, default=json_default)
            self.text_edit.setPlainText(self.current_json_text)
            self.btn_full_text.setEnabled(True)
        else:
            self.text_edit.setPlainText("{}")
            self.current_json_text = "{}"
            self.btn_full_text.setEnabled(False)

    def clear_display(self):
        if self.is_editing:
            self.end_edit_mode()
        self.current_node = None            # 選択解除後に古いノードを編集できないようにする
        self.original_properties_backup = None
        self._update_edit_button_state()
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
        
    def start_edit_mode(self):
        """編集モードを開始する"""
        if not self._is_editable(self.current_node):
            return  # ボタン以外の経路から呼ばれても、編集対象外ノードは編集させない

        self.is_editing = True

        # ボタンの表示切り替え
        self.btn_edit.setVisible(False)
        self.btn_reset.setVisible(True)
        self.btn_save.setVisible(True)

        # テーブルを編集可能にする
        self.table_widget.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | 
            QTableWidget.EditTrigger.EditKeyPressed
        )
        
        # 編集モード中であることをわかりやすくするため、Value列（列1）の背景色を変更する
        edit_bg_color = QColor("#fffdf0")  # 薄い黄色
        for row in range(self.table_widget.rowCount()):
            val_item = self.table_widget.item(row, 1)
            if val_item:
                if val_item.flags() & Qt.ItemFlag.ItemIsEditable:
                    val_item.setBackground(edit_bg_color)

    def reset_edits(self):
        """変更を破棄して元の状態に戻す"""
        if self.original_properties_backup:
            self._load_table_data(self.original_properties_backup)
        self.end_edit_mode()

    def save_edits(self):
        """テーブルの編集内容をノードの properties に反映し、生JSON・ツリー表示を更新する"""
        node = self.current_node
        if not self._is_editable(node):
            return

        # 編集中のセルエディタを確定させる（フォーカスをテーブルへ移すとデリゲートが commit する）
        self.table_widget.setFocus()

        rows = []
        for row in range(self.table_widget.rowCount()):
            key_item = self.table_widget.item(row, 0)
            val_item = self.table_widget.item(row, 1)
            if key_item and val_item:
                rows.append((key_item.text(), val_item.text()))

        # 作業コピーへ適用し、全行が成功したときだけ本体へコミットする
        # （途中で入力エラーになっても node.properties を半端な状態にしない）
        work = copy.deepcopy(node.properties)
        try:
            changed = apply_flat_rows(work, rows)
        except ValueError as e:
            QMessageBox.warning(self, "入力エラー", f"{e}\n\n入力を修正して、もう一度保存してください。")
            return  # 編集モードは継続

        if changed:
            node.properties.clear()          # dict の同一性を保ったまま差し替え
            node.properties.update(work)
            self._refresh_node_label(node)

        self.current_json_text = json.dumps(node.properties, indent=2, ensure_ascii=False, default=json_default)
        self.text_edit.setPlainText(self.current_json_text)
        self.original_properties_backup = copy.deepcopy(node.properties)
        self._load_table_data(node.properties)

        if changed:
            self.node_updated.emit(node)     # ツリー表示の同期・変更フラグ更新は親側で行う
            QMessageBox.information(self, "完了", "プロパティの変更を反映しました。")
        else:
            QMessageBox.information(self, "完了", "変更はありませんでした。")
        self.end_edit_mode()

    @staticmethod
    def _refresh_node_label(node: SBOMNode):
        """プロパティ変更に合わせてツリー上のノード名を作り直す（core/parser.py の命名規則と同じ）"""
        p = node.properties
        if node.node_type == "package":
            node.name = f"📦 {p.get('name', 'Unknown Package')} ({p.get('versionInfo', 'N/A')})"
        elif node.node_type == "document_info":
            node.name = f"ℹ️ {p.get('name', 'DocumentRoot')}"
        elif node.node_type == "file":
            node.name = f"📄 {p.get('fileName', 'Unknown File')}"
        elif node.node_type == "relationship":
            node.name = (f"🔗 {p.get('spdxElementId', 'N/A')} ➔ "
                         f"[{p.get('relationshipType', 'UNKNOWN')}] ➔ {p.get('relatedSpdxElement', 'N/A')}")
        elif node.node_type == "licenses":
            node.name = f"📜 {p.get('name', '(none)')}"

    def end_edit_mode(self):
        """編集モードを終了して通常表示に戻す"""
        self.btn_edit.setVisible(True)
        self.btn_reset.setVisible(False)
        self.btn_save.setVisible(False)
        self.is_editing = False

        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row in range(self.table_widget.rowCount()):
            val_item = self.table_widget.item(row, 1)
            if val_item:
                val_item.setBackground(QColor(0, 0, 0, 0))  # 背景色をリセット（透明）
