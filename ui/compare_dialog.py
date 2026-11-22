# ui/compare_dialog.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
from typing import Callable, List, Optional, Set

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QRectF, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTabBar, QTableView, QTextBrowser, QVBoxLayout,
)

from core.compare_report import detail_html, docs_html
from core.comparer import (
    CompareResult, DiffStatus, FLAG_LABELS, PackageDiff, STATUS_LABELS, VERSION_CHANGE_LABELS,
    compare, export_csv,
)
from ui import theme
from ui.compare_setup_dialog import CompareSetupDialog
from ui.widgets import StatCard

_STATUS_ORDER = {DiffStatus.REMOVED: 0, DiffStatus.ADDED: 1, DiffStatus.VERSION_CHANGED: 2,
                 DiffStatus.MODIFIED: 3, DiffStatus.UNCHANGED: 4}
_ARROWS = {"upgrade": "↑", "downgrade": "↓"}

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
DIFF_ROLE = Qt.ItemDataRole.UserRole + 2


class DiffTableModel(QAbstractTableModel):
    HEADERS = ["状態", "パッケージ名", "旧バージョン (A)", "新バージョン (B)", "変更項目", "要注意"]

    def __init__(self, diffs: List[PackageDiff], parent=None):
        super().__init__(parent)
        self.diffs = diffs

    def set_diffs(self, diffs: List[PackageDiff]):
        self.beginResetModel()
        self.diffs = diffs
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.diffs)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    @staticmethod
    def _text(d: PackageDiff, col: int) -> str:
        if col == 0:
            arrow = _ARROWS.get(d.version_change, "")
            return STATUS_LABELS[d.status] + (f" {arrow}" if arrow else "")
        if col == 1:
            return d.name
        if col == 2:
            return d.version_a
        if col == 3:
            return d.version_b
        if col == 4:
            return ", ".join(d.changed_fields)
        return "⚠ " + " / ".join(FLAG_LABELS[f] for f in d.flags) if d.flags else ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        d = self.diffs[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(d, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = self._text(d, col)
            if col == 0 and d.version_change:
                tip = f"{STATUS_LABELS[d.status]}（{VERSION_CHANGE_LABELS[d.version_change]}）"
            return tip or None
        if role == Qt.ItemDataRole.ForegroundRole:
            # 行全体は塗らない。要注意だけ赤、未変更は控えめな色にする
            t = theme.tokens()
            if col == 5 and d.flags:
                return QColor(t.danger_fg)
            if d.status == DiffStatus.UNCHANGED:
                return QColor(t.text_muted)
            return None
        if role == SORT_ROLE:
            if col == 0:
                return _STATUS_ORDER[d.status]
            return self._text(d, col).lower()
        if role == DIFF_ROLE:
            return d
        return None


class StatusChipDelegate(QStyledItemDelegate):
    """「状態」列: 丸いチップ + 行の左端に色バー（変更のある行のみ）"""

    def paint(self, painter, option, index):
        d = index.data(DIFF_ROLE)
        if d is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""                                   # 文字は自前で描くので、背景・選択色だけ標準描画させる
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        strong, bg, fg = theme.tone_colors(theme.STATUS_TONES[d.status.value])
        fm = opt.fontMetrics
        h = fm.height() + 4
        avail = opt.rect.width() - 20
        label = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(avail - 16, 10))
        w = min(avail, fm.horizontalAdvance(label) + 16)
        r = QRectF(opt.rect.left() + 10, opt.rect.center().y() - h / 2 + 0.5, w, h)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(r, h / 2, h / 2)
        painter.setPen(QColor(fg))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        if d.status != DiffStatus.UNCHANGED:
            painter.fillRect(QRect(opt.rect.left(), opt.rect.top() + 3, 3, opt.rect.height() - 6), QColor(strong))
        painter.restore()


class DiffFilterProxy(QSortFilterProxyModel):
    """状態（タブ）・要注意のみ・検索語で行を絞り込む"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._statuses: Optional[Set[DiffStatus]] = None
        self._attention_only = False
        self._terms: List[str] = []
        self.setSortRole(SORT_ROLE)

    def set_statuses(self, statuses: Optional[Set[DiffStatus]]):
        self._statuses = statuses
        self.invalidateFilter()

    def set_attention_only(self, on: bool):
        self._attention_only = on
        self.invalidateFilter()

    def set_text(self, text: str):
        self._terms = text.lower().split()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        d = self.sourceModel().diffs[source_row]
        if self._statuses is not None and d.status not in self._statuses:
            return False
        if self._attention_only and not d.flags:
            return False
        if self._terms:
            hay = " ".join((d.name, d.key, d.version_a, d.version_b, d.spdx_id_a, d.spdx_id_b)).lower()
            return all(t in hay for t in self._terms)
        return True


# タブ定義: (表示名, 対象の状態 / None=すべて)
_TABS = [
    ("差分", {DiffStatus.ADDED, DiffStatus.REMOVED, DiffStatus.VERSION_CHANGED, DiffStatus.MODIFIED}),
    ("追加", {DiffStatus.ADDED}),
    ("削除", {DiffStatus.REMOVED}),
    ("変更", {DiffStatus.VERSION_CHANGED, DiffStatus.MODIFIED}),
    ("未変更", {DiffStatus.UNCHANGED}),
    ("すべて", None),
]

# 統計カード: (キー, 表示名, 色の系統, クリックで開くタブ)
_CARDS = [
    ("added", "追加", "success", 1),
    ("removed", "削除", "danger", 2),
    ("version_changed", "バージョン変更", "warning", 3),
    ("modified", "その他の変更", "info", 3),
    ("unchanged", "未変更", "neutral", 4),
    ("attention", "⚠ 要注意", "danger", 0),
]


class SbomCompareDialog(QDialog):
    """比較結果ウィンドウ（非モーダル）。

    jump_callback(node) -> bool: メインのツリーで node を選択する。そのノードが現在のツリーに無ければ False。
    options_callback(mode, groups): 比較条件を変更したときに呼ぶ（設定の保存用）。
    """

    def __init__(self, result: CompareResult, jump_callback: Callable[[object], bool],
                 start_dir: str = "", options_callback: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
                            | Qt.WindowType.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1250, 780)

        self.result = result
        self._jump = jump_callback
        self._start_dir = start_dir
        self._options_cb = options_callback

        self._build_ui()
        self.set_result(result)

    # -- UI 構築 ------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        # A / B のドキュメント情報
        self.docs_label = QLabel()
        self.docs_label.setTextFormat(Qt.TextFormat.RichText)
        self.docs_label.setWordWrap(True)
        self.docs_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.docs_label)

        # 統計カード（クリックで該当タブへ）
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self.cards = {}
        for key, caption, tone, tab in _CARDS:
            card = StatCard(caption, tone)
            card.clicked.connect(lambda k=key, t=tab: self._on_card_clicked(k, t))
            cards_row.addWidget(card, 1)
            self.cards[key] = card
        layout.addLayout(cards_row)

        # 注意書き（SPDX バージョン違いなど）
        self.warning_label = QLabel()
        self.warning_label.setTextFormat(Qt.TextFormat.RichText)
        self.warning_label.setWordWrap(True)
        self.warning_label.setProperty("banner", True)
        self.warning_label.setProperty("tone", "warning")
        layout.addWidget(self.warning_label)

        # タブ + 絞り込み
        filter_row = QHBoxLayout()
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        for name, _ in _TABS:
            self.tab_bar.addTab(name)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)
        filter_row.addWidget(self.tab_bar)
        filter_row.addStretch(1)
        self.attention_check = QCheckBox("⚠ 要注意のみ")
        self.attention_check.toggled.connect(self._on_attention_toggled)
        filter_row.addWidget(self.attention_check)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("検索（名前・バージョン・SPDXID。スペース区切りで AND）")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(320)
        self.search_edit.textChanged.connect(lambda t: (self._proxy.set_text(t), self._refresh_view()))
        filter_row.addWidget(self.search_edit)
        layout.addLayout(filter_row)

        # 一覧 | 詳細
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._model = DiffTableModel([])
        self._proxy = DiffFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self.table = QTableView()
        self.table.setModel(self._proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setSortingEnabled(True)
        self._proxy.sort(-1)
        self.table.setItemDelegateForColumn(0, StatusChipDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        for col, width in enumerate((150, 240, 120, 120, 260, 200)):
            self.table.setColumnWidth(col, width)
        self.table.doubleClicked.connect(lambda idx: self._jump_to_tree())
        splitter.addWidget(self.table)

        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.document().setDocumentMargin(14)
        splitter.addWidget(self.detail)
        splitter.setSizes([760, 480])
        layout.addWidget(splitter, 1)

        # 下部ボタン（主操作は「メインのツリーで表示」だけ）
        bottom = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setProperty("role", "muted")
        bottom.addWidget(self.status_label, 1)
        btn_opts = QPushButton("条件を変更...")
        btn_opts.setToolTip("突合キーや比較する項目を変えて、もう一度比較します")
        btn_opts.clicked.connect(self._change_options)
        bottom.addWidget(btn_opts)
        btn_swap = QPushButton("A ⇄ B 入れ替え")
        btn_swap.setToolTip("基準（旧）と対象（新）を入れ替えて、もう一度比較します")
        btn_swap.clicked.connect(self._swap)
        bottom.addWidget(btn_swap)
        btn_csv = QPushButton("CSV 出力...")
        btn_csv.setToolTip("差分を CSV に出力します。現在のタブが『すべて』『未変更』のときは未変更の行も含めます。")
        btn_csv.clicked.connect(self._export_csv)
        bottom.addWidget(btn_csv)
        bottom.addSpacing(8)
        btn_close = QPushButton("閉じる")
        btn_close.setProperty("variant", "ghost")
        btn_close.clicked.connect(self.close)
        bottom.addWidget(btn_close)
        self.btn_jump = QPushButton("メインのツリーで表示")
        self.btn_jump.setProperty("variant", "primary")
        self.btn_jump.setToolTip("選択中のパッケージを、メイン画面のツリーで選択します（ダブルクリックでも可）")
        self.btn_jump.clicked.connect(self._jump_to_tree)
        bottom.addWidget(self.btn_jump)
        layout.addLayout(bottom)

        self.table.selectionModel().currentRowChanged.connect(lambda cur, prev: self._show_detail())

    # -- テーマ変更 -----------------------------------------------------------

    def changeEvent(self, event):
        # テーマ（パレット）が切り替わったら、HTML で作っている部分と表を描き直す
        if event.type() == QEvent.Type.ApplicationPaletteChange and hasattr(self, "table"):
            self.docs_label.setText(docs_html(self.result))
            self.table.viewport().update()
            self._show_detail()
        super().changeEvent(event)

    # -- 結果の反映 ---------------------------------------------------------

    def set_result(self, result: CompareResult):
        self.result = result
        self.setWindowTitle(f"SBOM 比較 - {result.doc_a.label}  ⇄  {result.doc_b.label}")
        self.docs_label.setText(docs_html(result))

        if result.warnings:
            self.warning_label.setText("<br>".join("⚠ " + w.replace("<", "&lt;") for w in result.warnings))
            self.warning_label.show()
        else:
            self.warning_label.hide()

        s = result.summary()
        self.cards["added"].set_value(s["added"])
        self.cards["removed"].set_value(s["removed"])
        self.cards["version_changed"].set_value(s["version_changed"], f"↑{s['upgrade']}  ↓{s['downgrade']}")
        self.cards["modified"].set_value(s["modified"])
        self.cards["unchanged"].set_value(s["unchanged"])
        n_attention = sum(1 for d in result.diffs if d.flags)
        self.cards["attention"].set_value(n_attention)
        self.cards["attention"].setToolTip(
            "\n".join(f"{FLAG_LABELS[k]}: {s[k]}" for k in FLAG_LABELS if s.get(k)) or "要注意の変更はありません")

        for i, (name, statuses) in enumerate(_TABS):
            n = len(result.diffs) if statuses is None else result.count(*statuses)
            self.tab_bar.setTabText(i, f"{name} ({n})")

        self._model.set_diffs(result.diffs)
        self._proxy.sort(-1)
        self._on_tab_changed(self.tab_bar.currentIndex())

    def _on_tab_changed(self, index: int):
        if index < 0:
            return
        self._proxy.set_statuses(_TABS[index][1])
        self._refresh_view(select_first=True)

    def _on_attention_toggled(self, on: bool):
        self._proxy.set_attention_only(on)
        self._refresh_view(select_first=True)

    def _on_card_clicked(self, key: str, tab: int):
        self.attention_check.setChecked(key == "attention")
        if self.tab_bar.currentIndex() == tab:
            self._on_tab_changed(tab)
        else:
            self.tab_bar.setCurrentIndex(tab)

    def _refresh_view(self, select_first: bool = False):
        if select_first and self._proxy.rowCount():
            self.table.selectRow(0)
        self._show_detail()

    # -- 選択中の行 ---------------------------------------------------------

    def _current_diff(self) -> Optional[PackageDiff]:
        # 行クリック時は currentRowChanged が「選択状態の更新」より先に届くため、選択済みかは確認せず現在行を使う
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        return self._proxy.data(self._proxy.index(idx.row(), 0), DIFF_ROLE)

    def _show_detail(self):
        self.status_label.setText(f"{self._proxy.rowCount()} 件を表示")
        d = self._current_diff()
        if d is None:
            msg = "差分はありません。" if not self.result.count(
                DiffStatus.ADDED, DiffStatus.REMOVED, DiffStatus.VERSION_CHANGED, DiffStatus.MODIFIED) \
                else "左の一覧からパッケージを選択すると、詳細を表示します。"
            muted = theme.tokens().text_muted
            self.detail.setHtml(f"<p style='color:{muted}'>{msg}</p>")
            return
        self.detail.setHtml(detail_html(d, self.result))

    def _jump_to_tree(self):
        d = self._current_diff()
        if d is None:
            return
        for node in (d.node_a, d.node_b):
            if node is not None and self._jump(node):
                self.status_label.setText("メインのツリーで選択しました。")
                return
        self.status_label.setText("このパッケージは、メイン画面で開いている SBOM のツリーにありません。")

    # -- ボタン -------------------------------------------------------------

    def _recompare(self, root_a, root_b, label_a, label_b, mode, groups):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = compare(root_a, root_b, mode, groups, label_a=label_a, label_b=label_b)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "比較エラー", f"{type(e).__name__}: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.set_result(result)

    def _swap(self):
        r = self.result
        self._recompare(r.root_b, r.root_a, r.doc_b.label, r.doc_a.label, r.mode, r.groups)

    def _change_options(self):
        r = self.result
        dlg = CompareSetupDialog(self, title="比較条件の変更", base_text=r.doc_a.label, target_text=r.doc_b.label,
                                 ask_target=False, mode=r.mode, groups=r.groups)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mode, groups = dlg.match_mode(), dlg.selected_groups()
        if self._options_cb:
            self._options_cb(mode, groups)
        self._recompare(r.root_a, r.root_b, r.doc_a.label, r.doc_b.label, mode, groups)

    def _export_csv(self):
        default = os.path.join(self._start_dir or "", "sbom_diff.csv")
        path, _ = QFileDialog.getSaveFileName(self, "差分を CSV に出力", default, "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".csv"
        include_unchanged = self.tab_bar.currentIndex() in (4, 5)
        try:
            n = export_csv(self.result, path, include_unchanged=include_unchanged)
        except OSError as e:
            QMessageBox.critical(self, "CSV 出力エラー",
                                 f"書き出せませんでした（Excel などで開いたままになっていないか確認してください）:\n{e}")
            return
        self.status_label.setText(f"CSV に {n} 行を出力しました: {path}")
