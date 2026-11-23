# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import re

from core.i18n import t
from core.license_manager import SPDXLicenseManager


class LicenseStringValidator:
    """SPDXライセンスリストを使用してライセンス文字列の妥当性をチェックするクラス"""

    UNKNOWN_VALUES = {"noassertion", "none", "unknown", ""}

    def __init__(self, license_manager: SPDXLicenseManager):
        self.license_manager = license_manager

    def validate_license_expression(self, license_str: str) -> dict:
        """
        ライセンス文字列を解析し、有効かどうかを判定する。
        :return: {
            "is_valid": bool,
            "status": "VALID" | "PLACEHOLDER" | "UNKNOWN_LICENSE",   ← 言語に依存しない ID
            "message": str                                            ← 現在の言語の説明
        }
        """
        if not license_str:
            return {
                "is_valid": True,  # 空欄は未定義扱いとしてエラーにはせずメッセージを分ける
                "status": "PLACEHOLDER",
                "message": t("license.msg.unset"),
            }

        cleaned_str = license_str.strip()
        cleaned_lower = cleaned_str.lower()

        # 1. 予約語（NOASSERTION / NONE 等）のチェック
        if cleaned_lower in self.UNKNOWN_VALUES:
            return {
                "is_valid": True,
                "status": "PLACEHOLDER",
                "message": t("license.msg.placeholder", value=cleaned_str),
            }

        # 2. WITH例外が含まれる場合の分解
        if " with " in cleaned_lower:
            parts = re.split(r'\s+with\s+', cleaned_str, flags=re.IGNORECASE)
            base_lic = parts[0].strip()
            exception_id = parts[1].strip() if len(parts) > 1 else ""

            base_valid = self._is_expr_valid(base_lic)
            exc_valid = self.license_manager.is_valid_exception_id(exception_id) if exception_id else True

            if base_valid and exc_valid:
                return {"is_valid": True, "status": "VALID", "message": t("license.msg.valid_with_exception")}
            else:
                return {"is_valid": False, "status": "UNKNOWN_LICENSE",
                        "message": t("license.msg.invalid_with_exception")}

        # 3. 複合式 (AND, OR, 括弧) または単体IDのチェック
        tokens = re.split(r'[\s\(\)]+', cleaned_str)
        invalid_tokens = []

        for token in tokens:
            token_clean = token.strip()
            if not token_clean or token_clean.upper() in {"AND", "OR", "WITH"}:
                continue
            if not self.license_manager.is_valid_spdx_id(token_clean):
                invalid_tokens.append(token_clean)

        if not invalid_tokens:
            return {"is_valid": True, "status": "VALID", "message": t("license.msg.valid")}
        else:
            return {
                "is_valid": False,
                "status": "UNKNOWN_LICENSE",
                "message": t("license.msg.unknown_ids", ids=", ".join(invalid_tokens)),
            }

    def _is_expr_valid(self, expr: str) -> bool:
        if self.license_manager.is_valid_spdx_id(expr):
            return True
        tokens = re.split(r'[\s\(\)]+', expr)
        for tok in tokens:
            tok_clean = tok.strip()
            if not tok_clean or tok_clean.upper() in {"AND", "OR", "WITH"}:
                continue
            if not self.license_manager.is_valid_spdx_id(tok_clean):
                return False
        return True
