# test/test_i18n.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""core/i18n.py とメッセージカタログの整合性テスト（Qt 不要）。 実行: python -m unittest discover -s test -v"""

import ast
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import comparer as cmp
from core import i18n

_PLACEHOLDER = re.compile(r"\{(\w*)\}")


def _catalog(lang):
    i18n.reload_catalogs()
    return i18n.catalog(lang)          # ja.json + ja.*.json を結合したもの


def _used_static_keys():
    """ソース中の t("...") / t_in(lang, "...") のキー（リテラルのものだけ）。 {キー: [場所, ...]}"""
    used = {}
    for folder in ("core", "ui"):
        base = os.path.join(ROOT, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not name.endswith(".py") or (folder == "core" and name == "i18n.py"):
                continue
            path = os.path.join(base, name)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                fname = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                idx = 0 if fname in ("t", "_bi") else 1 if fname == "t_in" else None
                if idx is None or len(node.args) <= idx:
                    continue
                arg = node.args[idx]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    used.setdefault(arg.value, []).append(f"{folder}/{name}:{node.lineno}")
    return used


class CatalogTest(unittest.TestCase):
    def test_same_keys_in_all_languages(self):
        ja, en = set(_catalog("ja")), set(_catalog("en"))
        self.assertEqual(ja - en, set(), "ja にあって en に無いキー")
        self.assertEqual(en - ja, set(), "en にあって ja に無いキー")

    def test_placeholders_match(self):
        ja, en = _catalog("ja"), _catalog("en")
        for key in ja:
            self.assertEqual(sorted(_PLACEHOLDER.findall(ja[key])), sorted(_PLACEHOLDER.findall(en[key])),
                             f"プレースホルダ不一致: {key}")

    def test_no_empty_values(self):
        for lang in ("ja", "en"):
            for key, value in _catalog(lang).items():
                self.assertTrue(value.strip(), f"{lang}: {key} が空です")

    def test_all_literal_keys_used_in_code_exist(self):
        ja = _catalog("ja")
        missing = {k: v for k, v in _used_static_keys().items() if k not in ja}
        self.assertEqual(missing, {}, "カタログに無いキーが使われています")

    def test_dynamic_keys_exist(self):
        ja = _catalog("ja")
        keys = []
        keys += [f"compare.status.{s.value}" for s in cmp.DiffStatus]
        keys += [f"compare.match.label.{m.value}" for m in cmp.MatchKey]
        keys += [f"compare.match.hint.{m.value}" for m in cmp.MatchKey]
        keys += [f"compare.flag.{f}" for f in cmp.ALL_FLAGS]
        keys += [f"compare.version_change.{v}" for v in ("upgrade", "downgrade", "changed")]
        keys += [cmp.FIELD_GROUPS[g][0] for g in cmp.ALL_GROUPS]
        keys += [f"compare.matched.{m}" for m in ("spdxid", "name_version", "name", "purl", "name_fallback")]
        missing = [k for k in keys if k not in ja]
        self.assertEqual(missing, [], "カタログに無いキー（comparer.py の置き換え漏れの可能性）")


class TranslateTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("ja")

    def test_translate_and_params(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("compare.status.added"), "Added")
        self.assertEqual(i18n.t("compare.summary.added", n=3), "Added 3")
        i18n.set_language("ja")
        self.assertEqual(i18n.t("compare.status.added"), "追加")

    def test_t_in_ignores_ui_language(self):
        i18n.set_language("ja")
        self.assertEqual(i18n.t_in("en", "compare.status.added"), "Added")

    def test_missing_key_returns_key_and_bad_params_do_not_raise(self):
        self.assertEqual(i18n.t("no.such.key"), "no.such.key")
        self.assertIn("{n}", i18n.t("compare.summary.added"))          # パラメータ不足でも落ちない

    def test_normalize(self):
        self.assertEqual(i18n.normalize_language("ja_JP"), "ja")
        self.assertEqual(i18n.normalize_language("en-US"), "en")
        self.assertEqual(i18n.normalize_language("fr"), "en")
        self.assertIn(i18n.normalize_language("auto"), ("ja", "en"))

    def test_pseudo(self):
        i18n.set_language("pseudo")
        self.assertTrue(i18n.t("compare.status.added").startswith("[!"))


if __name__ == "__main__":
    unittest.main()
