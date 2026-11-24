# test/test_serializer_i18n.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""core/serializer.py の警告・エラー文言の多言語化テスト（Qt 不要）。 実行: python -m unittest discover -s test -v"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import i18n
from core import serializer as ser


def setUpModule():
    i18n.set_language("ja")


def tearDownModule():
    i18n.set_language("ja")


def bad_doc():
    return {
        "spdxVersion": "SPDX-2.2", "SPDXID": "SPDXRef-DOCUMENT",
        "packages": [{"SPDXID": "bad id", "name": "a", "downloadLocation": "", "filesAnalyzed": "yes"}],
        "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                           "relatedSpdxElement": "SPDXRef-Nope"}],
        "hasExtractedLicensingInfos": [{"licenseId": "x"}],
    }


class SerializerI18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("ja")

    def test_same_number_of_warnings_in_both_languages(self):
        ja = ser.validate_spdx_document(bad_doc())
        i18n.set_language("en")
        en = ser.validate_spdx_document(bad_doc())
        self.assertEqual(len(ja), len(en))
        self.assertGreater(len(ja), 5)
        self.assertNotEqual(ja, en)

    def test_messages_in_each_language(self):
        ja = " ".join(ser.validate_spdx_document(bad_doc()))
        self.assertIn("必須項目 'name' がありません", ja)
        self.assertIn("存在しない SPDXID を参照しています", ja)
        i18n.set_language("en")
        en = " ".join(ser.validate_spdx_document(bad_doc()))
        self.assertIn("The required field 'name' is missing", en)
        self.assertIn("refers to an SPDXID that does not exist", en)

    def test_no_untranslated_keys_leak(self):
        for lang in ("ja", "en"):
            i18n.set_language(lang)
            for msg in ser.validate_spdx_document(bad_doc()):
                self.assertNotIn("serializer.", msg)

    def test_warning_limit_message(self):
        doc = {"packages": [{"name": f"p{i}"} for i in range(40)]}          # 警告が 50 件を超える
        msgs = ser.validate_spdx_document(doc)
        self.assertEqual(len(msgs), 51)
        self.assertIn("省略", msgs[-1])
        i18n.set_language("en")
        self.assertIn("omitted", ser.validate_spdx_document(doc)[-1])

    def test_convert_value_errors_follow_language(self):
        with self.assertRaises(ValueError) as cm:
            ser.convert_value(True, "maybe")
        self.assertIn("true または false", str(cm.exception))
        i18n.set_language("en")
        with self.assertRaises(ValueError) as cm:
            ser.convert_value(1, "x")
        self.assertIn("Enter an integer", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            ser.apply_flat_rows({"a": 1.5}, [("a", "zzz")])
        self.assertIn("Enter a number", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
