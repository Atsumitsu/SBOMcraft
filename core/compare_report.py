# core/compare_report.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""比較結果の表示用 HTML を作る（Qt 非依存。比較ウィンドウのサマリ／詳細ペインで使う）。"""

from __future__ import annotations

import html
from typing import List

from core.comparer import (
    CompareResult, DiffStatus, DocInfo, FLAG_CHECKSUM_MISMATCH, FLAG_LABELS, FieldChange, PackageDiff,
    STATUS_LABELS, VERSION_CHANGE_LABELS,
)

# 明るい背景に暗い文字を明示する（OS のダークテーマでも読めるようにする）
STATUS_COLORS = {
    DiffStatus.ADDED: "#DFF5E1",
    DiffStatus.REMOVED: "#FFD9D9",
    DiffStatus.VERSION_CHANGED: "#FFF0B3",
    DiffStatus.MODIFIED: "#FFF8D6",
    DiffStatus.UNCHANGED: "#FFFFFF",
}
_OLD_BG = "#FFE3E3"
_NEW_BG = "#E1F5E4"
_TEXT = "#000000"


def _e(s) -> str:
    return html.escape("" if s is None else str(s))


def _signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


def _doc_line(tag: str, doc: DocInfo) -> str:
    detail = " / ".join(x for x in (doc.name, doc.spdx_version, doc.created) if x)
    return (f"<b>{_e(tag)}</b> {_e(doc.label)}"
            f"<span style='color:#555555'>　{_e(detail)}　({doc.package_count} packages)</span>")


def summary_html(result: CompareResult) -> str:
    s = result.summary()
    other_ver = s["version_changed"] - s["upgrade"] - s["downgrade"]
    parts = [
        f"パッケージ総数: 旧 {s['total_a']} → 新 {s['total_b']} ({_signed(s['total_b'] - s['total_a'])})",
        f"<span style='background:{STATUS_COLORS[DiffStatus.ADDED]}'>&nbsp;追加 {s['added']}&nbsp;</span>",
        f"<span style='background:{STATUS_COLORS[DiffStatus.REMOVED]}'>&nbsp;削除 {s['removed']}&nbsp;</span>",
        f"<span style='background:{STATUS_COLORS[DiffStatus.VERSION_CHANGED]}'>&nbsp;"
        f"バージョン変更 {s['version_changed']}（↑{s['upgrade']} ↓{s['downgrade']}"
        + (f" その他{other_ver}" if other_ver else "") + ")&nbsp;</span>",
        f"<span style='background:{STATUS_COLORS[DiffStatus.MODIFIED]}'>&nbsp;その他の変更 {s['modified']}&nbsp;</span>",
        f"未変更 {s['unchanged']}",
    ]
    lines = [_doc_line("A（旧）", result.doc_a), _doc_line("B（新）", result.doc_b), "　".join(parts)]
    attention = [f"⚠ {FLAG_LABELS[k]} {s[k]}" for k in FLAG_LABELS if s.get(k)]
    if attention:
        lines.append(f"<span style='color:#B00020'><b>{_e('　'.join(attention))}</b></span>")
    return "<br>".join(lines)


def _row(label: str, old: str, new: str) -> str:
    return (f"<tr><td style='padding:3px 8px'><b>{_e(label)}</b></td>"
            f"<td style='padding:3px 8px;background:{_OLD_BG};color:{_TEXT}'>{old}</td>"
            f"<td style='padding:3px 8px;background:{_NEW_BG};color:{_TEXT}'>{new}</td></tr>")


def _scalar_cell(value) -> str:
    if value is None:
        return "<i style='color:#777777'>（なし）</i>"
    if value == "":
        return "<i style='color:#777777'>（空）</i>"
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
    color = STATUS_COLORS[diff.status]
    out = [
        f"<h3 style='margin-bottom:2px'>{_e(diff.name)}</h3>",
        f"<p style='margin-top:2px'><span style='background:{color};color:{_TEXT}'>&nbsp;{STATUS_LABELS[diff.status]}&nbsp;</span>",
    ]
    if diff.matched_by:
        out.append(f"　突合: {_e(diff.matched_by)}")
    out.append(f"　キー: {_e(diff.key)}</p>")

    if diff.flags:
        mism = FLAG_CHECKSUM_MISMATCH in diff.flags
        out.append("<p style='color:#B00020'><b>⚠ " + _e(" / ".join(FLAG_LABELS[f] for f in diff.flags)) + "</b>")
        if mism:
            out.append("<br>同じバージョンなのに checksum が一致しません。再ビルド・再配布・すり替えの可能性があるため確認してください。")
        out.append("</p>")
    for note in diff.notes:
        out.append(f"<p style='color:#8A5A00'>ℹ {_e(note)}</p>")

    a_head = f"A（旧）<br><small>{_e(result.doc_a.label)}</small>"
    b_head = f"B（新）<br><small>{_e(result.doc_b.label)}</small>"
    rows: List[str] = []
    if diff.status not in (DiffStatus.ADDED, DiffStatus.REMOVED):
        if diff.version_a != diff.version_b:
            kind = VERSION_CHANGE_LABELS.get(diff.version_change, "")
            rows.append(_row(f"versionInfo（{kind}）" if kind else "versionInfo",
                             _scalar_cell(diff.version_a or None), _scalar_cell(diff.version_b or None)))
        if diff.spdx_id_a != diff.spdx_id_b:
            rows.append(_row("SPDXID", _scalar_cell(diff.spdx_id_a or None), _scalar_cell(diff.spdx_id_b or None)))
        for fc in diff.field_changes:
            rows.extend(_change_rows(fc))
        if rows:
            out.append("<table cellspacing='0' cellpadding='0' border='1' style='border-collapse:collapse;border-color:#BBBBBB'>"
                       f"<tr><th style='padding:3px 8px'>項目</th><th style='padding:3px 8px'>{a_head}</th>"
                       f"<th style='padding:3px 8px'>{b_head}</th></tr>{''.join(rows)}</table>")
        else:
            out.append("<p>比較対象の項目に差分はありません。</p>")
    else:
        added = diff.status == DiffStatus.ADDED
        ver = diff.version_b if added else diff.version_a
        sid = diff.spdx_id_b if added else diff.spdx_id_a
        out.append(f"<p>{'B（新）' if added else 'A（旧）'} にのみ存在します。</p>")
        out.append(f"<p>version: {_e(ver) or '（なし）'}<br>SPDXID: {_e(sid) or '（なし）'}</p>")
        out.append(_props_summary(diff.node_b if added else diff.node_a))
    return "".join(out)
