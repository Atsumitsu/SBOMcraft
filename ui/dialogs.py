# ui/dialogs.py
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 XZ Manj

import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, 
    QPushButton, QApplication, QMessageBox, QLabel, QWidget
)

class FullTextDialog(QDialog):
    """長文のテキストを大画面でスクロール表示・コピーするためのダイアログ"""
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)

        layout = QVBoxLayout(self)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(text)
        font = self.text_edit.font()
        font.setFamily("Courier New")
        self.text_edit.setFont(font)
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        btn_copy = QPushButton("📋 クリップボードにコピー")
        btn_copy.clicked.connect(self.copy_to_clipboard)
        btn_layout.addWidget(btn_copy)
        
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)

    def copy_to_clipboard(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())
        QMessageBox.information(self, "完了", "テキストをクリップボードにコピーしました。")

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About SBOMcraft")
        self.resize(520, 450)  # アイコン追加に合わせて少しだけサイズを微調整
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # -------------------------------------------------------------
        # ヘッダーエリア（アイコンとタイトルを横に並べる）
        # -------------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(15)

        # 1. アイコンの読み込みと表示
        icon_label = QLabel()
        icon_path = "SBOMCraft2-512.png" # 実行ディレクトリまたは適切なパスを指定してください
        
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            # 512pxだと少し大きすぎるため、ダイアログ用に64x64に綺麗に縮小します
            scaled_pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(scaled_pixmap)
        else:
            # 万が一画像が見つからない場合のフォールバック（不格好にならないように絵文字を表示）
            icon_label.setText("<span style='font-size: 32px;'>📦</span>")
        
        header_layout.addWidget(icon_label)

        # 2. アプリ名とバージョン情報のテキスト
        title_label = QLabel(
            "<div style='margin-top: 5px;'>"
            "<h2 style='margin: 0; color: #2c3e50;'>SBOMcraft</h2>"
            "<p style='margin: 4px 0 0 0; color: #555;'><b>Version:</b> 0.5.0.0 (2026.07)</p>"
            "</div>"
        )
        header_layout.addWidget(title_label, 1) # 1を指定して右側のスペースを引き伸ばす

        layout.addLayout(header_layout)

        # -------------------------------------------------------------
        # メインエリア（ライセンス・謝辞のテキストブラウザ）
        # -------------------------------------------------------------
        info_browser = QTextBrowser()
        info_browser.setOpenExternalLinks(True)
        
        about_html = """
        <h3>📄 Software License</h3>
                <p><b>SPDX-License-Identifier:</b> <a href="https://spdx.org/licenses/MIT.html">MIT</a></p>
                <p>Copyright (c) 2026 XZ Manj</p>
                
        <hr>
        <h3>📦 Third-Party Licenses & Acknowledgements</h3>
                <p>This software integrates and builds upon excellent tools provided by the open-source community:</p>
        
        <ul>
            <li>
                <b>PySide6 (Qt for Python)</b><br>
                License: LGPL-3.0-only</br>
                URL: <a href="https://www.qt.io/ja-jp/development/download-open-source">https://www.qt.io</a><br>
            </li>
            <li>
                <b>Python</b><br>
                ver:3.13</br>
                License: PSF-2.0<br>
            </li>
            <li>
                <b>ntia-conformance-checker (SPDX Official Tool)</b><br>
                Version: 5.0.3</br>
                License: <a href="https://spdx.org/licenses/Apache-2.0.html">Apache-2.0</a><br>
                URL:<a href="https://github.com/spdx/ntia-conformance-checker">https://github.com/spdx/ntia-conformance-checker</a><br>
                Developed by the SPDX Community. Special thanks to their contributors for enabling strict NTIA and CISA (fsct3-min) conformance checking via their official Python APIs.<br>
            </li>
            <li>
                <b>spdx-tools (SPDX Official Tool)</b><br>
                Version: 0.8.5</br>
                License: <a href="https://spdx.org/licenses/Apache-2.0.html">Apache-2.0</a><br>
            </li>
            <li>
                <b>spdx-python-model (SPDX Official Tool)</b><br>
                Version: 0.0.4</br>
                License: <a href="https://spdx.org/licenses/Apache-2.0.html">Apache-2.0</a><br>
            </li>
        </ul>        
        <p style="font-size: 11px; color: #666; margin-top: 15px;">
        All other registered trademarks and copyrights are the property of their respective owners.
        </p>        """
        info_browser.setHtml(about_html)
        layout.addWidget(info_browser)

        # -------------------------------------------------------------
        # フッターエリア（閉じるボタン）
        # -------------------------------------------------------------
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        