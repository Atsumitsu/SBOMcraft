# core/compare_apply.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""比較結果の『新側(B)』を、基準側(A)のツリーへ取り込む（Qt 非依存・単体テスト可能）。

* 変更あり / バージョン変更: changed_fields の項目だけ B の値で上書き（B に無ければ削除）。SPDXID は変えない。
* 追加: B のパッケージを A にコピー（SPDXID が衝突したら別 ID にする）。
* 削除: include_removed=True のときだけ A から除く（そのパッケージを参照する Relationship も除く）。
ノードの生成は make_node(name=, node_type=, spdx_id=, properties=) に任せる（SBOMNode / テスト用の偽ノード両対応）。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, List, Set, Tuple

from core.comparer import DiffStatus, PackageDiff, iter_package_nodes
from core.i18n import t

NodeFactory = Callable[..., Any]


@dataclass
class AdoptResult:
    modified: List[Any] = field(default_factory=list)      # 値を書き換えたノード
    added: List[Any] = field(default_factory=list)         # 新しく加えたノード
    removed: List[Any] = field(default_factory=list)       # 除いたノード
    removed_relationships: int = 0
    kept_removed: int = 0                                  # 『削除』だが include_removed=False のため残した件数
    skipped: List[Tuple[PackageDiff, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.modified or self.added or self.removed)


def _used_ids(root) -> Set[str]:
    ids: Set[str] = set()
    props = getattr(root, "properties", None)
    if isinstance(props, dict) and props.get("SPDXID"):
        ids.add(props["SPDXID"])
    for folder in root.children:
        for node in folder.children:
            if node.node_type == "relationship":
                continue
            p = node.properties if isinstance(node.properties, dict) else {}
            sid = p.get("SPDXID") or getattr(node, "spdx_id", "")
            if sid:
                ids.add(sid)
    return ids


def _unique_id(sid: str, used: Set[str]) -> str:
    if sid and sid not in used:
        return sid
    base = sid or "SPDXRef-Package"
    n = 1
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"


def _packages_folder(root, make_node: NodeFactory):
    for f in root.children:
        if f.node_type == "packages_folder":
            return f
    for f in root.children:
        if any(c.node_type == "package" for c in f.children):
            return f
    folder = make_node(name="📁 Packages", node_type="packages_folder", spdx_id="", properties={})
    folder.parent = root
    idx = 1 if root.children and root.children[0].node_type == "document_info" else 0
    root.children.insert(idx, folder)
    return folder


def _detach(root, node) -> bool:
    for f in root.children:
        for i, c in enumerate(f.children):
            if c is node:
                del f.children[i]
                node.parent = None
                return True
    return False


def _drop_relationships(root, sid: str) -> int:
    if not sid:
        return 0
    n = 0
    for f in root.children:
        keep = []
        for c in f.children:
            p = c.properties if isinstance(c.properties, dict) else {}
            if c.node_type == "relationship" and sid in (p.get("spdxElementId"), p.get("relatedSpdxElement")):
                n += 1
            else:
                keep.append(c)
        if len(keep) != len(f.children):
            f.children[:] = keep
    return n


def adopt_new_side(root_a, diffs: Iterable[PackageDiff], make_node: NodeFactory,
                   include_removed: bool = False) -> AdoptResult:
    """diffs の B 側の内容を root_a（基準側）に反映する。root_a はその場で書き換える（UI スレッドから呼ぶこと）。"""
    res = AdoptResult()
    live = {id(n) for n in iter_package_nodes(root_a)}      # 比較後に A から消えたノードを触らないための確認用
    used = _used_ids(root_a)

    for d in diffs:
        if d.status == DiffStatus.UNCHANGED:
            continue

        if d.status == DiffStatus.ADDED:
            if d.node_b is None:
                continue
            props = copy.deepcopy(d.node_b.properties)
            old_id = props.get("SPDXID", "")
            new_id = _unique_id(old_id, used)
            if new_id != old_id:
                props["SPDXID"] = new_id
                res.notes.append(t("adopt.note.id_renamed", name=d.name, old=old_id or "-", new=new_id))
            used.add(new_id)
            node = make_node(name=props.get("name", ""), node_type="package", spdx_id=new_id, properties=props)
            folder = _packages_folder(root_a, make_node)
            node.parent = folder
            folder.children.append(node)
            live.add(id(node))
            res.added.append(node)

        elif d.status == DiffStatus.REMOVED:
            if not include_removed:
                res.kept_removed += 1
                continue
            node = d.node_a
            if node is None or id(node) not in live:
                res.skipped.append((d, t("adopt.skip.not_in_tree")))
                continue
            sid = node.properties.get("SPDXID") or getattr(node, "spdx_id", "")
            _detach(root_a, node)
            live.discard(id(node))
            res.removed_relationships += _drop_relationships(root_a, sid)
            res.removed.append(node)

        else:                                               # VERSION_CHANGED / MODIFIED
            na, nb = d.node_a, d.node_b
            if na is None or nb is None or id(na) not in live:
                res.skipped.append((d, t("adopt.skip.not_in_tree")))
                continue
            pa, pb = na.properties, nb.properties
            changed = False
            for fname in d.changed_fields:
                if fname in pb:
                    if fname not in pa or pa[fname] != pb[fname]:
                        pa[fname] = copy.deepcopy(pb[fname])
                        changed = True
                elif fname in pa:
                    del pa[fname]
                    changed = True
            if changed:
                res.modified.append(na)
    return res