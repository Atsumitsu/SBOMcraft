# ui/detail_panel.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj


import json
from typing import Any, List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QTableWidget, QTableWidgetItem, QTextEdit, QSplitter, QHeaderView, QPushButton
)
from core.parser import SBOMNode
from ui.dialogs import FullTextDialog

class DetailPanel(QWidget):
    """選択されたノードのプロパティ(Key-Value)と生JSONをオンデマンド表示するパネル"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_json_text = ""
        self.current_node_name = ""
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
        kv_layout.addWidget(QLabel("■ プロパティ (Key-Value)"))
        
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
        json_header_layout.addWidget(QLabel("■ 該当箇所の生 JSON (オンデマンド生成)"))
        
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
            for key, val in data.items():
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
        self.table_widget.setRowCount(0)
        properties = node.properties
        self.current_node_name = node.name
        
        if properties:
            flattened_rows = self._flatten_properties(properties)
            self.table_widget.setRowCount(len(flattened_rows))
            for row_idx, (key, value) in enumerate(flattened_rows):
                key_item = QTableWidgetItem(key)
                val_item = QTableWidgetItem(value)
                if value == "":
                    key_item.setForeground(Qt.GlobalColor.darkGray)
                self.table_widget.setItem(row_idx, 0, key_item)
                self.table_widget.setItem(row_idx, 1, val_item)
        
            self.current_json_text = json.dumps(properties, indent=2, ensure_ascii=False)
            self.text_edit.setPlainText(self.current_json_text)
            self.btn_full_text.setEnabled(True)
        else:
            self.text_edit.setPlainText("{}")
            self.current_json_text = "{}"
            self.btn_full_text.setEnabled(False)

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
        