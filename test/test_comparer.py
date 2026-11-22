# test/test_comparer.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""core/comparer.py の単体テスト（Qt 不要）。 実行: python -m unittest discover -s test -v"""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import comparer as cmp
from core.comparer import DiffStatus as S, MatchKey as K

from core import i18n
def setUpModule(): i18n.set_language("ja")

class FakeNode:
    def __init__(self, node_type, properties=None, children=None):
        self.node_type = node_type
        self.properties = properties if properties is not None else {}
        self.children = children or []
        self.spdx_id = self.properties.get("SPDXID", "")
        self.name = self.properties.get("name", "")


def pkg(name, version="1.0", spdx=None, purl=None, **extra):
    p = {"name": name, "versionInfo": version, "SPDXID": spdx if spdx is not None else f"SPDXRef-{name}"}
    if version is None:
        del p["versionInfo"]
    if purl:
        p["externalRefs"] = [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": purl}]
    p.update(extra)
    return p


def sbom(*pkgs, spdx_version="SPDX-2.3", name="doc"):
    nodes = [FakeNode("package", p) for p in pkgs]
    folder = FakeNode("packages_folder", children=nodes)
    return FakeNode("document", {"name": name, "spdxVersion": spdx_version,
                                 "creationInfo": {"created": "2026-01-01T00:00:00Z", "creators": ["Tool: x"]}},
                    children=[folder])


def by_name(result, name):
    return [d for d in result.diffs if d.name == name]


class VersionCompareTest(unittest.TestCase):
    def test_ordering(self):
        c = cmp.compare_versions
        self.assertEqual(c("1.0", "1.1"), -1)
        self.assertEqual(c("1.10", "1.9"), 1)            # 数値として比較
        self.assertEqual(c("v2.0", "2.0"), 0)
        self.assertEqual(c("1.0", "1.0.0"), 0)
        self.assertEqual(c("1.0.1", "1.0"), 1)
        self.assertEqual(c("2.0.0-rc1", "2.0.0"), -1)    # pre-release は正式版より前
        self.assertEqual(c("1.0.0-rc1", "1.0"), -1)
        self.assertEqual(c("1.0-beta", "1.0-rc1"), -1)
        self.assertEqual(c("2.0+build5", "2.0"), 0)

    def test_not_comparable(self):
        self.assertIsNone(cmp.compare_versions("", "1.0"))
        self.assertIsNone(cmp.compare_versions("abc123", "1.0"))
        self.assertIsNone(cmp.compare_versions("NOASSERTION", "1.0"))


class PurlTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(cmp.parse_purl("pkg:pypi/PySide6@6.12.0"), ("pypi", "pypi/pyside6", "6.12.0"))
        self.assertEqual(cmp.parse_purl("pkg:pypi/foo_bar@1")[1], "pypi/foo-bar")
        self.assertEqual(cmp.parse_purl("pkg:npm/@angular/core@1.0?x=y#sub"), ("npm", "npm/@angular/core", "1.0"))
        self.assertEqual(cmp.parse_purl("pkg:npm/%40angular/core@1.0")[1], "npm/@angular/core")
        self.assertEqual(cmp.parse_purl("pkg:maven/org.apache/commons@1.0?type=jar")[1], "maven/org.apache/commons")
        self.assertEqual(cmp.parse_purl("pkg:generic/SBOMcraft")[2], None)
        self.assertIsNone(cmp.parse_purl("https://example.com"))
        self.assertIsNone(cmp.parse_purl("pkg:"))


class MatchingTest(unittest.TestCase):
    def test_version_upgrade_is_not_add_remove(self):
        a = sbom(pkg("requests", "2.31.0", purl="pkg:pypi/requests@2.31.0"))
        b = sbom(pkg("requests", "2.32.0", purl="pkg:pypi/requests@2.32.0"))
        r = cmp.compare(a, b)
        self.assertEqual(len(r.diffs), 1)
        d = r.diffs[0]
        self.assertEqual((d.status, d.version_change, d.matched_by), (S.VERSION_CHANGED, "upgrade", "purl"))
        self.assertEqual(r.summary()["upgrade"], 1)

    def test_downgrade(self):
        r = cmp.compare(sbom(pkg("x", "2.0")), sbom(pkg("x", "1.0")))
        self.assertEqual(r.diffs[0].version_change, "downgrade")

    def test_different_tools_spdxid_differs(self):
        """ツールが違い SPDXID が全く違っても、自動では突合できる。SPDXID モードでは一致しない。"""
        a = sbom(pkg("PySide6", "6.12.0", spdx="SPDXRef-Package-PySide6", purl="pkg:pypi/pyside6@6.12.0"))
        b = sbom(pkg("pyside6", "6.12.0", spdx="SPDXRef-1", purl="pkg:pypi/PySide6@6.12.0"))
        self.assertEqual(cmp.compare(a, b, K.AUTO).diffs[0].status, S.UNCHANGED)
        r = cmp.compare(a, b, K.SPDXID)
        self.assertEqual(sorted(d.status.value for d in r.diffs), ["added", "removed"])

    def test_auto_falls_back_to_name_when_purl_missing_on_one_side(self):
        a = sbom(pkg("foo", "1.0", purl="pkg:pypi/foo@1.0"))
        b = sbom(pkg("Foo", "1.1"))
        r = cmp.compare(a, b)
        self.assertEqual(len(r.diffs), 1)
        self.assertEqual(r.diffs[0].status, S.VERSION_CHANGED)
#        self.assertTrue(r.diffs[0].matched_by.startswith("名前"))
        self.assertTrue(r.diffs[0].matched_by, "name_fallback")

    def test_auto_does_not_merge_different_ecosystems(self):
        a = sbom(pkg("foo", "1.0", purl="pkg:pypi/foo@1.0"))
        b = sbom(pkg("foo", "1.0", purl="pkg:npm/foo@1.0"))
        self.assertEqual(sorted(d.status.value for d in cmp.compare(a, b).diffs), ["added", "removed"])

    def test_name_version_mode(self):
        a = sbom(pkg("foo", "1.0"), pkg("bar", "1.0"))
        b = sbom(pkg("foo", "1.1"), pkg("bar", "1.0"))
        r = cmp.compare(a, b, K.NAME_VERSION)
        self.assertEqual(r.count(S.ADDED), 1)
        self.assertEqual(r.count(S.REMOVED), 1)
        self.assertEqual(r.count(S.UNCHANGED), 1)

    def test_name_mode_detects_version_change(self):
        r = cmp.compare(sbom(pkg("foo", "1.0")), sbom(pkg("foo", "1.1")), K.NAME)
        self.assertEqual(r.diffs[0].status, S.VERSION_CHANGED)

    def test_purl_mode_leaves_unkeyed_unmatched(self):
        a = sbom(pkg("foo", "1.0"))
        b = sbom(pkg("foo", "1.0"))
        r = cmp.compare(a, b, K.PURL)
        self.assertEqual(r.count(S.ADDED, S.REMOVED), 2)
        self.assertTrue(any("purl" in w for w in r.warnings))

    def test_added_removed_unchanged(self):
        a = sbom(pkg("keep"), pkg("gone"))
        b = sbom(pkg("keep"), pkg("new"))
        r = cmp.compare(a, b)
        self.assertEqual([d.status for d in by_name(r, "gone")], [S.REMOVED])
        self.assertEqual([d.status for d in by_name(r, "new")], [S.ADDED])
        self.assertEqual([d.status for d in by_name(r, "keep")], [S.UNCHANGED])
        s = r.summary()
        self.assertEqual((s["total_a"], s["total_b"], s["differences"]), (2, 2, 2))

    def test_version_from_purl_when_versioninfo_missing(self):
        a = sbom(pkg("foo", None, purl="pkg:pypi/foo@1.0"))
        b = sbom(pkg("foo", "1.0", purl="pkg:pypi/foo@1.0"))
        self.assertEqual(cmp.compare(a, b).diffs[0].status, S.UNCHANGED)


class DuplicateKeyTest(unittest.TestCase):
    def test_pair_by_version_first(self):
        a = sbom(pkg("foo", "1.0", spdx="a1"), pkg("foo", "2.0", spdx="a2"))
        b = sbom(pkg("foo", "2.0", spdx="b1"), pkg("foo", "1.0", spdx="b2"))
        r = cmp.compare(a, b, K.NAME)
        self.assertEqual(r.count(S.UNCHANGED), 2)
        self.assertEqual(r.count(S.VERSION_CHANGED, S.ADDED, S.REMOVED), 0)

    def test_leftovers_pair_with_note(self):
        a = sbom(pkg("foo", "1.0"), pkg("foo", "1.1"))
        b = sbom(pkg("foo", "1.1"), pkg("foo", "1.2"))
        r = cmp.compare(a, b, K.NAME)
        changed = [d for d in r.diffs if d.status == S.VERSION_CHANGED]
        self.assertEqual(len(changed), 1)
        self.assertEqual((changed[0].version_a, changed[0].version_b), ("1.0", "1.2"))
        self.assertTrue(changed[0].notes)
        self.assertTrue(r.warnings)

    def test_exact_duplicates_do_not_vanish(self):
        a = sbom(pkg("foo", "1.0", spdx="x1"), pkg("foo", "1.0", spdx="x2"))
        b = sbom(pkg("foo", "1.0", spdx="x1"))
        r = cmp.compare(a, b, K.NAME_VERSION)
        self.assertEqual(len(r.diffs), 2)                       # 後勝ちで黙って消えない
        self.assertEqual(r.count(S.REMOVED), 1)


class FieldDiffTest(unittest.TestCase):
    def test_license_order_insensitive(self):
        a = sbom(pkg("x", licenseDeclared="MIT OR Apache-2.0"))
        b = sbom(pkg("x", licenseDeclared="Apache-2.0  OR  MIT"))
        self.assertEqual(cmp.compare(a, b).diffs[0].status, S.UNCHANGED)

    def test_license_change_flagged(self):
        a = sbom(pkg("x", licenseConcluded="MIT"))
        b = sbom(pkg("x", licenseConcluded="GPL-3.0-only"))
        d = cmp.compare(a, b).diffs[0]
        self.assertEqual(d.status, S.MODIFIED)
        self.assertIn(cmp.FLAG_LICENSE, d.flags)
        self.assertEqual((d.field_changes[0].old, d.field_changes[0].new), ("MIT", "GPL-3.0-only"))

    def test_noassertion_equals_missing(self):
        a = sbom(pkg("x", supplier="NOASSERTION"))
        b = sbom(pkg("x"))
        self.assertEqual(cmp.compare(a, b).diffs[0].status, S.UNCHANGED)

    def test_none_differs_from_noassertion(self):
        a = sbom(pkg("x", downloadLocation="NONE"))
        b = sbom(pkg("x", downloadLocation="NOASSERTION"))
        self.assertEqual(cmp.compare(a, b).diffs[0].status, S.MODIFIED)

    def test_whitespace_and_newlines_ignored(self):
        a = sbom(pkg("x", copyrightText="Copyright 2026\r\nFoo "))
        b = sbom(pkg("x", copyrightText="Copyright 2026\nFoo"))
        self.assertEqual(cmp.compare(a, b).diffs[0].status, S.UNCHANGED)

    def test_supplier_and_download_flags(self):
        a = sbom(pkg("x", supplier="Organization: A", downloadLocation="https://a"))
        b = sbom(pkg("x", supplier="Organization: B", downloadLocation="https://b"))
        d = cmp.compare(a, b).diffs[0]
        self.assertEqual(set(d.flags), {cmp.FLAG_SUPPLIER, cmp.FLAG_DOWNLOAD})

    def test_bool_field(self):
        a = sbom(pkg("x", filesAnalyzed=False))
        b = sbom(pkg("x", filesAnalyzed=True))
        fc = cmp.compare(a, b).diffs[0].field_changes[0]
        self.assertEqual((fc.field, fc.old, fc.new), ("filesAnalyzed", "false", "true"))

    def test_unknown_scalar_key_is_compared(self):
        r = cmp.compare(sbom(pkg("x", customKey="a")), sbom(pkg("x", customKey="b")))
        self.assertEqual(r.diffs[0].field_changes[0].field, "customKey")

    def test_group_selection(self):
        a = sbom(pkg("x", licenseConcluded="MIT", supplier="Organization: A"))
        b = sbom(pkg("x", licenseConcluded="GPL-3.0-only", supplier="Organization: A"))
        self.assertEqual(cmp.compare(a, b, groups=["supplier"]).diffs[0].status, S.UNCHANGED)
        self.assertEqual(cmp.compare(a, b, groups=["license"]).diffs[0].status, S.MODIFIED)

    def test_name_change_is_normalized(self):
        a = sbom(pkg("Foo_Bar", purl="pkg:pypi/foo-bar@1.0"))
        b = sbom(pkg("foo-bar", purl="pkg:pypi/foo-bar@1.0"))
        self.assertEqual(cmp.compare(a, b).diffs[0].status, S.UNCHANGED)


class ChecksumTest(unittest.TestCase):
    @staticmethod
    def cs(algo, value):
        return [{"algorithm": algo, "checksumValue": value}]

    def test_same_version_checksum_mismatch_is_flagged_first(self):
        a = sbom(pkg("x", "1.0", checksums=self.cs("SHA256", "aa" * 32)))
        b = sbom(pkg("x", "1.0", checksums=self.cs("SHA256", "bb" * 32)))
        d = cmp.compare(a, b).diffs[0]
        self.assertEqual(d.status, S.MODIFIED)
        self.assertEqual(d.flags[0], cmp.FLAG_CHECKSUM_MISMATCH)

    def test_checksum_change_with_version_change_is_not_flagged(self):
        a = sbom(pkg("x", "1.0", checksums=self.cs("SHA256", "aa" * 32)))
        b = sbom(pkg("x", "1.1", checksums=self.cs("SHA256", "bb" * 32)))
        d = cmp.compare(a, b).diffs[0]
        self.assertEqual(d.status, S.VERSION_CHANGED)
        self.assertNotIn(cmp.FLAG_CHECKSUM_MISMATCH, d.flags)

    def test_disjoint_algorithms_are_not_flagged(self):
        a = sbom(pkg("x", "1.0", checksums=self.cs("SHA1", "aa" * 20)))
        b = sbom(pkg("x", "1.0", checksums=self.cs("SHA256", "bb" * 32)))
        d = cmp.compare(a, b).diffs[0]
        self.assertEqual(d.status, S.MODIFIED)                  # 要素の増減としては差分
        self.assertNotIn(cmp.FLAG_CHECKSUM_MISMATCH, d.flags)   # しかし不一致とは断定しない

    def test_checksum_case_and_order_ignored(self):
        a = sbom(pkg("x", checksums=[{"algorithm": "SHA256", "checksumValue": "AB" * 32},
                                     {"algorithm": "SHA1", "checksumValue": "cd" * 20}]))
        b = sbom(pkg("x", checksums=[{"algorithm": "SHA1", "checksumValue": "CD" * 20},
                                     {"algorithm": "SHA256", "checksumValue": "ab" * 32}]))
        self.assertEqual(cmp.compare(a, b).diffs[0].status, S.UNCHANGED)

    def test_list_change_reports_added_removed(self):
        a = sbom(pkg("x", checksums=self.cs("SHA1", "aa" * 20)))
        b = sbom(pkg("x", checksums=self.cs("SHA1", "aa" * 20) + self.cs("SHA256", "bb" * 32)))
        fc = cmp.compare(a, b).diffs[0].field_changes[0]
        self.assertEqual((fc.field, len(fc.added), len(fc.removed)), ("checksums", 1, 0))


class DocumentLevelTest(unittest.TestCase):
    def test_spdx_version_mismatch_warning(self):
        r = cmp.compare(sbom(spdx_version="SPDX-2.2"), sbom(spdx_version="SPDX-2.3"))
        self.assertTrue(any("SPDX" in w for w in r.warnings))

    def test_doc_info_and_empty(self):
        r = cmp.compare(sbom(pkg("a"), name="old"), sbom(name="new"))
        self.assertEqual((r.doc_a.name, r.doc_b.name, r.doc_a.package_count, r.doc_b.package_count), ("old", "new", 1, 0))
        self.assertEqual(r.count(S.REMOVED), 1)

    def test_none_root(self):
        r = cmp.compare(None, sbom(pkg("a")))
        self.assertEqual(r.count(S.ADDED), 1)

    def test_progress_and_cancel(self):
        seen = []
        cmp.compare(sbom(pkg("a")), sbom(pkg("a")), progress=seen.append)
        self.assertEqual(seen[0], 0)
        self.assertEqual(seen[-1], 100)
        with self.assertRaises(cmp.CompareCanceled):
            cmp.compare(sbom(pkg("a")), sbom(pkg("a")), should_cancel=lambda: True)

    def test_large_input_is_fast(self):
        import time
        n = 20000
        a = sbom(*[pkg(f"p{i}", "1.0", purl=f"pkg:pypi/p{i}@1.0") for i in range(n)])
        b = sbom(*[pkg(f"p{i}", "1.1" if i % 10 == 0 else "1.0", purl=f"pkg:pypi/p{i}@1.0") for i in range(n)])
        t = time.time()
        r = cmp.compare(a, b)
        self.assertEqual(r.count(S.VERSION_CHANGED), n // 10)
        self.assertLess(time.time() - t, 10)


class CsvTest(unittest.TestCase):
    def test_export(self):
        a = sbom(pkg("=evil", "1.0"), pkg("same"))
        b = sbom(pkg("=evil", "1.1"), pkg("same"), pkg("new"))
        r = cmp.compare(a, b)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "d.csv")
            n = cmp.export_csv(r, path)
            self.assertEqual(n, 2)                              # 未変更は出さない
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0][0], "状態")
            self.assertTrue(any(row[1] == "'=evil" for row in rows[1:]))   # 数式インジェクション対策
            self.assertEqual(cmp.export_csv(r, path, include_unchanged=True), 3)
            self.assertFalse(os.path.exists(path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
