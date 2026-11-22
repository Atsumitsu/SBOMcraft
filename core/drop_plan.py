# core/drop_plan.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""ドラッグ＆ドロップされたファイルをどう扱うかを決める（Qt 非依存・単体テスト可能）。

  1 ファイル / 未読み込み  → OPEN                     通常どおり開く
  1 ファイル / 読み込み済み → ASK_OPEN_OR_COMPARE     新規で開くか、現在の SBOM と比較するかを確認
  2 ファイル / 未読み込み  → COMPARE_TWO              1 つ目を開き、2 つ目と自動で比較する
  2 ファイル / 読み込み済み → CONFIRM_COMPARE_TWO     現在の SBOM を閉じて 2 つを比較してよいか確認
  それ以外（3 つ以上・.json 以外・フォルダ・処理中など） → REJECT（理由つき）
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Sequence, Tuple
from core.i18n import t

MAX_FILES = 2
ALLOWED_EXTENSIONS = (".json",)


class DropKind(str, Enum):
    OPEN = "open"
    ASK_OPEN_OR_COMPARE = "ask_open_or_compare"
    COMPARE_TWO = "compare_two"
    CONFIRM_COMPARE_TWO = "confirm_compare_two"
    REJECT = "reject"


@dataclass(frozen=True)
class DropPlan:
    kind: DropKind
    paths: Tuple[str, ...] = ()
    reason: str = ""            # REJECT のときの理由（ステータスバーに表示する）


def _reject(reason: str) -> DropPlan:
    return DropPlan(DropKind.REJECT, (), reason)


def plan_drop(paths: Sequence[str], has_loaded: bool, busy: bool) -> DropPlan:
    """paths はドロップされたローカルパス（先頭から順に 1 つ目・2 つ目）。ファイルシステムは 2 個以下のときだけ見る。"""
    paths = [p for p in paths if p]
    if busy:
        return _reject(t("drop.reject.busy"))
    if not paths:
        return _reject(t("drop.reject.empty"))
    if len(paths) > MAX_FILES:
        return _reject(t("drop.reject.too_many", max=MAX_FILES, n=len(paths)))
    if any(os.path.isdir(p) for p in paths):
        return _reject(t("drop.reject.folder"))
    if any(not p.lower().endswith(ALLOWED_EXTENSIONS) for p in paths):
        return _reject(t("drop.reject.not_json"))
    if any(not os.path.isfile(p) for p in paths):
        return _reject(t("drop.reject.not_found"))
    if len(paths) == 2 and os.path.normcase(os.path.abspath(paths[0])) == os.path.normcase(os.path.abspath(paths[1])):
        return _reject(t("drop.reject.same_file"))

    paths_t = tuple(paths)
    if len(paths_t) == 1:
        return DropPlan(DropKind.ASK_OPEN_OR_COMPARE if has_loaded else DropKind.OPEN, paths_t)
    return DropPlan(DropKind.CONFIRM_COMPARE_TWO if has_loaded else DropKind.COMPARE_TWO, paths_t)

