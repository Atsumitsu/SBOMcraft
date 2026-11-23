# core/validator.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 SBOMcraft Project
"""
SBOM 適合性検証エンジン（NTIA 最小要件 / CISA 2026 拡張要件）。Qt 非依存。

* 検証ロジックとレポート HTML の生成は、ここだけに置く（旧 validator.py と validator_worker.py の二重実装を統合）。
* core/validator_worker.py は、このモジュールの validate_sbom() をスレッドで呼ぶだけ。
* 画面に出す文言は core.i18n.t() で現在の言語に翻訳する。指摘の code（ERR_xxx / WRN_xxx）は言語に依存しない ID。
* レポートの配色は set_colors() で差し替えられる（ui/theme.py がテーマ適用時に呼ぶ）。未設定ならライト相当の既定値。
"""

from __future__ import annotations

import html
import re
import time
from typing import Any, Callable, Dict, List, Optional

from core.i18n import t

# 未定義・保留値の判定用予約語（小文字比較）
UNKNOWN_VALUES = frozenset({
    "noassertion", "none", "unknown", "organization: unknown", "person: unknown",
})

# 非推奨・弱小ハッシュアルゴリズム（小文字表記）
WEAK_HASH_ALGORITHMS = frozenset({"md5", "sha1", "sha-1"})

# 指摘の ID。文言は locales の validation.issue.<ID>.msg / .fix
ISSUE_CODES = (
    "ERR_CISA_AUTHOR_MISSING", "ERR_CISA_TOOL_MISSING", "WRN_CISA_TOOL_VERSION_MISSING",
    "ERR_CISA_TIMESTAMP_MISSING", "WRN_CISA_CONTEXT_MISSING", "ERR_CISA_RELATION_EMPTY",
    "ERR_NTIA_NAME_MISSING", "ERR_NTIA_VERSION_MISSING", "ERR_NTIA_PROVIDER_MISSING",
    "WRN_CISA_IDENTIFIER_MISSING", "WRN_CISA_HASH_MISSING", "ERR_CISA_WEAK_HASH_ALGORITHM",
    "WRN_CISA_LICENSE_MISSING",
)

_DEFAULT_COLORS: Dict[str, str] = {
    "pass": "#28a745", "fail": "#dc3545", "warn": "#d97706",
    "muted": "#555555", "head_bg": "#f8f9fa", "border": "#dddddd",
}
_colors: Dict[str, str] = dict(_DEFAULT_COLORS)


def set_colors(colors: Dict[str, str]) -> None:
    _colors.update(colors)


StatusCallback = Callable[[str], None]
PercentCallback = Callable[[int], None]


def issue(code: str) -> Dict[str, str]:
    """指摘 1 件（code は言語非依存。msg / fix は現在の言語）。"""
    return {"code": code, "msg": t(f"validation.issue.{code}.msg"), "fix": t(f"validation.issue.{code}.fix")}


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _is_unknown_party(value: Any) -> bool:
    """supplier / originator が未記載または未定義値か。
    ※ 既存の挙動（予約語を『部分一致』で判定）をそのまま維持している。"""
    s = _s(value)
    return (not s) or any(u in s.lower() for u in UNKNOWN_VALUES)


def _is_unknown_value(value: Any) -> bool:
    """name / version / ライセンスなどが未記載または未定義値か（完全一致）。"""
    s = _s(value).strip().lower()
    return (not s) or s in UNKNOWN_VALUES


# ---------------------------------------------------------------------------
# 検証
# ---------------------------------------------------------------------------

def validate_sbom(data: Optional[Dict[str, Any]], profile: str = "CISA2026",
                  status: Optional[StatusCallback] = None,
                  percent: Optional[PercentCallback] = None) -> Dict[str, Any]:
    """
    SPDX 辞書を検証して結果を返す。
    戻り値: {"passed", "report_html", "error_packages", "doc_errors", "doc_warnings", "elapsed", "profile"}
      error_packages の各要素: {"index", "spdx_id", "name", "errors": [issue], "warnings": [issue]}
    status / percent は進捗通知（任意）。
    """
    say = status or (lambda _m: None)
    pct = percent or (lambda _p: None)
    start = time.time()

    if not data:
        say(t("validation.progress.empty"))
        report = f"<font color='red'>{html.escape(t('validation.progress.empty_report'))}</font>"
        return _result(False, profile, time.time() - start, [], [], [], report)

    say(t("validation.progress.parsing"))
    pct(20)
    creation_info = data.get("creationInfo")
    if not isinstance(creation_info, dict):
        creation_info = {}
    creators = [c for c in (creation_info.get("creators") or []) if isinstance(c, str)]
    packages = data.get("packages") or []
    relationships = data.get("relationships") or []
    doc_comment = _s(data.get("comment") or creation_info.get("comment"))
    pct(30)

    doc_errors: List[Dict[str, str]] = []
    doc_warnings: List[Dict[str, str]] = []
    error_packages: List[Dict[str, Any]] = []
    is_cisa = profile.startswith("CISA")

    # ---- ドキュメントレベル（メタデータ） ----
    say(t("validation.progress.doc_check"))
    if is_cisa:
        authors = [c for c in creators if c.startswith("Person:") or c.startswith("Organization:")]
        if not [a for a in authors if a.strip().lower() not in UNKNOWN_VALUES]:
            doc_errors.append(issue("ERR_CISA_AUTHOR_MISSING"))

        tool_creators = [c for c in creators if c.startswith("Tool:")]
        if not tool_creators:
            doc_errors.append(issue("ERR_CISA_TOOL_MISSING"))
        elif not any(re.search(r"[\d\-\/\.\s]", c.replace("Tool:", "")) for c in tool_creators):
            doc_warnings.append(issue("WRN_CISA_TOOL_VERSION_MISSING"))

        created = creation_info.get("created")
        if not created or _s(created).strip().lower() in UNKNOWN_VALUES:
            doc_errors.append(issue("ERR_CISA_TIMESTAMP_MISSING"))

        if not any(ctx in doc_comment.lower() for ctx in ("before build", "build", "after build", "deployed")):
            doc_warnings.append(issue("WRN_CISA_CONTEXT_MISSING"))

        if not relationships:
            doc_errors.append(issue("ERR_CISA_RELATION_EMPTY"))
    pct(40)

    # ---- パッケージレベル ----
    total = len(packages)
    say(t("validation.progress.pkg_start", total=f"{total:,}"))
    update_interval = max(1, total // 20)

    for idx, pkg in enumerate(packages):
        if idx % update_interval == 0 or idx == total - 1:
            p = 40 + int((idx / total) * 50)
            say(t("validation.progress.pkg_progress", done=f"{idx + 1:,}", total=f"{total:,}", pct=p))
            pct(p)
        if not isinstance(pkg, dict):
            continue

        pkg_name = _s(pkg.get("name"))
        pkg_id = pkg.get("SPDXID") or f"Pkg-{idx}"
        errs: List[Dict[str, str]] = []
        warns: List[Dict[str, str]] = []

        if _is_unknown_value(pkg_name):
            errs.append(issue("ERR_NTIA_NAME_MISSING"))
        if _is_unknown_value(pkg.get("versionInfo")):
            errs.append(issue("ERR_NTIA_VERSION_MISSING"))
        if _is_unknown_party(pkg.get("supplier")) and _is_unknown_party(pkg.get("originator")):
            errs.append(issue("ERR_NTIA_PROVIDER_MISSING"))

        if is_cisa:
            ext_refs = [r for r in (pkg.get("externalRefs") or []) if isinstance(r, dict)]
            if not any(r.get("referenceType") in ("purl", "cpe22Type", "cpe23Type") for r in ext_refs):
                warns.append(issue("WRN_CISA_IDENTIFIER_MISSING"))

            has_valid_hash = has_strong_hash = False
            for chk in (pkg.get("checksums") or []):
                if not isinstance(chk, dict):
                    continue
                val = _s(chk.get("checksumValue")).strip().lower()
                algo = _s(chk.get("algorithm")).strip().lower()
                if val and val not in UNKNOWN_VALUES:
                    has_valid_hash = True
                    if algo not in WEAK_HASH_ALGORITHMS:
                        has_strong_hash = True
            if not has_valid_hash:
                warns.append(issue("WRN_CISA_HASH_MISSING"))
            elif not has_strong_hash:
                errs.append(issue("ERR_CISA_WEAK_HASH_ALGORITHM"))

            if _is_unknown_value(pkg.get("licenseConcluded")) and _is_unknown_value(pkg.get("licenseDeclared")):
                warns.append(issue("WRN_CISA_LICENSE_MISSING"))

        if errs or warns:
            error_packages.append({"index": idx, "spdx_id": pkg_id, "name": pkg_name or "Unknown",
                                   "errors": errs, "warnings": warns})

    # ---- レポート ----
    say(t("validation.progress.report"))
    pct(95)
    passed = not doc_errors and not any(p["errors"] for p in error_packages)
    elapsed = time.time() - start
    report = build_report_html(profile, passed, elapsed, doc_errors, doc_warnings, error_packages)
    pct(100)
    say(t("validation.progress.done", sec=f"{elapsed:.2f}"))
    return _result(passed, profile, elapsed, doc_errors, doc_warnings, error_packages, report)


def _result(passed, profile, elapsed, doc_errors, doc_warnings, error_packages, report_html) -> Dict[str, Any]:
    return {"passed": passed, "report_html": report_html, "error_packages": error_packages,
            "doc_errors": doc_errors, "doc_warnings": doc_warnings, "elapsed": elapsed, "profile": profile}


# ---------------------------------------------------------------------------
# レポート HTML
# ---------------------------------------------------------------------------

def _e(value: Any) -> str:
    return html.escape(_s(value))


def build_report_html(profile: str, passed: bool, elapsed: float,
                      doc_errors: List[Dict[str, str]], doc_warnings: List[Dict[str, str]],
                      error_packages: List[Dict[str, Any]]) -> str:
    c = _colors
    status_color = c["pass"] if passed else c["fail"]
    status_text = t("validation.report.pass") if passed else t("validation.report.fail")

    out = [
        '<div style="font-family: sans-serif; line-height: 1.5;">',
        f"<h3>{_e(t('validation.report.title', profile=profile))}</h3>",
        f"<p><b>{_e(t('validation.report.overall'))}</b> "
        f"<span style=\"color: {status_color}; font-weight: bold; font-size: 1.1em;\">{_e(status_text)}</span> "
        f"{_e(t('validation.report.elapsed', sec=f'{elapsed:.3f}'))}</p>",
    ]

    fix_label = _e(t("validation.report.fix_label"))
    if doc_errors or doc_warnings:
        out.append(f"<h4>{_e(t('validation.report.doc_heading'))}</h4><ul>")
        for err in doc_errors:
            out.append(f"<li style='color: {c['fail']}; margin-bottom: 6px;'>❌ <b>[{_e(err['code'])}]</b> {_e(err['msg'])}<br>"
                       f"<span style='color: {c['muted']}; font-size: 0.9em;'>💡 <b>{fix_label}</b> {_e(err['fix'])}</span></li>")
        for warn in doc_warnings:
            out.append(f"<li style='color: {c['warn']}; margin-bottom: 6px;'>⚠️ <b>[{_e(warn['code'])}]</b> {_e(warn['msg'])}<br>"
                       f"<span style='color: {c['muted']}; font-size: 0.9em;'>💡 <b>{fix_label}</b> {_e(warn['fix'])}</span></li>")
        out.append("</ul>")

    if error_packages:
        out.append(f"<h4>{_e(t('validation.report.pkg_heading', n=len(error_packages)))}</h4>")
        out.append(f"<table border='1' cellspacing='0' cellpadding='6' "
                   f"style='border-collapse:collapse; width:100%; border: 1px solid {c['border']};'>")
        out.append(f"<tr bgcolor='{c['head_bg']}'><th>Pkg ID</th><th>{_e(t('validation.report.col_name'))}</th>"
                   f"<th>{_e(t('validation.report.col_errors'))}</th><th>{_e(t('validation.report.col_warnings'))}</th></tr>")
        for p in error_packages:
            err_items = [f"<font color='{c['fail']}'>❌ <b>[{_e(e['code'])}]</b> {_e(e['msg'])}</font><br>"
                         f"<small style='color:{c['muted']};'>💡 {_e(e['fix'])}</small>" for e in p["errors"]]
            warn_items = [f"<font color='{c['warn']}'>⚠️ <b>[{_e(w['code'])}]</b> {_e(w['msg'])}</font><br>"
                          f"<small style='color:{c['muted']};'>💡 {_e(w['fix'])}</small>" for w in p["warnings"]]
            out.append(f"<tr><td><code>{_e(p['spdx_id'])}</code></td><td><b>{_e(p['name'])}</b></td>"
                       f"<td>{'<br><br>'.join(err_items) if err_items else '-'}</td>"
                       f"<td>{'<br><br>'.join(warn_items) if warn_items else '-'}</td></tr>")
        out.append("</table>")
    else:
        out.append(f"<p style='color: {c['pass']};'>{_e(t('validation.report.all_ok'))}</p>")

    out.append("</div>")
    return "".join(out)
