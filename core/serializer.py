# core/serializer.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""
編集済みの SBOMNode ツリーから SPDX 2.3 JSON を再構築し、安全に保存するためのモジュール。

Qt には依存しない（ノードは node_type / properties / children / extra_sections を
持つ duck-typing で扱う）ため、単体テストが容易。
画面に出す警告・エラー文言は core.i18n.t() で現在の言語に翻訳する。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Tuple

from core.i18n import t

# ---------------------------------------------------------------------------
# 1. ツリー → SPDX 2.3 辞書
# ---------------------------------------------------------------------------

# Packages の表示順（DetailPanel の詳細表示と Excel 出力の列順で共通利用）。
PACKAGE_PRIORITY_KEYS: List[str] = [
    "SPDXID", "name", "versionInfo", "supplier", "originator",
    "downloadLocation", "filesAnalyzed", "licenseConcluded", "licenseDeclared",
]

# SPDX 2.3 JSON のトップレベルキーの標準的な並び順。
# ここに無いキー（extra_sections 由来の未知キー等）は末尾に元の順序で付く。
SPDX_TOP_LEVEL_ORDER: List[str] = [
    "documentNamespace", "spdxVersion", "dataLicense", "SPDXID", "name",
    "comment", "externalDocumentRefs", "creationInfo", "documentDescribes",
    "packages", "files", "snippets", "relationships", "annotations",
    "hasExtractedLicensingInfos",
]

# 子ノードの node_type → SPDX トップレベルのセクション名
# （フォルダ名ではなく中身のノード種別で振り分けるので、フォルダ名変更に強い）
_SECTION_BY_NODE_TYPE: Dict[str, str] = {
    "package": "packages",
    "file": "files",
    "relationship": "relationships",
    "licenses": "hasExtractedLicensingInfos",
}


def build_spdx_document(root_node) -> Dict[str, Any]:
    """
    メモリ上のツリー(root_node)から、現在の編集内容を反映した SPDX 2.3 辞書を作る。

    - Document Information ノードの properties をドキュメントヘッダとして使う
    - Packages / Files / Relationships / ExtractedLicense 各フォルダの子ノードの
      properties をセクションとして並べる（ツリーの子の順序＝元ファイルの順序）
    - パーサが専用ノードを持たないトップレベルキー（snippets / annotations /
      externalDocumentRefs など）は root_node.extra_sections から書き戻す
    """
    if root_node is None:
        return {}

    doc: Dict[str, Any] = {}

    doc_info = next((c for c in root_node.children if c.node_type == "document_info"), None)
    header = doc_info.properties if doc_info is not None else root_node.properties
    doc.update(header)

    sections: Dict[str, List[Any]] = {}
    for folder in root_node.children:
        if folder.node_type == "document_info":
            continue
        for node in folder.children:
            section = _SECTION_BY_NODE_TYPE.get(node.node_type)
            if section:
                sections.setdefault(section, []).append(node.properties)
    doc.update(sections)

    for key, value in (getattr(root_node, "extra_sections", None) or {}).items():
        doc.setdefault(key, value)

    # 標準的なキー順に整列（未知キーは末尾）
    ordered: Dict[str, Any] = {k: doc[k] for k in SPDX_TOP_LEVEL_ORDER if k in doc}
    ordered.update({k: v for k, v in doc.items() if k not in ordered})
    return ordered


# ---------------------------------------------------------------------------
# 2. 保存前の構造チェック（警告のみ。保存はブロックしない）
# ---------------------------------------------------------------------------

_SPDXID_RE = re.compile(r"^SPDXRef-[A-Za-z0-9.\-]+$")
_LICENSEREF_RE = re.compile(r"^LicenseRef-[A-Za-z0-9.\-]+$")
_SPECIAL_RELATED = {"NONE", "NOASSERTION"}
_MAX_WARNINGS = 50


def validate_spdx_document(doc: Dict[str, Any]) -> List[str]:
    """SPDX 2.3 JSON スキーマ上の必須項目・ID 整合性を簡易チェックし、警告文のリストを返す（現在の言語）。"""
    w: List[str] = []

    def warn(msg: str) -> None:
        if len(w) < _MAX_WARNINGS:
            w.append(msg)
        elif len(w) == _MAX_WARNINGS:
            w.append(t("serializer.warn.truncated"))

    def required(where: str, key: str) -> None:
        warn(t("serializer.warn.required", where=where, key=key))

    # --- ドキュメントヘッダ ---
    for key in ("spdxVersion", "dataLicense", "SPDXID", "name", "documentNamespace", "creationInfo"):
        if key not in doc or doc[key] in ("", None):
            required("Document", key)
    ver = doc.get("spdxVersion")
    if ver and ver != "SPDX-2.3":
        warn(t("serializer.warn.spdx_version", value=repr(ver)))
    ci = doc.get("creationInfo")
    if isinstance(ci, dict):
        for key in ("created", "creators"):
            if not ci.get(key):
                required("creationInfo", key)

    # --- SPDXID の形式・重複 ---
    seen: Dict[str, str] = {}

    def register(spdx_id: Any, where: str) -> None:
        if not isinstance(spdx_id, str) or not spdx_id:
            warn(t("serializer.warn.spdxid_missing", where=where))
            return
        if not _SPDXID_RE.match(spdx_id):
            warn(t("serializer.warn.spdxid_format", where=where, id=repr(spdx_id)))
        if spdx_id in seen:
            warn(t("serializer.warn.spdxid_dup", where=where, id=repr(spdx_id), other=seen[spdx_id]))
        else:
            seen[spdx_id] = where

    if doc.get("SPDXID"):
        register(doc["SPDXID"], "Document")

    for i, p in enumerate(doc.get("packages", [])):
        where = f"Package[{i}] {p.get('name', '')}"
        register(p.get("SPDXID"), where)
        for key in ("name", "downloadLocation"):
            if p.get(key) in (None, ""):
                required(where, key)
        if "filesAnalyzed" in p and not isinstance(p["filesAnalyzed"], bool):
            warn(t("serializer.warn.files_analyzed", where=where, value=repr(p["filesAnalyzed"])))

    for i, f in enumerate(doc.get("files", [])):
        where = f"File[{i}] {f.get('fileName', '')}"
        register(f.get("SPDXID"), where)
        if not f.get("fileName"):
            required(where, "fileName")
        if not f.get("checksums"):
            required(where, "checksums")

    for i, s in enumerate(doc.get("snippets", [])):
        register(s.get("SPDXID"), f"Snippet[{i}]")

    # --- Relationships の参照整合性 ---
    for i, r in enumerate(doc.get("relationships", [])):
        where = f"Relationship[{i}]"
        for key in ("spdxElementId", "relationshipType", "relatedSpdxElement"):
            if not r.get(key):
                required(where, key)
        for key in ("spdxElementId", "relatedSpdxElement"):
            ref = r.get(key)
            if (ref and ref not in seen and ref not in _SPECIAL_RELATED
                    and not str(ref).startswith("DocumentRef-")):
                warn(t("serializer.warn.dangling_ref", where=where, key=key, ref=repr(ref)))

    # --- 抽出ライセンス情報 ---
    for i, lic in enumerate(doc.get("hasExtractedLicensingInfos", [])):
        where = f"ExtractedLicense[{i}]"
        lid = lic.get("licenseId")
        if not lid or not _LICENSEREF_RE.match(str(lid)):
            warn(t("serializer.warn.licenseid_format", where=where, id=repr(lid)))
        if not lic.get("extractedText"):
            required(where, "extractedText")

    return w


# ---------------------------------------------------------------------------
# 3. 安全な JSON 書き出し
# ---------------------------------------------------------------------------

def json_default(obj: Any) -> Any:
    """標準 json が扱えない型（ijson 由来の Decimal 等）のフォールバック。"""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, (set, tuple)):
        return list(obj)
    raise TypeError(t("serializer.err.json_type", type=type(obj).__name__))


def write_json_atomic(path: str, data: Any, indent: int = 2, verify: bool = True) -> None:
    """
    JSON をアトミックに書き出す。

    1. 保存先と同じディレクトリの一時ファイルに UTF-8 で書く（日本語はそのまま）
    2. flush + fsync、verify=True なら json.load で読み戻して構文を確認
    3. os.replace で本番ファイルへ置換

    途中で失敗しても元のファイルは壊れず、一時ファイルも残らない。
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".sbomcraft_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False,
                      allow_nan=False, default=json_default)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        if verify:
            with open(tmp_path, "r", encoding="utf-8") as f:
                json.load(f)

        if os.path.exists(path):          # 既存ファイルの権限を引き継ぐ
            try:
                shutil.copymode(path, tmp_path)
            except OSError:
                pass
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# 4. DetailPanel のテーブル行 → properties への反映（Qt 非依存）
# ---------------------------------------------------------------------------

_INDENT = 4  # DetailPanel._flatten_properties が 1 階層ごとに付ける空白数


def convert_value(old: Any, text: str) -> Any:
    """元の値の型に合わせて入力文字列を変換する。型に合わなければ ValueError（メッセージは現在の言語）。"""
    if isinstance(old, bool):                      # bool は int のサブクラスなので先に判定
        low = text.strip().lower()
        if low in ("true", "false"):
            return low == "true"
        raise ValueError(t("serializer.err.bool", value=repr(text)))
    if isinstance(old, int):
        try:
            return int(text.strip())
        except ValueError:
            raise ValueError(t("serializer.err.int", value=repr(text))) from None
    if isinstance(old, (float, Decimal)):
        try:
            return float(text.strip())
        except ValueError:
            raise ValueError(t("serializer.err.float", value=repr(text))) from None
    return text                                    # str / None はそのまま文字列として扱う


def apply_flat_rows(properties: Dict[str, Any], rows: Iterable[Tuple[str, str]]) -> bool:
    """
    DetailPanel のテーブル行 [(インデント付きキー, 値文字列), ...] を properties に反映する。

    - 値が変わった葉(スカラー)だけを書き換える（None/小数などの往復劣化を防ぐ）
    - dict だけでなく list の中の dict / list も辿る
    - 入力が型に合わない場合は ValueError（呼び出し側で作業コピーを破棄すること）

    Returns: 1 つでも値が変わったら True
    """
    containers: List[Any] = [properties]   # containers[d] = 深さ d の行が属するコンテナ
    changed = False

    for display_key, text in rows:
        stripped = display_key.lstrip(" ")
        depth = (len(display_key) - len(stripped)) // _INDENT
        key = stripped.strip()

        if depth >= len(containers):        # 親が特定できない行は無視
            continue
        del containers[depth + 1:]
        container = containers[depth]

        if isinstance(container, list):
            if not (key.startswith("[") and key.endswith("]")):
                continue
            try:
                slot: Any = int(key[1:-1])
            except ValueError:
                continue
            if not 0 <= slot < len(container):
                continue
        elif isinstance(container, dict):
            if key not in container:
                continue
            slot = key
        else:
            continue

        old = container[slot]
        if isinstance(old, (dict, list)):
            containers.append(old)          # 子行のためにコンテナを積む
            continue

        if text == str(old):                # 表示と同じ＝未変更
            continue
        container[slot] = convert_value(old, text)
        changed = True

    return changed
