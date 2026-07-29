# core/parser.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import ijson
import os
from typing import Dict, List, Any
from PySide6.QtCore import QObject, Signal

class SBOMNode:
    """共通のデータモデル（ツリー構造の1ノード）"""
    def __init__(self, name: str, node_type: str = "unknown", spdx_id: str = "", properties: dict = None):
        self.name = name
        self.node_type = node_type
        self.spdx_id = spdx_id
        self.properties = properties if properties is not None else {}
        self.children: List['SBOMNode'] = []
        self.parent: 'SBOMNode' = None

    def append_child(self, child: 'SBOMNode'):
        child.parent = self
        self.children.append(child)

    def child_count(self) -> int:
        return len(self.children)

class ParseWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    # 進捗（0〜100）をメイン画面に伝えるシグナル
    progress = Signal(int)

    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath
        self._is_canceled = False # キャンセル判定用フラグ

    def cancel(self):
        """外部（メイン画面）からパースを中断するためのメソッド"""
        self._is_canceled = True

    def run(self):
        try:
            # 1. ファイルサイズの取得（進捗率計算用）
            file_size = os.path.getsize(self.filepath)
            if file_size == 0:
                 raise ValueError("ファイルが空です。")

            root = SBOMNode(name="📒 DocumentRoot", node_type="document")
            doc_info_node = SBOMNode(name="ℹ️ Document Information", node_type="document_info")
            packages_folder = SBOMNode(name="📁 Packages", node_type="packages_folder")
            files_folder = SBOMNode(name="📁 Files", node_type="category_folder")
<<<<<<< HEAD
            relations_folder = SBOMNode(name="📁 Relationships", node_type="relations_folder")
=======
            relations_folder = SBOMNode(name="📁 Relationships", node_type="category_folder")
>>>>>>> af1e97c9afbfe2c9e7d4a4fd9c0042fa08817b2a
            licenses_folder = SBOMNode(name="📁 ExtractedLicense", node_type="category_folder")

            package_map: Dict[str, SBOMNode] = {}
            file_map: Dict[str, SBOMNode] = {}
            relationships_raw = []

            # 読み込みカウンター
            loop_counter = 0

            with open(self.filepath, 'rb') as f:
                items = ijson.kvitems(f, '')
                for k, v in items:
                    # ユーザーがキャンセルボタンを押していたら処理を即中断
                    if self._is_canceled:
                        self.finished.emit(None) # メインスレッド側に中断（結果なし）を通知
                        return

                    # 進行状況の計算と通知（100ループに1回通知してUI負荷を軽減）
                    loop_counter += 1
                    if loop_counter % 100 == 0:
                        current_pos = f.tell() # 現在ファイル内の何バイト目を開いているか
                        current_percent = int((current_pos / file_size) * 100)
                        self.progress.emit(min(current_percent, 99)) # 完了時以外は99%で止める

                    # --- パースロジック ---
                    # 【修正】'comment' を対象フィールドに追加
                    if k in ('SPDXID', 'name', 'spdxVersion', 'creationInfo', 
                             'dataLicense', 'documentNamespace', 'documentDescribes', 'comment'):
                        root.properties[k] = v
                        doc_info_node.properties[k] = v
                        if k == 'name':
                            doc_info_node.name = f"ℹ️ {v}"
                        elif k == 'SPDXID':
                            doc_info_node.spdx_id = v
                        
                    elif k == 'packages':
                        for pkg in v:
                            if self._is_canceled: # ネスト内でもキャンセルをチェック
                                self.finished.emit(None)
                                return
                            pkg_id = pkg.get('SPDXID', '')
                            pkg_name = pkg.get('name', 'Unknown Package')
                            pkg_node = SBOMNode(
                                name=f"📦 {pkg_name} ({pkg.get('versionInfo', 'N/A')})",
                                node_type="package",
                                spdx_id=pkg_id,
                                properties=pkg
                            )
                            packages_folder.append_child(pkg_node)
                             
                    elif k == 'files':
                        for file_info in v:
                            if self._is_canceled:
                                self.finished.emit(None)
                                return
                            f_id = file_info.get('SPDXID', '')
                            f_name = file_info.get('fileName', 'Unknown File')
                            f_node = SBOMNode(
                                name=f"📄 {f_name}",
                                node_type="file",
                                spdx_id=f_id,
                                properties=file_info
                            )
                            files_folder.append_child(f_node)

                    elif k == 'hasExtractedLicensingInfos':
                        for license_info in v:
                            if self._is_canceled:
                                self.finished.emit(None)
                                return
                            l_id = license_info.get('licenseId', '')
                            l_name = license_info.get('name', '(none)')
                            l_node = SBOMNode(
                                name=f"📜 {l_name}",
                                node_type="licenses",
                                spdx_id=l_id,
                                properties=license_info
                            )
                            licenses_folder.append_child(l_node)
                            
                    elif k == 'relationships':
                        relationships_raw = v

                # リレーションの登録
                for rel in relationships_raw:
                    if self._is_canceled:
                        self.finished.emit(None)
                        return
                    el_id = rel.get('spdxElementId', 'N/A')
                    rel_id = rel.get('relatedSpdxElement', 'N/A')
                    rel_type = rel.get('relationshipType', 'UNKNOWN')
                     
                    rel_node = SBOMNode(
                        name=f"🔗 {el_id} ➔ [{rel_type}] ➔ {rel_id}",
                        node_type="relationship",
                        spdx_id=f"{el_id}-{rel_id}",
                        properties=rel
                    )
                    relations_folder.append_child(rel_node)

            # ツリー構造の結合
            root.append_child(doc_info_node)
            if packages_folder.child_count() > 0:
                root.append_child(packages_folder)
            if files_folder.child_count() > 0:
                root.append_child(files_folder)
            if relations_folder.child_count() > 0:
                root.append_child(relations_folder)
            if licenses_folder.child_count() > 0:
                root.append_child(licenses_folder)

            # 100%完了を通知して終了
            self.progress.emit(100)
            self.finished.emit(root)
            
        except Exception as e:
            self.error.emit(str(e))