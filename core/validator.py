# core/validator.py
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 XZ Manj

import os
import json
import time
from ntia_conformance_checker import SbomChecker

class SBOMValidator:
    """NTIA最小要件およびCISA推奨要件を、公式APIまたは自作の高速エンジンで検証するクラス"""

    @staticmethod
    def check_compliance(file_path: str, profile: str = "NTIA", engine: str = "Custom") -> dict:
        """
        指定されたSBOMファイルを指定の規格（profile）とエンジン（engine）で検証する。
        """
        if not file_path or not os.path.exists(file_path):
            return {
                "passed": False, 
                "report_html": "<font color='red'>ファイルが見つかりません。</font>", 
                "error_packages": []
            }

        start_time = time.time()

        # -------------------------------------------------------------
        # パターンA: SPDX Official (公式API) 経由での検証
        # -------------------------------------------------------------
        if engine == "SPDX":
            try:
                if profile == "CISA":
                    sbom_checker = SbomChecker(file_path, True, 'fsct3-min')
                else:
                    sbom_checker = SbomChecker(file_path)
                
                is_compliant = sbom_checker.compliant
                report_html = sbom_checker.output_html()
                
                elapsed = time.time() - start_time
                prefix = f"<p style='color: gray; font-size: 11px;'>⏱️ SPDX Official API 処理時間: {elapsed:.2f} 秒</p>"
                
                return {
                    "passed": is_compliant,
                    "report_html": prefix + report_html,
                    "error_packages": []
                }
            except Exception as e:
                return {
                    "passed": False,
                    "report_html": f"<h3>❌ SPDX Official エラー</h3><p><font color='red'>{str(e)}</font></p>",
                    "error_packages": []
                }

        # -------------------------------------------------------------
        # パターンB: Custom (自作高速エンジン) での検証
        # -------------------------------------------------------------
        else:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # --- 1. ドキュメント全体のメタデータ検証 ---
                creation_info = data.get("creationInfo", {})
                creators = creation_info.get("creators", [])
                created_timestamp = creation_info.get("created")
                doc_comment = data.get("comment")

                metadata_errors = []
                
                has_author = any("Person:" in c or "Organization:" in c for c in creators)
                has_tool = any("Tool:" in c for c in creators)

                if profile == "CISA":
                    if not has_author:
                        metadata_errors.append("A. SBOM作成者 (Author) の指定がありません。")
                    if not has_tool:
                        metadata_errors.append("I. 生成ツールの名称 (Tool Name) の指定がありません。")
                    if not created_timestamp:
                        metadata_errors.append("J. タイムスタンプ (Timestamp) の指定がありません。")

                # --- 2. パッケージ・リレーションシップの検証 ---
                packages = data.get("packages", [])
                relationships = data.get("relationships", [])
                
                error_packages = []    # 適合性を落とす致命的な不備
                warning_packages = []  # NOASSERTIONなど、許容されるが確認推奨の項目
                total_pkgs = len(packages)
                
                missing_name = 0
                missing_version = 0
                missing_supplier = 0
                missing_hash = 0      
                missing_license = 0   
                missing_identifier = 0

                for idx, pkg in enumerate(packages):
                    reasons_err = []
                    reasons_warn = []
                    
                    name = pkg.get("name")
                    version = pkg.get("versionInfo")
                    supplier = pkg.get("supplier", "NOASSERTION")
                    originator = pkg.get("originator", "NOASSERTION")
                    
                    if not name:
                        missing_name += 1
                        reasons_err.append("Name欠落")
                    if not version:
                        missing_version += 1
                        reasons_err.append("Version欠落")
                    
                    # Supplier / Originator 双方ともにNOASSERTIONの場合はクリティカルエラー
                    if "NOASSERTION" in supplier and "NOASSERTION" in originator:
                        missing_supplier += 1
                        reasons_err.append("識別子(Supplier/Originator)欠落")

                    if profile == "CISA":
                        # F. Component Hash の検証 (見直し: 空はエラー、NOASSERTIONは警告)
                        hashes = pkg.get("checksums", [])
                        if not hashes:
                            missing_hash += 1
                            # 実務上、ハッシュを定義できないメタパッケージ等があるためWarningへ
                            reasons_warn.append("Hash未記載(NOASSERTION等)")
                        
                        # G. License の検証 (見直し: 欠落・NOASSERTIONは警告)
                        lic_concluded = pkg.get("licenseConcluded", "NOASSERTION")
                        lic_declared = pkg.get("licenseDeclared", "NOASSERTION")
                        if "NOASSERTION" in lic_concluded and "NOASSERTION" in lic_declared:
                            missing_license += 1
                            # ライセンス不明は実務上多発するためWarningへ
                            reasons_warn.append("License未明記(NOASSERTION)")

                        # E. Software Identifiers の検証
                        external_refs = pkg.get("externalRefs", [])
                        has_valid_id = any(
                            ref.get("referenceType") in ["purl", "cpe22Type", "cpe23Type"] or 
                            ref.get("referenceCategory") in ["SECURITY", "PACKAGE-MANAGER"]
                            for ref in external_refs
                        )
                        if not has_valid_id:
                            missing_identifier += 1
                            reasons_err.append("ソフトウェア識別子(purl/CPE)欠落")

                    if reasons_err:
                        error_packages.append({
                            "index": idx,
                            "name": name or f"Unknown_Pkg_{idx}",
                            "reasons": " / ".join(reasons_err)
                        })
                    
                    if reasons_warn and not reasons_err:
                        warning_packages.append({
                            "index": idx,
                            "name": name or f"Unknown_Pkg_{idx}",
                            "reasons": " / ".join(reasons_warn)
                        })

                # H. Dependency Relationship (依存関係) の検証
                has_relationships = len(relationships) > 0
                relationship_error = False
                if profile == "CISA" and not has_relationships:
                    relationship_error = True

                # 【変更点】warning_packages は、最終的な判定 (passed) を「不適合」にしない
                passed = (len(metadata_errors) == 0) and (len(error_packages) == 0) and (not relationship_error)
                
                elapsed = time.time() - start_time
                status_color = "green" if passed else "red"
                status_text = "【適合】" if passed else "【不適合】"

                # --- 3. HTMLレポートの生成 ---
                html = f"""
                <div style='font-family: sans-serif; padding: 10px;'>
                    <h2 style='color: {status_color}; margin-bottom: 5px;'>{profile} 適合性判定結果: {status_text}</h2>
                    <p style='color: gray; font-size: 11px; margin-top: 0;'>⏱️ Custom高速エンジン 処理時間: {elapsed:.2f} 秒 / スキャン対象: {total_pkgs} 件</p>
                    <hr>
                    <h3>📊 検証サマリー ({profile} プロファイル)</h3>
                    <table border='1' cellpadding='5' style='border-collapse: collapse; width: 100%; border-color: #ddd;'>
                        <tr style='background-color: #f2f2f2;'><th>要件チェック項目</th><th>ステータス</th><th>件数 / 状態</th></tr>
                        <tr><td>コンポーネント名 (Name)</td><td>{"✅ OK" if missing_name==0 else "❌ 不備あり"}</td><td>{missing_name} 件</td></tr>
                        <tr><td>バージョン情報 (Version)</td><td>{"✅ OK" if missing_version==0 else "❌ 不備あり"}</td><td>{missing_version} 件</td></tr>
                        <tr><td>作成者/提供者 (Supplier/Originator)</td><td>{"✅ OK" if missing_supplier==0 else "❌ 不備あり"}</td><td>{missing_supplier} 件</td></tr>
                """
                
                if profile == "CISA":
                    html += f"""
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> SBOM作成者 (Author)</td><td>{"✅ OK" if has_author else "❌ 不備あり"}</td><td>{"記載あり" if has_author else "未記載"}</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> 生成ツール名 (Tool Name)</td><td>{"✅ OK" if has_tool else "❌ 不備あり"}</td><td>{"記載あり" if has_tool else "未記載"}</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> タイムスタンプ (Timestamp)</td><td>{"✅ OK" if created_timestamp else "❌ 不備あり"}</td><td>{created_timestamp or "未記載"}</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> ハッシュ値 (Hashes)</td><td>{"⚠️ 注意" if missing_hash>0 else "✅ OK"}</td><td>{missing_hash} 件 (NOASSERTION許容)</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> ライセンス (License)</td><td>{"⚠️ 注意" if missing_license>0 else "✅ OK"}</td><td>{missing_license} 件 (NOASSERTION許容)</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> ソフトウェア識別子 (purl/CPE)</td><td>{"✅ OK" if missing_identifier==0 else "❌ 不備あり"}</td><td>{missing_identifier} 件</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> 依存関係の明記 (Relationships)</td><td>{"✅ OK" if has_relationships else "❌ 不備あり"}</td><td>{"あり" if has_relationships else "なし (0件)"}</td></tr>
                    """
                
                html += "</table>"

                # メタデータのエラー表示
                if metadata_errors:
                    html += "<h3 style='color: red; margin-top: 20px;'>❌ ドキュメント全体の不備 (CISAメタデータ項目)</h3><ul>"
                    for m_err in metadata_errors:
                        html += f"<li><font color='red'>{m_err}</font></li>"
                    html += "</ul>"

                # 致命的な不備（Error）の表示
                if error_packages:
                    html += f"<h3 style='color: red; margin-top: 20px;'>❌ エラーが検出されたパッケージ一覧 ({len(error_packages)}件)</h3><ul>"
                    for err in error_packages[:50]:
                        html += f"<li><b>{err['name']}</b>: <font color='red'>{err['reasons']}</font></li>"
                    if len(error_packages) > 50:
                        html += f"<li>...ほか {len(error_packages) - 50} 件のパッケージに致命的な不備があります。</li>"
                    html += "</ul>"
                
                # 【新設】許容されたが確認を推奨する不備（Warning）の表示
                if warning_packages:
                    html += f"<h3 style='color: #d97706; margin-top: 20px;'>⚠️ 警告・確認推奨パッケージ一覧 ({len(warning_packages)}件)</h3>"
                    html += "<p style='font-size:12px; color:gray;'>※これらの項目はNOASSERTION等のため、プロファイル適合判定自体はパスしています。</p><ul>"
                    for wrn in warning_packages[:50]:
                        html += f"<li><b>{wrn['name']}</b>: <font color='#d97706'>{wrn['reasons']}</font></li>"
                    if len(warning_packages) > 50:
                        html += f"<li>...ほか {len(warning_packages) - 50} 件のパッケージに警告があります。</li>"
                    html += "</ul>"
                    
                if profile == "CISA" and relationship_error:
                    html += "<h3 style='color: red; margin-top: 20px;'>❌ 依存関係のエラー</h3><p><font color='red'>relationships フィールドが空、または依存関係が記述されていません。</font></p>"

                if passed and not error_packages:
                    html += f"<p style='color: green; font-size: 14px; font-weight: bold; margin-top: 20px;'>🎉 素晴らしい！このSBOMファイルは {profile} の必須要件をすべて満たしています。</p>"

                html += "</div>"

                return {
                    "passed": passed,
                    "report_html": html,
                    "error_packages": error_packages
                }

            except Exception as e:
                return {
                    "passed": False,
                    "report_html": f"<h3>❌ Customエンジン エラー</h3><p><font color='red'>{str(e)}</font></p>",
                    "error_packages": []
                }