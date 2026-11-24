# ui/dialogs.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QTextBrowser,
    QPushButton, QApplication, QMessageBox, QLabel
)
from core import VERSION, COPYRIGHT
from core.i18n import t
from ui import theme


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
        self.text_edit.setFont(theme.mono_font(10))
        layout.addWidget(self.text_edit)

        btn_layout = QHBoxLayout()
        btn_copy = QPushButton(t("dialogs.copy"))
        btn_copy.clicked.connect(self.copy_to_clipboard)
        btn_layout.addWidget(btn_copy)

        btn_close = QPushButton(t("dialogs.close"))
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def copy_to_clipboard(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())
        QMessageBox.information(self, t("dialogs.done_title"), t("dialogs.copied"))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About SBOMcraft")
        self.resize(520, 450)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        tok = theme.tokens()     # ※ 変数名を t にすると翻訳関数 t() を隠してしまうため tok とする

        # -------------------------------------------------------------
        # ヘッダーエリア（アイコンとタイトルを横に並べる）
        # -------------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(15)

        icon_label = QLabel()
        icon_path = "SBOMCraft2-512.png"  # 実行ディレクトリまたは適切なパスを指定してください

        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            # 512pxだと少し大きすぎるため、ダイアログ用に64x64に綺麗に縮小します
            scaled_pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(scaled_pixmap)
        else:
            # 画像が見つからない場合のフォールバック
            icon_label.setText("<span style='font-size: 32px;'>📦</span>")

        header_layout.addWidget(icon_label)

        title_label = QLabel(
            "<div style='margin-top: 5px;'>"
            f"<h2 style='margin: 0; color: {tok.text};'>SBOMCraft</h2>"
            f"<p style='margin: 4px 0 0 0; color: {tok.text_muted};'><b>{t('about.version')}</b> {VERSION}</p>"
            "</div>"
        )
        header_layout.addWidget(title_label, 1)

        layout.addLayout(header_layout)

        # -------------------------------------------------------------
        # メインエリア（ライセンス・謝辞のテキストブラウザ）
        # ライセンス名・著作権表記などの法的表記は翻訳せず、原文のまま表示する
        # -------------------------------------------------------------
        info_browser = QTextBrowser()
        info_browser.setOpenExternalLinks(True)

        about_html = f"""
        <h3>📄 {t('about.license_heading')}</h3>
        <p><b>SPDX-License-Identifier:</b> <a href="https://spdx.org/licenses/Apache-2.0.html">Apache-2.0</a></p>
        <p>[COPYRIGHT_TEXT]</p>

        <hr>
        <h3>📦 {t('about.third_party_heading')}</h3>
        <p>{t('about.third_party_intro')}</p>

        <ul>
            <li>
                <b>Python</b><br>
                ver:3.13<br>
                License: PSF-2.0<br>
            </li>
            <li>
                <b>PySide6 (Qt for Python)</b><br>
                License: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only <br>
                URL: <a href="https://www.qt.io/ja-jp/development/download-open-source">https://www.qt.io</a><br>
            </li>
            <li>
                <b>ijson</b><br>
                License: BSD-3-Clause AND ISC<br>
            </li>
            <li>
                <b>cyclonedx-python-lib</b><br>
                License: <a href="https://spdx.org/licenses/Apache-2.0.html">Apache-2.0</a><br>
            </li>
            <li>
                <b>packageurl-python</b><br>
                License: MIT<br>
            </li>
            <li>
                <b>openpyxl</b><br>
                License: MIT<br>
                Author: Eric Gazoni, Charlie Clark<br>
            </li>
            <li>
                <b>Lucide Icons (https://lucide.dev)</b><br>
                License: ISC License<br>
                Copyright (c) 2026 Lucide Icons and Contributors<br>
            </li>
        </ul>
        <p style="font-size: 11px; color: {tok.text_muted}; margin-top: 15px;">
        {t('about.trademarks')}
        </p>
        """
        # HTML内の特定の文字列 [COPYRIGHT_TEXT] を一元管理の変数に置き換える
        info_browser.setHtml(about_html.replace("[COPYRIGHT_TEXT]", COPYRIGHT))
        layout.addWidget(info_browser)

        # -------------------------------------------------------------
        # フッターエリア（閉じるボタン）
        # -------------------------------------------------------------
        btn_close = QPushButton(t("dialogs.close"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
