# core/compare_report.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""比較結果の表示用 HTML を作る（Qt 非依存。比較ウィンドウのサマリ／詳細ペインで使う）。

配色は set_colors() で差し替えられる（ui/theme.py がテーマ適用時に呼ぶ）。
未設定のときはライトテーマ相当の既定値を使うので、単体テストは Qt なしで動く。
文言は core.i18n.t() で現在の言語に翻訳する。
"""

from __future__ import annotations

import html
from typing import Dict, List

from core.comparer import (
    ALL_FLAGS, CompareResult, DiffStatus, DocInfo, FLAG_CHECKSUM_MISMATCH, FieldChange, PackageDiff,
    flag_label, matched_by_label, status_label, version_change_label,
)
from core.i18n import t

_DEFAULT_COLORS: Dict[str, str] = {
    "text": "#1F2937", "muted": "#6B7280", "border": "#C9CED6",
    "danger": "#991B1B", "note": "#92400E",
    "old_bg": "#FDECEC", "new_bg": "#E7F6EC",
    "added_bg": "#E7F6EC", "added_fg": "#166534",
    "removed_bg": "#FDECEC", "removed_fg": "#991B1B",
    "version_changed_bg": "#FEF3C7", "version_changed_fg": "#92400E",
    "modified_bg": "#E0F2FE", "modified_fg": "#075985",
    "unchanged_bg": "#F1F3F6", "unchanged_fg": "#6B7280",
}
_colors: Dict[str, str] = dict(_DEFAULT_COLORS)

# 旧 API 互換（ライト既定の背景色）。新しいコードは _chip() を使う
STATUS_COLORS = {s: _DEFAULT_COLORS[f"{s.value}_bg"] for s in DiffStatus}


def set_colors(colors: Dict[str, str]) -> None:
    _colors.update(colors)


def _c(key: str) -> str:
    return _colors[key]


def _e(s) -> str:
    return html.escape("" if s is None else str(s))


def _signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


def _chip(status: DiffStatus, text: str) -> str:
    v = status.value
    return f"<span style='background:{_c(v + '_bg')};color:{_c(v + '_fg')}'>&nbsp;{_e(text)}&nbsp;</span>"


def _doc_line(tag_key: str, doc: DocInfo) -> str:
    detail = " / ".join(x for x in (doc.name, doc.spdx_version, doc.created) if x)
    count = t("compare.doc.packages", n=doc.package_count)
    return (f"<b>{_e(t(tag_key))}</b> {_e(doc.label)}"
            f"<span style='color:{_c('muted')}'>　{_e(detail)}　({_e(count)})</span>")


def docs_html(result: CompareResult) -> str:
    """A・B 2 つのドキュメント情報（統計カードの上に表示する）"""
    return "<br>".join([_doc_line("compare.doc.a", result.doc_a), _doc_line("compare.doc.b", result.doc_b)])


def summary_html(result: CompareResult) -> str:
    s = result.summary()
    other_ver = s["version_changed"] - s["upgrade"] - s["downgrade"]
    if other_ver:
        ver_text = t("compare.summary.version_changed_other", n=s["version_changed"],
                     up=s["upgrade"], down=s["downgrade"], other=other_ver)
    else:
        ver_text = t("compare.summary.version_changed", n=s["version_changed"],
                     up=s["upgrade"], down=s["downgrade"])
    parts = [
        t("compare.summary.total", a=s["total_a"], b=s["total_b"], diff=_signed(s["total_b"] - s["total_a"])),
        _chip(DiffStatus.ADDED, t("compare.summary.added", n=s["added"])),
        _chip(DiffStatus.REMOVED, t("compare.summary.removed", n=s["removed"])),
        _chip(DiffStatus.VERSION_CHANGED, ver_text),
        _chip(DiffStatus.MODIFIED, t("compare.summary.modified", n=s["modified"])),
        t("compare.summary.unchanged", n=s["unchanged"]),
    ]
    lines = [docs_html(result), "　".join(parts)]
    attention = [f"⚠ {flag_label(k)} {s[k]}" for k in ALL_FLAGS if s.get(k)]
    if attention:
        lines.append(f"<span style='color:{_c('danger')}'><b>{_e('　'.join(attention))}</b></span>")
    return "<br>".join(lines)


def _row(label: str, old: str, new: str) -> str:
    pad = "padding:4px 8px"
    return (f"<tr><td style='{pad}'><b>{_e(label)}</b></td>"
            f"<td style='{pad};background:{_c('old_bg')};color:{_c('text')}'>{old}</td>"
            f"<td style='{pad};background:{_c('new_bg')};color:{_c('text')}'>{new}</td></tr>")


def _scalar_cell(value) -> str:
    if value is None:
        return f"<i style='color:{_c('muted')}'>{_e(t('compare.value.none'))}</i>"
    if value == "":
        return f"<i style='color:{_c('muted')}'>{_e(t('compare.value.empty'))}</i>"
    return _e(value).replace("\n", "<br>")


def _change_rows(fc: FieldChange) -> List[str]:
    if not fc.is_list:
        return [_row(fc.field, _scalar_cell(fc.old), _scalar_cell(fc.new))]
    rows = []
    for x in fc.removed:
        rows.append(_row(fc.field, f"− {_e(x)}", ""))
    for x in fc.added:
        rows.append(_row(fc.field, "", f"＋ {_e(x)}"))
    return rows


def _props_summary(node) -> str:
    """追加／削除パッケージの要点（ツリーで詳細を見る前の目安）"""
    props = getattr(node, "properties", None) or {}
    keys = ("licenseConcluded", "licenseDeclared", "supplier", "downloadLocation", "homepage")
    items = [f"<li>{k}: {_e(props[k])}</li>" for k in keys if props.get(k) not in (None, "")]
    return f"<ul>{''.join(items)}</ul>" if items else ""


def detail_html(diff: PackageDiff, result: CompareResult) -> str:
    out = [
        f"<h3 style='margin-bottom:2px'>{_e(diff.name)}</h3>",
        f"<p style='margin-top:2px'>{_chip(diff.status, status_label(diff.status))}",
    ]
    if diff.matched_by:
        out.append("　" + _e(t("compare.detail.matched", value=matched_by_label(diff.matched_by))))
    out.append("　" + _e(t("compare.detail.key", value=diff.key)) + "</p>")

    if diff.flags:
        mism = FLAG_CHECKSUM_MISMATCH in diff.flags
        out.append(f"<p style='color:{_c('danger')}'><b>⚠ " + _e(" / ".join(flag_label(f) for f in diff.flags)) + "</b>")
        if mism:
            out.append("<br>" + _e(t("compare.detail.checksum_mismatch")))
        out.append("</p>")
    for note in diff.notes:
        out.append(f"<p style='color:{_c('note')}'>ℹ {_e(note)}</p>")

    a_head = f"{_e(t('compare.doc.a'))}<br><small>{_e(result.doc_a.label)}</small>"
    b_head = f"{_e(t('compare.doc.b'))}<br><small>{_e(result.doc_b.label)}</small>"
    rows: List[str] = []
    if diff.status not in (DiffStatus.ADDED, DiffStatus.REMOVED):
        if diff.version_a != diff.version_b:
            kind = version_change_label(diff.version_change)
            rows.append(_row(t("compare.detail.version_row", kind=kind) if kind else "versionInfo",
                             _scalar_cell(diff.version_a or None), _scalar_cell(diff.version_b or None)))
        if diff.spdx_id_a != diff.spdx_id_b:
            rows.append(_row("SPDXID", _scalar_cell(diff.spdx_id_a or None), _scalar_cell(diff.spdx_id_b or None)))
        for fc in diff.field_changes:
            rows.extend(_change_rows(fc))
        if rows:
            out.append(f"<table cellspacing='0' cellpadding='0' border='1' style='border-collapse:collapse;border-color:{_c('border')}'>"
                       f"<tr><th style='padding:4px 8px'>{_e(t('compare.detail.field'))}</th>"
                       f"<th style='padding:4px 8px'>{a_head}</th>"
                       f"<th style='padding:4px 8px'>{b_head}</th></tr>{''.join(rows)}</table>")
        else:
            out.append(f"<p>{_e(t('compare.detail.no_diff'))}</p>")
    else:
        added = diff.status == DiffStatus.ADDED
        ver = diff.version_b if added else diff.version_a
        sid = diff.spdx_id_b if added else diff.spdx_id_a
        none = _e(t("compare.value.none"))
        side = t("compare.doc.b" if added else "compare.doc.a")
        out.append(f"<p>{_e(t('compare.detail.only_in', side=side))}</p>")
        out.append(f"<p>version: {_e(ver) or none}<br>SPDXID: {_e(sid) or none}</p>")
        out.append(_props_summary(diff.node_b if added else diff.node_a))
    return "".join(out)
