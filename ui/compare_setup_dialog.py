# ui/compare_setup_dialog.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
from typing import Iterable, List, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from core.comparer import ALL_GROUPS, group_label, match_key_hint, match_key_label, MatchKey
from core.i18n import t

class CompareSetupDialog(QDialog):
    """比較の条件（対象ファイル・突合キー・比較する項目）を選ぶダイアログ。

    ask_target=False のときは対象ファイルの入力欄を出さず、条件だけを変更する（再比較用）。
    """

    def __init__(self, parent=None, *, title: str = "", base_text: str = "",
                 ask_target: bool = True, target_text: str = "", start_dir: str = "",
                 mode: MatchKey = MatchKey.AUTO, groups: Optional[Iterable[str]] = None):
        super().__init__(parent)
        self.setWindowTitle(title or t(...))
        self.setMinimumWidth(560)
        self._ask_target = ask_target
        self._start_dir = start_dir
        self._group_boxes = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        base_label = QLabel(base_text)
        base_label.setWordWrap(True)
        form.addRow(t("compare.setup.base"), base_label)

        self.path_edit = QLineEdit()
        if ask_target:
            row = QHBoxLayout()
            self.path_edit.setPlaceholderText(t("compare.setup.target_placeholder"))
            row.addWidget(self.path_edit, 1)
            browse = QPushButton(t("compare.setup.browse"))
            browse.clicked.connect(self._browse)
            row.addWidget(browse)
            form.addRow(t("compare.setup.target"), row)
        elif target_text:
            target_label = QLabel(target_text)
            target_label.setWordWrap(True)
            form.addRow(t("compare.setup.target"), target_label)

        self.mode_combo = QComboBox()
        for m in MatchKey:
            self.mode_combo.addItem(match_key_label(m), m.value)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(MatchKey(mode).value)))
        self.mode_combo.currentIndexChanged.connect(self._update_hint)
        form.addRow(t("compare.setup.match_key"), self.mode_combo)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setProperty("role", "muted")
        layout.addWidget(self.hint_label)

        box = QGroupBox(t("compare.setup.fields"))
        box_layout = QVBoxLayout(box)
        ver = QCheckBox(t("compare.setup.version_always"))
        ver.setChecked(True)
        ver.setEnabled(False)
        box_layout.addWidget(ver)
        selected = set(groups) if groups is not None else set(ALL_GROUPS)
        for g in ALL_GROUPS:
            cb = QCheckBox(group_label(g))
            cb.setChecked(g in selected)
            self._group_boxes[g] = cb
            box_layout.addWidget(cb)
        layout.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("compare.setup.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("compare.setup.cancel"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_hint()

    # -- 内部 ---------------------------------------------------------------

    def _update_hint(self):
        self.hint_label.setText("ℹ " + match_key_hint(self.match_mode()))

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("compare.setup.browse_title"), self._start_dir, "JSON Files (*.json);;All Files (*)")
        if path:
            self.path_edit.setText(path)

    def _on_accept(self):
        if self._ask_target:
            path = self.path_edit.text().strip().strip('"')
            if not path or not os.path.isfile(path):
                QMessageBox.warning(self, t("compare.setup.warn_title"), t(".warn_select"))
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
