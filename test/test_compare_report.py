# test/test_compare_report.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""core/compare_report.py の単体テスト（Qt 不要）。 実行: python -m unittest discover -s test -v"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import comparer as cmp
from core.compare_report import detail_html, summary_html
from test_comparer import pkg, sbom
from core import i18n
def setUpModule(): i18n.set_language("ja")

class ReportTest(unittest.TestCase):
    def test_html_is_escaped(self):
        a = sbom(pkg("<script>alert(1)</script>", "1.0", licenseConcluded="<b>MIT</b>"), name="<i>old</i>")
        b = sbom(pkg("<script>alert(1)</script>", "1.1", licenseConcluded="GPL"), name="new")
        r = cmp.compare(a, b, label_a="<a.json>", label_b="b.json")
        html_all = summary_html(r) + "".join(detail_html(d, r) for d in r.diffs)
        self.assertNotIn("<script>", html_all)
        self.assertNotIn("<b>MIT</b>", html_all)
        self.assertNotIn("<a.json>", html_all)

    def test_checksum_mismatch_message(self):
        cs = lambda v: [{"algorithm": "SHA256", "checksumValue": v * 32}]
        r = cmp.compare(sbom(pkg("x", "1.0", checksums=cs("aa"))), sbom(pkg("x", "1.0", checksums=cs("bb"))))
        self.assertIn("checksum が一致しません", detail_html(r.diffs[0], r))
        self.assertIn("checksum", summary_html(r))

    def test_all_statuses_render(self):
        a = sbom(pkg("gone"), pkg("up", "1.0"), pkg("same"))
        b = sbom(pkg("new"), pkg("up", "2.0"), pkg("same"))
        r = cmp.compare(a, b)
        self.assertEqual(len(r.diffs), 4)
        for d in r.diffs:
            self.assertIn(d.name, detail_html(d, r))


if __name__ == "__main__":
    unittest.main()
