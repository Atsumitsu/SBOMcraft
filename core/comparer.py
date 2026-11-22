# core/comparer.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""
SBOM 比較エンジン（Qt 非依存・標準ライブラリのみ）。

考え方
------
* 「突合キー」（どのパッケージ同士を同一物とみなすか）と、
  「比較する属性」（version / license / checksum など）を分けて扱う。
* version は突合キーに含めず“属性”として比較する。だからバージョンアップが
  「削除 + 追加」ではなく「バージョン変更」として検出できる。
* 同一キーのパッケージが複数ある場合は、version → SPDXID → 出現順の順にペアにする。
  推測でペアにした場合は PackageDiff.notes に注意書きを残す。

対象: Packages のみ（MVP）。入力は core.parser.SBOMNode のルート
（node_type == "package" のノードを列挙できればよい。テストでは FakeNode で代用できる）。
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple
from urllib.parse import unquote
from core.i18n import t

# ---------------------------------------------------------------------------
# 公開する型
# ---------------------------------------------------------------------------

class MatchKey(str, Enum):
    AUTO = "auto"                    # purl（version 除く）→ 名前 の順で突合
    SPDXID = "spdxid"                # SPDXID が同じもの
    NAME_VERSION = "name_version"    # 名前 + バージョンが同じもの
    NAME = "name"                    # 名前が同じもの（version は属性として比較）
    PURL = "purl"                    # purl（version 除く）が同じもの。purl 無しは突合しない

class DiffStatus(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    VERSION_CHANGED = "version_changed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"

# 要注意フラグ
FLAG_CHECKSUM_MISMATCH = "checksum_mismatch"   # 同一バージョンなのに checksum が違う（すり替えの可能性）
FLAG_LICENSE = "license_changed"
FLAG_SUPPLIER = "supplier_changed"
FLAG_DOWNLOAD = "download_changed"

ALL_FLAGS = (FLAG_CHECKSUM_MISMATCH, FLAG_LICENSE, FLAG_SUPPLIER, FLAG_DOWNLOAD)

def match_key_label(m) -> str:     return t(f"compare.match.label.{MatchKey(m).value}")
def match_key_hint(m) -> str:      return t(f"compare.match.hint.{MatchKey(m).value}")
def status_label(s) -> str:        return t(f"compare.status.{DiffStatus(s).value}")
def flag_label(flag: str) -> str:  return t(f"compare.flag.{flag}")
def version_change_label(v: str) -> str:
    return t(f"compare.version_change.{v}") if v else ""
def matched_by_label(mid: str) -> str:
    return t(f"compare.matched.{mid}") if mid else ""
def group_label(g: str) -> str:    return t(FIELD_GROUPS[g][0])

# 比較する項目のグループ（バージョンは常に比較する）
FIELD_GROUPS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "license": ("ライセンス", ("licenseConcluded", "licenseDeclared", "licenseComments", "licenseInfoFromFiles")),
    "supplier": ("供給者 / 作成者", ("supplier", "originator")),
    "hash": ("ハッシュ", ("checksums", "packageVerificationCode")),
    "extref": ("外部参照（purl / CPE など）", ("externalRefs",)),
    "location": ("取得先・URL", ("downloadLocation", "homepage", "packageFileName")),
    "text": ("説明・著作権表示", ("copyrightText", "summary", "description", "comment", "sourceInfo", "attributionTexts")),
    "other": ("その他（名前・用途・日付・未知の項目）",
              ("name", "filesAnalyzed", "primaryPackagePurpose", "releaseDate", "builtDate", "validUntilDate", "*")),
}
ALL_GROUPS: Tuple[str, ...] = tuple(FIELD_GROUPS.keys())

_SET_FIELDS = frozenset({"checksums", "externalRefs", "licenseInfoFromFiles", "attributionTexts"})
_LICENSE_FIELDS = frozenset({"licenseConcluded", "licenseDeclared", "licenseInfoFromFiles"})
# 比較対象外のキー（識別子・バージョン・他ノードとの関連）
_SKIP_KEYS = frozenset({"SPDXID", "versionInfo", "hasFiles", "annotations", "relationships"})
_KNOWN_KEYS = frozenset(k for _, keys in FIELD_GROUPS.values() for k in keys if k != "*") | _SKIP_KEYS


class CompareCanceled(Exception):
    pass


@dataclass
class FieldChange:
    field: str
    old: Optional[str] = None        # スカラー項目の旧値（未設定は None）
    new: Optional[str] = None
    added: List[str] = field(default_factory=list)     # 一覧項目（checksums など）で増えた要素
    removed: List[str] = field(default_factory=list)   # 一覧項目で減った要素

    @property
    def is_list(self) -> bool:
        return self.field in _SET_FIELDS


@dataclass
class PackageDiff:
    status: DiffStatus
    name: str
    key: str                                   # 画面表示用の突合キー（purl or 名前）
    version_a: str = ""
    version_b: str = ""
    version_change: str = ""                   # upgrade / downgrade / changed / ""
    spdx_id_a: str = ""
    spdx_id_b: str = ""
    matched_by: str = ""                       # どのキーで突合したか
    field_changes: List[FieldChange] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    node_a: Any = None
    node_b: Any = None

    @property
    def changed_fields(self) -> List[str]:
        names = ["versionInfo"] if self.status == DiffStatus.VERSION_CHANGED else []
        names.extend(fc.field for fc in self.field_changes)
        return names

    @property
    def is_attention(self) -> bool:
        return bool(self.flags)


@dataclass
class DocInfo:
    label: str = ""
    name: str = ""
    spdx_version: str = ""
    created: str = ""
    creators: List[str] = field(default_factory=list)
    package_count: int = 0


@dataclass
class CompareResult:
    mode: MatchKey
    groups: Tuple[str, ...]
    doc_a: DocInfo
    doc_b: DocInfo
    diffs: List[PackageDiff]
    warnings: List[str] = field(default_factory=list)
    root_a: Any = None
    root_b: Any = None

    def count(self, *statuses: DiffStatus) -> int:
        return sum(1 for d in self.diffs if d.status in statuses)

    def summary(self) -> Dict[str, int]:
        s = {
            "total_a": self.doc_a.package_count,
            "total_b": self.doc_b.package_count,
            "added": self.count(DiffStatus.ADDED),
            "removed": self.count(DiffStatus.REMOVED),
            "version_changed": self.count(DiffStatus.VERSION_CHANGED),
            "modified": self.count(DiffStatus.MODIFIED),
            "unchanged": self.count(DiffStatus.UNCHANGED),
            "upgrade": 0, "downgrade": 0,
            FLAG_CHECKSUM_MISMATCH: 0, FLAG_LICENSE: 0, FLAG_SUPPLIER: 0, FLAG_DOWNLOAD: 0,
        }
        for d in self.diffs:
            if d.version_change in ("upgrade", "downgrade"):
                s[d.version_change] += 1
            for fl in d.flags:
                s[fl] += 1
        s["changed"] = s["version_changed"] + s["modified"]
        s["differences"] = s["added"] + s["removed"] + s["changed"]
        return s


# ---------------------------------------------------------------------------
# 正規化ヘルパー
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    """値 → 比較・表示用テキスト。None は ''、bool は true/false、改行は \\n に統一して前後の空白を除く。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    s = value if isinstance(value, str) else str(value)
    return s.replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_name(name: str) -> str:
    """突合用の名前。大文字小文字と区切り文字（- _ . 空白）の違いを吸収する（PySide6 / pyside6、foo_bar / foo-bar）。"""
    return re.sub(r"[-_.\s]+", "-", _text(name).lower())


def parse_purl(purl: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """purl → (type, 正規化した namespace/name, version)。version・qualifiers・subpath は含めない。解釈できなければ None。"""
    s = _text(purl)
    if not s.lower().startswith("pkg:"):
        return None
    s = s[4:].lstrip("/").split("#", 1)[0].split("?", 1)[0]
    if not s:
        return None
    slash = s.rfind("/")
    head, last = (s[:slash + 1], s[slash + 1:]) if slash >= 0 else ("", s)
    version: Optional[str] = None
    if "@" in last:                       # 'pkg:npm/@angular/core@1.0' の '@angular' は head 側にあるので影響しない
        last, version = last.split("@", 1)
        version = unquote(version) or None
    path = unquote(head + last)
    if "/" not in path:
        return None
    ptype, rest = path.split("/", 1)
    ptype = ptype.strip().lower()
    rest = rest.strip("/").lower()
    if not ptype or not rest:
        return None
    if ptype == "pypi":
        rest = re.sub(r"[-_.]+", "-", rest)
    return ptype, f"{ptype}/{rest}", version


def _norm_purl_locator(locator: str) -> str:
    """externalRefs の purl 比較用。種別・名前の大文字小文字や pypi の区切り違いを吸収する（version と qualifiers は原文のまま）。"""
    parsed = parse_purl(locator)
    if not parsed:
        return locator
    qual = _text(locator).split("#", 1)[0].partition("?")[2]
    return f"pkg:{parsed[1]}" + (f"@{parsed[2]}" if parsed[2] else "") + (f"?{qual}" if qual else "")


def _find_purl(props: Dict[str, Any]) -> Optional[str]:
    refs = props.get("externalRefs")
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        loc = _text(ref.get("referenceLocator"))
        if _text(ref.get("referenceType")).lower() == "purl" or loc.lower().startswith("pkg:"):
            if parse_purl(loc):
                return loc
    return None


# バージョン比較 -----------------------------------------------------------

# 'rc' や 'beta' のようにリリース版より“前”を表す語。未知の英字（post / final など）はリリース版以後とみなす
_PRE_RELEASE_RANK = {"dev": -5, "snapshot": -5, "alpha": -4, "a": -4, "beta": -3, "b": -3,
                     "preview": -2, "pre": -2, "rc": -1, "c": -1}


def _version_tokens(v: str) -> Optional[List[Tuple[int, Any]]]:
    s = _text(v)
    if not s:
        return None
    s = re.sub(r"^[vV](?=\d)", "", s).split("+", 1)[0]      # 先頭の v と +build を除く
    if not s or not s[0].isdigit():
        return None                                         # コミットハッシュ等は大小比較しない
    toks: List[Tuple[int, Any]] = []
    for part in re.findall(r"\d+|[A-Za-z]+", s):
        toks.append((0, int(part)) if part.isdigit() else (1, part.lower()))
    return toks or None


def _cmp_token(x: Tuple[int, Any], y: Tuple[int, Any]) -> int:
    if x[0] == 0 and y[0] == 0:
        return (x[1] > y[1]) - (x[1] < y[1])
    if x[0] == 1 and y[0] == 1:
        rx, ry = _PRE_RELEASE_RANK.get(x[1], 1), _PRE_RELEASE_RANK.get(y[1], 1)
        if rx != ry:
            return (rx > ry) - (rx < ry)
        return (x[1] > y[1]) - (x[1] < y[1])
    num, alpha = (x, y) if x[0] == 0 else (y, x)            # 数字 vs 英字
    num_wins = _PRE_RELEASE_RANK.get(alpha[1], 1) < 0       # 英字が pre-release なら数字側が新しい
    result = 1 if num_wins else -1
    return result if x is num else -result


def compare_versions(a: str, b: str) -> Optional[int]:
    """a < b なら -1、等しければ 0、a > b なら 1。数値として解釈できないバージョンは None。"""
    ta, tb = _version_tokens(a), _version_tokens(b)
    if ta is None or tb is None:
        return None
    for x, y in zip(ta, tb):
        c = _cmp_token(x, y)
        if c:
            return c
    longer, sign = (ta, 1) if len(ta) > len(tb) else (tb, -1)
    rest = longer[min(len(ta), len(tb)):]
    for tok in rest:                                        # 長い方の余りを先頭から見る
        if tok == (0, 0):
            continue                                        # 1.0 と 1.0.0 は同じ
        if tok[0] == 0:
            return sign                                     # 1.0 と 1.0.1 は後者が新しい
        return -sign if _PRE_RELEASE_RANK.get(tok[1], 1) < 0 else sign   # 1.0-rc1 は 1.0 より古い
    return 0


# ライセンス式 -------------------------------------------------------------

def _norm_license(expr: str) -> str:
    """AND / OR だけの単純な式は項の順序を無視して比較する。括弧を含む式は空白と大文字小文字だけ吸収する。"""
    t = " ".join(expr.split())
    if not t:
        return ""
    if "(" in t or ")" in t:
        return t.lower()
    ands = re.split(r"\s+AND\s+", t, flags=re.I)
    ors = re.split(r"\s+OR\s+", t, flags=re.I)
    if len(ands) > 1 and len(ors) > 1:
        return t.lower()
    if len(ands) > 1:
        return " and ".join(sorted(p.lower() for p in ands))
    if len(ors) > 1:
        return " or ".join(sorted(p.lower() for p in ors))
    return t.lower()


def _norm_scalar(field_name: str, value: Any) -> str:
    """比較用の正規形。項目なし ≡ NOASSERTION として扱う（NONE は別物）。"""
    if isinstance(value, dict):                                      # packageVerificationCode
        excluded = value.get("packageVerificationCodeExcludedFiles") or []
        return _text(value.get("packageVerificationCodeValue")).lower() + "|" + ",".join(sorted(map(_text, excluded)))
    t = _text(value)
    if t.upper() == "NOASSERTION":
        t = ""
    if field_name in _LICENSE_FIELDS:
        return _norm_license(t)
    if field_name == "name":
        return normalize_name(t)
    if field_name == "filesAnalyzed":
        return t.lower()
    return t


def _display_scalar(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        v = _text(value.get("packageVerificationCodeValue"))
        ex = value.get("packageVerificationCodeExcludedFiles") or []
        return v + (f"  (除外: {', '.join(map(_text, ex))})" if ex else "")
    return _text(value)


def _set_elements(field_name: str, value: Any) -> Dict[str, str]:
    """一覧項目 → {比較用の正規形: 表示用テキスト}"""
    out: Dict[str, str] = {}
    if not isinstance(value, list):
        return out
    for item in value:
        if field_name == "checksums" and isinstance(item, dict):
            algo = _text(item.get("algorithm")).upper().replace("_", "-")
            val = _text(item.get("checksumValue")).lower()
            out[f"{algo}\0{val}"] = f"{algo}: {val}"
        elif field_name == "externalRefs" and isinstance(item, dict):
            cat = _text(item.get("referenceCategory")).upper().replace("_", "-")
            typ = _text(item.get("referenceType"))
            loc = _text(item.get("referenceLocator"))
            key_loc = _norm_purl_locator(loc) if typ.lower() == "purl" else loc
            out[f"{cat}\0{typ.lower() if typ.lower() == 'purl' else typ}\0{key_loc}"] = f"{cat} / {typ}: {loc}"
        else:
            t = _text(item)
            if field_name in _LICENSE_FIELDS:
                out[t.lower()] = t
            elif t:
                out[t] = t
    return out


# ---------------------------------------------------------------------------
# パッケージの内部表現と突合
# ---------------------------------------------------------------------------

class _Pkg:
    __slots__ = ("idx", "node", "props", "spdx_id", "name", "norm_name", "version",
                 "purl", "purl_type", "purl_base")

    def __init__(self, idx: int, node: Any):
        p = node.properties if isinstance(getattr(node, "properties", None), dict) else {}
        self.idx = idx
        self.node = node
        self.props = p
        self.spdx_id = _text(p.get("SPDXID")) or _text(getattr(node, "spdx_id", ""))
        self.name = _text(p.get("name")) or _text(getattr(node, "name", ""))
        self.norm_name = normalize_name(self.name)
        self.purl = _find_purl(p)
        parsed = parse_purl(self.purl) if self.purl else None
        self.purl_type, self.purl_base = (parsed[0], parsed[1]) if parsed else ("", "")
        v = _text(p.get("versionInfo"))
        if v.upper() == "NOASSERTION":
            v = ""
        self.version = v or ((parsed[2] or "") if parsed else "")    # versionInfo が無ければ purl の @version を使う

    @property
    def display_key(self) -> str:
        return self.purl_base or self.name or self.spdx_id


def _key_purl(p: _Pkg) -> Optional[str]:
    return p.purl_base or None


def _key_name(p: _Pkg) -> Optional[str]:
    return p.norm_name or None


def _key_spdxid(p: _Pkg) -> Optional[str]:
    return p.spdx_id or None


def _key_name_version(p: _Pkg) -> Optional[str]:
    return f"{p.norm_name}\0{p.version.lower()}" if p.norm_name else None


_KeyFunc = Callable[[_Pkg], Optional[str]]
_Compat = Callable[[_Pkg, _Pkg], bool]


def _passes(mode: MatchKey) -> List[Tuple[_KeyFunc, str, Optional[_Compat]]]:
    def purl_type_compatible(a: _Pkg, b: _Pkg) -> bool:           # purl の種別が両方あって違うなら別物（pypi/foo と npm/foo）
        return not (a.purl_type and b.purl_type and a.purl_type != b.purl_type)

    if mode == MatchKey.SPDXID:
        return [(_key_spdxid, "SPDXID", None)]
    if mode == MatchKey.NAME_VERSION:
        return [(_key_name_version, "名前+バージョン", None)]
    if mode == MatchKey.NAME:
        return [(_key_name, "名前", None)]
    if mode == MatchKey.PURL:
        return [(_key_purl, "purl", None)]
    return [(_key_purl, "purl", None), (_key_name, "名前（purl 無しのため）", purl_type_compatible)]


def _group(pkgs: Iterable[_Pkg], keyfunc: _KeyFunc) -> Tuple[Dict[str, List[_Pkg]], List[_Pkg]]:
    groups: Dict[str, List[_Pkg]] = {}
    unkeyed: List[_Pkg] = []
    for p in pkgs:
        k = keyfunc(p)
        if k is None:
            unkeyed.append(p)
        else:
            groups.setdefault(k, []).append(p)
    return groups, unkeyed


def _pair_group(la: List[_Pkg], lb: List[_Pkg], compat: Optional[_Compat]
                ) -> Tuple[List[Tuple[_Pkg, _Pkg]], List[_Pkg], List[_Pkg]]:
    """同一キーの中でペアを作る。version 一致 → SPDXID 一致 → 出現順。"""
    ok = compat or (lambda a, b: True)
    pairs: List[Tuple[_Pkg, _Pkg]] = []
    left_a, left_b = list(la), list(lb)

    def take(match: Callable[[_Pkg, _Pkg], bool]) -> None:
        for a in list(left_a):
            for b in left_b:
                if ok(a, b) and match(a, b):
                    pairs.append((a, b))
                    left_a.remove(a)
                    left_b.remove(b)
                    break

    take(lambda a, b: a.version == b.version)
    take(lambda a, b: bool(a.spdx_id) and a.spdx_id == b.spdx_id)
    take(lambda a, b: True)
    return pairs, left_a, left_b


# ---------------------------------------------------------------------------
# 差分の計算
# ---------------------------------------------------------------------------

def iter_package_nodes(root_node: Any) -> Iterator[Any]:
    """ツリーから package ノードを元の順序で列挙する（excel_io / serializer と同じ走査）。"""
    if root_node is None:
        return
    for folder in root_node.children:
        for node in folder.children:
            if node.node_type == "package":
                yield node


def _doc_info(root: Any, label: str, count: int) -> DocInfo:
    props: Dict[str, Any] = {}
    if root is not None:
        props = dict(getattr(root, "properties", {}) or {})
        info = next((c for c in root.children if getattr(c, "node_type", "") == "document_info"), None)
        if info is not None:
            props = {**props, **(info.properties or {})}
    ci = props.get("creationInfo") if isinstance(props.get("creationInfo"), dict) else {}
    return DocInfo(
        label=label,
        name=_text(props.get("name")),
        spdx_version=_text(props.get("spdxVersion")),
        created=_text(ci.get("created")),
        creators=[_text(c) for c in (ci.get("creators") or [])],
        package_count=count,
    )


def _fields_for(groups: Sequence[str], a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for g in ALL_GROUPS:
        if g not in groups:
            continue
        for k in FIELD_GROUPS[g][1]:
            if k != "*":
                names.append(k)
    if "other" in groups:                                      # このSBOM固有のスカラー項目
        extra = {k for src in (a, b) for k, v in src.items()
                 if k not in _KNOWN_KEYS and not isinstance(v, (dict, list))}
        names.extend(sorted(extra))
    return names


def _diff_pair(a: _Pkg, b: _Pkg, matched_by: str, ambiguous: bool, groups: Sequence[str]) -> PackageDiff:
    d = PackageDiff(
        status=DiffStatus.UNCHANGED, name=b.name or a.name, key=b.display_key or a.display_key,
        version_a=a.version, version_b=b.version, spdx_id_a=a.spdx_id, spdx_id_b=b.spdx_id,
        matched_by=matched_by, node_a=a.node, node_b=b.node,
    )
    if ambiguous:
        d.notes.append(t("compare.note.ambiguous"))

    for fname in _fields_for(groups, a.props, b.props):
        va, vb = a.props.get(fname), b.props.get(fname)
        if fname in _SET_FIELDS:
            ea, eb = _set_elements(fname, va), _set_elements(fname, vb)
            if set(ea) != set(eb):
                d.field_changes.append(FieldChange(
                    fname,
                    added=sorted(eb[k] for k in eb if k not in ea),
                    removed=sorted(ea[k] for k in ea if k not in eb),
                ))
        elif _norm_scalar(fname, va) != _norm_scalar(fname, vb):
            d.field_changes.append(FieldChange(fname, _display_scalar(va), _display_scalar(vb)))

    changed = {fc.field for fc in d.field_changes}
    if changed & {"licenseConcluded", "licenseDeclared"}:
        d.flags.append(FLAG_LICENSE)
    if "supplier" in changed:
        d.flags.append(FLAG_SUPPLIER)
    if "downloadLocation" in changed:
        d.flags.append(FLAG_DOWNLOAD)
    if "hash" in groups and a.version and a.version == b.version and _checksum_mismatch(a.props, b.props):
        d.flags.insert(0, FLAG_CHECKSUM_MISMATCH)

    if a.version != b.version:
        d.status = DiffStatus.VERSION_CHANGED
        c = compare_versions(a.version, b.version)
        d.version_change = "upgrade" if c == -1 else "downgrade" if c == 1 else "changed"
    elif d.field_changes:
        d.status = DiffStatus.MODIFIED
    return d


def _checksum_mismatch(pa: Dict[str, Any], pb: Dict[str, Any]) -> bool:
    """両方に存在する同じアルゴリズムで、値が食い違っているか（片方にしか無いアルゴリズムは判定しない）。"""
    def by_algo(props: Dict[str, Any]) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = {}
        for k in _set_elements("checksums", props.get("checksums")):
            algo, val = k.split("\0", 1)
            out.setdefault(algo, set()).add(val)
        return out
    ca, cb = by_algo(pa), by_algo(pb)
    return any(ca[algo] != cb[algo] for algo in ca.keys() & cb.keys())


def compare(root_a: Any, root_b: Any, mode: MatchKey = MatchKey.AUTO,
            groups: Optional[Iterable[str]] = None,
            label_a: str = "A", label_b: str = "B",
            progress: Optional[Callable[[int], None]] = None,
            should_cancel: Optional[Callable[[], bool]] = None) -> CompareResult:
    """root_a（基準・旧）と root_b（対象・新）のパッケージを比較する。"""
    mode = MatchKey(mode)
    groups = tuple(g for g in ALL_GROUPS if g in set(groups if groups is not None else ALL_GROUPS))

    def tick(percent: int) -> None:
        if should_cancel and should_cancel():
            raise CompareCanceled()
        if progress:
            progress(percent)

    pkgs_a = [_Pkg(i, n) for i, n in enumerate(iter_package_nodes(root_a))]
    pkgs_b = [_Pkg(i, n) for i, n in enumerate(iter_package_nodes(root_b))]
    tick(0)

    pairs: List[Tuple[_Pkg, _Pkg, str, bool]] = []
    rest_a, rest_b = list(pkgs_a), list(pkgs_b)
    for keyfunc, label, compat in _passes(mode):
        ga, un_a = _group(rest_a, keyfunc)
        gb, un_b = _group(rest_b, keyfunc)
        next_a, next_b = list(un_a), list(un_b)
        for key, la in ga.items():
            lb = gb.get(key)
            if not lb:
                next_a.extend(la)
                continue
            matched, left_a, left_b = _pair_group(la, lb, compat)
            ambiguous = len(la) > 1 or len(lb) > 1
            pairs.extend((a, b, label, ambiguous) for a, b in matched)
            next_a.extend(left_a)
            next_b.extend(left_b)
        for key, lb in gb.items():
            if key not in ga:
                next_b.extend(lb)
        rest_a, rest_b = next_a, next_b
        tick(10)

    diffs: List[PackageDiff] = []
    total = max(len(pairs), 1)
    for n, (a, b, label, ambiguous) in enumerate(pairs):
        diffs.append(_diff_pair(a, b, label, ambiguous, groups))
        if n % 200 == 0:
            tick(10 + int(85 * n / total))

    for p in sorted(rest_a, key=lambda x: x.idx):
        diffs.append(PackageDiff(DiffStatus.REMOVED, p.name, p.display_key, version_a=p.version,
                                 spdx_id_a=p.spdx_id, node_a=p.node))
    for p in sorted(rest_b, key=lambda x: x.idx):
        diffs.append(PackageDiff(DiffStatus.ADDED, p.name, p.display_key, version_b=p.version,
                                 spdx_id_b=p.spdx_id, node_b=p.node))

    # 見やすい順: 追加・削除・変更が先、未変更は最後。同順位は名前順
    order = {DiffStatus.REMOVED: 0, DiffStatus.ADDED: 1, DiffStatus.VERSION_CHANGED: 2,
             DiffStatus.MODIFIED: 3, DiffStatus.UNCHANGED: 4}
    diffs.sort(key=lambda d: (order[d.status], d.name.lower(), d.version_b, d.version_a))

    result = CompareResult(
        mode=mode, groups=groups,
        doc_a=_doc_info(root_a, label_a, len(pkgs_a)), doc_b=_doc_info(root_b, label_b, len(pkgs_b)),
        diffs=diffs, root_a=root_a, root_b=root_b,
    )
    result.warnings = _build_warnings(result, pkgs_a, pkgs_b, mode)
    tick(100)
    return result


def _build_warnings(result: CompareResult, pkgs_a: List[_Pkg], pkgs_b: List[_Pkg], mode: MatchKey) -> List[str]:
    w: List[str] = []
    va, vb = result.doc_a.spdx_version, result.doc_b.spdx_version
    if va and vb and va != vb:
        w.append(t("compare.warn.spdx_version", a=va, b=vb))

    n_amb = sum(1 for d in result.diffs if d.notes)
    if n_amb:
        w.append(t("compare.warn.ambiguous", n=n_amb))

    if mode == MatchKey.SPDXID:
        miss = sum(1 for p in pkgs_a + pkgs_b if not p.spdx_id)
        if miss:
            w.append(t("compare.warn.no_spdxid", n=miss))
    elif mode == MatchKey.PURL:
        miss = sum(1 for p in pkgs_a + pkgs_b if not p.purl_base)
        if miss:
            w.append(t("compare.warn.no_purl", n=miss))
    elif mode == MatchKey.AUTO:
        fb = sum(1 for d in result.diffs if d.matched_by == "name_fallback" and d.status != DiffStatus.ADDED
                 and d.status != DiffStatus.REMOVED)
        if fb:
            w.append(t("compare.warn.name_fallback", n=fb))

    if mode == MatchKey.SPDXID and result.diffs:
        s = result.summary()
        total = max(s["total_a"], s["total_b"], 1)
        if (s["added"] + s["removed"]) / total > 0.5 and total >= 5:
            w.append(t("compare.warn.spdxid_mostly_unmatched"))
    return w


# ---------------------------------------------------------------------------
# CSV 出力
# ---------------------------------------------------------------------------

def _csv_safe(value: str) -> str:
    """Excel で開いたときに数式として解釈されないようにする。"""
    return "'" + value if value and value[0] in "=+-@\t\r" else value


def describe_change(fc: FieldChange) -> str:
    if fc.is_list:
        parts = [f"+ {x}" for x in fc.added] + [f"- {x}" for x in fc.removed]
        return f"{fc.field}: " + " / ".join(parts)
    old = t("compare.value.none") if fc.old is None else fc.old
    new = t("compare.value.none") if fc.new is None else fc.new
    return f"{fc.field}: {old} → {new}"


def export_csv(result: CompareResult, path: str, include_unchanged: bool = False) -> int:
    """差分を CSV（UTF-8 BOM 付き・Excel 向け）に書き出す。書き出した行数を返す。"""
    header = [t(f"compare.csv.{k}") 
              for k in ("status","name","old_version","new_version",
                        "version_change","old_spdxid","new_spdxid","key",
                        "matched_by","attention","changed_fields","details")]
    
    rows = 0
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for d in result.diffs:
            if d.status == DiffStatus.UNCHANGED and not include_unchanged:
                continue
            w.writerow([_csv_safe(x) for x in [
                status_label(d.status), d.name, d.version_a, d.version_b,
               version_change_label(d.version_change), d.spdx_id_a, d.spdx_id_b,
                d.key,matched_by_label(d.matched_by), " / ".join(flag_label(x) for x in d.flags),
                ", ".join(d.changed_fields),
                " | ".join(describe_change(fc) for fc in d.field_changes),
            ]])
            rows += 1
    os.replace(tmp, path)
    return rows
