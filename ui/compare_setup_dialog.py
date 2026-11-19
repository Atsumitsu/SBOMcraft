# ui/compare_setup_dialog.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
from typing import Iterable, List, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from core.comparer import ALL_GROUPS, FIELD_GROUPS, MATCH_KEY_HINTS, MATCH_KEY_LABELS, MatchKey


class CompareSetupDialog(QDialog):
    """比較の条件（対象ファイル・突合キー・比較する項目）を選ぶダイアログ。

    ask_target=False のときは対象ファイルの入力欄を出さず、条件だけを変更する（再比較用）。
    """

    def __init__(self, parent=None, *, title: str = "SBOM の比較", base_text: str = "",
                 ask_target: bool = True, target_text: str = "", start_dir: str = "",
                 mode: MatchKey = MatchKey.AUTO, groups: Optional[Iterable[str]] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self._ask_target = ask_target
        self._start_dir = start_dir
        self._group_boxes = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        base_label = QLabel(base_text)
        base_label.setWordWrap(True)
        form.addRow("基準 (A・旧):", base_label)

        self.path_edit = QLineEdit()
        if ask_target:
            row = QHBoxLayout()
            self.path_edit.setPlaceholderText("比較する SBOM (SPDX JSON) を選択してください")
            row.addWidget(self.path_edit, 1)
            browse = QPushButton("参照...")
            browse.clicked.connect(self._browse)
            row.addWidget(browse)
            form.addRow("対象 (B・新):", row)
        elif target_text:
            target_label = QLabel(target_text)
            target_label.setWordWrap(True)
            form.addRow("対象 (B・新):", target_label)

        self.mode_combo = QComboBox()
        for m in MatchKey:
            self.mode_combo.addItem(MATCH_KEY_LABELS[m], m.value)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(MatchKey(mode).value)))
        self.mode_combo.currentIndexChanged.connect(self._update_hint)
        form.addRow("突合キー:", self.mode_combo)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #555555;")
        layout.addWidget(self.hint_label)

        box = QGroupBox("比較する項目")
        box_layout = QVBoxLayout(box)
        ver = QCheckBox("バージョン（常に比較します）")
        ver.setChecked(True)
        ver.setEnabled(False)
        box_layout.addWidget(ver)
        selected = set(groups) if groups is not None else set(ALL_GROUPS)
        for g in ALL_GROUPS:
            cb = QCheckBox(FIELD_GROUPS[g][0])
            cb.setChecked(g in selected)
            self._group_boxes[g] = cb
            box_layout.addWidget(cb)
        layout.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("比較する")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_hint()

    # -- 内部 ---------------------------------------------------------------

    def _update_hint(self):
        self.hint_label.setText("ℹ " + MATCH_KEY_HINTS[self.match_mode()])

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "比較する SBOM を選択", self._start_dir, "JSON Files (*.json);;All Files (*)")
        if path:
            self.path_edit.setText(path)

    def _on_accept(self):
        if self._ask_target:
            path = self.path_edit.text().strip().strip('"')
            if not path or not os.path.isfile(path):
                QMessageBox.warning(self, "比較", "比較する SBOM ファイルを選択してください。")
                return
        self.accept()

    # -- 結果 ---------------------------------------------------------------

    def target_path(self) -> str:
        return self.path_edit.text().strip().strip('"')

    def match_mode(self) -> MatchKey:
        return MatchKey(self.mode_combo.currentData())   # QVariant 経由で str になるため Enum に戻す

    def selected_groups(self) -> List[str]:
        return [g for g in ALL_GROUPS if self._group_boxes[g].isChecked()]

    def values(self) -> Tuple[str, MatchKey, List[str]]:
        return self.target_path(), self.match_mode(), self.selected_groups()
