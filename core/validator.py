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
                    # CISAプロファイル指定 ('fsct3-min')
                    sbom_checker = SbomChecker(file_path, True, 'fsct3-min')
                else:
                    # 通常のNTIA最小要件
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

                packages = data.get("packages", [])
                relationships = data.get("relationships", [])
                
                error_packages = []
                total_pkgs = len(packages)
                
                missing_name = 0
                missing_version = 0
                missing_supplier = 0
                missing_originator = 0
                missing_hash = 0      
                missing_license = 0   

                for idx, pkg in enumerate(packages):
                    reasons = []
                    name = pkg.get("name")
                    version = pkg.get("versionInfo")
                    supplier = pkg.get("supplier", "NOASSERTION")
                    originator = pkg.get("originator", "NOASSERTION")
                    
                    if not name:
                        missing_name += 1
                        reasons.append("Name欠落")
                    if not version:
                        missing_version += 1
                        reasons.append("Version欠落")
                    if "NOASSERTION" in supplier and "NOASSERTION" in originator:
                        missing_supplier += 1
                        reasons.append("識別子(Supplier/Originator)欠落")

                    if profile == "CISA":
                        hashes = pkg.get("checksums", [])
                        if not hashes:
                            missing_hash += 1
                            reasons.append("Hash未記載")
                        
                        lic_concluded = pkg.get("licenseConcluded", "NOASSERTION")
                        lic_declared = pkg.get("licenseDeclared", "NOASSERTION")
                        if "NOASSERTION" in lic_concluded and "NOASSERTION" in lic_declared:
                            missing_license += 1
                            reasons.append("License未明記")

                    if reasons:
                        error_packages.append({
                            "index": idx,
                            "name": name or f"Unknown_Pkg_{idx}",
                            "reasons": " / ".join(reasons)
                        })

                has_relationships = len(relationships) > 0
                relationship_error = False
                if profile == "CISA" and not has_relationships:
                    relationship_error = True

                passed = (len(error_packages) == 0) and (not relationship_error)
                
                elapsed = time.time() - start_time
                status_color = "green" if passed else "red"
                status_text = "【適合】" if passed else "【不適合】"

                html = f"""
                <div style='font-family: sans-serif; padding: 10px;'>
                    <h2 style='color: {status_color}; margin-bottom: 5px;'>{profile} 適合性判定結果: {status_text}</h2>
                    <p style='color: gray; font-size: 11px; margin-top: 0;'>⏱️ Custom高速エンジン 処理時間: {elapsed:.2f} 秒 / スキャン対象: {total_pkgs} 件</p>
                    <hr>
                    <h3>📊 検証サマリー ({profile} プロファイル)</h3>
                    <table border='1' cellpadding='5' style='border-collapse: collapse; width: 100%; border-color: #ddd;'>
                        <tr style='background-color: #f2f2f2;'><th>要件チェック項目</th><th>ステータス</th><th>不備件数</th></tr>
                        <tr><td>コンポーネント名 (Name)</td><td>{"✅ OK" if missing_name==0 else "❌ 不備あり"}</td><td>{missing_name} 件</td></tr>
                        <tr><td>バージョン情報 (Version)</td><td>{"✅ OK" if missing_version==0 else "❌ 不備あり"}</td><td>{missing_version} 件</td></tr>
                        <tr><td>作成者/提供者 (Supplier/Originator)</td><td>{"✅ OK" if missing_supplier==0 else "❌ 不備あり"}</td><td>{missing_supplier} 件</td></tr>
                """
                
                if profile == "CISA":
                    html += f"""
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> ハッシュ値 (Hashes)</td><td>{"✅ OK" if missing_hash==0 else "❌ 不備あり"}</td><td>{missing_hash} 件</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> ライセンス (License)</td><td>{"✅ OK" if missing_license==0 else "❌ 不備あり"}</td><td>{missing_license} 件</td></tr>
                        <tr style='background-color: #f9f9ff;'><td><b>[CISA推奨]</b> 依存関係の明記 (Relationships)</td><td>{"✅ OK" if has_relationships else "❌ 不備あり"}</td><td>{"あり" if has_relationships else "なし (0件)"}</td></tr>
                    """
                
                html += "</table>"

                if not passed:
                    html += f"<h3 style='color: red; margin-top: 20px;'>⚠️ 不備が検出されたパッケージ一覧 ({len(error_packages)}件)</h3><ul>"
                    for err in error_packages[:100]:
                        html += f"<li><b>{err['name']}</b>: <font color='red'>{err['reasons']}</font></li>"
                    if len(error_packages) > 100:
                        html += f"<li>...ほか {len(error_packages) - 100} 件のパッケージに不備があります。ツリー画面を確認してください。</li>"
                    html += "</ul>"
                else:
                    html += f"<p style='color: green; font-size: 14px; font-weight: bold; margin-top: 20px;'>🎉 素晴らしい！このSBOMファイルは {profile} のすべての要件を満たしています。</p>"

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