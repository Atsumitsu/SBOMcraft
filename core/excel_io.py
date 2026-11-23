# core/excel_io.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""
Packages の Excel 出力 / 取り込み（Phase 1: スカラー項目のみ）。

Qt には依存しない（ノードは node_type / properties / children を持つ duck-typing で扱う）ため、
単体テストが容易。core/serializer.py と同じ方針。

設計の要点
----------
* 出力: Packages シート（1パッケージ=1行）と _meta シート（書式バージョン・説明）を作る。
  すべてのセルをテキスト書式(@)かつ文字列型で書くので、Excel による自動型変換
  （1.10 → 1.1、ハッシュ → 指数表記、先頭 '=' の数式化）を避けられる。
* 取り込み: 「Excel の値」と「現在のメモリ上の SBOM」を比較して **差分(CellChange)だけ** を作る。
  パッケージを作り直さないので、Excel に出していない項目（checksums / externalRefs /
  annotations 等）や元のキー順は変更されない。
* 行の主キーは SPDXID。並べ替え・フィルタ・列の並べ替え/削除をしても壊れない。
  Excel に無い行・列は「変更なし」と扱い、削除はしない。
* 変更のなかったセルは検証しない（元データが仕様違反でも、触らなければエラーにならない）。

Phase 2: 入れ子の一覧（checksums / externalRefs）は別シート（Checksums / ExternalRefs）に
1 要素 = 1 行で出力する。取り込みは『パッケージ単位の一覧』として扱う:
* 同じ SPDXID の行の集合 = そのパッケージの一覧。シートに現れないパッケージは変更しない。
* 既存要素との突合は『内容が同じ行』で行う（順序非依存）ので、並べ替えても差分にならない。
  行の削除 = 要素の削除、行の追加 = 要素の追加、値の変更 = 削除 + 追加。
* 内容が変わっていない要素は元の dict をそのまま残す（Excel に出していないキーも保持される）。
* 新規・変更された要素だけを検証し、エラーがあればその一覧（パッケージ単位）は反映しない。

多言語化（Phase 3）:
* Excel ファイルは共有される前提なので、ファイルに書く説明（_meta のガイド・列見出しのコメント・
  入力規則のメッセージ）は常に『日本語 / English』の併記にする（UI 言語に依存しない）。
  列見出し（SPDXID, name ...）は SPDX のキー名なので翻訳しない（取り込み時の突合に使う）。
* 取り込みの結果として画面に出すメッセージ（ImportIssue など）は UI 言語（t()）で出す。
* 『未出力』マーカーは取り込み時に文字列一致で判定するため、言語に依存しない固定文字列にする。
  旧バージョンが出力したマーカーも受理する。
"""

from __future__ import annotations

import copy
import datetime as _dt
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from core.i18n import t, t_in
from core.serializer import PACKAGE_PRIORITY_KEYS   # 列順は DetailPanel の表示順と共通

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

FORMAT_VERSION = 2          # 2: Checksums / ExternalRefs シートを追加（Phase 2）
SHEET_META = "_meta"
SHEET_PACKAGES = "Packages"
SHEET_CHECKSUMS = "Checksums"
SHEET_EXTERNALREFS = "ExternalRefs"

MAX_CELL_CHARS = 32767          # Excel のセル文字数上限
# 言語に依存しない固定文字列（日英併記）。取り込み時に一致判定するので、安易に変更しないこと。
TOO_LONG_MARKER = "⚠[TRUNCATED >32767 chars / 32767文字超・未出力]"
# 以前のバージョンが出力したマーカー（取り込み時のみ受理する）
LEGACY_TOO_LONG_MARKERS: Tuple[str, ...] = ("⚠(32767文字超のため未出力・取り込み時は無視されます)",)
_MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024   # zip 爆弾対策
_MAX_ZIP_ENTRIES = 10_000

META_KEYS = (
    "formatVersion", "tool", "toolVersion", "exportedAt",
    "documentName", "documentNamespace", "packageCount", "editRevision",
)

PRIMARY_PACKAGE_PURPOSES: Tuple[str, ...] = (
    "APPLICATION", "FRAMEWORK", "LIBRARY", "CONTAINER", "OPERATING-SYSTEM",
    "DEVICE", "FIRMWARE", "SOURCE", "ARCHIVE", "FILE", "INSTALL", "OTHER",
)

# Packages シートの列にしない（入れ子構造）キー。データ側にスカラーで入っていても列にしない。
# checksums / externalRefs は専用シート、それ以外は Excel では扱わない（常に保持される）。
NON_SCALAR_KEYS = frozenset({
    "checksums", "externalRefs", "attributionTexts", "licenseInfoFromFiles",
    "hasFiles", "annotations", "packageVerificationCode",
})


def _is_too_long_marker(value: Any) -> bool:
    return isinstance(value, str) and (value == TOO_LONG_MARKER or value in LEGACY_TOO_LONG_MARKERS)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str = "str"            # str / bool / enum / date / int / float
    required: bool = False
    readonly: bool = False
    choices: Tuple[str, ...] = ()
    extra_choices: Tuple[str, ...] = ()   # 入力は受け付けるが、プルダウンには出さない（旧表記など）
    suggestions: Tuple[str, ...] = ()     # プルダウン候補（候補以外も入力可）
    width: int = 24
    help: str = ""                        # メッセージカタログのキー（例: "excel.help.name"）。出力時に日英併記にする


# 列の並び順 = このリストの順（未知のスカラーキーは末尾にアルファベット順で追加）
PACKAGE_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec("SPDXID", readonly=True, width=34, help="excel.help.spdxid"),
    FieldSpec("name", required=True, width=28, help="excel.help.name"),
    FieldSpec("versionInfo", width=14, help="excel.help.version"),
    FieldSpec("supplier", width=30, help="excel.help.supplier"),
    FieldSpec("originator", width=30, help="excel.help.originator"),
    FieldSpec("downloadLocation", required=True, width=36, help="excel.help.download"),
    FieldSpec("filesAnalyzed", kind="bool", width=14, help="excel.help.files_analyzed"),
    FieldSpec("licenseConcluded", width=26, help="excel.help.license"),
    FieldSpec("licenseDeclared", width=26, help="excel.help.license"),
    FieldSpec("packageFileName", width=24, help="excel.help.package_file_name"),
    FieldSpec("homepage", width=34, help="excel.help.homepage"),
    FieldSpec("copyrightText", width=36, help="excel.help.copyright"),
    FieldSpec("summary", width=40, help="excel.help.summary"),
    FieldSpec("description", width=50, help="excel.help.description"),
    FieldSpec("comment", width=36, help="excel.help.comment"),
    FieldSpec("sourceInfo", width=30, help="excel.help.source_info"),
    FieldSpec("licenseComments", width=30, help="excel.help.license_comments"),
    FieldSpec("primaryPackagePurpose", kind="enum", choices=PRIMARY_PACKAGE_PURPOSES,
              width=24, help="excel.help.purpose"),
    FieldSpec("releaseDate", kind="date", width=22, help="excel.help.date"),
    FieldSpec("builtDate", kind="date", width=22, help="excel.help.date"),
    FieldSpec("validUntilDate", kind="date", width=22, help="excel.help.date"),
]
# 列順は『PACKAGE_PRIORITY_KEYS の順 → 残りの既知キー（上のリスト順）』に揃える
PACKAGE_FIELD_SPECS.sort(key=lambda sp: (PACKAGE_PRIORITY_KEYS.index(sp.key)
                                         if sp.key in PACKAGE_PRIORITY_KEYS else len(PACKAGE_PRIORITY_KEYS)))
_KNOWN_SPECS: Dict[str, FieldSpec] = {s.key: s for s in PACKAGE_FIELD_SPECS}

# --- Phase 2: 一覧シート（Checksums / ExternalRefs） ---------------------------------

CHECKSUM_ALGORITHMS: Tuple[str, ...] = (
    "SHA1", "SHA224", "SHA256", "SHA384", "SHA512", "SHA3-256", "SHA3-384", "SHA3-512",
    "BLAKE2b-256", "BLAKE2b-384", "BLAKE2b-512", "BLAKE3", "MD2", "MD4", "MD5", "MD6", "ADLER32",
)
# 16進数の桁数が固定のアルゴリズム（BLAKE3 / MD6 は可変長のため桁数チェックしない）
_HASH_HEX_LENGTHS: Dict[str, int] = {
    "SHA1": 40, "SHA224": 56, "SHA256": 64, "SHA384": 96, "SHA512": 128,
    "SHA3-256": 64, "SHA3-384": 96, "SHA3-512": 128,
    "BLAKE2b-256": 64, "BLAKE2b-384": 96, "BLAKE2b-512": 128,
    "MD2": 32, "MD4": 32, "MD5": 32, "ADLER32": 8,
}
REFERENCE_CATEGORIES: Tuple[str, ...] = ("SECURITY", "PACKAGE-MANAGER", "PERSISTENT-ID", "OTHER")
LEGACY_REFERENCE_CATEGORIES: Tuple[str, ...] = ("PACKAGE_MANAGER", "PERSISTENT_ID")   # SPDX 2.2 の表記
# SPDX 2.3 で定義済みの referenceType と、その通常のカテゴリ
KNOWN_REFERENCE_TYPES: Dict[str, str] = {
    "cpe22Type": "SECURITY", "cpe23Type": "SECURITY", "advisory": "SECURITY",
    "fix": "SECURITY", "url": "SECURITY", "swid": "SECURITY",
    "maven-central": "PACKAGE-MANAGER", "npm": "PACKAGE-MANAGER", "nuget": "PACKAGE-MANAGER",
    "bower": "PACKAGE-MANAGER", "purl": "PACKAGE-MANAGER",
    "swh": "PERSISTENT-ID", "gitoid": "PERSISTENT-ID",
}
# referenceType ごとに referenceLocator が満たすべき接頭辞
_REF_LOCATOR_PREFIX: Dict[str, str] = {"purl": "pkg:", "cpe23Type": "cpe:2.3:", "cpe22Type": "cpe:/"}


@dataclass(frozen=True)
class ListSheetSpec:
    sheet: str
    list_key: str                       # properties 上のキー
    columns: Tuple[FieldSpec, ...]      # SPDXID / name 以外の列


CHECKSUM_SHEET_SPEC = ListSheetSpec(SHEET_CHECKSUMS, "checksums", (
    FieldSpec("algorithm", kind="enum", required=True, choices=CHECKSUM_ALGORITHMS, width=16,
              help="excel.help.algorithm"),
    FieldSpec("checksumValue", required=True, width=72, help="excel.help.checksum_value"),
))
EXTERNALREFS_SHEET_SPEC = ListSheetSpec(SHEET_EXTERNALREFS, "externalRefs", (
    FieldSpec("referenceCategory", kind="enum", required=True, choices=REFERENCE_CATEGORIES,
              extra_choices=LEGACY_REFERENCE_CATEGORIES, width=20, help="excel.help.ref_category"),
    FieldSpec("referenceType", required=True, width=18, suggestions=tuple(KNOWN_REFERENCE_TYPES),
              help="excel.help.ref_type"),
    FieldSpec("referenceLocator", required=True, width=60, help="excel.help.ref_locator"),
    FieldSpec("comment", width=36, help="excel.help.list_comment"),
))
LIST_SHEET_SPECS: Tuple[ListSheetSpec, ...] = (CHECKSUM_SHEET_SPEC, EXTERNALREFS_SHEET_SPEC)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_AGENT_RE = re.compile(r"^(Person|Organization): \S.*$", re.DOTALL)
_DATE_FMT = "%Y-%m-%dT%H:%M:%SZ"


class WorkbookFormatError(Exception):
    """取り込めない Excel ファイル（形式・構造の問題）。メッセージはそのまま画面に出せる。"""


class ImportCanceled(Exception):
    """ユーザー操作による中断。"""


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------

@dataclass
class ImportIssue:
    level: str       # "error"（その変更は適用しない） / "warning"（適用するが要確認） / "info"
    where: str       # 例: "Packages!C5" / "_meta"
    message: str


@dataclass
class CellChange:
    spdx_id: str
    package_name: str
    field: str
    old: Any                 # 変更前の値（未設定なら None）
    new: Any                 # 変更後の値（削除なら None）
    op: str                  # "set" / "add"（キー新規追加） / "delete"
    cell: str                # 例: "C5"
    node: Any = field(default=None, repr=False, compare=False)
    # --- 一覧（checksums / externalRefs）の変更のとき ---
    kind: str = "scalar"                                   # "scalar" / "list"
    added: List[Any] = field(default_factory=list, compare=False)     # 追加される要素
    removed: List[Any] = field(default_factory=list, compare=False)   # 削除される要素


@dataclass
class ImportPlan:
    changes: List[CellChange] = field(default_factory=list)
    issues: List[ImportIssue] = field(default_factory=list)
    rows_total: int = 0
    rows_matched: int = 0
    list_stats: Dict[str, int] = field(default_factory=dict)   # シート名 → 突合できたパッケージ数

    @property
    def packages_changed(self) -> int:
        return len({id(c.node) for c in self.changes})

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")


@dataclass
class RowData:
    row: int                                   # Excel の行番号（1 始まり）
    values: Dict[str, Any]                     # 見出し名 → セル値
    formula_cols: frozenset = frozenset()      # 数式セルだった見出し名


@dataclass
class ParsedTable:
    headers: Dict[str, int]                    # 見出し名 → 0 始まりの列番号
    rows: List[RowData]
    duplicate_headers: List[str] = field(default_factory=list)


@dataclass
class ParsedWorkbook:
    meta: Dict[str, Any]
    headers: Dict[str, int]                    # Packages シート: 見出し名 → 0 始まりの列番号
    rows: List[RowData]
    duplicate_headers: List[str] = field(default_factory=list)
    child_tables: Dict[str, ParsedTable] = field(default_factory=dict)   # Checksums / ExternalRefs
    child_errors: Dict[str, str] = field(default_factory=dict)           # 読み込めなかった一覧シート


@dataclass
class ApplyResult:
    applied: List[CellChange] = field(default_factory=list)
    skipped: List[Tuple[CellChange, str]] = field(default_factory=list)
    nodes: List[Any] = field(default_factory=list)   # 値が変わったノード（重複なし）


@dataclass
class ExportResult:
    package_count: int
    column_count: int
    list_rows: Dict[str, int] = field(default_factory=dict)   # シート名 → 出力した要素数


# ---------------------------------------------------------------------------
# 共通ヘルパー
# ---------------------------------------------------------------------------

def _bi(key: str, sep: str = " / ", **params) -> str:
    """UI 言語に関係なく『日本語 / English』の 2 言語併記にする（Excel ファイルは共有されるため）。
    日英で同じ文字列（SECURITY / PACKAGE-MANAGER ... など）のときは 1 つだけ返す。"""
    ja, en = t_in("ja", key, **params), t_in("en", key, **params)
    return ja if ja == en else f"{ja}{sep}{en}"


def iter_package_nodes(root_node) -> Iterator[Any]:
    """ツリーから package ノードを元の順序で列挙する（serializer と同じ走査）。"""
    if root_node is None:
        return
    for folder in root_node.children:
        for node in folder.children:
            if node.node_type == "package":
                yield node


def _document_properties(root_node) -> Dict[str, Any]:
    doc_info = next((c for c in root_node.children if c.node_type == "document_info"), None)
    return doc_info.properties if doc_info is not None else root_node.properties


def _nl(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _export_text(value: Any) -> Optional[str]:
    """メモリ上の値 → セルに書くテキスト（比較にも使う正規形）。None は None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    s = value if isinstance(value, str) else str(value)
    return ILLEGAL_CHARACTERS_RE.sub("", s)


def _kind_from_value(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def collect_columns(pkg_nodes: Iterable[Any]) -> List[FieldSpec]:
    """出力する列を決める: 既知の列（常に出す） + データ中に存在する未知のスカラーキー。"""
    extra: Dict[str, str] = {}
    for node in pkg_nodes:
        for key, val in node.properties.items():
            if key in _KNOWN_SPECS or key in NON_SCALAR_KEYS or key in extra:
                continue
            if isinstance(val, (dict, list)):
                continue
            extra[key] = _kind_from_value(val)
    cols = list(PACKAGE_FIELD_SPECS)
    for key in sorted(extra):
        cols.append(FieldSpec(key, kind=extra[key], width=24, help="excel.help.custom"))
    return cols


# ---------------------------------------------------------------------------
# 1. 出力
# ---------------------------------------------------------------------------

_FONT = Font(name="Arial", size=10)
_FONT_BOLD = Font(name="Arial", size=10, bold=True)
_FONT_TITLE = Font(name="Arial", size=14, bold=True)
_FONT_HEAD = Font(name="Arial", size=10, bold=True, color="FFFFFF")
_FILL_HEAD = PatternFill("solid", start_color="1F3864", end_color="1F3864")
_FILL_HEAD_RO = PatternFill("solid", start_color="595959", end_color="595959")
_FILL_RO = PatternFill("solid", start_color="EDEDED", end_color="EDEDED")
_ALIGN_TOP = Alignment(vertical="top")


def _text_cell(ws, text: Optional[str], *, font=_FONT, fill=None, align=_ALIGN_TOP) -> WriteOnlyCell:
    """常に『文字列型・テキスト書式』で書くセル。'=' で始まる値も数式にならない。"""
    c = WriteOnlyCell(ws, value=text)
    if text is not None:
        c.data_type = "s"          # value 代入時に '=' が数式扱いされるのを打ち消す
    c.number_format = "@"
    c.font = font
    if fill is not None:
        c.fill = fill
    c.alignment = align
    return c


def _head_cell(ws, spec: FieldSpec) -> WriteOnlyCell:
    """見出しセル。見出し文字列は SPDX のキー名（翻訳しない）。説明はコメントに日英併記で付ける。"""
    c = _text_cell(ws, spec.key, font=_FONT_HEAD, fill=_FILL_HEAD_RO if spec.readonly else _FILL_HEAD)
    if spec.help:
        cm = Comment(_bi(spec.help, sep="\n"), "SBOMcraft")
        cm.width, cm.height = 320, 110
        c.comment = cm
    return c


def _cell_text_for(props: Dict[str, Any], key: str) -> Optional[str]:
    if key not in props:
        return None
    val = props[key]
    if isinstance(val, (dict, list)):
        return None
    text = _export_text(val)
    if text is None or text == "":
        return None
    # 改行は LF に統一して書く（Excel のセル内改行も LF）。CR を含めると、環境（lxml の有無・OS・ライブラリの版）に
    # よって XML への書き出し／読み戻しで改行が増減することがある。取り込み側の比較は _nl() で CRLF/CR も LF に揃える。
    text = _nl(text)
    if len(text) > MAX_CELL_CHARS:
        return TOO_LONG_MARKER
    return text


# ガイドの行 ID（"8b" は 8 の続きの行）
_GUIDE_IDS = ("1", "2", "3", "4", "5", "6", "7", "8", "8b", "9", "10", "11")

# (項目, 例, 備考)。備考が '@' で始まるときはメッセージカタログのキー（日英併記にする）、それ以外はそのまま出す。
_FORMAT_EXAMPLES = [
    ("supplier / originator", "Organization: Example Corp", "Person: Taro Yamada (taro@example.com) / NOASSERTION"),
    ("filesAnalyzed", "true", "@excel.example.note.bool"),
    ("licenseConcluded / licenseDeclared", "Apache-2.0 AND MIT", "@excel.example.note.license"),
    ("primaryPackagePurpose", "LIBRARY", "APPLICATION, FRAMEWORK, LIBRARY, CONTAINER, OPERATING-SYSTEM, ..."),
    ("releaseDate / builtDate", "2026-01-31T00:00:00Z", "YYYY-MM-DDThh:mm:ssZ (UTC)"),
    ("algorithm / checksumValue", "SHA256 / e3b0c44298fc1c14... (64 digits)", "@excel.example.note.hash"),
    ("referenceCategory / referenceType", "PACKAGE-MANAGER / purl", "SECURITY, PACKAGE-MANAGER, PERSISTENT-ID, OTHER"),
    ("referenceLocator", "pkg:pypi/requests@2.32.0", "@excel.example.note.locator"),
]


def _example_note(note: str) -> str:
    return _bi(note[1:]) if note.startswith("@") else note


def _write_meta_sheet(ws, nodes: List[Any], root_node, app_version: str, edit_revision: int) -> None:
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 60
    doc = _document_properties(root_node)
    exported_at = _dt.datetime.now(_dt.timezone.utc).strftime(_DATE_FMT)
    meta_values = {
        "formatVersion": str(FORMAT_VERSION),
        "tool": "SBOMcraft",
        "toolVersion": str(app_version or ""),
        "exportedAt": exported_at,
        "documentName": str(doc.get("name", "") or ""),
        "documentNamespace": str(doc.get("documentNamespace", "") or ""),
        "packageCount": str(len(nodes)),
        "editRevision": str(int(edit_revision)),
    }

    ws.append([_text_cell(ws, _bi("excel.meta.title"), font=_FONT_TITLE)])
    ws.append([])
    for key in META_KEYS:
        ws.append([_text_cell(ws, key, font=_FONT_BOLD, fill=_FILL_RO),
                   _text_cell(ws, _export_text(meta_values[key]) or None)])
    ws.append([])
    ws.append([_text_cell(ws, _bi("excel.meta.guide_heading"), font=_FONT_BOLD)])
    for lang, label in (("ja", "【日本語】"), ("en", "[English]")):     # 日本語ブロック → 英語ブロック
        ws.append([_text_cell(ws, label, font=_FONT_BOLD)])
        for gid in _GUIDE_IDS:
            ws.append([_text_cell(ws, t_in(lang, f"excel.guide.{gid}"))])
    ws.append([])
    ws.append([_text_cell(ws, _bi("excel.meta.examples_heading"), font=_FONT_BOLD)])
    ws.append([_text_cell(ws, _bi("excel.meta.col_field"), font=_FONT_HEAD, fill=_FILL_HEAD),
               _text_cell(ws, _bi("excel.meta.col_example"), font=_FONT_HEAD, fill=_FILL_HEAD),
               _text_cell(ws, _bi("excel.meta.col_note"), font=_FONT_HEAD, fill=_FILL_HEAD)])
    for name, example, note in _FORMAT_EXAMPLES:
        ws.append([_text_cell(ws, name), _text_cell(ws, example), _text_cell(ws, _example_note(note))])


def _write_packages_sheet(ws, nodes: List[Any], columns: List[FieldSpec]) -> None:
    # write_only モードでは、列幅・ウィンドウ枠固定は最初の append より前に設定する
    ws.freeze_panes = "C2"
    for idx, spec in enumerate(columns, start=1):
        dim = ws.column_dimensions[get_column_letter(idx)]
        dim.width = spec.width
        dim.number_format = "@"        # 後から入力したセルもテキスト扱いにする

    ws.append([_head_cell(ws, spec) for spec in columns])

    for node in nodes:
        props = node.properties
        row = []
        for spec in columns:
            row.append(_text_cell(ws, _cell_text_for(props, spec.key),
                                  fill=_FILL_RO if spec.readonly else None))
        ws.append(row)

    last_row = len(nodes) + 1
    last_col = get_column_letter(len(columns))
    ws.auto_filter.ref = f"A1:{last_col}{last_row}"

    if nodes:
        for idx, spec in enumerate(columns, start=1):
            if spec.kind == "bool":
                _add_list_validation(ws, get_column_letter(idx), ("true", "false"), last_row,
                                     strict=True, label=spec.key)
            elif spec.kind == "enum" and spec.choices:
                _add_list_validation(ws, get_column_letter(idx), spec.choices, last_row,
                                     strict=True, label=spec.key)


_DV_EXTRA_ROWS = 1000     # 一覧シートは行を追加できるので、入力規則を末尾の先まで広げておく


def _add_list_validation(ws, letter: str, items, last_row: int, *, strict: bool, label: str) -> None:
    """プルダウン（リスト形式の入力規則）。strict=False は候補以外の入力も許可する。
    エラーメッセージはファイルに残るので日英併記。Excel の上限（タイトル 32 文字・本文 255 文字）に収める。"""
    formula = '"' + ",".join(items) + '"'
    if len(formula) > 255:                      # Excel の上限。超えるとファイルが壊れる
        return
    msg = _bi("excel.dv.choose", label=label) + ": " + ", ".join(items)
    if not strict:
        msg += " " + _bi("excel.dv.free")
    title = _bi("excel.dv.title_error" if strict else "excel.dv.title_confirm")
    dv = DataValidation(type="list", formula1=formula, allow_blank=True, showErrorMessage=True,
                        errorStyle="stop" if strict else "information",
                        errorTitle=title[:32],
                        error=msg[:255])
    dv.add(f"{letter}2:{letter}{last_row}")
    ws.data_validations.append(dv)              # WriteOnlyWorksheet に add_data_validation は無い


def _list_entries_or_none(node, list_key: str) -> Optional[List[Dict[str, Any]]]:
    """標準的な構造（dict の配列）なら要素のリスト、未設定なら []、非標準な構造なら None。"""
    val = node.properties.get(list_key)
    if val is None:
        return []
    if isinstance(val, list) and all(isinstance(e, dict) for e in val):
        return val
    return None


def _list_sheet_columns(spec: ListSheetSpec) -> List[FieldSpec]:
    return [
        FieldSpec("SPDXID", readonly=True, width=34, help="excel.help.spdxid"),
        FieldSpec("name", readonly=True, width=28, help="excel.help.list_name"),
    ] + list(spec.columns)


def _write_list_sheet(ws, nodes: List[Any], spec: ListSheetSpec) -> int:
    """1 要素 = 1 行。要素の無いパッケージには入力用の空行を 1 行出す。出力した要素数を返す。"""
    columns = _list_sheet_columns(spec)
    ws.freeze_panes = "C2"
    for idx, col in enumerate(columns, start=1):
        dim = ws.column_dimensions[get_column_letter(idx)]
        dim.width = col.width
        dim.number_format = "@"

    ws.append([_head_cell(ws, col) for col in columns])

    entry_count = 0
    last_row = 1
    for node in nodes:
        entries = _list_entries_or_none(node, spec.list_key)
        if entries is None:
            continue                            # 非標準な構造のパッケージは出さない（取り込みでも触らない）
        props = node.properties
        sid = _cell_text_for(props, "SPDXID")
        name = _cell_text_for(props, "name")
        for entry in (entries or [None]):       # 要素が無ければ入力用の空行
            row = [_text_cell(ws, sid, fill=_FILL_RO), _text_cell(ws, name, fill=_FILL_RO)]
            for col in spec.columns:
                row.append(_text_cell(ws, None if entry is None else _cell_text_for(entry, col.key)))
            ws.append(row)
            last_row += 1
            if entry is not None:
                entry_count += 1

    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{last_row}"
    dv_last = last_row + _DV_EXTRA_ROWS
    for idx, col in enumerate(columns, start=1):
        letter = get_column_letter(idx)
        if col.kind == "enum" and col.choices:
            _add_list_validation(ws, letter, col.choices, dv_last, strict=True, label=col.key)
        elif col.suggestions:
            _add_list_validation(ws, letter, col.suggestions, dv_last, strict=False, label=col.key)
    return entry_count


def _save_atomic(wb: Workbook, path: str) -> None:
    """一時ファイルに保存してから置換する（失敗しても既存ファイルを壊さない）。"""
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".sbomcraft_", suffix=".tmp", dir=directory)
    os.close(fd)
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, path)     # Excel で開いている場合 Windows では PermissionError
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def export_packages(root_node, path: str, *, app_version: str = "",
                    edit_revision: int = 0) -> ExportResult:
    """Packages を Excel(.xlsx) に出力する。"""
    nodes = list(iter_package_nodes(root_node))
    columns = collect_columns(nodes)

    wb = Workbook(write_only=True)
    wb.properties.creator = "SBOMcraft"
    wb.properties.title = "SBOMcraft Packages"
    ws_meta = wb.create_sheet(SHEET_META)
    ws_pkg = wb.create_sheet(SHEET_PACKAGES)
    list_sheets = [(spec, wb.create_sheet(spec.sheet)) for spec in LIST_SHEET_SPECS]
    _write_meta_sheet(ws_meta, nodes, root_node, app_version, edit_revision)
    _write_packages_sheet(ws_pkg, nodes, columns)
    list_rows = {spec.sheet: _write_list_sheet(ws, nodes, spec) for spec, ws in list_sheets}
    wb.active = 1                      # Packages シートを開いた状態にする
    _save_atomic(wb, path)
    return ExportResult(package_count=len(nodes), column_count=len(columns), list_rows=list_rows)


# ---------------------------------------------------------------------------
# 2. 読み込み（Excel → ParsedWorkbook）
# ---------------------------------------------------------------------------

def _check_zip_safety(path: str) -> None:
    if not zipfile.is_zipfile(path):
        raise WorkbookFormatError(t("excel.err.not_xlsx"))
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_ZIP_ENTRIES:
            raise WorkbookFormatError(t("excel.err.zip_entries"))
        if sum(i.file_size for i in infos) > _MAX_UNCOMPRESSED_BYTES:
            raise WorkbookFormatError(t("excel.err.zip_size"))


def read_workbook(path: str) -> ParsedWorkbook:
    """
    Excel を読み込む。値は data_only=True（数式は保存時の計算結果）で取得し、
    別途 data_only=False で『数式セルの位置』だけを調べる。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext != ".xlsx":
        raise WorkbookFormatError(t("excel.err.extension", ext=ext or t("excel.err.no_extension")))
    _check_zip_safety(path)

    wb_vals = wb_forms = None
    try:
        try:
            wb_vals = load_workbook(path, read_only=True, data_only=True, keep_links=False)
            wb_forms = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        except Exception as e:                         # openpyxl は多様な例外を投げる
            raise WorkbookFormatError(t("excel.err.open", error=e)) from e

        if SHEET_PACKAGES not in wb_vals.sheetnames:
            raise WorkbookFormatError(t("excel.err.no_packages_sheet", sheet=SHEET_PACKAGES))

        meta = _read_meta(wb_vals[SHEET_META]) if SHEET_META in wb_vals.sheetnames else {}
        packages = _read_table(wb_vals[SHEET_PACKAGES], wb_forms[SHEET_PACKAGES], SHEET_PACKAGES)

        # 一覧シート（Phase 2）は任意。無ければ「変更なし」、読めなければエラーとして記録する
        child_tables: Dict[str, ParsedTable] = {}
        child_errors: Dict[str, str] = {}
        for spec in LIST_SHEET_SPECS:
            if spec.sheet not in wb_vals.sheetnames:
                continue
            try:
                child_tables[spec.sheet] = _read_table(wb_vals[spec.sheet], wb_forms[spec.sheet], spec.sheet)
            except WorkbookFormatError as e:
                child_errors[spec.sheet] = str(e)
        return ParsedWorkbook(
            meta=meta, headers=packages.headers, rows=packages.rows,
            duplicate_headers=packages.duplicate_headers,
            child_tables=child_tables, child_errors=child_errors,
        )
    finally:
        for wb in (wb_vals, wb_forms):
            if wb is not None:
                wb.close()                             # read_only はファイルハンドルを保持する


def _read_meta(ws) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    ws.reset_dimensions()
    for row in ws.iter_rows(values_only=True):
        if len(row) >= 2 and isinstance(row[0], str) and row[0] in META_KEYS:
            meta[row[0]] = row[1]
    return meta


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _read_table(ws_vals, ws_forms, title: str) -> ParsedTable:
    """1 行目を見出し（SPDXID 列が必須）として表を読む。Packages / Checksums / ExternalRefs 共通。"""
    ws_vals.reset_dimensions()          # 寸法情報が不正なファイルでも全行を読む
    ws_forms.reset_dimensions()

    # 数式セルの位置（行番号, 0始まり列）
    formula_cells = set()
    for row in ws_forms.iter_rows():
        for cell in row:
            if getattr(cell, "data_type", None) == "f":
                formula_cells.add((cell.row, cell.column - 1))

    rows_iter = ws_vals.iter_rows(values_only=True)
    try:
        first = next(rows_iter)
    except StopIteration:
        raise WorkbookFormatError(t("excel.err.sheet_empty", sheet=title)) from None

    headers: Dict[str, int] = {}
    dups: List[str] = []
    for idx, v in enumerate(first):
        if isinstance(v, str) and v.strip():
            name = v.strip()
            if name in headers:
                dups.append(name)
            else:
                headers[name] = idx
    if "SPDXID" not in headers:
        raise WorkbookFormatError(t("excel.err.no_spdxid_header", sheet=title))

    rows: List[RowData] = []
    for row_no, values in enumerate(rows_iter, start=2):
        vals: Dict[str, Any] = {}
        fcols = []
        for name, idx in headers.items():
            v = values[idx] if idx < len(values) else None
            vals[name] = v
            if (row_no, idx) in formula_cells:
                fcols.append(name)
        if all(_is_blank(v) for v in vals.values()) and not fcols:
            continue                                    # 完全な空行
        rows.append(RowData(row=row_no, values=vals, formula_cols=frozenset(fcols)))
    return ParsedTable(headers=headers, rows=rows, duplicate_headers=dups)


# ---------------------------------------------------------------------------
# 3. 差分の作成（ParsedWorkbook × メモリ上の SBOM → ImportPlan）
# ---------------------------------------------------------------------------

Notes = List[Tuple[str, str]]


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("true", "false"):
            return low == "true"
    raise ValueError(t("excel.parse.bool", value=repr(raw)))


def _parse_int(raw: Any) -> int:
    if isinstance(raw, bool):
        raise ValueError(t("excel.parse.int", value=repr(raw)))
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            pass
    raise ValueError(t("excel.parse.int", value=repr(raw)))


def _parse_float(raw: Any) -> float:
    if isinstance(raw, bool):
        raise ValueError(t("excel.parse.float", value=repr(raw)))
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            pass
    raise ValueError(t("excel.parse.float", value=repr(raw)))


def _number_to_text(n: Any) -> str:
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n) if isinstance(n, int) else repr(n)


def _to_text(spec: FieldSpec, raw: Any, notes: Notes) -> str:
    """str / enum / date 列の値を文字列にする。数値・日付型で来た場合は警告を付ける。"""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, _dt.datetime):
        text = raw.strftime(_DATE_FMT) if spec.kind == "date" else raw.isoformat()
        notes.append(("warning", t("excel.note.as_date", text=text)))
        return text
    if isinstance(raw, _dt.date):
        text = raw.strftime("%Y-%m-%dT00:00:00Z") if spec.kind == "date" else raw.isoformat()
        notes.append(("warning", t("excel.note.as_date", text=text)))
        return text
    if isinstance(raw, bool):
        text = "true" if raw else "false"
        notes.append(("warning", t("excel.note.as_bool", text=text)))
        return text
    if isinstance(raw, (int, float)):
        text = _number_to_text(raw)
        notes.append(("warning", t("excel.note.as_number", text=text)))
        return text
    text = str(raw)
    notes.append(("warning", t("excel.note.unexpected_type", type=type(raw).__name__, text=repr(text))))
    return text


def _convert(spec: FieldSpec, raw: Any, notes: Notes) -> Any:
    kind = spec.kind
    if kind == "bool":
        return _parse_bool(raw)
    if kind == "int":
        return _parse_int(raw)
    if kind == "float":
        return _parse_float(raw)
    text = _to_text(spec, raw, notes)
    if kind == "enum":
        stripped = text.strip()
        if stripped not in spec.choices and stripped.upper() in spec.choices:
            stripped = stripped.upper()
        return stripped
    if kind == "date":
        return text.strip()
    return text


def _canon(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else (_number_to_text(value) if isinstance(value, (int, float)) else str(value))


def _same(new_text: str, old_text: str, kind: str) -> bool:
    if kind == "bool":
        return new_text.lower() == old_text.lower()
    return _nl(new_text) == _nl(old_text)


def _validate_changed(spec: FieldSpec, new: Any, notes: Notes) -> bool:
    """変更されたセルだけを検証する。error があれば False（その変更は適用しない）。"""
    ok = True
    if spec.kind == "enum" and new not in spec.choices:
        notes.append(("error", t("excel.val.enum", key=spec.key, choices=", ".join(spec.choices), input=repr(new))))
        ok = False
    if spec.kind == "date" and not _DATE_RE.match(str(new)):
        notes.append(("error", t("excel.val.date", key=spec.key, input=repr(new))))
        ok = False
    if spec.key in ("supplier", "originator") and isinstance(new, str):
        if new != "NOASSERTION" and not _AGENT_RE.match(new):
            notes.append(("warning", t("excel.val.agent", key=spec.key, input=repr(new))))
    if isinstance(new, str) and new != new.strip():
        notes.append(("warning", t("excel.note.whitespace")))
    return ok


def _evaluate_cell(spec: FieldSpec, old_present: bool, old: Any, raw: Any,
                   is_formula: bool) -> Tuple[Optional[str], Any, Notes]:
    """
    1 セルを評価する。戻り値: (op | None, new, notes)
      op=None は変更なし（notes に error が入っている場合は『変更できなかった』）。
    """
    notes: Notes = []

    if _is_too_long_marker(raw):                # 『未出力』マーカー（旧バージョンのものも含む）は無視
        return None, None, notes
    if is_formula:
        if raw is None:
            notes.append(("error", t("excel.note.formula_uncached")))
            return None, None, notes
        notes.append(("warning", t("excel.note.formula_cached")))

    old_text = _export_text(old) if old_present else None

    # 文字列セルが元の値と同じなら変更なし（空白のみの元値も含めて最優先で判定）
    if isinstance(raw, str) and old_text is not None and _nl(raw) == _nl(old_text):
        return None, None, [n for n in notes if n[0] == "error"]

    if _is_blank(raw):
        if old_text in (None, ""):
            return None, None, []
        if spec.required:
            notes.append(("error", t("excel.note.required_blank", key=spec.key)))
            return None, None, notes
        return "delete", None, notes

    try:
        new = _convert(spec, raw, notes)
    except ValueError as e:
        notes.append(("error", str(e)))
        return None, None, notes

    if old_text is not None and _same(_canon(new), old_text, spec.kind):
        return None, None, []

    if not _validate_changed(spec, new, notes):
        return None, None, notes
    return ("set" if old_present else "add"), new, notes


# ---------------------------------------------------------------------------
# 3b. 一覧（checksums / externalRefs）の差分
# ---------------------------------------------------------------------------

def _normalize_enum(col: FieldSpec, text: str) -> str:
    """列挙値は大文字小文字・前後の空白を無視して正規の表記に揃える（該当なしならそのまま）。"""
    stripped = text.strip()
    if not stripped:
        return text
    pool = {c.upper(): c for c in (*col.choices, *col.extra_choices)}
    return pool.get(stripped.upper(), text)


def _entry_canon(entry: Dict[str, Any], cols: List[FieldSpec]) -> Tuple[str, ...]:
    """既存の 1 要素を、Excel の 1 行と比較できる正規形（列ごとのテキストのタプル）にする。"""
    out = []
    for col in cols:
        txt = _cell_text_for(entry, col.key)
        txt = "" if txt is None else _nl(txt)
        if col.kind == "enum":
            txt = _normalize_enum(col, txt)
        out.append(txt)
    return tuple(out)


def _row_cell_text(col: FieldSpec, raw: Any) -> str:
    """Excel のセル → 比較用テキスト（空は ''）。型変換の警告はここでは出さない（追加行だけ別途出す）。
    旧バージョンの『未出力』マーカーは、現在のマーカーに揃える。"""
    if _is_blank(raw):
        return ""
    text = raw if isinstance(raw, str) else _to_text(col, raw, [])
    if text in LEGACY_TOO_LONG_MARKERS:
        return TOO_LONG_MARKER
    if col.kind == "enum":
        text = _normalize_enum(col, text)
    return _nl(text)


def _validate_added_entry(spec: ListSheetSpec, cols: List[FieldSpec], headers: Dict[str, int],
                          sid: str, rd: RowData, texts: Dict[str, str], out: List[ImportIssue]) -> None:
    """新規・変更された要素（= 既存要素と一致しなかった行）だけを検証する。"""

    def add(level: str, key: str, msg: str) -> None:
        letter = get_column_letter(headers[key] + 1)
        out.append(ImportIssue(level, f"{spec.sheet}!{letter}{rd.row}", f"[{sid}] {key}: {msg}"))

    for col in cols:
        text = texts[col.key]
        raw = rd.values.get(col.key)
        if text == TOO_LONG_MARKER:
            add("error", col.key, t("excel.list.marker_cannot_add"))
            continue
        if text == "":
            if col.required:
                add("error", col.key, t("excel.list.required"))
            continue
        if not isinstance(raw, str):
            notes: Notes = []
            _to_text(col, raw, notes)
            for level, msg in notes:
                add(level, col.key, msg)
        if col.key in rd.formula_cols:
            add("warning", col.key, t("excel.note.formula_cached"))
        if text != text.strip():
            add("warning", col.key, t("excel.note.whitespace"))
        if col.kind == "enum":
            if text in col.extra_choices:
                add("warning", col.key, t("excel.list.legacy_category", text=text, recommended=text.replace("_", "-")))
            elif text not in col.choices:
                add("error", col.key, t("excel.list.enum", choices=", ".join(col.choices), input=repr(text)))

    if spec.list_key == "checksums":
        alg, val = texts.get("algorithm", ""), texts.get("checksumValue", "")
        if val and val != TOO_LONG_MARKER and "checksumValue" in headers:
            if not re.fullmatch(r"[0-9a-fA-F]+", val):
                add("error", "checksumValue", t("excel.list.hash_not_hex"))
            elif alg in _HASH_HEX_LENGTHS and len(val) != _HASH_HEX_LENGTHS[alg]:
                add("error", "checksumValue",
                    t("excel.list.hash_length", alg=alg, expected=_HASH_HEX_LENGTHS[alg], actual=len(val)))
    elif spec.list_key == "externalRefs":
        cat, typ, loc = (texts.get("referenceCategory", ""), texts.get("referenceType", ""),
                         texts.get("referenceLocator", ""))
        expected = KNOWN_REFERENCE_TYPES.get(typ)
        if expected and cat and "referenceCategory" in headers and cat.replace("_", "-") != expected:
            add("warning", "referenceCategory",
                t("excel.list.category_mismatch", type=typ, expected=expected, actual=cat))
        prefix = _REF_LOCATOR_PREFIX.get(typ)
        if prefix and loc and loc != TOO_LONG_MARKER and "referenceLocator" in headers and not loc.startswith(prefix):
            add("error", "referenceLocator", t("excel.list.locator_prefix", type=typ, prefix=prefix))


def _row_label(sheet: str, row_nums: List[int]) -> str:
    """プレビューのセル欄に出す行番号。離れた行を範囲に見せないよう、少数なら列挙する。"""
    nums = sorted(set(row_nums))
    if len(nums) <= 3:
        return f"{sheet}!{','.join(str(n) for n in nums)}"
    return t("excel.row_label_many", sheet=sheet, first=nums[0], last=nums[-1], count=len(nums))


def _plan_list_change(spec: ListSheetSpec, cols: List[FieldSpec], headers: Dict[str, int], sid: str,
                      node: Any, old_present: bool, old_val: Any, old_entries: List[Dict[str, Any]],
                      rows: List[RowData], issues: List[ImportIssue]) -> Optional[CellChange]:
    """1 パッケージ分の一覧を Excel の行と突合し、変更があれば CellChange を返す（なければ None）。"""
    local: List[ImportIssue] = []

    # 1) 行 → 要素（空行は『要素なし』の目印として読み飛ばす）
    new_rows: List[Tuple[RowData, Dict[str, str]]] = []
    formula_error = False
    for rd in rows:
        texts: Dict[str, str] = {}
        bad = False
        for col in cols:
            raw = rd.values.get(col.key)
            if col.key in rd.formula_cols and raw is None:
                letter = get_column_letter(headers[col.key] + 1)
                local.append(ImportIssue("error", f"{spec.sheet}!{letter}{rd.row}",
                                         f"[{sid}] {col.key}: {t('excel.note.formula_uncached')}"))
                bad = formula_error = True
                break
            texts[col.key] = _row_cell_text(col, raw)
        if bad or all(v == "" for v in texts.values()):
            continue
        new_rows.append((rd, texts))
    if formula_error:
        issues.extend(local)
        return None

    # 2) 内容が同じ行を既存要素と 1 対 1 で突合（順序非依存。重複要素も個数どおりに扱う）
    available: Dict[Tuple[str, ...], List[int]] = {}
    for i, entry in enumerate(old_entries):
        available.setdefault(_entry_canon(entry, cols), []).append(i)
    retained: List[int] = []
    added_rows: List[Tuple[RowData, Dict[str, str]]] = []
    for rd, texts in new_rows:
        slots = available.get(tuple(texts[c.key] for c in cols))
        if slots:
            retained.append(slots.pop(0))
        else:
            added_rows.append((rd, texts))
    retained_set = set(retained)
    removed_idx = [i for i in range(len(old_entries)) if i not in retained_set]
    if not added_rows and not removed_idx:
        issues.extend(local)
        return None                                   # 並べ替えだけ等、内容の変更なし

    # 3) 追加される要素の検証（エラーがあれば、この一覧は反映しない）
    added_entries: List[Dict[str, Any]] = []
    for rd, texts in added_rows:
        _validate_added_entry(spec, cols, headers, sid, rd, texts, local)
        added_entries.append({c.key: texts[c.key] for c in cols if texts[c.key] != ""})
    issues.extend(local)
    if any(i.level == "error" for i in local):
        return None

    # 4) 新しい一覧 = 残る既存要素（元の順序・元の dict のまま） + 追加要素（シート上の順）
    new_list = [old_entries[i] for i in sorted(retained_set)] + added_entries
    if not new_list:
        op = "delete"
    else:
        op = "set" if old_present else "add"
    return CellChange(
        spdx_id=sid, package_name=str(node.properties.get("name", "")), field=spec.list_key,
        old=copy.deepcopy(old_val) if old_present else None,     # 競合検知用のスナップショット
        new=new_list if new_list else None, op=op,
        cell=_row_label(spec.sheet, [r.row for r in rows]),
        node=node, kind="list", added=added_entries, removed=[old_entries[i] for i in removed_idx],
    )


def _build_list_changes(plan: ImportPlan, spec: ListSheetSpec, table: ParsedTable,
                        index: Dict[str, List[Any]], tick: Callable[[], None]) -> None:
    issues = plan.issues
    missing = [c.key for c in spec.columns if c.required and c.key not in table.headers]
    if missing:
        issues.append(ImportIssue("error", f"{spec.sheet}!1",
                                  t("excel.issue.missing_required_columns",
                                    columns=", ".join(missing), sheet=spec.sheet)))
        return
    cols = [c for c in spec.columns if c.key in table.headers]
    for dup in table.duplicate_headers:
        issues.append(ImportIssue("warning", f"{spec.sheet}!1", t("excel.issue.dup_header", name=dup)))
    known = {"SPDXID", "name"} | {c.key for c in spec.columns}
    for name, idx in table.headers.items():
        if name not in known:
            issues.append(ImportIssue("warning", f"{spec.sheet}!{get_column_letter(idx + 1)}1",
                                      t("excel.issue.unknown_column", name=name)))

    # SPDXID ごとに行をまとめる（並べ替えや離れた行でも 1 つの一覧として扱う）
    groups: Dict[str, List[RowData]] = {}
    for rd in table.rows:
        tick()
        v = rd.values.get("SPDXID")
        sid = "" if v is None else str(v).strip()
        if not sid:
            if any(not _is_blank(rd.values.get(c.key)) for c in cols):
                issues.append(ImportIssue("warning", f"{spec.sheet}!A{rd.row}", t("excel.issue.blank_spdxid")))
            continue
        groups.setdefault(sid, []).append(rd)

    matched = 0
    for sid, rows in groups.items():
        where = f"{spec.sheet}!A{rows[0].row}"
        nodes = index.get(sid)
        if not nodes:
            issues.append(ImportIssue("warning", where, t("excel.issue.unknown_spdxid_list", sid=sid)))
            continue
        if len(nodes) > 1:
            issues.append(ImportIssue("error", where, t("excel.issue.dup_spdxid_sbom_list", sid=sid)))
            continue
        node = nodes[0]
        old_present = spec.list_key in node.properties
        old_val = node.properties.get(spec.list_key)
        old_entries = _list_entries_or_none(node, spec.list_key)
        if old_entries is None:
            issues.append(ImportIssue("warning", where,
                                      t("excel.issue.nonstandard_list", sid=sid, key=spec.list_key)))
            continue
        matched += 1
        change = _plan_list_change(spec, cols, table.headers, sid, node, old_present, old_val,
                                   old_entries, rows, issues)
        if change is not None:
            plan.changes.append(change)
    plan.list_stats[spec.sheet] = matched


def build_changes(
    root_node,
    parsed: ParsedWorkbook,
    *,
    current_revision: Optional[int] = None,
    progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ImportPlan:
    """Excel の内容と現在の SBOM を比較し、適用すべき差分とチェック結果を返す（SBOM は変更しない）。"""
    plan = ImportPlan()
    issues = plan.issues

    # --- メタ情報のチェック ---
    meta = parsed.meta
    if not meta:
        issues.append(ImportIssue("warning", SHEET_META, t("excel.issue.no_meta")))
    else:
        try:
            fv = int(str(meta.get("formatVersion", "")).strip())
            if fv > FORMAT_VERSION:
                issues.append(ImportIssue("warning", SHEET_META, t("excel.issue.newer_format", version=fv)))
        except ValueError:
            issues.append(ImportIssue("warning", SHEET_META, t("excel.issue.bad_format_version")))
        ns_x = str(meta.get("documentNamespace") or "")
        ns_now = str(_document_properties(root_node).get("documentNamespace") or "")
        if ns_x and ns_now and ns_x != ns_now:
            issues.append(ImportIssue("warning", SHEET_META,
                                      t("excel.issue.namespace_mismatch", excel=ns_x, current=ns_now)))
        if current_revision is not None:
            try:
                rev_x = int(str(meta.get("editRevision", "")).strip())
                if rev_x != current_revision:
                    issues.append(ImportIssue("warning", SHEET_META, t("excel.issue.edited_since_export")))
            except ValueError:
                pass

    # --- 列の突合 ---
    pkg_nodes = list(iter_package_nodes(root_node))
    columns = collect_columns(pkg_nodes)
    spec_by_key = {s.key: s for s in columns}
    for dup in parsed.duplicate_headers:
        issues.append(ImportIssue("warning", f"{SHEET_PACKAGES}!1", t("excel.issue.dup_header", name=dup)))
    for name, idx in parsed.headers.items():
        if name != "SPDXID" and name not in spec_by_key:
            issues.append(ImportIssue("warning", f"{SHEET_PACKAGES}!{get_column_letter(idx + 1)}1",
                                      t("excel.issue.unknown_column", name=name)))
    edit_cols = [(name, idx, spec_by_key[name]) for name, idx in parsed.headers.items()
                 if name in spec_by_key and not spec_by_key[name].readonly]

    # --- SPDXID → ノード ---
    index: Dict[str, List[Any]] = {}
    for node in pkg_nodes:
        sid = node.properties.get("SPDXID") or getattr(node, "spdx_id", "")
        if sid:
            index.setdefault(sid, []).append(node)

    # --- Excel 内の SPDXID 重複 ---
    def _sid_of(rd: RowData) -> str:
        v = rd.values.get("SPDXID")
        return "" if v is None else str(v).strip()

    counts: Dict[str, int] = {}
    for rd in parsed.rows:
        sid = _sid_of(rd)
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    reported_dups = set()

    plan.rows_total = len(parsed.rows)
    total_work = max(1, len(parsed.rows) + sum(len(tb.rows) for tb in parsed.child_tables.values()))
    done = [0]

    def tick() -> None:
        if should_cancel and should_cancel():
            raise ImportCanceled()
        done[0] += 1
        if progress and done[0] % 200 == 0:
            progress(min(99, int(done[0] * 100 / total_work)))

    for rd in parsed.rows:
        tick()

        sid = _sid_of(rd)
        where_row = f"{SHEET_PACKAGES}!A{rd.row}"
        if not sid:
            issues.append(ImportIssue("warning", where_row, t("excel.issue.blank_spdxid")))
            continue
        if counts[sid] > 1:
            if sid not in reported_dups:
                reported_dups.add(sid)
                issues.append(ImportIssue("error", where_row, t("excel.issue.dup_spdxid_excel", sid=sid)))
            continue
        nodes = index.get(sid)
        if not nodes:
            issues.append(ImportIssue("warning", where_row, t("excel.issue.unknown_spdxid_row", sid=sid)))
            continue
        if len(nodes) > 1:
            issues.append(ImportIssue("error", where_row, t("excel.issue.dup_spdxid_sbom_row", sid=sid)))
            continue

        node = nodes[0]
        props = node.properties
        plan.rows_matched += 1
        for name, idx, spec in edit_cols:
            old_present = name in props
            old = props.get(name)
            if isinstance(old, (dict, list)):
                continue                        # 入れ子の値は Excel からは触らない
            cell_addr = f"{get_column_letter(idx + 1)}{rd.row}"
            op, new, notes = _evaluate_cell(
                spec, old_present, old, rd.values.get(name), name in rd.formula_cols)
            for level, msg in notes:
                issues.append(ImportIssue(level, f"{SHEET_PACKAGES}!{cell_addr}", f"[{sid}] {name}: {msg}"))
            if op is not None:
                plan.changes.append(CellChange(
                    spdx_id=sid, package_name=str(props.get("name", "")), field=name,
                    old=old if old_present else None, new=new, op=op, cell=cell_addr, node=node))

    # --- 一覧シート（Checksums / ExternalRefs） ---
    for spec in LIST_SHEET_SPECS:
        if spec.sheet in parsed.child_errors:
            issues.append(ImportIssue("error", spec.sheet,
                                      t("excel.issue.sheet_ignored",
                                        error=parsed.child_errors[spec.sheet], sheet=spec.sheet)))
            continue
        table = parsed.child_tables.get(spec.sheet)
        if table is not None:
            _build_list_changes(plan, spec, table, index, tick)

    if progress:
        progress(100)
    return plan


# ---------------------------------------------------------------------------
# 4. 適用
# ---------------------------------------------------------------------------

def apply_changes(changes: Iterable[CellChange]) -> ApplyResult:
    """
    差分をノードの properties に書き込む（UI スレッドから呼ぶこと）。
    計画作成後に値が変わっていた項目（競合）は適用せず skipped に入れる。
    パッケージ単位で作業コピーに適用し、成功したものだけをコミットする。
    """
    result = ApplyResult()
    by_node: Dict[int, Tuple[Any, List[CellChange]]] = {}
    for ch in changes:
        by_node.setdefault(id(ch.node), (ch.node, []))[1].append(ch)

    for node, chs in by_node.values():
        work = copy.copy(node.properties)       # 浅いコピーで十分（スカラー値だけを差し替える）
        applied_here: List[CellChange] = []
        for ch in chs:
            present = ch.field in work
            if ch.op == "add":
                conflict = present
            else:
                conflict = (not present) or work[ch.field] != ch.old
            if conflict:
                result.skipped.append((ch, t("excel.apply.conflict")))
                continue
            if ch.op == "delete":
                del work[ch.field]
            else:
                work[ch.field] = ch.new
            applied_here.append(ch)
        if applied_here:
            node.properties.clear()                 # dict の同一性を保ったまま差し替え
            node.properties.update(work)
            result.applied.extend(applied_here)
            result.nodes.append(node)
    return result


def format_entry(list_key: str, entry: Any) -> str:
    """一覧の 1 要素を 1 行の文字列にする（プレビュー用）。"""
    if not isinstance(entry, dict):
        return str(entry)
    if list_key == "checksums":
        return f"{entry.get('algorithm', '?')}: {entry.get('checksumValue', '')}"
    if list_key == "externalRefs":
        text = (f"{entry.get('referenceType', '?')}: {entry.get('referenceLocator', '')}"
                f"  [{entry.get('referenceCategory', '?')}]")
        if entry.get("comment"):
            text += f"  // {entry['comment']}"
        return text
    return ", ".join(f"{k}={v}" for k, v in entry.items())


def describe_entries(list_key: str, entries: Optional[List[Any]], prefix: str = "") -> str:
    """要素のリストを改行区切りの文字列にする。空なら ''。"""
    return "\n".join(prefix + format_entry(list_key, e) for e in (entries or []))


def describe_value(value: Any, list_key: str = "") -> str:
    """プレビュー表示用の文字列化。"""
    if value is None:
        return t("excel.value.unset")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return describe_entries(list_key, value) or t("excel.value.empty_list")
    return str(value)
