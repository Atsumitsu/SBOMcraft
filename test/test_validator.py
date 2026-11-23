# test/test_validator.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 SBOMcraft Project
"""core/validator.py のテスト（Qt 不要）。 実行: python -m unittest discover -s test -v"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import i18n
from core import validator as v


def setUpModule():
    i18n.set_language("ja")


def tearDownModule():
    i18n.set_language("ja")


def good_pkg(**extra):
    p = {
        "SPDXID": "SPDXRef-P1", "name": "pkg", "versionInfo": "1.0",
        "supplier": "Organization: Example",
        "licenseConcluded": "MIT",
        "checksums": [{"algorithm": "SHA256", "checksumValue": "ab" * 32}],
        "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                          "referenceLocator": "pkg:pypi/pkg@1.0"}],
    }
    p.update(extra)
    return p


def good_doc(**extra):
    d = {
        "comment": "Generation Context: build",
        "creationInfo": {"created": "2026-01-01T00:00:00Z",
                         "creators": ["Organization: Example", "Tool: SBOMcraft-1.0"]},
        "packages": [good_pkg()],
        "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                           "relatedSpdxElement": "SPDXRef-P1"}],
    }
    d.update(extra)
    return d


def codes(items):
    return [i["code"] for i in items]


class ValidateTest(unittest.TestCase):
    def test_good_document_passes(self):
        r = v.validate_sbom(good_doc())
        self.assertTrue(r["passed"])
        self.assertEqual(r["error_packages"], [])
        self.assertEqual(r["doc_errors"], [])

    def test_missing_author_tool_timestamp_relationships(self):
        d = good_doc(relationships=[])
        d["creationInfo"] = {"creators": []}
        r = v.validate_sbom(d)
        self.assertFalse(r["passed"])
        self.assertEqual(set(codes(r["doc_errors"])),
                         {"ERR_CISA_AUTHOR_MISSING", "ERR_CISA_TOOL_MISSING",
                          "ERR_CISA_TIMESTAMP_MISSING", "ERR_CISA_RELATION_EMPTY"})

    def test_ntia_profile_skips_document_checks(self):
        d = good_doc(relationships=[])
        d["creationInfo"] = {}
        r = v.validate_sbom(d, profile="NTIA")
        self.assertTrue(r["passed"])

    def test_package_errors(self):
        d = good_doc(packages=[good_pkg(name="", versionInfo="NOASSERTION", supplier="NOASSERTION")])
        r = v.validate_sbom(d)
        self.assertFalse(r["passed"])
        self.assertEqual(set(codes(r["error_packages"][0]["errors"])),
                         {"ERR_NTIA_NAME_MISSING", "ERR_NTIA_VERSION_MISSING", "ERR_NTIA_PROVIDER_MISSING"})

    def test_weak_hash_only_is_error_but_strong_present_is_ok(self):
        weak = [{"algorithm": "SHA1", "checksumValue": "ab" * 20}, {"algorithm": "MD5", "checksumValue": "cd" * 16}]
        r = v.validate_sbom(good_doc(packages=[good_pkg(checksums=weak)]))
        self.assertIn("ERR_CISA_WEAK_HASH_ALGORITHM", codes(r["error_packages"][0]["errors"]))
        r = v.validate_sbom(good_doc(packages=[good_pkg(checksums=weak + [
            {"algorithm": "SHA256", "checksumValue": "ab" * 32}])]))
        self.assertTrue(r["passed"])

    def test_warnings_do_not_fail(self):
        p = good_pkg(licenseConcluded="NOASSERTION")
        del p["checksums"], p["externalRefs"]
        r = v.validate_sbom(good_doc(packages=[p]))
        self.assertTrue(r["passed"])
        self.assertEqual(set(codes(r["error_packages"][0]["warnings"])),
                         {"WRN_CISA_IDENTIFIER_MISSING", "WRN_CISA_HASH_MISSING", "WRN_CISA_LICENSE_MISSING"})

    def test_empty_data_and_no_packages(self):
        r = v.validate_sbom({})
        self.assertFalse(r["passed"])
        self.assertIn("エラー", r["report_html"])
        r = v.validate_sbom(good_doc(packages=[]))          # 0 件でもゼロ除算しない
        self.assertTrue(r["passed"])

    def test_malformed_entries_do_not_crash(self):
        d = good_doc(packages=[None, "x", good_pkg(checksums=["bad", None], externalRefs="oops")])
        d["creationInfo"] = {"creators": [None, 5, "Organization: A", "Tool: T-1"], "created": "2026-01-01T00:00:00Z"}
        v.validate_sbom(d)

    def test_progress_callbacks(self):
        pcts, msgs = [], []
        v.validate_sbom(good_doc(), status=msgs.append, percent=pcts.append)
        self.assertEqual(pcts[-1], 100)
        self.assertEqual(pcts, sorted(pcts))
        self.assertTrue(msgs)


class LanguageAndReportTest(unittest.TestCase):
    def test_issue_codes_exist_in_both_languages(self):
        for lang in ("ja", "en"):
            cat = i18n.catalog(lang)
            for code in v.ISSUE_CODES:
                self.assertIn(f"validation.issue.{code}.msg", cat)
                self.assertIn(f"validation.issue.{code}.fix", cat)

    def test_messages_follow_ui_language_but_codes_do_not(self):
        d = good_doc()
        d["creationInfo"] = {}
        try:
            i18n.set_language("en")
            en = v.validate_sbom(d)
            i18n.set_language("ja")
            ja = v.validate_sbom(d)
        finally:
            i18n.set_language("ja")
        self.assertEqual(codes(en["doc_errors"]), codes(ja["doc_errors"]))
        self.assertIn("author", en["doc_errors"][0]["msg"])
        self.assertIn("作成者", ja["doc_errors"][0]["msg"])
        self.assertIn("Non-conformant", en["report_html"])
        self.assertIn("不適合", ja["report_html"])

    def test_report_escapes_package_name(self):
        r = v.validate_sbom(good_doc(packages=[good_pkg(name="<b>x</b>", versionInfo="")]))
        self.assertNotIn("<b>x</b>", r["report_html"])
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", r["report_html"])

    def test_set_colors(self):
        v.set_colors({"pass": "#010203"})
        try:
            self.assertIn("#010203", v.validate_sbom(good_doc())["report_html"])
        finally:
            v.set_colors(v._DEFAULT_COLORS)


if __name__ == "__main__":
    unittest.main()
