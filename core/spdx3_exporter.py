# core/spdx3_exporter.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 SBOMcraft Project

import json
from datetime import datetime
import uuid

# SPDX 3.0.1 の SbomType 公式語彙定義
VALID_SBOM_TYPES = {"analyzed", "build", "deployed", "design", "runtime", "source"}

def convert_node_to_spdx3(root_node, output_path: str, meta_data: dict = None):
    """
    SBOMcraftの内部ツリーデータを走査し、
    SPDX 3.0.1 の正式仕様（Core / Software プロファイル）に準拠した 
    JSON-LD データを構築する。
    パッケージ間の依存関係およびライセンス情報を独立した Relationship ノードとして生成する。
    """
    if meta_data is None:
        meta_data = {}

    # 1. メタデータの取得
    doc_name = meta_data.get("document_name", "SBOM-Document")
    creator_str = meta_data.get("creator", "Organization: Unknown") 
    tool_str = meta_data.get("tool_name", "Tool: SBOMcraft-v1.0") 
    created = meta_data.get("created", datetime.utcnow().isoformat() + "Z") 
    user_comment = meta_data.get("comment", "") 
    sbom_type_val = meta_data.get("sbom_type", "analyzed") 
    data_license_raw = meta_data.get("data_license", "CC0-1.0")

    # ライセンス表記を SPDX の公式URI形式に正規化
    if not data_license_raw.startswith("http"):
        data_license = f"https://spdx.org/licenses/{data_license_raw}"
    else:
        data_license = data_license_raw

    doc_uuid = str(uuid.uuid4())[:8]
    base_ns = f"http://spdx.org/spdxdocs/{doc_name}-{doc_uuid}"

    graph_nodes = []

    # 2. CreationInfo の構築 (Blank Node ID を使用)
    creation_info_id = "_:creationinfo"

    # 3. エージェント（組織・人物・ツール）の分解とノード生成
    actors_map = {}

    def parse_and_create_actor(actor_input, default_type="Organization"):
        if not actor_input:
            return None
        
        if ":" in actor_input:
            p_type, name = actor_input.split(":", 1)
            p_type = p_type.strip()
            name = name.strip()
        else:
            p_type = default_type
            name = actor_input.strip()

        node_type = "Organization"
        if p_type.lower() in ["person", "p"]:
            node_type = "Person"
        elif p_type.lower() in ["tool", "t"]:
            node_type = "Tool"

        safe_name_id = name.replace(" ", "")
        actor_id = f"{base_ns}#SPDXRef-Actor-{safe_name_id}"

        if actor_id not in actors_map:
            actor_node = {
                "creationInfo": creation_info_id,
                "type": node_type,
                "spdxId": actor_id,
                "name": name
            }
            graph_nodes.append(actor_node)
            actors_map[actor_id] = actor_id

        return actor_id

    creator_id = parse_and_create_actor(creator_str, "Organization")
    tool_id = parse_and_create_actor(tool_str, "Tool")

    created_by_ids = [creator_id] if creator_id else []
    created_using_ids = [tool_id] if tool_id else []

    # CreationInfo ノード自体の定義
    creation_info_node = {
        "type": "CreationInfo",
        "spdxId": creation_info_id,
        "specVersion": "3.0.1",
        "created": created,
        "createdBy": created_by_ids,
        "createdUsing": created_using_ids,
        "dataLicense": "https://spdx.org/licenses/CC0-1.0"
    }
    graph_nodes.append(creation_info_node)

    # 4. ツリーからパッケージノードおよびリレーションシップノードを収集
    packages_to_process = []
    relationships_to_process = []

    def collect_nodes(node):
        if not node:
            return
        node_type = getattr(node, "node_type", "")
        if node_type == "package":
            packages_to_process.append(node)
        elif node_type == "relationship":
            relationships_to_process.append(node)
        
        for child in getattr(node, "children", []):
            collect_nodes(child)

    if root_node:
        collect_nodes(root_node)

    package_ids = []
    license_relationship_ids = []
    root_package_id = None

    for idx, pkg in enumerate(packages_to_process):
        properties = getattr(pkg, "properties", {})
        
        pkg_id = properties.get("SPDXID", "") or getattr(pkg, "spdx_id", "") or f"{base_ns}#SPDXRef-Package-{idx}"
        if not pkg_id.startswith("http"):
            pkg_id = f"{base_ns}#{pkg_id}"
            
        package_ids.append(pkg_id)
        if root_package_id is None:
            root_package_id = pkg_id  # 最初のパッケージをルートとみなす
        
        pkg_name = properties.get("name", "") or getattr(pkg, "name", "UnknownPackage")
        pkg_version = properties.get("versionInfo", "") or properties.get("version", "1.0.0")

        software_pkg = {
            "creationInfo": creation_info_id,
            "type": "software_Package",
            "spdxId": pkg_id,
            "name": pkg_name,
            "software_packageVersion": pkg_version
        }
        
        # --- ライセンス処理 (SPDX 3.0 準拠: 独立した Relationship ノードとして生成) ---
        declared_license = properties.get("licenseDeclared") or properties.get("declared_license")
        concluded_license = properties.get("licenseConcluded") or properties.get("concluded_license")

        def normalize_license_uri(lic):
            if not lic:
                return "https://spdx.org/licenses/NOASSERTION"
            if lic.startswith("http"):
                return lic
            if lic in ["NOASSERTION", "NONE"]:
                return f"https://spdx.org/licenses/{lic}"
            return f"https://spdx.org/licenses/{lic}"

        # 1. Declared License のリレーション生成
        dec_lic_uri = normalize_license_uri(declared_license)
        dec_rel_id = f"{base_ns}#SPDXRef-Relationship-DeclaredLicense-{idx}"
        license_relationship_ids.append(dec_rel_id)
        
        graph_nodes.append({
            "creationInfo": creation_info_id,
            "type": "Relationship",
            "spdxId": dec_rel_id,
            "from": pkg_id,
            "to": [dec_lic_uri],
            "relationshipType": "hasDeclaredLicense"
        })

        # 2. Concluded License のリレーション生成
        con_lic_uri = normalize_license_uri(concluded_license)
        con_rel_id = f"{base_ns}#SPDXRef-Relationship-ConcludedLicense-{idx}"
        license_relationship_ids.append(con_rel_id)
        
        graph_nodes.append({
            "creationInfo": creation_info_id,
            "type": "Relationship",
            "spdxId": con_rel_id,
            "from": pkg_id,
            "to": [con_lic_uri],
            "relationshipType": "hasConcludedLicense"
        })

        # --- ハッシュ (verifiedUsing プロパティに変更し、Hash クラスオブジェクトとしてネスト) ---
        checksums = properties.get("checksums", [])
        hashes_list = []
        if checksums:
            for cs in checksums:
                algo = cs.get("algorithm", "SHA256")
                val = cs.get("checksumValue", "")
                if val:
                    hashes_list.append({
                        "type": "Hash",
                        "algorithm": algo,
                        "hashValue": val
                    })
        
        if hashes_list:
            software_pkg["verifiedUsing"] = hashes_list
        else:
            software_pkg["verifiedUsing"] = [{
                "type": "Hash",
                "algorithm": "SHA256",
                "hashValue": "NOASSERTION"
            }]

        # --- packageUrl もしくは CPE ---
        external_refs = properties.get("externalRefs", [])
        purl_val = None
        cpe_val = None

        for ref in external_refs:
            ref_type = ref.get("referenceType", "")
            ref_locator = ref.get("referenceLocator", "")
            if "purl" in ref_type.lower() or ref_locator.startswith("pkg:"):
                purl_val = ref_locator
            elif "cpe" in ref_type.lower() or ref_locator.startswith("cpe:"):
                cpe_val = ref_locator

        if not purl_val:
            purl_val = properties.get("packageUrl") or properties.get("purl")

        if purl_val:
            software_pkg["software_packageUrl"] = purl_val
        elif cpe_val:
            software_pkg["software_packageUrl"] = cpe_val
        else:
            software_pkg["software_packageUrl"] = "NONE"

        # --- copyrightText ---
        copyright_text = properties.get("copyrightText") or properties.get("copyright")
        if copyright_text:
            software_pkg["software_copyrightText"] = copyright_text
        else:
            software_pkg["software_copyrightText"] = "NOASSERTION"

        # サプライヤーの処理
        supplier_str = properties.get("supplier")
        if supplier_str:
            supplier_id = parse_and_create_actor(supplier_str, "Organization")
            if supplier_id:
                software_pkg["suppliedBy"] = [supplier_id]

        graph_nodes.append(software_pkg)

    # 5. 依存関係リレーションシップノード（type: "Relationship"）の動的生成と追加
    dependency_relationship_ids = []
    for idx, rel_node in enumerate(relationships_to_process):
        rel_props = getattr(rel_node, "properties", {})
        
        el_id = rel_props.get("spdxElementId", "")
        rel_id = rel_props.get("relatedSpdxElement", "")
        rel_type_raw = rel_props.get("relationshipType", "dependsOn")
        
        # IDのURI形式への正規化
        if el_id and not el_id.startswith("http"):
            el_id = f"{base_ns}#{el_id}"
        if rel_id and not rel_id.startswith("http"):
            rel_id = f"{base_ns}#{rel_id}"
            
        rel_node_id = f"{base_ns}#SPDXRef-Relationship-Dependency-{idx}"
        dependency_relationship_ids.append(rel_node_id)
        
        # camelCaseへの変換ロジック
        rel_type_lower = rel_type_raw.lower()
        if "_" in rel_type_lower:
            parts = rel_type_lower.split("_")
            rel_type = parts[0] + "".join(p.capitalize() for p in parts[1:])
        else:
            rel_type = rel_type_raw

        relationship_obj = {
            "creationInfo": creation_info_id,
            "type": "Relationship",
            "spdxId": rel_node_id,
            "from": el_id,
            "to": [rel_id] if rel_id else [],
            "relationshipType": rel_type
        }
        graph_nodes.append(relationship_obj)

    # 6. Sbom（ドキュメント本体）クラスの構築
    document_id = f"{base_ns}#SPDXRef-DOCUMENT"
    
    # すべての作成された要素（Package、依存用Rel、ライセンス用Rel）を包含
    all_element_ids = package_ids + dependency_relationship_ids + license_relationship_ids
    spdx_sbom = {
        "creationInfo": creation_info_id,
        "type": "software_Sbom",
        "spdxId": document_id,
        "name": doc_name,
        "dataLicense": data_license,
        "rootElement": [root_package_id] if root_package_id else [],
        "element": all_element_ids
    }
    if sbom_type_val in VALID_SBOM_TYPES:
        spdx_sbom["software_sbomType"] = [sbom_type_val]
    else:
        spdx_sbom["software_sbomType"] = ["analyzed"]
    
    if user_comment:
        spdx_sbom["comment"] = user_comment
    
    # Sbom オブジェクトをグラフの先頭に挿入
    graph_nodes.insert(0, spdx_sbom)
    
    # 7. 最終的な JSON-LD 構造の組み立て
    spdx3_data = {
        "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
        "@graph": graph_nodes
    }
    
    # 8. ファイル書き出し
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spdx3_data, f, ensure_ascii=False, indent=2)
    
    return True