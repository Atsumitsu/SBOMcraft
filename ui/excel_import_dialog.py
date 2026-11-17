# ui/excel_import_dialog.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""Excel 取り込み前の差分プレビュー。ユーザーが確認・取捨選択してから SBOM に反映する。"""

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.excel_io import CellChange, ImportPlan, describe_value

_MAX_CELL_PREVIEW = 120
_COLOR_ERROR = QColor("#FFCCCC")      # 検証結果のハイライトと同じ色
_COLOR_WARNING = QColor("#FFF3CD")
_COLOR_ADD = QColor("#2E7D32")
_COLOR_DELETE = QColor("#C62828")

_COL_CHECK, _COL_ID, _COL_PKG, _COL_FIELD, _COL_OLD, _COL_NEW, _COL_CELL = range(7)


def _short(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\n", " ⏎ ")
    return text if len(text) <= _MAX_CELL_PREVIEW else text[:_MAX_CELL_PREVIEW] + "…"


class ExcelImportPreviewDialog(QDialog):
    def __init__(self, plan: ImportPlan, file_name: str, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Excel 取り込み - 変更内容の確認")
        self.resize(1100, 620)

        layout = QVBoxLayout(self)

        summary = (
            f"<b>{file_name}</b><br>"
            f"対象 {plan.rows_matched} 行 / 変更あり {plan.packages_changed} パッケージ・{len(plan.changes)} 項目"
            f" / <span style='color:#C62828'>エラー {plan.error_count}</span>"
            f" / <span style='color:#B26A00'>警告 {plan.warning_count}</span>"
        )
        lbl = QLabel(summary)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(lbl)
        if plan.error_count:
            note = QLabel("※ エラーのあるセルは反映されません（「チェック結果」タブで確認してください）。")
            note.setStyleSheet("color:#C62828;")
            layout.addWidget(note)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_changes_tab(), f"変更点 ({len(plan.changes)})")
        self.tabs.addTab(self._build_issues_tab(), f"チェック結果 (エラー {plan.error_count} / 警告 {plan.warning_count})")
        layout.addWidget(self.tabs, 1)
        if not plan.changes and plan.issues:
            self.tabs.setCurrentIndex(1)

        # --- ボタン ---
        row = QHBoxLayout()
        self.btn_all = QPushButton("すべて選択")
        self.btn_none = QPushButton("すべて解除")
        self.btn_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_none.clicked.connect(lambda: self._set_all_checked(False))
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_none)
        row.addStretch(1)
        self.btn_apply = QPushButton()
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self.accept)
        btn_cancel = QPushButton("キャンセル")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_apply)
        row.addWidget(btn_cancel)
        layout.addLayout(row)

        has_changes = bool(plan.changes)
        self.btn_all.setEnabled(has_changes)
        self.btn_none.setEnabled(has_changes)
        self._update_apply_button()

    # ------------------------------------------------------------------
    def _build_changes_tab(self) -> QWidget:
        table = QTableWidget(len(self.plan.changes), 7)
        table.setHorizontalHeaderLabels(["反映", "SPDXID", "パッケージ", "項目", "変更前", "変更後", "セル"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)

        table.blockSignals(True)
        for r, ch in enumerate(self.plan.changes):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            chk.setData(Qt.ItemDataRole.UserRole, r)          # 並べ替えても元の変更を引けるように
            table.setItem(r, _COL_CHECK, chk)

            new_text = "(削除)" if ch.op == "delete" else describe_value(ch.new)
            cells = {
                _COL_ID: ch.spdx_id, _COL_PKG: ch.package_name, _COL_FIELD: ch.field,
                _COL_OLD: describe_value(ch.old), _COL_NEW: new_text, _COL_CELL: ch.cell,
            }
            full = {_COL_OLD: describe_value(ch.old), _COL_NEW: new_text}
            for col, text in cells.items():
                it = QTableWidgetItem(_short(text))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                it.setToolTip(full.get(col, text))
                if col == _COL_NEW and ch.op == "delete":
                    it.setForeground(_COLOR_DELETE)
                elif col == _COL_NEW and ch.op == "add":
                    it.setForeground(_COLOR_ADD)
                table.setItem(r, col, it)
        table.blockSignals(False)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        for col, w in {_COL_CHECK: 50, _COL_ID: 210, _COL_PKG: 170, _COL_FIELD: 130,
                       _COL_OLD: 220, _COL_NEW: 220, _COL_CELL: 60}.items():
            table.setColumnWidth(col, w)
        table.setSortingEnabled(True)
        table.itemChanged.connect(lambda _it: self._update_apply_button())
        self.changes_table = table
        return table

    def _build_issues_tab(self) -> QWidget:
        issues = self.plan.issues
        table = QTableWidget(len(issues), 3)
        table.setHorizontalHeaderLabels(["レベル", "場所", "メッセージ"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        label = {"error": "エラー", "warning": "警告", "info": "情報"}
        for r, iss in enumerate(issues):
            for col, text in enumerate([label.get(iss.level, iss.level), iss.where, iss.message]):
                it = QTableWidgetItem(text)
                it.setToolTip(iss.message)
                if iss.level == "error":
                    it.setBackground(_COLOR_ERROR)
                elif iss.level == "warning":
                    it.setBackground(_COLOR_WARNING)
                table.setItem(r, col, it)
        table.setColumnWidth(0, 70)
        table.setColumnWidth(1, 130)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.resizeRowsToContents()
        return table

    # ------------------------------------------------------------------
    def _iter_check_items(self):
        t = self.changes_table
        for r in range(t.rowCount()):
            yield t.item(r, _COL_CHECK)

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.changes_table.blockSignals(True)
        for it in self._iter_check_items():
            it.setCheckState(state)
        self.changes_table.blockSignals(False)
        self._update_apply_button()

    def _update_apply_button(self):
        n = len(self.selected_changes())
        self.btn_apply.setText(f"選択した {n} 件を反映")
        self.btn_apply.setEnabled(n > 0)

    def selected_changes(self) -> List[CellChange]:
        if not self.plan.changes:
            return []
        picked = []
        for it in self._iter_check_items():
            if it.checkState() == Qt.CheckState.Checked:
                picked.append(it.data(Qt.ItemDataRole.UserRole))
        picked.sort()                              # Excel の行順で適用
        return [self.plan.changes[i] for i in picked]
