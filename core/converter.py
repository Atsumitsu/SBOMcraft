# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj

import uuid
from typing import Dict, Set
from cyclonedx.model.bom import Bom
from cyclonedx.model.component import Component, ComponentType
from cyclonedx.model import ExternalReference, ExternalReferenceType, HashAlgorithm, HashType 
from cyclonedx.model.dependency import Dependency
from cyclonedx.output.json import JsonV1Dot5
#from cyclonedx.factory.license import LicenseFactory
from cyclonedx.contrib.license.factories import LicenseFactory

# core.parser で定義している SBOMNode を参照
from core.parser import SBOMNode
from packageurl import PackageURL

class SPDXToCycloneDXConverter:
    """SBOMcraftの内部ツリー(SBOMNode)からCycloneDX JSONへ変換するコンバーター"""

    def __init__(self):
        self.license_factory = LicenseFactory()

    def convert(self, root_node: SBOMNode) -> str:
        """
        SBOMNode のルートノードを受け取り、CycloneDX 1.5 JSON 文字列を返す
        """
        bom = Bom()
        used_bom_refs: Set[str] = set()
        spdx_to_bom_ref: Dict[str] = {}  # SPDXID -> bom-ref の対応表

        # ノード検索用のヘルパー
        packages_folder = self._find_child_by_type(root_node, "packages_folder")
        doc_info = self._find_child_by_type(root_node, "document_info")
        relationships_node = self._find_child_by_type(root_node, "relations_folder")

        # 1. コンポーネント（Packages）の抽出と変換
        if packages_folder:
            print('packages_folder')
            for pkg_node in packages_folder.children:
                if pkg_node.node_type == "package":
                    print('package1')
                    component, original_spdx_id = self._create_component(pkg_node, used_bom_refs)
                    print('package2')
                    bom.components.add(component)
                    print('package3')
                    if original_spdx_id:
                        spdx_to_bom_ref[original_spdx_id] = component.bom_ref.value

        # 2. 依存関係（Relationships）の再構築
        if relationships_node and hasattr(relationships_node, "properties"):
            rel_list = relationships_node.properties.get("relationships_list", [])
            print('relationships_node')
            self._build_dependencies(bom, rel_list, spdx_to_bom_ref)

        # 3. CycloneDX JSON としてシリアライズ（出力）
        outputter  = JsonV1Dot5(bom)

        return outputter .output_as_string()

    def _create_component(self, pkg_node: SBOMNode, used_bom_refs: Set[str]) -> tuple[Component, str]:
        """SBOMNode(package) から CycloneDX Component を生成"""
        props = pkg_node.properties
        name = pkg_node.name or props.get("name", "Unknown-Package")
        version = props.get("versionInfo") or props.get("version")
        original_spdx_id = pkg_node.spdx_id or props.get("SPDXID", "")

        # bom-ref の生成（一意性の確保）
        bom_ref_val = self._generate_unique_bom_ref(original_spdx_id, name, used_bom_refs)

        component = Component(
            name=name,
            version=version,
            type=ComponentType.LIBRARY,
            bom_ref=bom_ref_val
        )

        # --- purl / CPE の設定 ---
        external_refs = props.get("externalRefs", [])
        for ref in external_refs:
            ref_type = ref.get("referenceType", "")
            ref_locator = ref.get("referenceLocator", "")
            
            if ref_type == "purl":
                try:
                    # ただの文字列ではなく、PackageURLオブジェクトに変換してセットする
                    component.purl = PackageURL.from_string(ref_locator)
                except ValueError:
                    pass  # 万が一purlの書式が不正な場合は安全にスキップ
            elif "cpe" in ref_type.lower():
                component.cpe = ref_locator

        # --- Checksums (Hashes) の設定 ---
        checksums = props.get("checksums", [])
        for cs in checksums:
            alg_str = cs.get("algorithm", "").upper().replace("-", "")
            val_str = cs.get("checksumValue", "")
            if hasattr(HashAlgorithm, alg_str) and val_str:
                alg_enum = getattr(HashAlgorithm, alg_str)
                component.hashes.add(HashType (algorithm=alg_enum, value=val_str))

        # --- License の設定 ---
        license_declared = props.get("licenseDeclared") or props.get("licenseConcluded")
        if license_declared and license_declared not in ["NOASSERTION", "NONE"]:
            try:
                lic = self.license_factory.make_from_string(license_declared)
                component.licenses.add(lic)
            except Exception:
                pass  # パース不能なカスタムライセンス文字列は安全にスキップ（または表現を調整）

        return component, original_spdx_id

    def _generate_unique_bom_ref(self, spdx_id: str, name: str, used_refs: Set[str]) -> str:
        """bom-ref の重複を回避し一意なIDを生成"""
        base_ref = spdx_id if spdx_id else f"ref-{name}"
        candidate = base_ref
        counter = 1
        
        while candidate in used_refs:
            candidate = f"{base_ref}-{counter}"
            counter += 1

        used_refs.add(candidate)
        return candidate

    def _build_dependencies(self, bom: Bom, rel_list: list, spdx_to_bom_ref: Dict[str, str]):
        """SPDXの Relationship 配列から CycloneDX の Dependency グラフを再構築"""
        dep_map: Dict[str, Set[str]] = {}

        for rel in rel_list:
            # DEPENDS_ON 依存関係の抽出
            if rel.get("relationshipType") in ["DEPENDS_ON", "DEPENDENCY_OF"]:
                element_id = rel.get("spdxElementId")
                related_id = rel.get("relatedSpdxElement")

                # DEPENDENCY_OF の場合は親子を反転
                if rel.get("relationshipType") == "DEPENDENCY_OF":
                    element_id, related_id = related_id, element_id

                parent_ref = spdx_to_bom_ref.get(element_id)
                child_ref = spdx_to_bom_ref.get(related_id)

                if parent_ref and child_ref:
                    if parent_ref not in dep_map:
                        dep_map[parent_ref] = set()
                    dep_map[parent_ref].add(child_ref)

        # Bom に Dependency を追加
        for parent_ref, children_refs in dep_map.items():
            dependency = Dependency(ref=parent_ref)
            for child_ref in children_refs:
                dependency.dependencies.add(Dependency(ref=child_ref))
            bom.dependencies.add(dependency)

    def _find_child_by_type(self, parent: SBOMNode, node_type: str) -> SBOMNode:
        """ノードの種別で子要素を探索"""
#        print(f"_find_child_by_type:{node_type}")
        for child in parent.children:
            if child.node_type == node_type:
#                 print("find")
                return child
        return None
    