# core/validator_worker.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 SBOMcraft Project
"""メモリ上の SBOM 辞書をバックグラウンドで検証し、進捗をシグナルで通知するスレッド。
検証ロジックとレポート生成は core/validator.py にある（このクラスは呼び出すだけ）。"""

import html

from PySide6.QtCore import QThread, Signal

from core.i18n import t
from core.validator import validate_sbom


class ValidationWorker(QThread):
    progress_status = Signal(str)    # 状態メッセージ
    progress_percent = Signal(int)   # 0〜100
    finished_report = Signal(dict)   # 検証結果（validate_sbom の戻り値）

    def __init__(self, sbom_data: dict, profile: str = "CISA2026"):
        super().__init__()
        self.sbom_data = sbom_data
        self.profile = profile

    def run(self):
        try:
            result = validate_sbom(
                self.sbom_data, self.profile,
                status=self.progress_status.emit, percent=self.progress_percent.emit,
            )
        except Exception as e:      # 例外で終わると、メニューが無効のまま戻らなくなるため必ず結果を返す
            message = f"{type(e).__name__}: {e}"
            self.progress_status.emit(t("validation.progress.failed", error=message))
            result = {
                "passed": False, "error_packages": [], "doc_errors": [], "doc_warnings": [],
                "profile": self.profile, "elapsed": 0.0,
                "report_html": f"<font color='red'>{html.escape(t('validation.progress.failed_report', error=message))}</font>",
            }
        self.finished_report.emit(result)
