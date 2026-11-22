# test/test_drop_plan.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""core/drop_plan.py の単体テスト（Qt 不要）。 実行: python -m unittest discover -s test -v"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.drop_plan import DropKind as K, plan_drop
from core import i18n
def setUpModule(): i18n.set_language("ja")


class DropPlanTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.d = self._td.name
        self.a = self._make("a.json")
        self.b = self._make("B.JSON")
        self.c = self._make("c.json")
        self.txt = self._make("note.txt")

    def _make(self, name):
        p = os.path.join(self.d, name)
        with open(p, "w") as f:
            f.write("{}")
        return p

    def test_one_file(self):
        self.assertEqual(plan_drop([self.a], has_loaded=False, busy=False).kind, K.OPEN)
        self.assertEqual(plan_drop([self.a], has_loaded=True, busy=False).kind, K.ASK_OPEN_OR_COMPARE)

    def test_two_files_keep_order(self):
        p = plan_drop([self.a, self.b], has_loaded=False, busy=False)
        self.assertEqual((p.kind, p.paths), (K.COMPARE_TWO, (self.a, self.b)))
        self.assertEqual(plan_drop([self.a, self.b], has_loaded=True, busy=False).kind, K.CONFIRM_COMPARE_TWO)

    def test_extension_is_case_insensitive(self):
        self.assertEqual(plan_drop([self.b], False, False).kind, K.OPEN)

    def test_three_or_more_rejected(self):
        p = plan_drop([self.a, self.b, self.c], False, False)
        self.assertEqual(p.kind, K.REJECT)
        self.assertIn("3", p.reason)

    def test_many_files_rejected_without_touching_filesystem(self):
        p = plan_drop([f"/no/such/{i}.json" for i in range(1000)], False, False)
        self.assertEqual(p.kind, K.REJECT)

    def test_non_json_rejected(self):
        self.assertEqual(plan_drop([self.txt], False, False).kind, K.REJECT)
        self.assertEqual(plan_drop([self.a, self.txt], False, False).kind, K.REJECT)

    def test_folder_rejected(self):
        p = plan_drop([self.d], False, False)
        self.assertEqual(p.kind, K.REJECT)
        self.assertIn("フォルダ", p.reason)

    def test_missing_file_rejected(self):
        self.assertEqual(plan_drop([os.path.join(self.d, "nope.json")], False, False).kind, K.REJECT)

    def test_non_local_url_rejected(self):
        self.assertEqual(plan_drop(["https://example.com/x.json"], False, False).kind, K.REJECT)

    def test_same_file_twice_rejected(self):
        self.assertEqual(plan_drop([self.a, self.a], False, False).kind, K.REJECT)

    def test_busy_rejected_first(self):
        p = plan_drop([self.a], True, True)
        self.assertEqual(p.kind, K.REJECT)
        self.assertIn("処理中", p.reason)

    def test_empty_rejected(self):
        self.assertEqual(plan_drop([], False, False).kind, K.REJECT)
        self.assertEqual(plan_drop(["", ""], False, False).kind, K.REJECT)


if __name__ == "__main__":
    unittest.main()
