# main.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import sys
from PySide6.QtCore import QSettings, QTranslator, QLibraryInfo
from PySide6.QtWidgets import QApplication

from core import i18n
from ui import theme
from ui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    settings = QSettings("MyCompany", "SBOMViewer")

    lang = i18n.set_language(str(settings.value("language", "auto")))
    qt_tr = QTranslator(app)       # QFileDialog / QMessageBox 標準ボタンなど。en は組み込みなので load 不要
    if qt_tr.load(f"qtbase_{lang}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt_tr)

    theme.apply_fonts(app, lang=lang)
    theme.apply_theme(app, str(settings.value("theme_mode", "auto")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())