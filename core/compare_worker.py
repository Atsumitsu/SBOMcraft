# core/compare_worker.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""SBOM 比較（ファイルの読み込み + 差分計算）をバックグラウンドで行うワーカー。ExcelImportWorker と同じ作法。"""

from typing import Iterable, Optional, Union

from PySide6.QtCore import QObject, Signal

from core.comparer import CompareCanceled, MatchKey, compare
from core.i18n import t
from core.parser import ParseWorker, SBOMNode

Source = Union[SBOMNode, str]       # 読み込み済みのルートノード、または SBOM JSON のパス


class CompareWorker(QObject):
    finished = Signal(object)       # CompareResult（キャンセル時は None）
    error = Signal(str)
    progress = Signal(int)          # 0〜100

    def __init__(self, source_a: Source, label_a: str, source_b: Source, label_b: str,
                 mode: MatchKey = MatchKey.AUTO, groups: Optional[Iterable[str]] = None):
        super().__init__()
        self.source_a, self.label_a = source_a, label_a
        self.source_b, self.label_b = source_b, label_b
        self.mode = mode
        self.groups = list(groups) if groups is not None else None
        self._is_canceled = False
        self._parser: Optional[ParseWorker] = None

    def cancel(self):
        """メイン側から DirectConnection で呼ぶこと（run 中はこのスレッドのイベントループが回らないため）。"""
        self._is_canceled = True
        if self._parser is not None:
            self._parser.cancel()

    # -- 内部 ---------------------------------------------------------------

    def _load(self, source: Source, label: str, base: float, span: float) -> Optional[SBOMNode]:
        """ファイルなら ParseWorker.run() をこのスレッドで直接呼んで読み込む（既存パーサをそのまま再利用）。"""
        if not isinstance(source, str):
            return source
        holder = {}
        parser = ParseWorker(source)
        parser.progress.connect(lambda p: self.progress.emit(int(base + span * p / 100)))
        parser.finished.connect(lambda root: holder.__setitem__("root", root))
        parser.error.connect(lambda msg: holder.__setitem__("error", msg))
        self._parser = parser
        if self._is_canceled:
            return None
        parser.run()
        self._parser = None
        if "error" in holder:
            raise ValueError(t("compare.worker.load_failed", label=label, error=holder["error"]))
        return holder.get("root")            # キャンセル時は None

    def run(self):
        try:
            n_files = sum(isinstance(s, str) for s in (self.source_a, self.source_b))
            parse_span = 70.0 if n_files else 0.0
            per_file = parse_span / n_files if n_files else 0.0

            base = 0.0
            roots = []
            for source, label in ((self.source_a, self.label_a), (self.source_b, self.label_b)):
                root = self._load(source, label, base, per_file)
                if root is None or self._is_canceled:
                    self.finished.emit(None)
                    return
                if isinstance(source, str):
                    base += per_file
                roots.append(root)

            result = compare(
                roots[0], roots[1], self.mode, self.groups,
                label_a=self.label_a, label_b=self.label_b,
                progress=lambda p: self.progress.emit(int(parse_span + (100 - parse_span) * p / 100)),
                should_cancel=lambda: self._is_canceled,
            )
            self.finished.emit(result)
        except CompareCanceled:
            self.finished.emit(None)
        except PermissionError:
            self.error.emit(t("compare.worker.permission"))
        except Exception as e:                       # 想定外もダイアログで通知できるようにする
            self.error.emit(f"{type(e).__name__}: {e}")
