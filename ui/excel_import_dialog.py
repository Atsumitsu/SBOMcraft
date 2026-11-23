# ui/excel_import_dialog.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""Excel 取り込み前の差分プレビュー。ユーザーが確認・取捨選択してから SBOM に反映する。"""

import html
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.excel_io import CellChange, ImportPlan, describe_entries, describe_value
from core.i18n import t
from ui import theme

_MAX_CELL_PREVIEW = 120

_COL_CHECK, _COL_ID, _COL_PKG, _COL_FIELD, _COL_OLD, _COL_NEW, _COL_CELL = range(7)


def _short(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\n", " ⏎ ")
    return text if len(text) <= _MAX_CELL_PREVIEW else text[:_MAX_CELL_PREVIEW] + "…"


class ExcelImportPreviewDialog(QDialog):
    def __init__(self, plan: ImportPlan, file_name: str, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle(t("excel.dlg.title"))
        self.resize(1100, 620)

        # ※ 色の変数名を t にすると翻訳関数 t() を隠してしまうため tok とする
        tok = theme.tokens()

        layout = QVBoxLayout(self)

        n_list = sum(1 for c in plan.changes if c.kind == "list")
        list_info = "".join(t("excel.dlg.summary_list", sheet=sheet, n=n) for sheet, n in plan.list_stats.items())
        summary = (
            f"<b>{html.escape(file_name)}</b><br>"
            f"{html.escape(t('excel.dlg.summary_main', rows=plan.rows_matched))}{html.escape(list_info)}"
            f" / {html.escape(t('excel.dlg.summary_changes', packages=plan.packages_changed, items=len(plan.changes), lists=n_list))}"
            f" / <span style='color:{tok.danger_fg}'>{html.escape(t('excel.dlg.errors', n=plan.error_count))}</span>"
            f" / <span style='color:{tok.warning_fg}'>{html.escape(t('excel.dlg.warnings', n=plan.warning_count))}</span>"
        )
        lbl = QLabel(summary)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(lbl)
        if plan.error_count:
            note = QLabel(t("excel.dlg.errors_note"))
            note.setStyleSheet(f"color:{tok.danger_fg};")
            layout.addWidget(note)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_changes_tab(), t("excel.dlg.tab_changes", n=len(plan.changes)))
        self.tabs.addTab(self._build_issues_tab(),
                         t("excel.dlg.tab_issues", errors=plan.error_count, warnings=plan.warning_count))
        layout.addWidget(self.tabs, 1)
        if not plan.changes and plan.issues:
            self.tabs.setCurrentIndex(1)
        if n_list:
            hint = QLabel(t("excel.dlg.list_hint"))
            hint.setProperty("role", "muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        # --- ボタン ---
        row = QHBoxLayout()
        self.btn_all = QPushButton(t("excel.dlg.select_all"))
        self.btn_none = QPushButton(t("excel.dlg.select_none"))
        self.btn_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_none.clicked.connect(lambda: self._set_all_checked(False))
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_none)
        row.addStretch(1)
        self.btn_apply = QPushButton()
        self.btn_apply.setProperty("variant", "primary")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self.accept)
        btn_cancel = QPushButton(t("excel.dlg.cancel"))
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
        table.setHorizontalHeaderLabels([
            t("excel.dlg.col_apply"), "SPDXID", t("excel.dlg.col_package"), t("excel.dlg.col_field"),
            t("excel.dlg.col_old"), t("excel.dlg.col_new"), t("excel.dlg.col_cell"),
        ])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)

        tok = theme.tokens()
        color_add, color_del = QColor(tok.success_fg), QColor(tok.danger_fg)

        table.blockSignals(True)
        for r, ch in enumerate(self.plan.changes):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            chk.setData(Qt.ItemDataRole.UserRole, r)          # 並べ替えても元の変更を引けるように
            table.setItem(r, _COL_CHECK, chk)

            if ch.kind == "list":
                # 一覧は『削除される要素 / 追加される要素』を並べて見せる（全体は吹き出しで確認）
                field_text = f"{ch.field}（＋{len(ch.added)} / －{len(ch.removed)}）"
                old_text = describe_entries(ch.field, ch.removed, "－ ") or t("excel.dlg.no_removed")
                if ch.op == "delete":
                    new_text = t("excel.dlg.list_deleted")
                else:
                    new_text = describe_entries(ch.field, ch.added, "＋ ") or t("excel.dlg.no_added")
                old_tip = t("excel.dlg.tip_old_list") + describe_value(ch.old, ch.field)
                new_tip = t("excel.dlg.tip_new_list") + (describe_entries(ch.field, ch.new) or t("excel.value.empty_list"))
                old_color = color_del if ch.removed else None
                new_color = color_del if ch.op == "delete" else (color_add if ch.added else None)
            else:
                field_text = ch.field
                old_text = describe_value(ch.old)
                new_text = t("excel.dlg.deleted") if ch.op == "delete" else describe_value(ch.new)
                old_tip, new_tip = old_text, new_text
                old_color = None
                new_color = color_del if ch.op == "delete" else (color_add if ch.op == "add" else None)

            cells = {
                _COL_ID: (ch.spdx_id, ch.spdx_id, None),
                _COL_PKG: (ch.package_name, ch.package_name, None),
                _COL_FIELD: (field_text, field_text, None),
                _COL_OLD: (old_text, old_tip, old_color),
                _COL_NEW: (new_text, new_tip, new_color),
                _COL_CELL: (ch.cell, ch.cell, None),
            }
            for col, (text, tip, color) in cells.items():
                it = QTableWidgetItem(_short(text))
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                it.setToolTip(tip)
                if color is not None:
                    it.setForeground(color)
                table.setItem(r, col, it)
        table.blockSignals(False)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        for col, w in {_COL_CHECK: 60, _COL_ID: 210, _COL_PKG: 170, _COL_FIELD: 170,
                       _COL_OLD: 220, _COL_NEW: 220, _COL_CELL: 90}.items():
            table.setColumnWidth(col, w)
        table.setSortingEnabled(True)
        table.itemChanged.connect(lambda _it: self._update_apply_button())
        self.changes_table = table
        return table

    def _build_issues_tab(self) -> QWidget:
        issues = self.plan.issues
        table = QTableWidget(len(issues), 3)
        table.setHorizontalHeaderLabels(
            [t("excel.dlg.col_level"), t("excel.dlg.col_where"), t("excel.dlg.col_message")])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(True)
        label = {"error": t("excel.dlg.level_error"), "warning": t("excel.dlg.level_warning"),
                 "info": t("excel.dlg.level_info")}
        _, err_bg, err_fg = theme.tone_colors("danger")
        _, warn_bg, warn_fg = theme.tone_colors("warning")
        for r, iss in enumerate(issues):
            for col, text in enumerate([label.get(iss.level, iss.level), iss.where, iss.message]):
                it = QTableWidgetItem(text)
                it.setToolTip(iss.message)
                if iss.level == "error":
                    it.setBackground(QColor(err_bg))
                    it.setForeground(QColor(err_fg))
                elif iss.level == "warning":
                    it.setBackground(QColor(warn_bg))
                    it.setForeground(QColor(warn_fg))
                table.setItem(r, col, it)
        table.setColumnWidth(0, 80)
        table.setColumnWidth(1, 130)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.resizeRowsToContents()
        return table

    # ------------------------------------------------------------------
    def _iter_check_items(self):
        tbl = self.changes_table
        for r in range(tbl.rowCount()):
            yield tbl.item(r, _COL_CHECK)

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.changes_table.blockSignals(True)
        for it in self._iter_check_items():
            it.setCheckState(state)
        self.changes_table.blockSignals(False)
        self._update_apply_button()

    def _update_apply_button(self):
        n = len(self.selected_changes())
        self.btn_apply.setText(t("excel.dlg.apply", n=n))
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
