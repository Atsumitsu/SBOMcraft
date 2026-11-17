# tests/test_excel_io.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""core/excel_io.py の単体テスト（Qt 不要）。 実行: python -m unittest discover -s tests -v"""

import datetime
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import load_workbook

from core import excel_io as xio


class FakeNode:
    def __init__(self, node_type, properties=None, children=None):
        self.node_type = node_type
        self.properties = properties if properties is not None else {}
        self.children = children or []
        self.spdx_id = self.properties.get("SPDXID", "")
        self.name = self.properties.get("name", "")


def make_pkg(i, **extra):
    props = {
        "SPDXID": f"SPDXRef-Package-{i}",
        "name": f"pkg{i}",
        "versionInfo": "1.10",
        "supplier": "Organization: Example Corp",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "MIT",
        "copyrightText": "Copyright (c) 2026\r\nExample",
        "summary": "=1+1",
        "checksums": [{"algorithm": "SHA1", "checksumValue": "ab12"}],
        "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                          "referenceLocator": f"pkg:generic/pkg{i}@1.10"}],
    }
    props.update(extra)
    return FakeNode("package", props)


def make_root(n=3, ns="http://spdx.org/spdxdocs/test-1", **extra_first):
    doc = FakeNode("document_info", {"name": "TestDoc", "documentNamespace": ns})
    pkgs = [make_pkg(i, **(extra_first if i == 0 else {})) for i in range(n)]
    folder = FakeNode("folder", children=pkgs)
    return FakeNode("root", children=[doc, folder]), pkgs


class ExcelTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "out.xlsx")

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, root, rev=0):
        return xio.export_packages(root, self.path, app_version="0.7.0.0", edit_revision=rev)

    def plan(self, root, **kw):
        return xio.build_changes(root, xio.read_workbook(self.path), **kw)

    def edit_cells(self, edits, sheet="Packages", mutate=None):
        """edits: {(header, row): value}"""
        wb = load_workbook(self.path)
        ws = wb[sheet]
        headers = {c.value: c.column for c in ws[1]}
        for (h, row), v in edits.items():
            ws.cell(row=row, column=headers[h]).value = v
        if mutate:
            mutate(wb)
        wb.save(self.path)

    @staticmethod
    def by_field(plan):
        return {(c.spdx_id, c.field): c for c in plan.changes}


class TestRoundTrip(ExcelTestBase):
    def test_unedited_roundtrip_has_no_changes(self):
        root, _ = make_root(5)
        res = self.export(root)
        self.assertEqual(res.package_count, 5)
        plan = self.plan(root)
        self.assertEqual(plan.changes, [])
        self.assertEqual([i for i in plan.issues if i.level == "error"], [])
        self.assertEqual(plan.rows_matched, 5)

    def test_formula_like_text_stays_text(self):
        root, _ = make_root(1)
        self.export(root)
        ws = load_workbook(self.path)["Packages"]
        headers = {c.value: c.column for c in ws[1]}
        cell = ws.cell(row=2, column=headers["summary"])
        self.assertEqual(cell.value, "=1+1")
        self.assertEqual(cell.data_type, "s")

    def test_version_text_preserved_and_text_format(self):
        root, _ = make_root(1)
        self.export(root)
        ws = load_workbook(self.path)["Packages"]
        headers = {c.value: c.column for c in ws[1]}
        cell = ws.cell(row=2, column=headers["versionInfo"])
        self.assertEqual(cell.value, "1.10")
        self.assertEqual(cell.number_format, "@")

    def test_meta_sheet_and_active_sheet(self):
        root, _ = make_root(2)
        self.export(root, rev=7)
        wb = load_workbook(self.path)
        self.assertEqual(wb.sheetnames, ["_meta", "Packages"])
        self.assertEqual(wb.active.title, "Packages")
        parsed = xio.read_workbook(self.path)
        self.assertEqual(parsed.meta["formatVersion"], "1")
        self.assertEqual(parsed.meta["editRevision"], "7")
        self.assertEqual(parsed.meta["packageCount"], "2")

    def test_nested_keys_not_exported(self):
        root, _ = make_root(1)
        self.export(root)
        parsed = xio.read_workbook(self.path)
        for k in ("checksums", "externalRefs"):
            self.assertNotIn(k, parsed.headers)

    def test_unknown_scalar_key_gets_column_and_roundtrips(self):
        root, pkgs = make_root(2, customKey="abc", customNum=5)
        self.export(root)
        parsed = xio.read_workbook(self.path)
        self.assertIn("customKey", parsed.headers)
        self.assertIn("customNum", parsed.headers)
        self.assertEqual(self.plan(root).changes, [])

    def test_too_long_text_is_ignored_on_import(self):
        root, pkgs = make_root(1, description="x" * 40000)
        self.export(root)
        plan = self.plan(root)
        self.assertEqual(plan.changes, [])

    def test_illegal_control_chars_do_not_break_export_or_roundtrip(self):
        root, _ = make_root(1, comment="a\x0bb\x01c")
        self.export(root)
        self.assertEqual(self.plan(root).changes, [])

    def test_empty_packages(self):
        root, _ = make_root(0)
        res = self.export(root)
        self.assertEqual(res.package_count, 0)
        plan = self.plan(root)
        self.assertEqual(plan.changes, [])


class TestEdits(ExcelTestBase):
    def setUp(self):
        super().setUp()
        self.root, self.pkgs = make_root(3)
        self.export(self.root)

    def test_set_add_delete(self):
        self.edit_cells({
            ("name", 2): "renamed",                      # set
            ("originator", 2): "Person: Taro (t@e.com)",  # add（元は未設定）
            ("licenseConcluded", 3): None,               # delete
        })
        plan = self.plan(self.root)
        ch = self.by_field(plan)
        self.assertEqual(ch[("SPDXRef-Package-0", "name")].op, "set")
        self.assertEqual(ch[("SPDXRef-Package-0", "name")].new, "renamed")
        self.assertEqual(ch[("SPDXRef-Package-0", "originator")].op, "add")
        self.assertEqual(ch[("SPDXRef-Package-1", "licenseConcluded")].op, "delete")
        self.assertEqual(len(plan.changes), 3)
        self.assertEqual(plan.packages_changed, 2)

    def test_bool_change_and_enum_and_date(self):
        self.edit_cells({
            ("filesAnalyzed", 2): "true",
            ("primaryPackagePurpose", 2): "library",
            ("releaseDate", 2): "2026-01-31T00:00:00Z",
        })
        ch = self.by_field(self.plan(self.root))
        self.assertIs(ch[("SPDXRef-Package-0", "filesAnalyzed")].new, True)
        self.assertEqual(ch[("SPDXRef-Package-0", "primaryPackagePurpose")].new, "LIBRARY")
        self.assertEqual(ch[("SPDXRef-Package-0", "releaseDate")].new, "2026-01-31T00:00:00Z")

    def test_invalid_values_are_errors_and_not_applied(self):
        self.edit_cells({
            ("filesAnalyzed", 2): "maybe",
            ("primaryPackagePurpose", 2): "WIDGET",
            ("releaseDate", 2): "2026/01/31",
            ("name", 3): None,
            ("downloadLocation", 3): "",
        })
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])
        self.assertEqual(plan.error_count, 5)

    def test_supplier_format_is_warning_but_applied(self):
        self.edit_cells({("supplier", 2): "Example Corp"})
        plan = self.plan(self.root)
        self.assertEqual(len(plan.changes), 1)
        self.assertTrue(any(i.level == "warning" and "supplier" in i.message for i in plan.issues))

    def test_surrounding_whitespace_warns(self):
        self.edit_cells({("name", 2): "pkg0 "})
        plan = self.plan(self.root)
        self.assertEqual(len(plan.changes), 1)
        self.assertTrue(any("空白" in i.message for i in plan.issues))

    def test_numeric_cell_for_text_field_warns(self):
        self.edit_cells({("versionInfo", 2): 1.1})        # 貼り付けで 1.10 が 1.1 になった想定
        plan = self.plan(self.root)
        ch = self.by_field(plan)[("SPDXRef-Package-0", "versionInfo")]
        self.assertEqual(ch.new, "1.1")
        self.assertTrue(any("数値" in i.message for i in plan.issues))

    def test_numeric_cell_equal_to_old_text_is_no_change(self):
        root, _ = make_root(1, versionInfo="2")
        self.export(root)
        self.edit_cells({("versionInfo", 2): 2})
        self.assertEqual(self.plan(root).changes, [])

    def test_datetime_cell_for_date_field(self):
        self.edit_cells({("releaseDate", 2): datetime.datetime(2026, 2, 3, 4, 5, 6)})
        ch = self.by_field(self.plan(self.root))[("SPDXRef-Package-0", "releaseDate")]
        self.assertEqual(ch.new, "2026-02-03T04:05:06Z")

    def test_crlf_text_is_not_flagged_unless_changed(self):
        self.assertEqual(self.plan(self.root).changes, [])
        self.edit_cells({("copyrightText", 2): "changed\nline"})
        self.assertEqual(len(self.plan(self.root).changes), 1)

    def test_formula_with_cached_value_is_used_uncached_is_error(self):
        self.edit_cells({("name", 2): '=UPPER("abc")'})     # openpyxl は計算結果を保存しない
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])
        self.assertTrue(any("数式" in i.message and i.level == "error" for i in plan.issues))


class TestStructure(ExcelTestBase):
    def setUp(self):
        super().setUp()
        self.root, self.pkgs = make_root(4)
        self.export(self.root)

    def test_shuffled_rows_and_deleted_columns(self):
        def mutate(wb):
            ws = wb["Packages"]
            headers = {c.value: c.column for c in ws[1]}
            ws.delete_cols(headers["licenseConcluded"])      # 列削除 → 変更なし扱い
            rows = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
            rows.reverse()                                    # 行の並べ替え
            for r_idx, vals in enumerate(rows, start=2):
                for c_idx, v in enumerate(vals, start=1):
                    ws.cell(row=r_idx, column=c_idx).value = v
        self.edit_cells({}, mutate=mutate)
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])
        self.assertEqual(plan.rows_matched, 4)

    def test_unknown_spdxid_and_duplicates(self):
        def mutate(wb):
            ws = wb["Packages"]
            ws.cell(row=2, column=1).value = "SPDXRef-Nope"          # 未知
            ws.cell(row=3, column=1).value = "SPDXRef-Package-3"      # Excel 内で重複
        self.edit_cells({}, mutate=mutate)
        plan = self.plan(self.root)
        msgs = [i.message for i in plan.issues]
        self.assertTrue(any("存在しない SPDXID" in m for m in msgs))
        self.assertTrue(any("重複" in m for m in msgs))
        self.assertEqual(plan.changes, [])

    def test_duplicate_spdxid_in_sbom_is_error(self):
        self.pkgs[1].properties["SPDXID"] = self.pkgs[0].properties["SPDXID"]
        self.edit_cells({("name", 2): "x"})
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])
        self.assertTrue(any("SBOM 内で" in i.message for i in plan.issues))

    def test_unrecognized_column_warns(self):
        def mutate(wb):
            ws = wb["Packages"]
            ws.cell(row=1, column=ws.max_column + 1).value = "myNote"
            ws.cell(row=2, column=ws.max_column).value = "memo"
        self.edit_cells({}, mutate=mutate)
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])
        self.assertTrue(any("myNote" in i.message for i in plan.issues))

    def test_container_value_under_scalar_column_is_never_touched(self):
        self.pkgs[0].properties["name"] = {"weird": 1}            # 不正だが入れ子
        self.edit_cells({("name", 2): "x"})
        ch = self.by_field(self.plan(self.root))
        self.assertNotIn(("SPDXRef-Package-0", "name"), ch)

    def test_missing_spdxid_header_is_fatal(self):
        def mutate(wb):
            wb["Packages"].cell(row=1, column=1).value = "ID"
        self.edit_cells({}, mutate=mutate)
        with self.assertRaises(xio.WorkbookFormatError):
            xio.read_workbook(self.path)

    def test_missing_packages_sheet_is_fatal(self):
        def mutate(wb):
            wb["Packages"].title = "Other"
        self.edit_cells({}, mutate=mutate)
        with self.assertRaises(xio.WorkbookFormatError):
            xio.read_workbook(self.path)

    def test_reject_wrong_extension_and_non_zip(self):
        bad = os.path.join(self.tmp.name, "x.xlsm")
        with open(bad, "wb") as f:
            f.write(b"x")
        with self.assertRaises(xio.WorkbookFormatError):
            xio.read_workbook(bad)
        bad2 = os.path.join(self.tmp.name, "x.xlsx")
        with open(bad2, "wb") as f:
            f.write(b"not a zip")
        with self.assertRaises(xio.WorkbookFormatError):
            xio.read_workbook(bad2)

    def test_meta_warnings(self):
        other, _ = make_root(4, ns="http://spdx.org/spdxdocs/other")
        plan = self.plan(other, current_revision=3)
        msgs = " ".join(i.message for i in plan.issues)
        self.assertIn("documentNamespace", msgs)
        self.assertIn("編集が行われています", msgs)

    def test_cancel(self):
        parsed = xio.read_workbook(self.path)
        with self.assertRaises(xio.ImportCanceled):
            xio.build_changes(self.root, parsed, should_cancel=lambda: True)


class TestApply(ExcelTestBase):
    def test_apply_updates_only_changed_fields_and_keeps_nested(self):
        root, pkgs = make_root(2)
        self.export(root)
        self.edit_cells({("name", 2): "renamed", ("summary", 2): None,
                         ("originator", 3): "Organization: X"})
        plan = self.plan(root)
        keys_before = list(pkgs[0].properties.keys())
        checks_before = pkgs[0].properties["checksums"]
        res = xio.apply_changes(plan.changes)
        self.assertEqual(len(res.applied), 3)
        self.assertEqual(len(res.nodes), 2)
        self.assertEqual(pkgs[0].properties["name"], "renamed")
        self.assertNotIn("summary", pkgs[0].properties)
        self.assertEqual(pkgs[1].properties["originator"], "Organization: X")
        self.assertIs(pkgs[0].properties["checksums"], checks_before)
        self.assertEqual([k for k in keys_before if k != "summary"],
                         [k for k in pkgs[0].properties.keys()])
        # 適用後に再出力 → 再取り込みで差分ゼロ
        self.export(root)
        self.assertEqual(self.plan(root).changes, [])

    def test_conflict_is_skipped(self):
        root, pkgs = make_root(1)
        self.export(root)
        self.edit_cells({("name", 2): "from-excel"})
        plan = self.plan(root)
        pkgs[0].properties["name"] = "changed-in-app"
        res = xio.apply_changes(plan.changes)
        self.assertEqual(res.applied, [])
        self.assertEqual(len(res.skipped), 1)
        self.assertEqual(pkgs[0].properties["name"], "changed-in-app")


class TestPerformance(ExcelTestBase):
    def test_5000_packages(self):
        root, _ = make_root(5000)
        t0 = time.time()
        self.export(root)
        t1 = time.time()
        plan = self.plan(root)
        t2 = time.time()
        self.assertEqual(plan.changes, [])
        print(f"\n  export 5000 pkgs: {t1 - t0:.1f}s / read+diff: {t2 - t1:.1f}s")
        self.assertLess(t1 - t0, 30)
        self.assertLess(t2 - t1, 30)


if __name__ == "__main__":
    unittest.main()
