# main.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from ui import theme
from ui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Fusion スタイル・パレット・QSS・フォントを適用（ウィンドウ生成より前に行う）
    settings = QSettings("MyCompany", "SBOMViewer")
    theme.apply_fonts(app)
    theme.apply_theme(app, str(settings.value("theme_mode", "auto")))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
