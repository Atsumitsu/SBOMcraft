# ui/main_window.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
import sys
import html
import traceback
from PySide6.QtCore import QThread, Slot, QModelIndex, Qt, QSettings, QEvent, QTimer
from PySide6.QtGui import QStandardItemModel, QStandardItem, QColor, QIcon, QPixmap, QActionGroup
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTreeView, QTextEdit, QSplitter, 
    QVBoxLayout, QHBoxLayout, QLabel, QHeaderView, 
    QStatusBar, QFileDialog, QMessageBox, QApplication,QDialog,QToolButton,QMenuBar, QToolButton, QMenu,
    QProgressDialog
)

from core.parser import ParseWorker, SBOMNode
from core.serializer import build_spdx_document, validate_spdx_document, write_json_atomic
from core.validator import SBOMValidator
from ui.detail_panel import DetailPanel
from ui.dialogs import AboutDialog
from ui.spdx3_dialog import Spdx3ExportDialog
from core.spdx3_exporter import convert_node_to_spdx3
from core.converter import SPDXToCycloneDXConverter
from core.validator_worker import ValidationWorker
from core.license_manager import SPDXLicenseManager
from ui.settings_dialog import SettingsDialog
from ui.license_check_dialog import LicenseCheckDialog
from core import VERSION
from core.excel_io import export_packages, apply_changes
from core.excel_worker import ExcelImportWorker
from ui.excel_import_dialog import ExcelImportPreviewDialog
from core.comparer import ALL_GROUPS, MatchKey
from core.drop_plan import DropKind, plan_drop
from core.compare_worker import CompareWorker
from ui.compare_dialog import SbomCompareDialog
from ui.compare_setup_dialog import CompareSetupDialog
from ui import theme
from ui.widgets import ISSUE_ROLE, TreeIssueDelegate, strip_leading_emoji
from core import i18n
from core.i18n import t

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SBOMcraft")
        self.settings = QSettings("MyCompany", "SBOMViewer")
        self.last_dir = self.settings.value("last_directory", "")
        self.current_root_node = None
        self.current_file_path = ""
        self._modified = False  # 未保存の編集があるか
        self._edit_revision = 0  # 編集のたびに増える通し番号（古い Excel の取り込み検知用）
        self._excel_busy = False  # Excel 取り込み中か
        self._excel_progress = None
        self._parse_busy = False  # SBOM の読み込み（パース）中か
        self._after_open = None  # 読み込み成功後に実行する処理（D&D の 2 ファイル自動比較で使う）
        self._drag_plan = None  # ドラッグ中の判定結果（DragMove のたびにファイルを調べ直さないため）
        self._compare_busy = False  # SBOM 比較の実行中か
        self._compare_progress = None
        self._compare_dialogs = []  # 開いている比較ウィンドウ（参照を保持する）
        self._compare_mode = self._load_compare_mode()
        self._compare_groups = self._load_compare_groups()

        # SPDX ライセンスマネージャーの初期化（ローカルキャッシュの読み込み）
        self.license_manager = SPDXLicenseManager()

        self.init_ui()
        
        # ドラッグ＆ドロップ: 入力欄などが先にドロップを受けてパスを書き込まないよう、アプリ全体のフィルターで先に処理する
        self.setAcceptDrops(True)
        for w in self.findChildren(QWidget):          # 入力欄などが先にドロップを受けて、パスを書き込まないようにする
            w.setAcceptDrops(False)
        QApplication.instance().installEventFilter(self)
        self._warn_if_elevated()
        self.restore_window_state()
        self.validator_thread = None

    def init_ui(self):
        self._menu_buttons = []      # テーマ切替時にアイコンを塗り直すために保持
        # -------------------------------------------------------------
        # 1. メニューバーの構築
        # -------------------------------------------------------------
        menu_toolbar = self.addToolBar("MenuToolbar")
        menu_toolbar.setMovable(False)
        from PySide6.QtCore import QSize
        menu_toolbar.setIconSize(QSize(16, 16))
        menu_toolbar.setObjectName("MenuToolbar")

        # 💡 ボタンとメニューをまとめて生成する保守しやすいヘルパー関数
        def add_menu_button(title: str, icon_filename: str, menu: QMenu) -> QToolButton:
            btn = QToolButton(self)
            btn.setText(title)
            icon_path = os.path.join("icons", icon_filename)
            if os.path.exists(icon_path):
                btn.setIcon(theme.icon(icon_filename) or QIcon(icon_path))
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            menu_toolbar.addWidget(btn)
            self._menu_buttons.append((btn, icon_filename))
            return btn

        # --- File メニュー用ボタンの作成 ---
        # ボタンを押したときに展開されるポップアップメニューを作成
        file_menu = QMenu(self)

        open_icon = theme.icon("book-open.svg") or QIcon(os.path.join("icons", "book-open.svg"))
        open_action = file_menu.addAction(open_icon, "Open SBOM JSON")
        open_action.setShortcut("Ctrl+O") # ショートカットキーも追加
        open_action.triggered.connect(self.open_file)

        theme_menu = file_menu.addMenu("テーマ")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for mode_key, mode_label in (("auto", "OS の設定に合わせる"), ("light", "ライト"), ("dark", "ダーク")):
            act = theme_menu.addAction(mode_label)
            act.setCheckable(True)
            act.setChecked(theme.mode() == mode_key)
            theme_group.addAction(act)
            act.triggered.connect(lambda _checked=False, m=mode_key: self._set_theme_mode(m))
        
        file_menu.addSeparator() # 区切り線

        # ▼ 追加: 設定画面を開くアクション
        settings_action = file_menu.addAction("Preferences...")
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings_dialog)

        file_menu.addSeparator() # 区切り線
        # 上書き保存アクション
        save_action = file_menu.addAction("上書き保存(&S)")
        save_action.setShortcut("Ctrl+S") # Ctrl+S
        save_action.triggered.connect(self.save_file)

        # 別名保存アクション
        save_as_action = file_menu.addAction("名前を付けて保存(&A)...")
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_file_as)

        # --- Excel 連携（Packages の一括編集） ---
        file_menu.addSeparator()
        excel_menu = file_menu.addMenu("Excel 連携")
        self.act_excel_export = excel_menu.addAction("Packages を Excel に出力...")
        self.act_excel_export.triggered.connect(self.export_packages_to_excel)
        self.act_excel_import = excel_menu.addAction("Excel から Packages を取り込み...")
        self.act_excel_import.triggered.connect(self.import_packages_from_excel)

        # --- SBOM の比較 ---
        file_menu.addSeparator()
        self.act_compare = file_menu.addAction("別の SBOM と比較...")
        self.act_compare.triggered.connect(self.compare_with_another_sbom)
        self.act_compare_saved = file_menu.addAction("保存前の変更を確認（ディスク上のファイルと比較）")
        self.act_compare_saved.triggered.connect(self.compare_with_saved_file)
               

        file_menu.addSeparator() # 区切り線
        lang_menu = file_menu.addMenu(t("menu.language"))
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)
        current = str(self.settings.value("language", "auto"))
        for code, label in [("auto", t("menu.language.auto"))] + i18n.available_languages():
            act = lang_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(current == code)
            lang_group.addAction(act)
            act.triggered.connect(lambda _c=False, c=code: self._set_language(c))

        file_menu.addSeparator() # 区切り線

        exit_action = file_menu.addAction("Exit")
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close) # 閉じるイベントを呼ぶ

        add_menu_button("  File", "folder.svg", file_menu)

# --- 2. Validation メニュー ---
        validation_menu = QMenu(self)
        self.act_license_check = validation_menu.addAction("License Check")
        self.act_license_check.triggered.connect(self.open_license_check_dialog)
        
        validation_menu.addSeparator()
        
        cisa_menu = validation_menu.addMenu("CISA")
        self.act_cisa_custom = cisa_menu.addAction("Custom CISA2026")
        self.act_cisa_custom.triggered.connect(lambda: self.trigger_validation("CISA2026"))
        
        add_menu_button("  Validation", "text-search.svg", validation_menu)

        # --- 3. Converter メニュー ---
        converter_menu = QMenu(self)
        self.action_export_spdx3ld = converter_menu.addAction("Export to SPDX 3.0 (JSON-LD)")
        self.action_export_cdx = converter_menu.addAction("Export to CycloneDX")
        self.action_export_spdx3ld.triggered.connect(self.on_export_spdx3_triggered)
        self.action_export_cdx.triggered.connect(self.export_to_cyclonedx)

        self.action_export_cdx.setEnabled(False)
        self.action_export_spdx3ld.setEnabled(False)
        self.set_validation_menu_enabled(False)
        
        add_menu_button("  Converter", "refresh-cw.svg", converter_menu)

        # --- 4. Help メニュー ---
        help_menu = QMenu(self)
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self.show_about_dialog)
        
        add_menu_button("  Help", "file-question-mark.svg", help_menu)

        # -------------------------------------------------------------
        # 2. メインレイアウト（スプリッター構造）
        # -------------------------------------------------------------
        self.vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        self.vertical_splitter.setObjectName("vertical_splitter")

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("main_splitter")

        # 左ペイン：ツリービュー
        self.tree_view = QTreeView()
        self.tree_view.setObjectName("tree_view")

        self.tree_view.setItemDelegate(TreeIssueDelegate(self.tree_view))
        self.tree_view.setIndentation(18)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setIconSize(QSize(16, 16))

        # ▼ ツリービュー専用のキープレスイベントを動的にオーバーライド
        def custom_tree_key_press(event):
            text = event.text()
            if text and len(text) == 1:
                char = self._normalize_search_char(text)
                if char and self.jump_to_node_starting_with(char):
                    event.accept()
                    return
            QTreeView.keyPressEvent(self.tree_view, event)
            
        self.tree_view.keyPressEvent = custom_tree_key_press

        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(["Name", "SPDXID"])
        self.tree_view.setModel(self.tree_model)
        self.main_splitter.addWidget(self.tree_view)

        # 右ペイン：詳細パネル
        self.detail_panel = DetailPanel()
        self.detail_panel.node_updated.connect(self.on_detail_node_updated)
        self.main_splitter.addWidget(self.detail_panel)
        self.main_splitter.setSizes([450, 750])

        self.vertical_splitter.addWidget(self.main_splitter)

        # 下段ペイン：検証ログパネル
        compliance_container = QWidget()
        compliance_layout = QVBoxLayout(compliance_container)
        compliance_layout.setContentsMargins(2, 2, 2, 0)
        
        # ▼ アイコンとタイトルを横並びにするヘッダーレイアウト
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(2, 0, 0, 0)
        header_layout.setSpacing(6) # アイコンと文字の間隔

        icon_label = QLabel()
        icon_path = os.path.join("icons", "monitor.svg") # .png の場合は拡張子を変更
        if os.path.exists(icon_path):
            # QIcon経由で読み込むと SVG でも PNG でも指定サイズに綺麗に描画されます
            icon_label.setPixmap((theme.icon("monitor.svg") or QIcon(icon_path)).pixmap(16, 16))
        header_layout.addWidget(icon_label)

        my_label = QLabel("コンソール")
        my_label.setProperty("role", "section")
        header_layout.addWidget(my_label)
        header_layout.addStretch() # 左寄せにするためのスペーサー

        compliance_layout.addLayout(header_layout)
    
        self.compliance_report = QTextEdit()
        self.compliance_report.setReadOnly(True)
        self.compliance_report.setPlaceholderText(
            "メニューの「File」->「Open SBOM JSON」からファイルを読み込んでください。\n"
            "SBOM (SPDX JSON) ファイルをウィンドウにドラッグ＆ドロップしても開けます。2 ファイルをドロップすると比較します。")
        compliance_layout.addWidget(self.compliance_report)
        
        self.vertical_splitter.addWidget(compliance_container)
        self.vertical_splitter.setSizes([600, 200])

        self.setCentralWidget(self.vertical_splitter)

        # イベント接続
        self.tree_view.clicked.connect(self.on_tree_item_clicked)

        # ステータスバー
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setMinimumHeight(28)
        self.status_bar.showMessage("Ready")

    def _set_language(self, code: str):
        if code == str(self.settings.value("language", "auto")):
            return
        self.settings.setValue("language", code)
        new = i18n.normalize_language(code)
        msgs = dict.fromkeys([i18n.t_in(new, "menu.language.restart_msg"),
                            i18n.t_in(i18n.current_language(), "menu.language.restart_msg")])
        QMessageBox.information(self, i18n.t_in(new, "menu.language.restart_title"), "\n\n".join(msgs))


    def set_validation_menu_enabled(self, enabled: bool):
        """メニューの有効・無効を一括切り替え"""
        self.act_license_check.setEnabled(enabled)
        self.act_cisa_custom.setEnabled(enabled)
        self.action_export_cdx.setEnabled(enabled)
        self.action_export_spdx3ld.setEnabled(enabled)
        self.act_excel_export.setEnabled(enabled)
        self.act_excel_import.setEnabled(enabled)
        self.act_compare.setEnabled(enabled)
        self._refresh_compare_saved_action()

    def _refresh_compare_saved_action(self):
        """『保存前の変更を確認』は、未保存の編集があり、ディスク上に元ファイルがあるときだけ有効にする"""
        if not hasattr(self, "act_compare_saved"):
            return
        self.act_compare_saved.setEnabled(
            self.act_compare.isEnabled() and self._modified
            and bool(self.current_file_path) and os.path.isfile(self.current_file_path)
        )

    def trigger_validation(self, profile: str):
        """メニューが選ばれた時の統合窓口（10MBチェックと警告を行う）"""
        if not self.current_file_path:
            return

        file_size = os.path.getsize(self.current_file_path)
        limit_10mb = 10 * 1024 * 1024

        # 10MBを超える場合の警告チェック処理
        if file_size > limit_10mb:
            size_mb = file_size / (1024 * 1024)
            reply = QMessageBox.question(
                self,
                "警告: 大容量ファイル",
                f"ファイルサイズが 10MB を超えています ({size_mb:.2f} MB)。\n"
                "検証処理に時間がかかる可能性がありますが、実行しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                self.compliance_report.append("⚠️ ユーザーにより検証処理がキャンセルされました。")
                return

        self.run_compliance_check(profile)

    def run_compliance_check(self, profile: str):
        # バックグラウンドスレッド(QThread)を使って非同期で適合性検証を実行する
        if not self.current_file_path:
            return

        # 1. コンソール出力エリアの初期化
        self.compliance_report.clear()
        self.compliance_report.append(f"⏳ 非同期検証処理を開始しました... [規格: {profile} ]")

        # 2. 二重実行を防止するためにメニューやボタンを一時無効化
        if hasattr(self, 'set_validation_menu_enabled'):
            self.set_validation_menu_enabled(False)

        # 3. バックグラウンドワーカーのインスタンス化
        sbom_dict = self.build_dict_from_root_node(self.current_root_node)
        self.validation_worker = ValidationWorker(sbom_data=sbom_dict, profile=profile)
#        self.validation_worker = ValidationWorker(self.current_file_path, profile=profile)

        # 4. リアルタイム進捗シグナルとUIスロットの接続
        self.validation_worker.progress_status.connect(self.on_validation_progress)
        self.validation_worker.finished_report.connect(self.on_validation_finished)

        # 5. バックグラウンド処理の開始
        self.validation_worker.start()

    def on_validation_progress(self, message: str):
        """ワーカーから進捗状況（ログ）が送られてくる度にコンソールにリアルタイム追記"""
        self.compliance_report.append(message)
        # 自動で最新ログ（最下部）へスクロール
        self.compliance_report.ensureCursorVisible()

    @Slot(dict)
    def on_validation_finished(self, result: dict):
        """検証完了時に最終HTMLレポートを描画する"""
        # HTML形式の検証結果レポートをレンダリングして表示
        self.compliance_report.setHtml(result["report_html"])
        
        self._mark_validation_issues(result.get("error_packages", []))

        # 無効化していたメニューやボタンの復元
        if hasattr(self, 'set_validation_menu_enabled'):
            self.set_validation_menu_enabled(True)

        # メモリ解放・ワーカー参照のクリア
        self.validation_worker = None

    def _mark_validation_issues(self, error_packages: list):
        """検証結果をツリーに反映する。行は塗らず、左端の色バーと名前の横のバッジで示す。"""
        root_item = self.tree_model.item(0, 0)
        if root_item is None:
            return
        folder = None
        for row in range(root_item.rowCount()):
            child = root_item.child(row, 0)
            if child is not None and child.data(Qt.ItemDataRole.UserRole) is not None \
                    and child.data(Qt.ItemDataRole.UserRole).node_type == "packages_folder":
                folder = child
                break
        if folder is None:
            return

        issues = {}
        for err in error_packages:
            errs = [e.get("msg", "") for e in err.get("errors", [])]
            warns = [w.get("msg", "") for w in err.get("warnings", [])]
            if errs:
                text = errs[0] + (f"（他 {len(errs) - 1} 件）" if len(errs) > 1 else "")
                issues[err["spdx_id"]] = (("error", text), "\n".join(errs + warns))
            else:
                text = (warns[0] if warns else "警告あり") + (f"（他 {len(warns) - 1} 件）" if len(warns) > 1 else "")
                issues[err["spdx_id"]] = (("warning", text), "\n".join(warns))

        for row in range(folder.rowCount()):
            item = folder.child(row, 0)
            if item is None:
                continue
            node = item.data(Qt.ItemDataRole.UserRole)
            found = issues.get(node.spdx_id) if node is not None else None
            item.setData(list(found[0]) if found else None, ISSUE_ROLE)
            item.setToolTip(found[1] if found else "")
        self.tree_view.viewport().update()

    def export_to_cyclonedx(self):
        """現在のSBOMデータをCycloneDX形式に変換して保存する"""
        if not self.current_root_node:
            QMessageBox.warning(self, "Warning", "先にSPDX JSONファイルを読み込んでください。")
            return

        # 保存先ファイルのデフォルト名を提案（元のファイル名 + _cyclonedx.json）
        default_save_path = os.path.splitext(self.current_file_path)[0] + "_cyclonedx.json"
        
        output_cdx_path, _ = QFileDialog.getSaveFileName(
            self, "Save CycloneDX JSON", default_save_path, "JSON Files (*.json);;All Files (*)"
        )

        if not output_cdx_path:
            return  # ユーザーがキャンセルした場合は何もしない

        self.compliance_report.append(f"<br>🔄 CycloneDXへの変換を開始します...<br><font color='gray'>出力先: {output_cdx_path}</font>")
        self.status_bar.showMessage("Converting to CycloneDX...")
        QApplication.processEvents()  # UIを一度更新してメッセージを表示

        try:
            # 1. コンバーターの初期化と実行（メモリ上のノードを渡す）
            converter = SPDXToCycloneDXConverter()
            cyclonedx_json_str = converter.convert(self.current_root_node)

            # 2. 結果の書き出し
            with open(output_cdx_path, "w", encoding="utf-8") as f:
                f.write(cyclonedx_json_str)

            # 3. 成功時のUI更新
            self.status_bar.showMessage(f"Successfully exported to {output_cdx_path}")
            self.compliance_report.append("<font color='green'><b>[SUCCESS]</b> CycloneDXへの変換と保存が完了しました！</font>")
            QMessageBox.information(self, "Success", "CycloneDX形式への変換・保存が完了しました。")

        except Exception as e:
            self.status_bar.showMessage("Conversion failed.")
            self.compliance_report.append(f"<font color='red'><b>[ERROR]</b> 変換失敗: {str(e)}</font>")
            QMessageBox.critical(self, "Conversion Error", f"変換中にエラーが発生しました:\n{str(e)}")

    def restore_window_state(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1200, 850)

        splitter_state = self.settings.value("main_splitter_state")
        if splitter_state:
            self.main_splitter.restoreState(splitter_state)

        v_splitter_state = self.settings.value("vertical_splitter_state")
        if v_splitter_state:
            self.vertical_splitter.restoreState(v_splitter_state)

        tree_state = self.settings.value("tree_view_state")
        if tree_state:
            self.tree_view.header().restoreState(tree_state)

    def closeEvent(self, event):
        if not self._maybe_save_changes():
            event.ignore()
            return
        for dlg in list(self._compare_dialogs):      # 独立ウィンドウの比較結果も一緒に閉じる
            dlg.close()
        QApplication.instance().removeEventFilter(self)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("main_splitter_state", self.main_splitter.saveState())
        self.settings.setValue("vertical_splitter_state", self.vertical_splitter.saveState())
        self.settings.setValue("tree_view_state", self.tree_view.header().saveState())
        super().closeEvent(event)

    def show_about_dialog(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def open_file(self):
        if self._is_busy():
            self.status_bar.showMessage("処理中のためファイルを開けません。完了してからやり直してください。", 5000)
            return
        if not self._maybe_save_changes():   # 未保存の編集があれば先に確認
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open SBOM JSON", self.last_dir, "JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            return
        self._open_path(file_path)

    def _open_path(self, file_path: str, after_open=None):
        """SBOM を読み込む（メニューの Open と D&D の共通処理）。after_open は読み込み成功後に呼ぶ関数。"""
        self._parse_busy = True
        self._after_open = after_open
        self.last_dir = os.path.dirname(file_path)
        self.settings.setValue("last_directory", self.last_dir)
        self.current_file_path = file_path
        
        self.compliance_report.clear()
        self.compliance_report.append("<font color='blue'><b>[INFO]</b> SBOMファイルの読み込みを開始しました...</font>")
        self.compliance_report.append(f"<font color='gray'>File: {file_path}</font><br>")

        self.tree_model.removeRows(0, self.tree_model.rowCount())
        self.detail_panel.clear_display()
        self.set_validation_menu_enabled(False)
        self.current_root_node = None

        # スレッドとワーカーの構築
        self.thread = QThread()
        self.worker = ParseWorker(file_path)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_parse_progress)
        self.worker.finished.connect(self.on_parse_success)
        self.worker.error.connect(self.on_parse_error)
        
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(self.thread.quit)
        self.worker.error.connect(self.worker.deleteLater)

        self.thread.start()

    @Slot(int)
    def on_parse_progress(self, percent: int):
        if percent % 10 == 0 or percent == 99:
            self.compliance_report.append(f"⏳ JSONパース中... {percent}%")
        self.status_bar.showMessage(f"Parsing SBOM... {percent}%")

    @Slot(object)
    def on_parse_success(self, root_node: SBOMNode):
        self._parse_busy = False
        self.compliance_report.append("<br><font color='green'><b>[SUCCESS]</b> JSONのパースが完了しました。</font>")
        self.compliance_report.append("🌿 ツリー画面を構築しています...")
        
        QApplication.processEvents()
        self.status_bar.showMessage("SBOM parsed. Building tree view...")
        self.current_root_node = root_node
        self._set_modified(False)
        self._edit_revision = 0
        
        self.tree_view.setUpdatesEnabled(False)
        self.tree_view.header().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        
        try:
            self.populate_tree(root_node, self.tree_model.invisibleRootItem())
            self.tree_view.expandToDepth(0)
        finally:
            self.tree_view.setUpdatesEnabled(True)
            self.tree_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            self.tree_view.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            self.tree_view.header().setSectionsMovable(True)
            self.tree_view.setColumnWidth(0, 450)

        self.status_bar.showMessage(f"SBOM loaded successfully. File: {self.current_file_path}")
        self.set_validation_menu_enabled(True) # 検証メニューを解禁
        self.compliance_report.append("✅ ツリーの構築が完了しました！")

        callback, self._after_open = self._after_open, None      # D&D の自動比較など、読み込み後に続けたい処理
        if callback:
            QTimer.singleShot(0, callback)

    @Slot(str)
    def on_parse_error(self, error_msg: str):
        self._parse_busy = False
        self._after_open = None
        self.compliance_report.append(f"<br><font color='red'><b>[ERROR]</b> 読み込み失敗: {error_msg}</font>")
        self.status_bar.showMessage(f"Error loading {self.current_file_path}: {error_msg}")
        QMessageBox.critical(self, "Parser Error", f"An error occurred while parsing:\n{error_msg}") 

    def populate_tree(self, node: SBOMNode, parent_item: QStandardItem):
        item_name = QStandardItem()
        self._apply_node_appearance(item_name, node)
        item_name.setData(node, Qt.ItemDataRole.UserRole)
        item_name.setEditable(False)  # ▼ ダブルクリックでの編集を禁止

        item_id = QStandardItem(node.spdx_id if node.spdx_id else "")
        item_id.setEditable(False)    # ▼ ダブルクリックでの編集を禁止
        
        parent_item.appendRow([item_name, item_id])
        
        # ▼ ルートノード（document）の直下にあるフォルダ群はソートせず、
        #    それ以外のフォルダの中身（末端の項目）を名称（node.name）で昇順ソートする
        if node.node_type == "document":
            children_to_process = node.children
        else:
            children_to_process = sorted(node.children, key=lambda x: x.name.lower())
        
        for child in children_to_process:
            self.populate_tree(child, item_name)

    _NODE_ICONS = {
        "document": "book-open.svg",
        "document_info": "info.svg",
        "packages_folder": "folder.svg",
        "category_folder": "folder.svg",
        "relations_folder": "folder.svg",
        "package": "package.svg",
        "file": "file-text.svg",
        "relationship": "link.svg",
        "licenses": "scale.svg",
    }

    def _apply_node_appearance(self, item: QStandardItem, node: SBOMNode):
        """アイコンがあれば『アイコン + 絵文字なしの名前』、無ければ従来どおり絵文字付きの名前で表示する"""
        icon = theme.icon(self._NODE_ICONS.get(node.node_type, ""))
        if icon is not None:
            item.setText(strip_leading_emoji(node.name))
            item.setIcon(icon)
        else:
            item.setText(node.name)

    def on_tree_item_clicked(self, index: QModelIndex):
        if not index.parent().isValid():
            # フォルダやドキュメント直下以外をクリックした場合のガード
            # ※もし「編集中にルート側をクリックした場合」もガードしたい場合はここにチェックを入れます
            if getattr(self.detail_panel, "is_editing", False):
                if not self._check_unsaved_changes():
                    return
            self.detail_panel.clear_display()
            return

        # 💡 【追加】もし現在詳細パネルが編集モード中なら、移動前に確認ダイアログを表示
        if getattr(self.detail_panel, "is_editing", False):
            if not self._check_unsaved_changes():
                # ユーザーが「キャンセル」を選んだ場合は、選択の移動を元のノードに戻す等の処理が必要ですが、
                # シンプルに処理を中断してツリーの選択を戻す場合はインデックス制御を行います。
                return

        model = self.tree_view.model()
        name_index = model.index(index.row(), 0, index.parent())
        item = model.itemFromIndex(name_index)
        if item:
            node = item.data(Qt.ItemDataRole.UserRole)
            if node:
                self.detail_panel.update_display(node)

    def _check_unsaved_changes(self) -> bool:
        """
        編集中に別のノードへ移動しようとした際の確認ダイアログ。
        Returns:
            bool: True = 移動を続行する（保存または破棄）, False = 移動をキャンセルする
        """
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("未保存の変更")
        msg_box.setText("プロパティが編集中です。\n変更を保存しますか？")
        
        # 💡 ボタンを定義して日本語のテキストをセットする
        btn_save = msg_box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        btn_discard = msg_box.addButton("破棄", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = msg_box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        
        msg_box.exec()

        clicked_button = msg_box.clickedButton()

        if clicked_button == btn_save:
            # 1. 保存を実行してから移動を許可
            self.detail_panel.save_edits()
            return True
        elif clicked_button == btn_discard:
            # 2. 変更を破棄（リセット）して移動を許可
            self.detail_panel.reset_edits()
            return True
        else:
            # 3. キャンセル（移動しない）
            return False
    
    # v0.6.2.0
    def on_export_spdx3_triggered(self):
        """SPDX 3.0 エクスポートダイアログを開き、入力されたメタデータを基に変換・保存を実行する"""
        # 読み込まれているルートノードが存在するかチェック
        if not hasattr(self, "current_root_node") or not self.current_root_node:
            QMessageBox.warning(self, "Warning", "エクスポートするSBOMデータが読み込まれていません。")
            return

        # 1. ルートノードの properties から既存メタデータを抽出して辞書を構築
        root_props = getattr(self.current_root_node, "properties", {})
        creation_info = root_props.get("creationInfo", {})
        creators = creation_info.get("creators", [])

        existing_meta = {
            "document_name": root_props.get("name", ""),
            "creators": creators,
            "creator": creators[0] if creators else "",
            "created": creation_info.get("created", ""),
            "comment": root_props.get("comment", "") or creation_info.get("comment", ""),
            "sbom_type": root_props.get("sbomType", ["analyzed"])[0] if isinstance(root_props.get("sbomType"), list) else root_props.get("sbomType", "analyzed"),
            "data_license": root_props.get("dataLicense", "CC0-1.0")
        }

        # 2. Spdx3ExportDialog を初期化（既存メタデータを渡して初期値を反映させる）
        dialog = Spdx3ExportDialog(existing_meta=existing_meta, parent=self)
        
        if dialog.exec() == Spdx3ExportDialog.Accepted:
            # 3. ダイアログで入力・編集されたメタデータを取得
            meta_data = dialog.get_input_data()

            # 4. 保存先ファイルダイアログの表示
            default_filename = "sbom_spdx3.jsonld"
            if hasattr(self, "current_file_path") and self.current_file_path:
                base_name = os.path.splitext(os.path.basename(self.current_file_path))[0]
                default_filename = f"{base_name}_spdx3.jsonld"

            file_path, _ = QFileDialog.getSaveFileName(
                self, "Save SPDX 3.0 JSON-LD", default_filename, "JSON-LD Files (*.jsonld *.json);;All Files (*)"
            )
            
            if file_path:
                try:
                    # 5. エクスポート処理の実行
                    convert_node_to_spdx3(self.current_root_node, file_path, meta_data=meta_data)
                    
                    if hasattr(self, "console"):
                        self.console.append(f"Successfully exported to SPDX 3.0: {file_path}")
                    QMessageBox.information(self, "Success", f"SPDX 3.0 へのエクスポートが完了しました:\n{file_path}")
                    
                except Exception as e:
                    error_msg = f"Export failed: {str(e)}"
                    if hasattr(self, "console"):
                        self.console.append(error_msg)
                    QMessageBox.critical(self, "Error", error_msg)
    # 2026/10/10
    def show_settings_dialog(self):
        """設定ダイアログを表示する"""
        dialog = SettingsDialog(license_manager=self.license_manager, parent=self)
        dialog.exec()

    def open_license_check_dialog(self):
        """ライセンスチェック詳細ダイアログを開く"""
        if not self.current_root_node:
            QMessageBox.warning(self, "Warning", "先にSBOMファイルを読み込んでください。")
            return
        
        dialog = LicenseCheckDialog(
            root_node=self.current_root_node,
            license_manager=self.license_manager,
            parent=self
        )
        dialog.exec()

#2026-11-14
    def keyPressEvent(self, event):
        # tree_view にフォーカスがあるとき、または通常のキー入力時
        # 1文字の英数字（あるいは全角英数字）が押されたかを判定
        text = event.text()
        if text and len(text) == 1 and (text.isalnum() or ord(text) > 127):
            # 全角英数字を半角に、大文字を小文字に正規化
            search_char = self._normalize_search_char(text)
            if search_char:
                if self.jump_to_node_starting_with(search_char):
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _normalize_search_char(self, char: str) -> str:
        """全角英数字を半角小文字に変換する"""
        # 全角英字 (Ａ-Ｚ, ａ-ｚ) や全角数字 (０-９) を半角に変換
        code = ord(char)
        if 0xFF21 <= code <= 0xFF3A:  # Ａ-Ｚ
            char = chr(code - 0xFEE0)
        elif 0xFF41 <= code <= 0xFF5A:  # ａ-ｚ
            char = chr(code - 0xFEE0)
        elif 0xFF10 <= code <= 0xFF19:  # ０-９
            char = chr(code - 0xFEE0)
        return char.lower()

    def jump_to_node_starting_with(self, char: str) -> bool:
        """ツリーモデルを走査し、指定された文字で始まるノードへフォーカスを移動する"""
        model = self.tree_model
        
        # 再帰的にアイテムを探索するヘルパー関数
        def search_items(parent_index: QModelIndex):
            for row in range(model.rowCount(parent_index)):
                index = model.index(row, 0, parent_index)
                item = model.itemFromIndex(index)
                if item:
                    node = item.data(Qt.ItemDataRole.UserRole)
                    if node and node.node_type == "package":  # 主にパッケージなどのノードを対象
                        node_name = node.name.lower()
                        # 絵文字やスペースを除外して純粋な名称の先頭文字と比較
                        # (例: "📦 PySide6" なら 'p' から始まるかチェック)
                        clean_name = "".join([c for c in node_name if c.isalnum()]).lower()
                        if clean_name.startswith(char):
                            return index
                
                # 子階層がある場合は再帰探索
                if model.hasChildren(index):
                    found = search_items(index)
                    if found.isValid():
                        return found
            return QModelIndex()

        target_index = search_items(QModelIndex())
        if target_index.isValid():
            self.tree_view.setCurrentIndex(target_index)
            self.tree_view.scrollTo(target_index, QTreeView.ScrollHint.PositionAtCenter)
            # 選択されたノードの詳細パネルも同時に更新させる
            self.on_tree_item_clicked(target_index)
            return True
        return False
    
    def build_dict_from_root_node(self, root_node: SBOMNode) -> dict:
        """メモリ上の root_node ツリーから、現在の編集内容を反映した SPDX 2.3 辞書を再構築する"""
        return build_spdx_document(root_node)

    @Slot(object)
    def on_detail_node_updated(self, updated_node: SBOMNode):
        """DetailPanel でノードが保存・更新されたとき、ツリービュー側の表示を同期させる"""
        self._set_modified(True)
        self._edit_revision += 1
        # Document Information の編集内容を DocumentRoot 側の properties にも反映
        # (SPDX3 エクスポート等が root.properties を参照するため)
        if updated_node.node_type == "document_info" and self.current_root_node:
            self.current_root_node.properties.update(updated_node.properties)

        model = self.tree_model

        # 1. 現在選択されているツリーアイテムを直接狙って高速に更新
        current_index = self.tree_view.currentIndex()
        if current_index.isValid():
            name_index = model.index(current_index.row(), 0, current_index.parent())
            item = model.itemFromIndex(name_index)
            if item:
                node = item.data(Qt.ItemDataRole.UserRole)
                if node == updated_node:
#                    item.setText(updated_node.name)
                    self._apply_node_appearance(item, updated_node)
                    return

        # 2. フォールバック：ツリー全体を再帰的に走査して該当ノードを更新
        def find_and_update(parent_index: QModelIndex):
            for row in range(model.rowCount(parent_index)):
                index = model.index(row, 0, parent_index)
                item = model.itemFromIndex(index)
                if item:
                    node = item.data(Qt.ItemDataRole.UserRole)
                    if node == updated_node:
#                        item.setText(updated_node.name)
                        self._apply_node_appearance(item, updated_node)
                        return True
                
                if model.hasChildren(index):
                    if find_and_update(index):
                        return True
            return False

        find_and_update(QModelIndex())

    # ------------------------------------------------------------------
    # Excel 連携（Packages の一括編集）
    # ------------------------------------------------------------------
    def export_packages_to_excel(self):
        """全 Packages のスカラー項目を Excel(.xlsx) に出力する"""
        if not self.current_root_node:
            QMessageBox.warning(self, "Warning", "先にSPDX JSONファイルを読み込んでください。")
            return
        if not self._commit_pending_edit():      # 編集中の内容を先に確定してから出力する
            return

        base = os.path.splitext(os.path.basename(self.current_file_path))[0] if self.current_file_path else "sbom"
        default = os.path.join(self.last_dir or "", f"{base}.packages.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "Packages を Excel に出力", default, "Excel Workbook (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        self.last_dir = os.path.dirname(path)
        self.settings.setValue("last_directory", self.last_dir)

        error = None
        result = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = export_packages(
                self.current_root_node, path,
                app_version=VERSION, edit_revision=self._edit_revision,
            )
        except PermissionError:
            error = "ファイルに書き込めません。Excel で開いている場合は閉じてから再実行してください。"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        finally:
            QApplication.restoreOverrideCursor()

        if error:
            self.compliance_report.append(f"<br><font color='red'><b>[ERROR]</b> Excel 出力失敗: {html.escape(error)}</font>")
            QMessageBox.critical(self, "Excel 出力エラー", error)
            return
        list_info = "".join(f" / {sheet} {n} 要素" for sheet, n in result.list_rows.items())
        self.compliance_report.append(
            f"<br><font color='green'><b>[SUCCESS]</b> Packages を Excel に出力しました "
            f"({result.package_count} 件 / {result.column_count} 列{list_info})</font><br>"
            f"<font color='gray'>File: {html.escape(path)}</font>"
        )
        self.status_bar.showMessage(f"Excel に出力しました: {path}")

    def import_packages_from_excel(self):
        """編集済みの Excel を読み込み、差分をプレビューしてから SBOM に反映する"""
        if not self.current_root_node:
            QMessageBox.warning(self, "Warning", "先にSPDX JSONファイルを読み込んでください。")
            return
        if self._excel_busy:
            return
        if not self._commit_pending_edit():
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Excel から Packages を取り込み", self.last_dir, "Excel Workbook (*.xlsx)"
        )
        if not path:
            return
        self.last_dir = os.path.dirname(path)
        self.settings.setValue("last_directory", self.last_dir)
        self._excel_import_path = path

        self._excel_busy = True
        self.set_validation_menu_enabled(False)       # 取り込み中は他の操作を止める
        self.compliance_report.append(f"<br><font color='blue'><b>[INFO]</b> Excel の取り込みを開始しました...</font>")
        self.compliance_report.append(f"<font color='gray'>File: {html.escape(path)}</font>")

        progress = QProgressDialog("Excel を読み込み・解析しています...", "キャンセル", 0, 100, self)
        progress.setWindowTitle("Excel 取り込み")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.show()
        self._excel_progress = progress

        self.excel_thread = QThread()
        self.excel_worker = ExcelImportWorker(self.current_root_node, path, self._edit_revision)
        self.excel_worker.moveToThread(self.excel_thread)

        self.excel_thread.started.connect(self.excel_worker.run)
        self.excel_worker.progress.connect(self.on_excel_import_progress)
        self.excel_worker.finished.connect(self.on_excel_import_finished)
        self.excel_worker.error.connect(self.on_excel_import_error)
        # run() 実行中はワーカー側のイベントループが回らないため、キャンセルは直接呼び出しで伝える
        progress.canceled.connect(self.excel_worker.cancel, Qt.ConnectionType.DirectConnection)

        self.excel_worker.finished.connect(self.excel_thread.quit)
        self.excel_worker.finished.connect(self.excel_worker.deleteLater)
        self.excel_thread.finished.connect(self.excel_thread.deleteLater)
        self.excel_worker.error.connect(self.excel_thread.quit)
        self.excel_worker.error.connect(self.excel_worker.deleteLater)

        self.excel_thread.start()

    def _finish_excel_import_ui(self):
        """進捗ダイアログを閉じ、メニューを元に戻す"""
        if self._excel_progress is not None:
            try:
                self._excel_progress.canceled.disconnect()   # close() は canceled を発火するため先に切り離す
            except (RuntimeError, TypeError):
                pass
            self._excel_progress.close()
            self._excel_progress.deleteLater()
            self._excel_progress = None
        self._excel_busy = False
        if self.current_root_node:
            self.set_validation_menu_enabled(True)

    @Slot(int)
    def on_excel_import_progress(self, percent: int):
        if self._excel_progress is not None:
            self._excel_progress.setValue(percent)

    @Slot(str)
    def on_excel_import_error(self, error_msg: str):
        self._finish_excel_import_ui()
        self.compliance_report.append(f"<br><font color='red'><b>[ERROR]</b> Excel 取り込み失敗: {html.escape(error_msg)}</font>")
        self.status_bar.showMessage("Excel の取り込みに失敗しました。")
        QMessageBox.critical(self, "Excel 取り込みエラー", error_msg)

    @Slot(object)
    def on_excel_import_finished(self, plan):
        self._finish_excel_import_ui()
        if plan is None:
            self.compliance_report.append("<font color='gray'>[INFO] Excel の取り込みをキャンセルしました。</font>")
            self.status_bar.showMessage("Excel の取り込みをキャンセルしました。")
            return

        dialog = ExcelImportPreviewDialog(plan, os.path.basename(self._excel_import_path), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.compliance_report.append("<font color='gray'>[INFO] Excel の取り込みを中止しました（SBOMは変更されていません）。</font>")
            return
        self._apply_excel_changes(plan, dialog.selected_changes())

    def _apply_excel_changes(self, plan, selected):
        """プレビューで承認された差分を SBOM（メモリ上のノード）に反映し、画面を同期する"""
        result = apply_changes(selected)

        for node in result.nodes:
            DetailPanel._refresh_node_label(node)
        self._refresh_tree_items(result.nodes)

        # 詳細パネルに表示中のノードが変わっていたら再表示
        current = getattr(self.detail_panel, "current_node", None)
        if current is not None and any(current is n for n in result.nodes):
            self.detail_panel.update_display(current)

        if result.applied:
            self._edit_revision += 1
            self._set_modified(True)

        skipped_errors = plan.error_count
        n_list = sum(1 for c in result.applied if c.kind == "list")
        self.compliance_report.append(
            f"<br><font color='green'><b>[SUCCESS]</b> Excel から {len(result.applied)} 項目の変更を反映しました "
            f"({len(result.nodes)} パッケージ / うち checksums・externalRefs の一覧 {n_list} 件)。</font>"
        )
        if skipped_errors or plan.warning_count:
            self.compliance_report.append(
                f"<font color='gray'>チェック結果: エラー {skipped_errors} 件（該当セルは未反映） / 警告 {plan.warning_count} 件</font>"
            )
        for ch, reason in result.skipped:
            self.compliance_report.append(
                f"<font color='orange'>[WARN] {html.escape(ch.spdx_id)} / {html.escape(ch.field)}: {html.escape(reason)}</font>"
            )
        if result.applied:
            self.compliance_report.append(
                "<font color='gray'>※ 以前の Validation 結果は古くなっています。必要に応じて再実行してください。</font>"
            )
        self.status_bar.showMessage(f"Excel から {len(result.applied)} 項目を反映しました（未保存）")

    def _refresh_tree_items(self, nodes):
        """指定ノードに対応するツリー項目の表示名だけを更新する（ツリー全体は再構築しない）"""
        targets = {id(n): n for n in nodes}
        if not targets:
            return
        stack = [self.tree_model.invisibleRootItem()]
        while stack and targets:
            parent = stack.pop()
            for row in range(parent.rowCount()):
                item = parent.child(row, 0)
                if item is None:
                    continue
                node = item.data(Qt.ItemDataRole.UserRole)
                if node is not None and id(node) in targets:
#                    item.setText(node.name)
                    self._apply_node_appearance(item, node)
                    del targets[id(node)]
                if item.rowCount():
                    stack.append(item)

    # ------------------------------------------------------------------
    # 保存処理
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # SBOM の比較
    # ------------------------------------------------------------------
    def _load_compare_mode(self) -> MatchKey:
        try:
            return MatchKey(str(self.settings.value("compare_mode", MatchKey.AUTO.value)))
        except ValueError:
            return MatchKey.AUTO

    def _load_compare_groups(self) -> list:
        raw = self.settings.value("compare_groups", None)
        if raw is None:
            return list(ALL_GROUPS)
        if isinstance(raw, str):
            raw = raw.split(",")
        return [g for g in ALL_GROUPS if g in raw]

    def _remember_compare_options(self, mode, groups):
        """比較条件（突合キー・比較する項目）を次回の既定値として保存する"""
        mode = MatchKey(mode)
        self._compare_mode, self._compare_groups = mode, list(groups)
        self.settings.setValue("compare_mode", mode.value)
        self.settings.setValue("compare_groups", ",".join(groups))

    def _compare_precheck(self) -> bool:
        if not self.current_root_node:
            QMessageBox.warning(self, "Warning", "先にSPDX JSONファイルを読み込んでください。")
            return False
        if self._compare_busy or self._excel_busy:
            return False
        return self._commit_pending_edit()      # 編集中のプロパティがあれば先に保存/破棄を確認

    def compare_with_another_sbom(self):
        """現在開いている SBOM（未保存の編集を含む）を基準(A)に、選んだファイル(B)と比較する"""
        if not self._compare_precheck():
            return
        name = os.path.basename(self.current_file_path) or "(無題)"
        label_a = self._current_compare_label()
        base_text = (f"{name}（現在開いている SBOM。未保存の編集内容を含みます）" if self._modified
                     else f"{name}（現在開いている SBOM）")
        dlg = CompareSetupDialog(self, title="別の SBOM と比較", base_text=base_text, ask_target=True,
                                 start_dir=self.last_dir, mode=self._compare_mode, groups=self._compare_groups)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        path, mode, groups = dlg.values()
        self._remember_compare_options(mode, groups)
        self.last_dir = os.path.dirname(path)
        self.settings.setValue("last_directory", self.last_dir)
        self._start_compare(self.current_root_node, label_a, path, os.path.basename(path), mode, groups)

    def compare_with_saved_file(self):
        """ディスク上の元ファイル(A)と、現在の編集内容(B)を比較する（保存前の変更確認）"""
        if not self._compare_precheck():
            return
        path = self.current_file_path
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "比較", "ディスク上に保存済みのファイルがありません。")
            return
        if not self._modified:
            QMessageBox.information(self, "比較", "未保存の変更はありません。")
            return
        name = os.path.basename(path)
        dlg = CompareSetupDialog(self, title="保存前の変更を確認", base_text=f"{name}（ディスク上のファイル）",
                                 target_text=f"{name}（現在の編集内容）", ask_target=False,
                                 mode=self._compare_mode, groups=self._compare_groups)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mode, groups = dlg.match_mode(), dlg.selected_groups()
        self._remember_compare_options(mode, groups)
        self._start_compare(path, f"{name} (ディスク上)", self.current_root_node, f"{name} (編集中)", mode, groups)

    def _start_compare(self, source_a, label_a: str, source_b, label_b: str, mode, groups):
        """source は読み込み済みのルートノード、または SBOM JSON のパス。読み込みと比較は別スレッドで行う"""
        self._compare_busy = True
        self.set_validation_menu_enabled(False)       # 比較中は他の操作を止める
        self.compliance_report.append("<br><font color='blue'><b>[INFO]</b> SBOM の比較を開始しました...</font>")
        self.compliance_report.append(
            f"<font color='gray'>A(旧): {html.escape(label_a)} / B(新): {html.escape(label_b)}</font>")

        progress = QProgressDialog("SBOM を読み込み・比較しています...", "キャンセル", 0, 100, self)
        progress.setWindowTitle("SBOM の比較")
        progress.setWindowModality(Qt.WindowModality.WindowModal)   # 比較中に編集されないよう、メイン画面の操作を止める
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.show()
        self._compare_progress = progress

        self.compare_thread = QThread()
        self.compare_worker = CompareWorker(source_a, label_a, source_b, label_b, mode, groups)
        self.compare_worker.moveToThread(self.compare_thread)

        self.compare_thread.started.connect(self.compare_worker.run)
        self.compare_worker.progress.connect(self.on_compare_progress)
        self.compare_worker.finished.connect(self.on_compare_finished)
        self.compare_worker.error.connect(self.on_compare_error)
        # run() 実行中はワーカー側のイベントループが回らないため、キャンセルは直接呼び出しで伝える
        progress.canceled.connect(self.compare_worker.cancel, Qt.ConnectionType.DirectConnection)

        self.compare_worker.finished.connect(self.compare_thread.quit)
        self.compare_worker.finished.connect(self.compare_worker.deleteLater)
        self.compare_thread.finished.connect(self.compare_thread.deleteLater)
        self.compare_worker.error.connect(self.compare_thread.quit)
        self.compare_worker.error.connect(self.compare_worker.deleteLater)

        self.compare_thread.start()

    def _finish_compare_ui(self):
        """進捗ダイアログを閉じ、メニューを元に戻す"""
        if self._compare_progress is not None:
            try:
                self._compare_progress.canceled.disconnect()   # close() は canceled を発火するため先に切り離す
            except (RuntimeError, TypeError):
                pass
            self._compare_progress.close()
            self._compare_progress.deleteLater()
            self._compare_progress = None
        self._compare_busy = False
        if self.current_root_node:
            self.set_validation_menu_enabled(True)

    @Slot(int)
    def on_compare_progress(self, percent: int):
        if self._compare_progress is not None:
            self._compare_progress.setValue(percent)

    @Slot(str)
    def on_compare_error(self, error_msg: str):
        self._finish_compare_ui()
        self.compliance_report.append(f"<br><font color='red'><b>[ERROR]</b> 比較失敗: {html.escape(error_msg)}</font>")
        self.status_bar.showMessage("SBOM の比較に失敗しました。")
        QMessageBox.critical(self, "比較エラー", error_msg)

    @Slot(object)
    def on_compare_finished(self, result):
        self._finish_compare_ui()
        if result is None:
            self.compliance_report.append("<font color='gray'>[INFO] SBOM の比較をキャンセルしました。</font>")
            self.status_bar.showMessage("SBOM の比較をキャンセルしました。")
            return

        s = result.summary()
        self.compliance_report.append(
            f"<font color='green'><b>[SUCCESS]</b> 比較が完了しました。"
            f"追加 {s['added']} / 削除 {s['removed']} / 変更 {s['changed']} / 未変更 {s['unchanged']}</font>")
        self.status_bar.showMessage("SBOM の比較が完了しました。")

        dlg = SbomCompareDialog(result, self._jump_to_node, start_dir=self.last_dir,
                                options_callback=self._remember_compare_options, parent=None)   # 独立ウィンドウ（親にすると常にメイン画面の前面に出るため）
        self._compare_dialogs.append(dlg)
        dlg.finished.connect(lambda _code=0, d=dlg: self._forget_compare_dialog(d))
        dlg.show()

    def _forget_compare_dialog(self, dlg):
        if dlg in self._compare_dialogs:
            self._compare_dialogs.remove(dlg)

    def _jump_to_node(self, node) -> bool:
        """比較ウィンドウからの依頼: node をメインのツリーで選択する。現在のツリーに無ければ False"""
        if node is None or self.current_root_node is None:
            return False
        model = self.tree_model

        def search(parent_index: QModelIndex) -> QModelIndex:
            for row in range(model.rowCount(parent_index)):
                index = model.index(row, 0, parent_index)
                item = model.itemFromIndex(index)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) is node:
                    return index
                if model.hasChildren(index):
                    found = search(index)
                    if found.isValid():
                        return found
            return QModelIndex()

        index = search(QModelIndex())
        if not index.isValid():
            return False
        parent = index.parent()
        while parent.isValid():
            self.tree_view.expand(parent)
            parent = parent.parent()
        self.tree_view.setCurrentIndex(index)
        self.tree_view.scrollTo(index, QTreeView.ScrollHint.PositionAtCenter)
        self.on_tree_item_clicked(index)
        self.raise_()
        self.activateWindow()
        return True

    # ------------------------------------------------------------------
    # ドラッグ＆ドロップ
    # ------------------------------------------------------------------
    def _is_busy(self) -> bool:
        return self._parse_busy or self._compare_busy or self._excel_busy

    def _current_compare_label(self) -> str:
        name = os.path.basename(self.current_file_path) or "(無題)"
        return f"{name} (編集中)" if self._modified else name

    def _is_in_main_window(self, obj) -> bool:
        """obj がメイン画面（またはその部品）か。子ダイアログ（確認・進捗など）や別ウィンドウは含めない"""
        if obj is self:
            return True
        if not isinstance(obj, QWidget) or not self.isAncestorOf(obj):
            return False
        return not isinstance(obj.window(), QDialog)

    def eventFilter(self, obj, event):
        et = event.type()
        if (et in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
                and self._is_in_main_window(obj)):
            mime = event.mimeData()
            if mime is not None and mime.hasUrls():
                self._safe_drag_event(event, et)
                return True
        return super().eventFilter(obj, event)

    # 標準の受け口。上のフィルターで処理されなかったとき（ドロップ先がメイン画面そのものの場合など）に使われる
    def dragEnterEvent(self, event):
        self._safe_drag_event(event, QEvent.Type.DragEnter)

    def dragMoveEvent(self, event):
        self._safe_drag_event(event, QEvent.Type.DragMove)

    def dropEvent(self, event):
        self._safe_drag_event(event, QEvent.Type.Drop)

    def _safe_drag_event(self, event, et):
        """例外で event が未処理のまま戻ると、原因が分からないまま禁止マークになるため、必ず内容を表示する"""
        try:
            self._on_drag_event(event, et)
        except Exception as e:
            traceback.print_exc()
            event.ignore()
            self.status_bar.showMessage(f"ドロップの処理でエラーが発生しました: {type(e).__name__}: {e}", 10000)

    def _warn_if_elevated(self):
        """Windows で管理者として実行していると、通常権限のエクスプローラーからはドロップできない（UIPI）"""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return
        if elevated:
            msg = ("管理者権限で実行中のため、エクスプローラーからのドラッグ＆ドロップは使えません"
                   "（Windows の仕様）。通常の権限で起動し直してください。")
            self.status_bar.showMessage(msg, 20000)
            self.compliance_report.append(f"<font color='#B36B00'><b>[WARN]</b> {html.escape(msg)}</font>")

    def _on_drag_event(self, event, et):
        if et == QEvent.Type.Drop or et == QEvent.Type.DragEnter or self._drag_plan is None:
            paths = [u.toLocalFile() if u.isLocalFile() else u.toString() for u in event.mimeData().urls()]
            self._drag_plan = plan_drop(paths, has_loaded=self.current_root_node is not None, busy=self._is_busy())
        plan = self._drag_plan

        if plan.kind == DropKind.REJECT:
            event.ignore()
            if et != QEvent.Type.DragMove:
                self.status_bar.showMessage(plan.reason, 5000)
            if et == QEvent.Type.Drop:
                self._drag_plan = None
            return
        event.acceptProposedAction()
        if et == QEvent.Type.Drop:
            self._drag_plan = None
            # ドロップ元（エクスプローラー等）を待たせないよう、ダイアログを伴う処理はイベントの外で実行する
            QTimer.singleShot(0, lambda: self._execute_drop_plan(plan))

    def _execute_drop_plan(self, plan):
        if self._is_busy():
            return
        paths = list(plan.paths)
        if plan.kind == DropKind.OPEN:
            if self._maybe_save_changes():
                self._open_path(paths[0])
        elif plan.kind == DropKind.ASK_OPEN_OR_COMPARE:
            self._ask_open_or_compare(paths[0])
        elif plan.kind == DropKind.COMPARE_TWO:
            self._open_and_compare(paths[0], paths[1])
        elif plan.kind == DropKind.CONFIRM_COMPARE_TWO:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("ファイルのドロップ")
            box.setText("2 つのファイルがドロップされました。")
            box.setInformativeText(
                f"現在開いている SBOM を閉じて、次の 2 ファイルを比較します。\n\n"
                f"A（旧）: {os.path.basename(paths[0])}\nB（新）: {os.path.basename(paths[1])}")
            btn_ok = box.addButton("比較する", QMessageBox.ButtonRole.AcceptRole)
            btn_cancel = box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_ok)
            box.setEscapeButton(btn_cancel)
            box.exec()
            if box.clickedButton() is btn_ok:
                self._open_and_compare(paths[0], paths[1])

    def _ask_open_or_compare(self, path: str):
        """SBOM を開いている状態で 1 ファイルがドロップされたとき: 新規で開くか、比較するかを確認する"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("ファイルのドロップ")
        box.setText(f"「{os.path.basename(path)}」がドロップされました。")
        box.setInformativeText(
            "新規として開くか、現在開いている SBOM と比較するかを選んでください。\n\n"
            "・新規として開く: 現在の SBOM を閉じて読み込みます。\n"
            "・現在の SBOM と比較: 現在の SBOM（未保存の編集を含む）を A（旧）、"
            "ドロップしたファイルを B（新）として比較します。")
        btn_open = box.addButton("新規として開く", QMessageBox.ButtonRole.AcceptRole)
        btn_compare = box.addButton("現在の SBOM と比較", QMessageBox.ButtonRole.AcceptRole)
        btn_cancel = box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_open)
        box.setEscapeButton(btn_cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_open:
            if self._maybe_save_changes():
                self._open_path(path)
        elif clicked is btn_compare:
            if not self._compare_precheck():
                return
            self._start_compare(self.current_root_node, self._current_compare_label(),
                                path, os.path.basename(path), self._compare_mode, self._compare_groups)

    def _open_and_compare(self, first: str, second: str):
        """1 つ目を開き（メイン画面のツリー = A）、読み込み完了後に 2 つ目(B)と前回の条件で自動比較する"""
        if not self._maybe_save_changes():
            return

        def compare_after_open():
            if self.current_root_node is None:       # 読み込みに失敗した場合は比較しない
                return
            self._start_compare(self.current_root_node, os.path.basename(first),
                                second, os.path.basename(second), self._compare_mode, self._compare_groups)

        self._open_path(first, after_open=compare_after_open)

    def _set_modified(self, modified: bool):
        self._modified = modified
        self._update_window_title()
        self._refresh_compare_saved_action()

    def _update_window_title(self):
        name = os.path.basename(self.current_file_path) if self.current_file_path else ""
        title = f"SBOMcraft - {name}" if name else "SBOMcraft"
        self.setWindowTitle(f"{title} *" if self._modified else title)

    def _commit_pending_edit(self) -> bool:
        """DetailPanel が編集モードのままなら、保存/破棄/キャンセルを確認する。False=処理を中止"""
        if getattr(self.detail_panel, "is_editing", False):
            return self._check_unsaved_changes()
        return True

    def _maybe_save_changes(self) -> bool:
        """ファイルを閉じる/開き直す前の未保存確認。True=続行 / False=キャンセル"""
        if not self._commit_pending_edit():
            return False
        if not (self._modified and self.current_root_node):
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("未保存の変更")
        box.setText("変更内容がファイルに保存されていません。\n保存しますか？")
        btn_save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        btn_discard = box.addButton("破棄", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked == btn_save:
            return self.save_file()      # 保存に失敗/キャンセルしたら False → 閉じない
        return clicked == btn_discard

    def save_file(self) -> bool:
        """現在開いているファイルに上書き保存する。成功したら True"""
        if not self.current_root_node:
            QMessageBox.warning(self, "Warning", "保存するSBOMデータが読み込まれていません。")
            return False
        if not self._commit_pending_edit():
            return False
        if not self.current_file_path:
            return self.save_file_as()
        return self._write_to_file(self.current_file_path)

    def save_file_as(self) -> bool:
        """ファイルチューザーを開いて別名で保存する。成功したら True"""
        if not self.current_root_node:
            QMessageBox.warning(self, "Warning", "保存するSBOMデータが読み込まれていません。")
            return False
        if not self._commit_pending_edit():
            return False

        default_path = self.current_file_path or os.path.join(self.last_dir or "", "sbom.spdx.json")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "名前を付けて保存", default_path, "SPDX JSON (*.json);;All Files (*)"
        )
        if not file_path:
            return False
        if not os.path.splitext(file_path)[1]:
            file_path += ".json"
        return self._write_to_file(file_path)

    def _write_to_file(self, file_path: str) -> bool:
        """
        編集内容を反映した SPDX 2.3 JSON を file_path にアトミックに書き出す。
        成功したら True。失敗時は元のファイルを壊さず False を返す。
        """
        if not self.current_root_node:
            return False

        error = None
        warnings = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            doc = self.build_dict_from_root_node(self.current_root_node)   # ツリー → SPDX 辞書
            warnings = validate_spdx_document(doc)                         # 構造チェック(警告のみ)
            write_json_atomic(file_path, doc, indent=2)                    # 一時ファイル→置換
        except Exception as e:
            error = e
        finally:
            QApplication.restoreOverrideCursor()

        if error is not None:
            self.status_bar.showMessage("Save failed.")
            self.compliance_report.append(
                f"<font color='red'><b>[ERROR]</b> 保存失敗: {html.escape(str(error))}</font>")
            QMessageBox.critical(self, "エラー", f"ファイルの保存に失敗しました:\n{error}")
            return False

        # --- 成功時の状態更新 ---
        self.current_file_path = file_path
        self.last_dir = os.path.dirname(file_path)
        self.settings.setValue("last_directory", self.last_dir)
        self._set_modified(False)

        self.status_bar.showMessage(f"Saved: {file_path}")
        self.compliance_report.append(
            f"<font color='green'><b>[SUCCESS]</b> 保存しました:</font> "
            f"<font color='gray'>{html.escape(file_path)}</font>")
        if warnings:
            self.compliance_report.append(
                f"<font color='#b36b00'><b>[WARN]</b> SPDX 2.3 の構造チェックで {len(warnings)} 件の指摘があります"
                "（ファイルは保存済みです）:</font>")
            for msg in warnings:
                self.compliance_report.append(f"&nbsp;&nbsp;・{html.escape(msg)}")
        return True

    def _set_theme_mode(self, mode: str):
        theme.apply_theme(QApplication.instance(), mode)
        self.settings.setValue("theme_mode", mode)

    def changeEvent(self, event):
        # テーマ（パレット）が変わったら、色を塗ったアイコンを塗り直す
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self._refresh_theme_assets()
        super().changeEvent(event)

    def _refresh_theme_assets(self):
        for btn, filename in getattr(self, "_menu_buttons", []):
            ico = theme.icon(filename)
            if ico is not None:
                btn.setIcon(ico)
        model = getattr(self, "tree_model", None)
        if model is None:
            return
        stack = [model.invisibleRootItem()]
        while stack:
            parent = stack.pop()
            for row in range(parent.rowCount()):
                item = parent.child(row, 0)
                if item is None:
                    continue
                node = item.data(Qt.ItemDataRole.UserRole)
                if node is not None:
                    self._apply_node_appearance(item, node)
                if item.rowCount():
                    stack.append(item)
