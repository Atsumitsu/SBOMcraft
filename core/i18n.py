# core/i18n.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""
UI 文字列の多言語化（Qt 非依存・標準ライブラリのみ）。

* メッセージ ID（"compare.status.added" など）→ 文字列 の対応を locales/<lang>.json に持つ（フラットな JSON）。
* t(key, **params) が現在の言語で文字列を返す。{name} 形式のプレースホルダは str.format で置換する。
* 解決順: 現在の言語 → FALLBACK_LANGUAGE(en) → DEFAULT_LANGUAGE(ja) → キー文字列そのもの
  （キーが画面にそのまま出るので、翻訳漏れに気付ける）。
* set_language() は起動時（main.py）に 1 回だけ呼ぶ運用（再起動で反映）。スレッドからは t() の読み取りだけを行う。
* t_in(lang, key) は UI 言語に関係なく指定言語で取得する（Excel の日英併記ガイドなどで使う）。

注意: モジュール直下・クラス属性で t() を呼ばないこと（import 時に言語が固定される）。
      関数の中、または「キー」だけを保持して表示時に t() を呼ぶ。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Tuple

DEFAULT_LANGUAGE = "ja"        # 原文の言語。set_language() を呼ばない場合（単体テストなど）もこれ
FALLBACK_LANGUAGE = "en"
PSEUDO_LANGUAGE = "pseudo"     # 直書き文字列の取りこぼし確認用（開発時のみ）

# 言語名は「その言語自身の表記」で出す（翻訳しない）
LANGUAGE_NAMES: Dict[str, str] = {"ja": "日本語", "en": "English"}

# Windows の言語 ID（下位 10 bit）→ 言語コード
_PRIMARY_LANG_IDS = {0x11: "ja", 0x09: "en"}

_current: str = DEFAULT_LANGUAGE
_catalogs: Dict[str, Dict[str, str]] = {}


# ---------------------------------------------------------------------------
# カタログの読み込み
# ---------------------------------------------------------------------------

def _locales_dir() -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "locales")        # PyInstaller: --add-data "locales;locales"


def _load(lang: str) -> Dict[str, str]:
    cat = _catalogs.get(lang)
    if cat is None:
        path = os.path.join(_locales_dir(), f"{lang}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cat = {k: v for k, v in data.items() if isinstance(v, str) and not k.startswith("_")}
        except (OSError, ValueError):
            cat = {}
        _catalogs[lang] = cat
    return cat


def reload_catalogs() -> None:
    _catalogs.clear()


# ---------------------------------------------------------------------------
# 言語の選択
# ---------------------------------------------------------------------------

def available_languages() -> List[Tuple[str, str]]:
    """[("ja", "日本語"), ("en", "English")]（メニュー用）"""
    return list(LANGUAGE_NAMES.items())


def detect_system_language() -> str:
    """OS の表示言語。対応していない言語は英語。"""
    if sys.platform == "win32":
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return _PRIMARY_LANG_IDS.get(lang_id & 0x3FF, "en")
        except Exception:
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value:
            return "ja" if value.lower().startswith("ja") else "en"
    return "en"


def normalize_language(lang: str) -> str:
    """"auto" / "ja_JP" / "en-US" などを、対応している言語コードに丸める。"""
    code = (lang or "auto").strip().lower().replace("-", "_")
    if code == "auto":
        return detect_system_language()
    if code == PSEUDO_LANGUAGE:
        return code
    code = code.split("_", 1)[0]
    return code if code in LANGUAGE_NAMES else FALLBACK_LANGUAGE


def set_language(lang: str) -> str:
    """言語を設定し、実際に使う言語コードを返す。"""
    global _current
    _current = normalize_language(lang)
    return _current


def current_language() -> str:
    return _current


# ---------------------------------------------------------------------------
# 翻訳
# ---------------------------------------------------------------------------

def _lookup(lang: str, key: str):
    for code in (lang, FALLBACK_LANGUAGE, DEFAULT_LANGUAGE):
        text = _load(code).get(key)
        if text is not None:
            return text
    return None


def t_in(lang: str, key: str, **params) -> str:
    """指定した言語で文字列を取得する（UI 言語とは無関係）。"""
    text = _lookup(lang, key)
    if text is None:
        return key
    if params:
        try:
            text = text.format(**params)
        except (KeyError, IndexError, ValueError):
            pass                                     # プレースホルダの不整合で落とさない（テストで検出する）
    return text


_PSEUDO_MAP = str.maketrans("aeiouAEIOU", "àéîöüÀÉÎÖÜ")


def t(key: str, **params) -> str:
    """現在の言語で文字列を取得する。"""
    if _current == PSEUDO_LANGUAGE:
        return "[!" + t_in(FALLBACK_LANGUAGE, key, **params).translate(_PSEUDO_MAP) + "!]"
    return t_in(_current, key, **params)
