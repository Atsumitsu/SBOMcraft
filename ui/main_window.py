# ui/main_window.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
from PySide6.QtCore import QThread, Slot, QModelIndex, Qt, QSettings
from PySide6.QtGui import QStandardItemModel, QStandardItem, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTreeView, QTextEdit, QSplitter, 
    QVBoxLayout, QHBoxLayout, QLabel, QHeaderView, 
    QStatusBar, QFileDialog, QMessageBox, QApplication
)

from core.parser import ParseWorker, SBOMNode
from core.validator import SBOMValidator
from ui.detail_panel import DetailPanel
from ui.dialogs import AboutDialog
from core.converter import SPDXToCycloneDXConverter
from core.validator_worker import ValidationWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SBOMcraft")
        self.settings = QSettings("MyCompany", "SBOMViewer")
        self.last_dir = self.settings.value("last_directory", "")
        self.current_root_node = None
        self.current_file_path = ""
        
        self.init_ui()
        self.restore_window_state()
        self.validator_thread = None

    def init_ui(self):
        # -------------------------------------------------------------
        # 1. メニューバーの構築
        # -------------------------------------------------------------
        menu_bar = self.menuBar()

        # --- File メニュー ---
        file_menu = menu_bar.addMenu("File")
        
        open_action = file_menu.addAction("📂 Open SBOM JSON")
        open_action.setShortcut("Ctrl+O") # ショートカットキーも追加
        open_action.triggered.connect(self.open_file)
        
        file_menu.addSeparator() # 区切り線
        
        exit_action = file_menu.addAction("❌ Exit")
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close) # 閉じるイベントを呼ぶ

        # --- Validation メニュー ---
        validation_menu = menu_bar.addMenu("Validation")
        
        # CISA サブメニュー
        cisa_menu = validation_menu.addMenu("CISA")
        self.act_cisa_custom = cisa_menu.addAction("Custom CISA2026")

        # イベント接続
        self.act_cisa_custom.triggered.connect(lambda: self.trigger_validation("CISA2026"))

        # --- Converter メニュー ---
        converter_menu = menu_bar.addMenu("Converter")
        self.action_export_cdx = converter_menu.addAction("🔄 Export to CycloneDX")
        self.action_export_cdx.triggered.connect(self.export_to_cyclonedx)
        
        # 初期状態ではファイルがないため無効化しておく
        self.action_export_cdx.setEnabled(False)

        # 初期状態では検証メニューを無効化
        self.set_validation_menu_enabled(False)

        # --- Help メニュー ---
        help_menu = menu_bar.addMenu("Help")
        about_action = help_menu.addAction("ℹ️ About")
        about_action.triggered.connect(self.show_about_dialog)

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
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(["Name", "SPDXID"])
        self.tree_view.setModel(self.tree_model)
        self.main_splitter.addWidget(self.tree_view)

        # 右ペイン：詳細パネル
        self.detail_panel = DetailPanel()
        self.main_splitter.addWidget(self.detail_panel)
        self.main_splitter.setSizes([450, 750])

        self.vertical_splitter.addWidget(self.main_splitter)

        # 下段ペイン：検証ログパネル
        compliance_container = QWidget()
        compliance_layout = QVBoxLayout(compliance_container)
        compliance_layout.setContentsMargins(2, 2, 2, 0)
        
        my_label = QLabel("■ コンソール")
        my_label.setStyleSheet("margin-left: 2px;")
        compliance_layout.addWidget(my_label)
    
        self.compliance_report = QTextEdit()
        self.compliance_report.setReadOnly(True)
        self.compliance_report.setPlaceholderText("メニューの「File」->「Open SBOM JSON」からファイルを読み込んでください。")
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

    def set_validation_menu_enabled(self, enabled: bool):
        """メニューの有効・無効を一括切り替え"""
        self.act_cisa_custom.setEnabled(enabled)
        self.action_export_cdx.setEnabled(enabled)

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
        self.validation_worker = ValidationWorker(self.current_file_path, profile=profile)

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

    def on_validation_finished(self, result: dict):
        """検証完了時に最終HTMLレポートを描画する"""
        # HTML形式の検証結果レポートをレンダリングして表示
        self.compliance_report.setHtml(result["report_html"])
        # エラー箇所を赤く染めるUI処理
        if result.get("error_packages"):
            root_item = self.tree_model.item(0, 0)
            tree_pkg_folder_item = None
            if root_item:
                for row in range(root_item.rowCount()):
                    child_item = root_item.child(row, 0)
                    if child_item and "Packages" in child_item.text():
                        tree_pkg_folder_item = child_item
                        break

            if tree_pkg_folder_item:
                warning_color = QColor("#FFCCCC")
                for err in result["error_packages"]:
                    idx = err["index"]
                    reasons_str = err["reasons"]
                    
                    pkg_item_name = tree_pkg_folder_item.child(idx, 0)
                    pkg_item_id = tree_pkg_folder_item.child(idx, 1)

                    if pkg_item_name and pkg_item_id:
                        pkg_item_name.setBackground(warning_color)
                        pkg_item_id.setBackground(warning_color)
                        if not pkg_item_name.text().startswith("⚠️"):
                            pkg_item_name.setText(f"⚠️ {pkg_item_name.text()} 【{reasons_str}】")

        # 無効化していたメニューやボタンの復元
        if hasattr(self, 'set_validation_menu_enabled'):
            self.set_validation_menu_enabled(True)

        # メモリ解放・ワーカー参照のクリア
        self.validation_worker = None

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
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("main_splitter_state", self.main_splitter.saveState())
        self.settings.setValue("vertical_splitter_state", self.vertical_splitter.saveState())
        self.settings.setValue("tree_view_state", self.tree_view.header().saveState())
        super().closeEvent(event)

    def show_about_dialog(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open SBOM JSON", self.last_dir, "JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            return

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
        self.compliance_report.append("<br><font color='green'><b>[SUCCESS]</b> JSONのパースが完了しました。</font>")
        self.compliance_report.append("🌿 ツリー画面を構築しています...")
        
        QApplication.processEvents()
        self.status_bar.showMessage("SBOM parsed. Building tree view...")
        self.current_root_node = root_node
        
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

    @Slot(str)
    def on_parse_error(self, error_msg: str):
        self.compliance_report.append(f"<br><font color='red'><b>[ERROR]</b> 読み込み失敗: {error_msg}</font>")
        self.status_bar.showMessage(f"Error loading {self.current_file_path}: {error_msg}")
        QMessageBox.critical(self, "Parser Error", f"An error occurred while parsing:\n{error_msg}") 

    def populate_tree(self, node: SBOMNode, parent_item: QStandardItem):
        item_name = QStandardItem(node.name)
        item_name.setData(node, Qt.ItemDataRole.UserRole)
        item_id = QStandardItem(node.spdx_id if node.spdx_id else "")
        
        parent_item.appendRow([item_name, item_id])
        for child in node.children:
            self.populate_tree(child, item_name)

    def on_tree_item_clicked(self, index: QModelIndex):
        if not index.parent().isValid():
            self.detail_panel.clear_display()
            return
        model = self.tree_view.model()
        name_index = model.index(index.row(), 0, index.parent())
        item = model.itemFromIndex(name_index)
        if item:
            node = item.data(Qt.ItemDataRole.UserRole)
            if node:
                self.detail_panel.update_display(node)