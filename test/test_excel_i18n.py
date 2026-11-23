# test/test_excel_i18n.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""Excel 連携の多言語化テスト（Qt 不要）。 実行: python -m unittest discover -s test -v"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openpyxl import load_workbook

from core import excel_io as xio
from core import i18n
from test_excel_io import ExcelTestBase, make_root


def setUpModule():
    i18n.set_language("ja")


def tearDownModule():
    i18n.set_language("ja")


def _all_text(ws):
    out = []
    for row in ws.iter_rows(values_only=True):
        out.extend(str(v) for v in row if v)
    return "\n".join(out)


class CatalogKeysTest(unittest.TestCase):
    def test_help_keys_and_guide_ids_exist_in_both_languages(self):
        specs = list(xio.PACKAGE_FIELD_SPECS)
        for ls in xio.LIST_SHEET_SPECS:
            specs += list(ls.columns) + xio._list_sheet_columns(ls)
        keys = {s.help for s in specs if s.help} | {"excel.help.custom"}
        keys |= {f"excel.guide.{gid}" for gid in xio._GUIDE_IDS}
        keys |= {n[1:] for _, _, n in xio._FORMAT_EXAMPLES if n.startswith("@")}
        keys |= {"excel.meta.title", "excel.meta.guide_heading", "excel.meta.examples_heading",
                 "excel.dv.choose", "excel.dv.free", "excel.dv.title_error", "excel.dv.title_confirm"}
        for lang in ("ja", "en"):
            cat = i18n.catalog(lang)
            for k in keys:
                self.assertIn(k, cat, f"{lang}: {k}")


class BilingualExportTest(ExcelTestBase):
    def _check_bilingual(self):
        wb = load_workbook(self.path)
        meta = _all_text(wb["_meta"])
        self.assertIn("編集ガイド", meta)
        self.assertIn("Editing guide", meta)
        self.assertIn("【日本語】", meta)
        self.assertIn("[English]", meta)
        ws = wb["Packages"]
        headers = {c.value: c for c in ws[1]}
        comment = headers["name"].comment.text
        self.assertIn("パッケージ名", comment)
        self.assertIn("Package name", comment)
        for dv in ws.data_validations.dataValidation:        # Excel の上限
            self.assertLessEqual(len(dv.error), 255)
            self.assertLessEqual(len(dv.errorTitle), 32)

    def test_export_is_bilingual_regardless_of_ui_language(self):
        root, _ = make_root(2)
        for lang in ("ja", "en"):
            i18n.set_language(lang)
            self.export(root)
            self._check_bilingual()
        i18n.set_language("ja")

    def test_headings_are_not_translated(self):
        root, _ = make_root(1)
        i18n.set_language("en")
        self.export(root)
        parsed = xio.read_workbook(self.path)
        self.assertIn("SPDXID", parsed.headers)
        self.assertIn("versionInfo", parsed.headers)
        i18n.set_language("ja")

    def test_roundtrip_has_no_changes_in_english(self):
        root, _ = make_root(3)
        i18n.set_language("en")
        self.export(root)
        self.assertEqual(self.plan(root).changes, [])
        i18n.set_language("ja")


class NewlineTest(ExcelTestBase):
    def test_exported_cells_contain_no_cr(self):
        """CR を書かない（環境によって XML 経由で改行が増減するのを避けるため）。CRLF の元データも往復で差分にならない。"""
        root, _ = make_root(2)                       # copyrightText に "\r\n" を含む
        self.export(root)
        ws = load_workbook(self.path)["Packages"]
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if isinstance(v, str):
                    self.assertNotIn("\r", v)
        self.assertEqual(self.plan(root).changes, [])


class MarkerTest(ExcelTestBase):
    def test_new_marker_is_language_independent(self):
        self.assertIn("TRUNCATED", xio.TOO_LONG_MARKER)
        self.assertIn("未出力", xio.TOO_LONG_MARKER)

    def test_legacy_marker_is_ignored_on_scalar(self):
        root, _ = make_root(1, description="x" * 40000)
        self.export(root)
        self.edit_cells({("description", 2): xio.LEGACY_TOO_LONG_MARKERS[0]})
        self.assertEqual(self.plan(root).changes, [])

    def test_legacy_marker_is_normalized_in_lists(self):
        root, pkgs = make_root(1)
        pkgs[0].properties["externalRefs"][0]["comment"] = "y" * 40000
        self.export(root)
        wb = load_workbook(self.path)
        ws = wb["ExternalRefs"]
        h = {c.value: c.column for c in ws[1]}
        ws.cell(row=2, column=h["comment"]).value = xio.LEGACY_TOO_LONG_MARKERS[0]
        wb.save(self.path)
        plan = self.plan(root)
        self.assertEqual(plan.changes, [])
        self.assertEqual([i for i in plan.issues if i.level == "error"], [])


class MessageLanguageTest(ExcelTestBase):
    def tearDown(self):
        i18n.set_language("ja")
        super().tearDown()

    def test_error_messages_follow_ui_language(self):
        bad = os.path.join(self.tmp.name, "x.xlsm")
        with open(bad, "wb") as f:
            f.write(b"x")
        i18n.set_language("en")
        with self.assertRaises(xio.WorkbookFormatError) as cm:
            xio.read_workbook(bad)
        self.assertIn("Only .xlsx", str(cm.exception))
        i18n.set_language("ja")
        with self.assertRaises(xio.WorkbookFormatError) as cm:
            xio.read_workbook(bad)
        self.assertIn("対応しているのは .xlsx のみ", str(cm.exception))

    def test_issue_messages_follow_ui_language(self):
        root, _ = make_root(2)
        self.export(root)
        self.edit_cells({("filesAnalyzed", 2): "maybe"})
        i18n.set_language("en")
        plan = self.plan(root)
        self.assertTrue(any("Enter true or false" in i.message for i in plan.issues))
        i18n.set_language("ja")
        plan = self.plan(root)
        self.assertTrue(any("true または false" in i.message for i in plan.issues))


if __name__ == "__main__":
    unittest.main()
