# main.py
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 XZ Manj

import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # メインウィンドウの生成と表示
    window = MainWindow()
    window.show()
    
    # Fusionスタイルの強制適用ルーチン
    sys.argv.append("--style")
    sys.argv.append("fusion")
    sys.argv = sys.argv[:1] + ["-style", "fusion"] + sys.argv[1:]
    
    sys.exit(app.exec())
    