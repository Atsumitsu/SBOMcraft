# tests/test_excel_io_lists.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""Phase 2: Checksums / ExternalRefs シートのテスト。 実行: python -m unittest discover -s tests -v"""

import copy
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openpyxl import load_workbook

from core import excel_io as xio
from test_excel_io import ExcelTestBase, FakeNode, make_pkg

SHA1 = "a" * 40
SHA1_B = "d" * 40
SHA256 = "b" * 64
SHA256_B = "e" * 64
SHA512 = "c" * 128
PURL0 = "pkg:pypi/pkg0@1.0"
PURL0B = "pkg:pypi/pkg0b@2.0"
CPE0 = "cpe:2.3:a:vendor:pkg0:1.0:*:*:*:*:*:*:*"


def make_list_root():
    """pkg0: 複数要素 / pkg1: 1要素 + 空の externalRefs / pkg2: キー無し / pkg3: 非標準な checksums"""
    p0 = make_pkg(0,
                  checksums=[{"algorithm": "SHA1", "checksumValue": SHA1},
                             {"algorithm": "SHA256", "checksumValue": SHA256}],
                  externalRefs=[{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                                 "referenceLocator": PURL0},
                                {"referenceCategory": "SECURITY", "referenceType": "cpe23Type",
                                 "referenceLocator": CPE0, "comment": "NVD"}])
    p1 = make_pkg(1, checksums=[{"algorithm": "SHA256", "checksumValue": SHA256}], externalRefs=[])
    p2 = make_pkg(2)
    del p2.properties["checksums"], p2.properties["externalRefs"]
    p3 = make_pkg(3, checksums={"weird": "dict"})
    doc = FakeNode("document_info", {"name": "TestDoc", "documentNamespace": "http://spdx.org/spdxdocs/test-1"})
    root = FakeNode("root", children=[doc, FakeNode("folder", children=[p0, p1, p2, p3])])
    return root, [p0, p1, p2, p3]


class ListBase(ExcelTestBase):
    def setUp(self):
        super().setUp()
        self.root, self.pkgs = make_list_root()
        self.export(self.root)

    # --- openpyxl での Excel 編集ヘルパー ---
    def wb(self):
        return load_workbook(self.path)

    def save(self, wb):
        wb.save(self.path)

    @staticmethod
    def hdr(ws):
        return {c.value: c.column for c in ws[1]}

    def rows_of(self, ws, sid):
        col = self.hdr(ws)["SPDXID"]
        return [r for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=col).value == sid]

    def put(self, ws, row, **vals):
        h = self.hdr(ws)
        for k, v in vals.items():
            ws.cell(row=row, column=h[k]).value = v

    def add_row(self, ws, sid, **vals):
        row = ws.max_row + 1
        self.put(ws, row, SPDXID=sid, **vals)
        return row

    def list_changes(self, plan, field):
        return {c.spdx_id: c for c in plan.changes if c.kind == "list" and c.field == field}

    def errors(self, plan):
        return [i for i in plan.issues if i.level == "error"]

    def warnings(self, plan):
        return [i for i in plan.issues if i.level == "warning"]


class TestListExport(ListBase):
    def test_sheets_columns_and_placeholder_rows(self):
        wb = self.wb()
        self.assertEqual(wb.sheetnames, ["_meta", "Packages", "Checksums", "ExternalRefs"])
        ws = wb["Checksums"]
        self.assertEqual([c.value for c in ws[1]], ["SPDXID", "name", "algorithm", "checksumValue"])
        self.assertEqual(len(self.rows_of(ws, "SPDXRef-Package-0")), 2)
        self.assertEqual(len(self.rows_of(ws, "SPDXRef-Package-1")), 1)
        ph = self.rows_of(ws, "SPDXRef-Package-2")                   # キー無し → 入力用の空行
        self.assertEqual(len(ph), 1)
        self.assertIsNone(ws.cell(row=ph[0], column=3).value)
        self.assertEqual(self.rows_of(ws, "SPDXRef-Package-3"), [])  # 非標準 → 出さない
        self.assertEqual(ws.cell(row=self.rows_of(ws, "SPDXRef-Package-0")[0], column=2).value, "pkg0")
        ws = wb["ExternalRefs"]
        self.assertEqual([c.value for c in ws[1]],
                         ["SPDXID", "name", "referenceCategory", "referenceType", "referenceLocator", "comment"])
        self.assertEqual(len(self.rows_of(ws, "SPDXRef-Package-0")), 2)
        self.assertEqual(len(self.rows_of(ws, "SPDXRef-Package-1")), 1)   # 空配列 → 空行

    def test_export_result_counts(self):
        res = self.export(self.root)
        # 要素数（空行は数えない）: ExternalRefs は pkg0 の 2 件 + pkg3 の 1 件
        self.assertEqual(res.list_rows, {"Checksums": 3, "ExternalRefs": 3})

    def test_all_text_format_and_validations(self):
        wb = self.wb()
        ws = wb["Checksums"]
        cell = ws.cell(row=2, column=4)
        self.assertEqual(cell.number_format, "@")
        self.assertEqual(ws.freeze_panes, "C2")
        dvs = {str(d.sqref): d for d in ws.data_validations.dataValidation}
        alg = next(d for k, d in dvs.items() if k.startswith("C2:"))
        self.assertIn("SHA256", alg.formula1)
        last = int(str(alg.sqref).split(":")[1][1:])
        self.assertGreater(last, ws.max_row + 500)                   # 行追加に備えて先まで広げている
        ws = wb["ExternalRefs"]
        formulas = [d.formula1 for d in ws.data_validations.dataValidation]
        self.assertTrue(any("PACKAGE-MANAGER" in f for f in formulas))
        self.assertTrue(any("purl" in f for f in formulas))          # referenceType の候補
        for d in ws.data_validations.dataValidation:
            self.assertLessEqual(len(d.error), 255)
            self.assertLessEqual(len(d.formula1), 255)

    def test_formula_like_and_long_text_in_lists(self):
        root, pkgs = make_list_root()
        pkgs[0].properties["externalRefs"][1]["comment"] = "=1+1"
        pkgs[0].properties["externalRefs"][0]["comment"] = "x" * 40000
        self.export(root)
        ws = self.wb()["ExternalRefs"]
        row = self.rows_of(ws, "SPDXRef-Package-0")[1]
        cell = ws.cell(row=row, column=self.hdr(ws)["comment"])
        self.assertEqual((cell.value, cell.data_type), ("=1+1", "s"))
        self.assertEqual(self.plan(root).changes, [])                # マーカーも含め往復で差分なし


class TestListRoundTrip(ListBase):
    def test_unedited_roundtrip_has_no_changes(self):
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])
        self.assertEqual(self.errors(plan), [])
        self.assertEqual(self.warnings(plan), [])
        # pkg3 は非標準なのでシートに出ておらず、突合対象にもならない
        self.assertEqual(plan.list_stats, {"Checksums": 3, "ExternalRefs": 4})

    def test_sorting_rows_is_not_a_change(self):
        wb = self.wb()
        for name in ("Checksums", "ExternalRefs"):
            ws = wb[name]
            rows = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
            rows.reverse()
            for ri, vals in enumerate(rows, start=2):
                for ci, v in enumerate(vals, start=1):
                    ws.cell(row=ri, column=ci).value = v
        self.save(wb)
        self.assertEqual(self.plan(self.root).changes, [])

    def test_name_column_is_ignored(self):
        wb = self.wb()
        ws = wb["Checksums"]
        self.put(ws, 2, name="totally different")
        self.save(wb)
        self.assertEqual(self.plan(self.root).changes, [])

    def test_missing_child_sheets_means_no_change(self):
        wb = self.wb()
        del wb["Checksums"]
        del wb["ExternalRefs"]
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])
        self.assertEqual(self.errors(plan), [])

    def test_missing_optional_column_is_excluded_from_comparison(self):
        wb = self.wb()
        ws = wb["ExternalRefs"]
        ws.delete_cols(self.hdr(ws)["comment"])
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])                           # コメント付きの要素も差分にならない

    def test_case_and_whitespace_of_enums_normalized(self):
        wb = self.wb()
        ws = wb["Checksums"]
        row = self.rows_of(ws, "SPDXRef-Package-1")[0]
        self.put(ws, row, algorithm=" sha256 ")
        self.save(wb)
        self.assertEqual(self.plan(self.root).changes, [])


class TestListEdits(ListBase):
    def test_add_entry_by_new_row(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="SHA512", checksumValue=SHA512)
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(self.errors(plan), [])
        ch = self.list_changes(plan, "checksums")["SPDXRef-Package-0"]
        self.assertEqual((ch.op, len(ch.added), len(ch.removed)), ("set", 1, 0))
        self.assertEqual([e["algorithm"] for e in ch.new], ["SHA1", "SHA256", "SHA512"])
        old = self.pkgs[0].properties["checksums"]
        self.assertIs(ch.new[0], old[0])                             # 既存要素は元の dict のまま
        self.assertIs(ch.new[1], old[1])
        self.assertEqual(ch.new[2], {"algorithm": "SHA512", "checksumValue": SHA512})
        self.assertEqual(len(plan.changes), 1)

    def test_fill_placeholder_row_adds_key(self):
        wb = self.wb()
        ws = wb["ExternalRefs"]
        row = self.rows_of(ws, "SPDXRef-Package-2")[0]
        self.put(ws, row, referenceCategory="PACKAGE-MANAGER", referenceType="purl",
                 referenceLocator="pkg:pypi/pkg2@1.0")
        self.save(wb)
        plan = self.plan(self.root)
        ch = self.list_changes(plan, "externalRefs")["SPDXRef-Package-2"]
        self.assertEqual(ch.op, "add")
        self.assertEqual(ch.new, [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                                   "referenceLocator": "pkg:pypi/pkg2@1.0"}])
        res = xio.apply_changes(plan.changes)
        self.assertEqual(self.pkgs[2].properties["externalRefs"], ch.new)
        self.assertEqual(len(res.applied), 1)

    def test_fill_placeholder_on_empty_array_is_set(self):
        wb = self.wb()
        ws = wb["ExternalRefs"]
        row = self.rows_of(ws, "SPDXRef-Package-1")[0]
        self.put(ws, row, referenceCategory="OTHER", referenceType="custom-type", referenceLocator="anything")
        self.save(wb)
        ch = self.list_changes(self.plan(self.root), "externalRefs")["SPDXRef-Package-1"]
        self.assertEqual(ch.op, "set")                               # キーはあった（空配列）
        self.assertEqual(ch.old, [])

    def test_delete_row_removes_entry(self):
        wb = self.wb()
        ws = wb["Checksums"]
        ws.delete_rows(self.rows_of(ws, "SPDXRef-Package-0")[0])     # SHA1 の行
        self.save(wb)
        ch = self.list_changes(self.plan(self.root), "checksums")["SPDXRef-Package-0"]
        self.assertEqual((ch.op, len(ch.added), len(ch.removed)), ("set", 0, 1))
        self.assertEqual(ch.removed[0]["algorithm"], "SHA1")
        self.assertEqual([e["algorithm"] for e in ch.new], ["SHA256"])

    def test_delete_all_rows_of_a_package_is_noop(self):
        wb = self.wb()
        ws = wb["Checksums"]
        for r in sorted(self.rows_of(ws, "SPDXRef-Package-0"), reverse=True):
            ws.delete_rows(r)
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(plan.changes, [])                           # シートに現れない → 変更なし
        self.assertEqual(self.errors(plan), [])

    def test_blanking_all_rows_clears_the_list(self):
        wb = self.wb()
        ws = wb["Checksums"]
        for r in self.rows_of(ws, "SPDXRef-Package-0"):
            self.put(ws, r, algorithm=None, checksumValue=None)
        self.save(wb)
        plan = self.plan(self.root)
        ch = self.list_changes(plan, "checksums")["SPDXRef-Package-0"]
        self.assertEqual((ch.op, ch.new, len(ch.removed)), ("delete", None, 2))
        xio.apply_changes(plan.changes)
        self.assertNotIn("checksums", self.pkgs[0].properties)

    def test_modified_entry_is_remove_plus_add_and_moves_to_end(self):
        wb = self.wb()
        ws = wb["Checksums"]
        self.put(ws, self.rows_of(ws, "SPDXRef-Package-0")[0], checksumValue=SHA1_B)   # SHA1 を修正
        self.save(wb)
        ch = self.list_changes(self.plan(self.root), "checksums")["SPDXRef-Package-0"]
        self.assertEqual((len(ch.added), len(ch.removed)), (1, 1))
        self.assertEqual([e["checksumValue"] for e in ch.new], [SHA256, SHA1_B])

    def test_comment_edit_on_external_ref(self):
        wb = self.wb()
        ws = wb["ExternalRefs"]
        row = self.rows_of(ws, "SPDXRef-Package-0")[1]
        self.put(ws, row, comment="NVD (updated)")
        self.save(wb)
        ch = self.list_changes(self.plan(self.root), "externalRefs")["SPDXRef-Package-0"]
        self.assertEqual(ch.added[0]["comment"], "NVD (updated)")
        self.assertEqual(ch.removed[0]["comment"], "NVD")

    def test_duplicate_entries_are_counted(self):
        root, pkgs = make_list_root()
        pkgs[1].properties["checksums"].append(dict(pkgs[1].properties["checksums"][0]))   # 同一要素が 2 つ
        self.export(root)
        self.assertEqual(self.plan(root).changes, [])
        wb = self.wb()
        ws = wb["Checksums"]
        ws.delete_rows(self.rows_of(ws, "SPDXRef-Package-1")[0])
        self.save(wb)
        ch = self.list_changes(self.plan(root), "checksums")["SPDXRef-Package-1"]
        self.assertEqual((len(ch.added), len(ch.removed), len(ch.new)), (0, 1, 1))

    def test_extra_keys_in_retained_entries_are_preserved(self):
        root, pkgs = make_list_root()
        pkgs[0].properties["checksums"][0]["note"] = "custom"
        self.export(root)
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="MD5", checksumValue="f" * 32)
        self.save(wb)
        plan = self.plan(root)
        xio.apply_changes(plan.changes)
        self.assertEqual(pkgs[0].properties["checksums"][0]["note"], "custom")
        self.assertEqual(len(pkgs[0].properties["checksums"]), 3)

    def test_algorithm_is_normalized_on_added_entry(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-1", algorithm="sha1", checksumValue=SHA1.upper())
        self.save(wb)
        ch = self.list_changes(self.plan(self.root), "checksums")["SPDXRef-Package-1"]
        self.assertEqual(ch.added[0], {"algorithm": "SHA1", "checksumValue": SHA1.upper()})


class TestListValidation(ListBase):
    def _check_rejected(self, sheet, row_vals, expect_in_msg, sid="SPDXRef-Package-0"):
        wb = self.wb()
        self.add_row(wb[sheet], sid, **row_vals)
        self.save(wb)
        plan = self.plan(self.root)
        errs = self.errors(plan)
        self.assertTrue(errs, f"エラーが出るはず: {row_vals}")
        self.assertTrue(any(expect_in_msg in e.message for e in errs), [e.message for e in errs])
        self.assertEqual([c for c in plan.changes if c.kind == "list"], [])   # 一覧ごと反映しない
        return plan

    def test_checksum_errors(self):
        self._check_rejected("Checksums", dict(algorithm="SHA999", checksumValue=SHA1), "次のいずれか")
        self._check_rejected("Checksums", dict(algorithm="SHA1", checksumValue="zz" + "a" * 38), "16進数")
        self._check_rejected("Checksums", dict(algorithm="SHA1", checksumValue=SHA1 + " "), "16進数")
        self._check_rejected("Checksums", dict(algorithm="SHA256", checksumValue=SHA1), "64 桁")
        self._check_rejected("Checksums", dict(algorithm="SHA1", checksumValue=None), "必須")
        self._check_rejected("Checksums", dict(algorithm=None, checksumValue=SHA1), "必須")

    def test_variable_length_hash_not_length_checked(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="BLAKE3", checksumValue="ab" * 20)
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(self.errors(plan), [])
        self.assertEqual(len(plan.changes), 1)

    def test_externalref_errors(self):
        self._check_rejected("ExternalRefs", dict(referenceCategory="PACKAGE-MANAGER", referenceType="purl",
                                                   referenceLocator="pypi/requests"), "'pkg:'")
        self._check_rejected("ExternalRefs", dict(referenceCategory="SECURITY", referenceType="cpe23Type",
                                                   referenceLocator="cpe:/a:x"), "cpe:2.3:")
        self._check_rejected("ExternalRefs", dict(referenceCategory="NOPE", referenceType="purl",
                                                   referenceLocator=PURL0B), "次のいずれか")
        self._check_rejected("ExternalRefs", dict(referenceCategory="OTHER", referenceType=None,
                                                   referenceLocator="x"), "必須")
        self._check_rejected("ExternalRefs", dict(referenceCategory="OTHER", referenceType="t",
                                                   referenceLocator=None), "必須")

    def test_externalref_warnings_but_applied(self):
        wb = self.wb()
        ws = wb["ExternalRefs"]
        self.add_row(ws, "SPDXRef-Package-0", referenceCategory="PACKAGE_MANAGER", referenceType="purl",
                     referenceLocator=PURL0B)                         # 旧表記
        self.add_row(ws, "SPDXRef-Package-1", referenceCategory="SECURITY", referenceType="purl",
                     referenceLocator="pkg:pypi/x@1")                 # カテゴリ不一致
        self.add_row(ws, "SPDXRef-Package-2", referenceCategory="OTHER", referenceType="custom",
                     referenceLocator=" pkg:x ")                      # 空白
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(self.errors(plan), [])
        self.assertEqual(len(plan.changes), 3)
        msgs = " ".join(w.message for w in self.warnings(plan))
        self.assertIn("旧表記", msgs)
        self.assertIn("通常のカテゴリ", msgs)
        self.assertIn("空白", msgs)

    def test_one_bad_package_does_not_block_others(self):
        wb = self.wb()
        ws = wb["Checksums"]
        self.add_row(ws, "SPDXRef-Package-0", algorithm="SHA999", checksumValue=SHA1)     # NG
        self.add_row(ws, "SPDXRef-Package-1", algorithm="SHA1", checksumValue=SHA1)       # OK
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(set(self.list_changes(plan, "checksums")), {"SPDXRef-Package-1"})
        self.assertEqual(len(self.errors(plan)), 1)

    def test_error_in_added_row_also_blocks_removals_in_same_list(self):
        wb = self.wb()
        ws = wb["Checksums"]
        ws.delete_rows(self.rows_of(ws, "SPDXRef-Package-0")[0])                          # 削除は妥当
        self.add_row(ws, "SPDXRef-Package-0", algorithm="SHA1", checksumValue="xyz")      # 追加が不正
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual(self.list_changes(plan, "checksums"), {})

    def test_unchanged_invalid_existing_data_is_never_validated(self):
        root, pkgs = make_list_root()
        pkgs[0].properties["checksums"][0] = {"algorithm": "SHA1", "checksumValue": "short"}   # 元から不正
        pkgs[0].properties["externalRefs"][0]["referenceLocator"] = "not-a-purl"
        self.export(root)
        plan = self.plan(root)
        self.assertEqual(plan.changes, [])
        self.assertEqual(self.errors(plan), [])

    def test_numeric_cell_warns_and_fails_length(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="SHA1", checksumValue=1234567890)
        self.save(wb)
        plan = self.plan(self.root)
        msgs = [i.message for i in plan.issues]
        self.assertTrue(any("数値として" in m for m in msgs))
        self.assertTrue(any("40 桁" in m for m in msgs))

    def test_too_long_marker_cannot_be_added(self):
        wb = self.wb()
        self.add_row(wb["ExternalRefs"], "SPDXRef-Package-0", referenceCategory="OTHER", referenceType="t",
                     referenceLocator=xio.TOO_LONG_MARKER)
        self.save(wb)
        self.assertTrue(any("マーカー" in e.message for e in self.errors(self.plan(self.root))))

    def test_uncached_formula_is_error(self):
        wb = self.wb()
        ws = wb["Checksums"]
        self.put(ws, self.rows_of(ws, "SPDXRef-Package-1")[0], checksumValue='=REPT("a",64)')
        self.save(wb)
        plan = self.plan(self.root)
        self.assertTrue(any("数式" in e.message for e in self.errors(plan)))
        self.assertEqual(self.list_changes(plan, "checksums"), {})


class TestListStructure(ListBase):
    def test_unknown_and_blank_spdxid(self):
        wb = self.wb()
        ws = wb["Checksums"]
        self.add_row(ws, "SPDXRef-Nope", algorithm="SHA1", checksumValue=SHA1)
        self.add_row(ws, None, algorithm="SHA1", checksumValue=SHA1)
        self.add_row(ws, None)                                         # 完全な空行は黙って無視
        self.save(wb)
        plan = self.plan(self.root)
        msgs = [w.message for w in self.warnings(plan)]
        self.assertTrue(any("存在しない SPDXID" in m for m in msgs))
        self.assertTrue(any("SPDXID が空" in m for m in msgs))
        self.assertEqual(len(msgs), 2)
        self.assertEqual(plan.changes, [])

    def test_duplicate_spdxid_in_sbom_is_error(self):
        self.pkgs[1].properties["SPDXID"] = self.pkgs[0].properties["SPDXID"]
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="SHA1", checksumValue=SHA1_B)
        self.save(wb)
        plan = self.plan(self.root)
        self.assertTrue(any("SBOM 内で" in e.message for e in self.errors(plan)))
        self.assertEqual(self.list_changes(plan, "checksums"), {})

    def test_nonstandard_list_is_left_alone(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-3", algorithm="SHA1", checksumValue=SHA1)
        self.save(wb)
        plan = self.plan(self.root)
        self.assertTrue(any("標準的でない" in w.message for w in self.warnings(plan)))
        self.assertEqual(plan.changes, [])
        self.assertEqual(self.pkgs[3].properties["checksums"], {"weird": "dict"})

    def test_missing_required_column_ignores_sheet(self):
        wb = self.wb()
        ws = wb["Checksums"]
        ws.delete_cols(self.hdr(ws)["checksumValue"])
        self.add_row(wb["ExternalRefs"], "SPDXRef-Package-0", referenceCategory="OTHER",
                     referenceType="t", referenceLocator="x")
        self.save(wb)
        plan = self.plan(self.root)
        self.assertTrue(any("必須の列" in e.message for e in self.errors(plan)))
        self.assertEqual(set(self.list_changes(plan, "checksums")), set())
        self.assertEqual(set(self.list_changes(plan, "externalRefs")), {"SPDXRef-Package-0"})  # 他は有効

    def test_missing_spdxid_header_ignores_that_sheet_only(self):
        wb = self.wb()
        wb["Checksums"].cell(row=1, column=1).value = "ID"
        self.put(wb["Packages"], 2, name="renamed")
        self.save(wb)
        parsed = xio.read_workbook(self.path)
        self.assertIn("Checksums", parsed.child_errors)
        plan = xio.build_changes(self.root, parsed)
        self.assertTrue(any("SPDXID" in e.message and e.where == "Checksums" for e in self.errors(plan)))
        self.assertEqual([c.field for c in plan.changes], ["name"])   # Packages は通常どおり処理される

    def test_unrecognized_column_in_list_sheet_warns(self):
        wb = self.wb()
        ws = wb["ExternalRefs"]
        ws.cell(row=1, column=ws.max_column + 1).value = "memo"
        self.save(wb)
        self.assertTrue(any("memo" in w.message for w in self.warnings(self.plan(self.root))))

    def test_progress_and_cancel_cover_child_sheets(self):
        parsed = xio.read_workbook(self.path)
        seen = []
        xio.build_changes(self.root, parsed, progress=seen.append)
        self.assertEqual(seen[-1], 100)
        calls = [0]

        def cancel_late():
            calls[0] += 1
            return calls[0] > len(parsed.rows) + 1                   # Packages を終えた後（一覧の途中）で中断

        with self.assertRaises(xio.ImportCanceled):
            xio.build_changes(self.root, parsed, should_cancel=cancel_late)

    def test_phase1_style_workbook_still_imports(self):
        wb = self.wb()
        del wb["Checksums"]
        del wb["ExternalRefs"]
        self.put(wb["Packages"], 2, name="renamed")
        self.save(wb)
        plan = self.plan(self.root)
        self.assertEqual([(c.field, c.kind) for c in plan.changes], [("name", "scalar")])


class TestListApply(ListBase):
    def test_apply_then_reexport_is_clean(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="SHA512", checksumValue=SHA512)
        ws = wb["ExternalRefs"]
        ws.delete_rows(self.rows_of(ws, "SPDXRef-Package-0")[1])
        self.put(wb["Packages"], 3, name="renamed")
        self.save(wb)
        plan = self.plan(self.root)
        res = xio.apply_changes(plan.changes)
        self.assertEqual(len(res.applied), 3)
        p0 = self.pkgs[0].properties
        self.assertEqual([e["algorithm"] for e in p0["checksums"]], ["SHA1", "SHA256", "SHA512"])
        self.assertEqual(len(p0["externalRefs"]), 1)
        self.assertEqual(self.pkgs[1].properties["name"], "renamed")
        self.export(self.root)                                        # 適用後の再出力 → 差分ゼロ
        self.assertEqual(self.plan(self.root).changes, [])

    def test_conflict_is_skipped_for_lists(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="SHA512", checksumValue=SHA512)
        self.save(wb)
        plan = self.plan(self.root)
        self.pkgs[0].properties["checksums"][0]["checksumValue"] = SHA1_B     # 計画後にアプリ側で変更
        res = xio.apply_changes(plan.changes)
        self.assertEqual(res.applied, [])
        self.assertEqual(len(res.skipped), 1)
        self.assertEqual(len(self.pkgs[0].properties["checksums"]), 2)

    def test_old_snapshot_is_independent_copy(self):
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="SHA512", checksumValue=SHA512)
        self.save(wb)
        ch = self.list_changes(self.plan(self.root), "checksums")["SPDXRef-Package-0"]
        self.assertIsNot(ch.old, self.pkgs[0].properties["checksums"])
        self.assertEqual(ch.old, self.pkgs[0].properties["checksums"])

    def test_row_label(self):
        self.assertEqual(xio._row_label("Checksums", [5]), "Checksums!5")
        self.assertEqual(xio._row_label("ExternalRefs", [17, 2]), "ExternalRefs!2,17")
        self.assertEqual(xio._row_label("Checksums", [2, 3, 4, 40]), "Checksums!2…40（4行）")
        wb = self.wb()
        self.add_row(wb["Checksums"], "SPDXRef-Package-0", algorithm="SHA512", checksumValue=SHA512)
        self.save(wb)
        ch = self.list_changes(self.plan(self.root), "checksums")["SPDXRef-Package-0"]
        self.assertRegex(ch.cell, r"^Checksums!\d+,\d+,\d+$")   # 既存 2 行 + 追加 1 行

    def test_describe_helpers(self):
        self.assertEqual(xio.format_entry("checksums", {"algorithm": "SHA1", "checksumValue": "ab"}), "SHA1: ab")
        text = xio.format_entry("externalRefs", {"referenceCategory": "SECURITY", "referenceType": "advisory",
                                                  "referenceLocator": "https://x", "comment": "c"})
        self.assertIn("advisory: https://x", text)
        self.assertIn("[SECURITY]", text)
        self.assertIn("// c", text)
        self.assertEqual(xio.describe_entries("checksums", []), "")
        self.assertEqual(xio.describe_entries("checksums", [{"algorithm": "A", "checksumValue": "1"}], "＋ "), "＋ A: 1")
        self.assertEqual(xio.describe_value([]), "(空)")


class TestListPerformance(ExcelTestBase):
    def test_5000_packages_with_lists(self):
        pkgs = [make_pkg(i, checksums=[{"algorithm": "SHA256", "checksumValue": SHA256}],
                         externalRefs=[{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                                        "referenceLocator": f"pkg:generic/p{i}@1"}]) for i in range(5000)]
        doc = FakeNode("document_info", {"name": "T", "documentNamespace": "ns"})
        root = FakeNode("root", children=[doc, FakeNode("folder", children=pkgs)])
        t0 = time.time()
        self.export(root)
        t1 = time.time()
        plan = self.plan(root)
        t2 = time.time()
        print(f"\n  [lists] export 5000 pkgs: {t1 - t0:.1f}s / read+diff: {t2 - t1:.1f}s")
        self.assertEqual(plan.changes, [])
        self.assertEqual(plan.list_stats, {"Checksums": 5000, "ExternalRefs": 5000})
        self.assertLess(t1 - t0, 30)
        self.assertLess(t2 - t1, 40)


if __name__ == "__main__":
    unittest.main()
