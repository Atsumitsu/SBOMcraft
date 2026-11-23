# core/excel_worker.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""Excel 取り込み（読み込み + 差分作成）をバックグラウンドで行うワーカー。ParseWorker と同じ作法。"""

from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.excel_io import (
    ImportCanceled, WorkbookFormatError, build_changes, read_workbook,
)
from core.i18n import t


class ExcelImportWorker(QObject):
    finished = Signal(object)    # ImportPlan（キャンセル時は None）
    error = Signal(str)
    progress = Signal(int)       # 0〜100

    def __init__(self, root_node, path: str, current_revision: Optional[int] = None):
        super().__init__()
        self.root_node = root_node
        self.path = path
        self.current_revision = current_revision
        self._is_canceled = False

    def cancel(self):
        """メイン側から DirectConnection で呼ぶこと（run 中はこのスレッドのイベントループが回らないため）。"""
        self._is_canceled = True

    def run(self):
        try:
            parsed = read_workbook(self.path)
            if self._is_canceled:
                self.finished.emit(None)
                return
            plan = build_changes(
                self.root_node, parsed,
                current_revision=self.current_revision,
                progress=self.progress.emit,
                should_cancel=lambda: self._is_canceled,
            )
            self.finished.emit(plan)
        except ImportCanceled:
            self.finished.emit(None)
        except WorkbookFormatError as e:
            self.error.emit(str(e))
        except PermissionError:
            self.error.emit(t("excel.err.permission"))
        except Exception as e:                       # 想定外もダイアログで通知できるようにする
            self.error.emit(f"{type(e).__name__}: {e}")
