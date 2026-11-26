# test/test_compare_apply.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""core/compare_apply.py の単体テスト（Qt 不要）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import comparer as cmp
from core import i18n
from core.compare_apply import adopt_new_side
from test_comparer import FakeNode, pkg, sbom


def setUpModule():
    i18n.set_language("ja")


def make_node(*, name, node_type, spdx_id, properties):
    return FakeNode(node_type, properties)


def rel(src, dst):
    return FakeNode("relationship", {"spdxElementId": src, "relationshipType": "DEPENDS_ON",
                                     "relatedSpdxElement": dst})


class AdoptTest(unittest.TestCase):
    def setUp(self):
        self.a = sbom(pkg("x", "1.0", licenseConcluded="MIT"), pkg("gone"), pkg("keep"))
        self.a.children.append(FakeNode("relations_folder", children=[rel("SPDXRef-keep", "SPDXRef-gone")]))
        self.b = sbom(pkg("x", "1.1", licenseConcluded="GPL-3.0-only"), pkg("keep"), pkg("new"))
        self.r = cmp.compare(self.a, self.b)

    def names(self, root):
        return sorted(n.properties["name"] for n in cmp.iter_package_nodes(root))

    def test_modified_and_added_but_removed_is_kept_by_default(self):
        res = adopt_new_side(self.a, self.r.diffs, make_node)
        self.assertEqual((len(res.modified), len(res.added), len(res.removed), res.kept_removed), (1, 1, 0, 1))
        self.assertEqual(self.names(self.a), ["gone", "keep", "new", "x"])
        x = next(n for n in cmp.iter_package_nodes(self.a) if n.properties["name"] == "x")
        self.assertEqual((x.properties["versionInfo"], x.properties["licenseConcluded"]), ("1.1", "GPL-3.0-only"))
        self.assertEqual(x.properties["SPDXID"], "SPDXRef-x")                 # SPDXID は変えない

    def test_include_removed_drops_relationships_and_converges(self):
        res = adopt_new_side(self.a, self.r.diffs, make_node, include_removed=True)
        self.assertEqual(len(res.removed), 1)
        self.assertEqual(res.removed_relationships, 1)
        self.assertEqual(self.a.children[-1].children, [])
        again = cmp.compare(self.a, self.b)
        self.assertEqual(again.summary()["differences"], 0)

    def test_spdxid_collision_is_renamed(self):
        a = sbom(pkg("p", "1.0", spdx="SPDXRef-1"))
        b = sbom(pkg("p", "1.0", spdx="SPDXRef-1"), pkg("q", "1.0", spdx="SPDXRef-1"))
        res = adopt_new_side(a, cmp.compare(a, b).diffs, make_node)
        self.assertEqual(res.added[0].properties["SPDXID"], "SPDXRef-1-1")
        self.assertTrue(res.notes)

    def test_added_node_is_a_copy(self):
        res = adopt_new_side(self.a, self.r.diffs, make_node)
        res.added[0].properties["name"] = "edited"
        self.assertEqual(self.names(self.b), ["keep", "new", "x"])

    def test_node_missing_from_tree_is_skipped(self):
        diffs = [d for d in self.r.diffs if d.status == cmp.DiffStatus.MODIFIED or d.name == "x"]
        for f in self.a.children:
            f.children = [c for c in f.children if c.properties.get("name") != "x"]
        res = adopt_new_side(self.a, diffs, make_node)
        self.assertEqual(len(res.skipped), 1)


if __name__ == "__main__":
    unittest.main()