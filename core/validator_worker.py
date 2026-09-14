# SPDX-License-Identifier: Apache-.0
# Copyright (c) 2026 SBOMcraft Project

import os
import json
import re
import time
from PySide6.QtCore import QThread, Signal

class ValidationWorker(QThread):
    """巨大SBOMファイルの適合性チェックをバックグラウンドで実行し、進捗状況をリアルタイムに通知するワーカー"""

    # 外部（UIメイン画面）へ通知するシグナル群
    progress_status = Signal(str)  # 状態メッセージ（例: "パッケージ走査中 (500/2000)..."）
    progress_percent = Signal(int) # パーセンテージ (0-100)
    finished_report = Signal(dict) # 検証完了時の結果データ

    UNKNOWN_VALUES = {
        "noassertion", 
        "none", 
        "unknown", 
        "organization: unknown", 
        "person: unknown"
    }

    def __init__(self, file_path: str, profile: str = "CISA 2026"):
        super().__init__()
        self.file_path = file_path
        self.profile = profile

    def run(self):
        start_time = time.time()

        if not self.file_path or not os.path.exists(self.file_path):
            self.progress_status.emit("❌ エラー: ファイルが存在しません。")
            self.finished_report.emit({
                "passed": False,
                "report_html": "<font color='red'>エラー: 指定されたファイルが見つかりません。</font>",
                "error_packages": []
            })
            return

        # 1. JSON読み込み開始
        self.progress_status.emit("📄 SBOMファイルを読み込み中 (JSONパース)...")
        self.progress_percent.emit(10)

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.progress_status.emit(f"❌ パース失敗: {str(e)}")
            self.finished_report.emit({
                "passed": False,
                "report_html": f"<font color='red'>エラー: JSONのパースに失敗しました ({str(e)})</font>",
                "error_packages": []
            })
            return

        self.progress_percent.emit(30)
        
        creation_info = data.get("creationInfo", {})
        creators = creation_info.get("creators", [])
        packages = data.get("packages", [])
        relationships = data.get("relationships", [])
        doc_comment = data.get("comment", "") or creation_info.get("comment", "")

        doc_errors = []
        doc_warnings = []
        error_packages = []

        total_packages = len(packages)

        # 2. ドキュメントメタデータチェック
        self.progress_status.emit("🔍 ドキュメントレベル（メタデータ）の検証中...")
        if self.profile.startswith("CISA"):
            authors = [c for c in creators if c.startswith("Person:") or c.startswith("Organization:")]
            valid_authors = [a for a in authors if a.strip().lower() not in self.UNKNOWN_VALUES]
            if not valid_authors:
                doc_errors.append("ERR_CISA_AUTHOR_MISSING: A. SBOM作成者 (Author) の指定がありません。")

            tool_creators = [c for c in creators if c.startswith("Tool:")]
            if not tool_creators:
                doc_errors.append("ERR_CISA_TOOL_MISSING: I. 生成ツール名 (Tool Name) の指定がありません。")
            else:
                has_version = any(re.search(r'[\d\-\/\.\s]', c.replace("Tool:", "")) for c in tool_creators)
                if not has_version:
                    doc_warnings.append("WRN_CISA_TOOL_VERSION_MISSING: I. 生成ツールのバージョン (Tool Version) が明記されていない可能性があります。")

            created_timestamp = creation_info.get("created")
            if not created_timestamp or str(created_timestamp).strip().lower() in self.UNKNOWN_VALUES:
                doc_errors.append("ERR_CISA_TIMESTAMP_MISSING: J. タイムスタンプ (Timestamp) の指定がありません。")

            if not any(ctx in doc_comment.lower() for ctx in ["before build", "build", "after build", "deployed"]):
                doc_warnings.append("WRN_CISA_CONTEXT_MISSING: K. SBOM生成コンテキスト (Generation Context) の明記が推奨されます。")

            if not relationships or len(relationships) == 0:
                doc_errors.append("ERR_CISA_RELATION_EMPTY: H. 依存関係グラフ (Relationships) が1件も存在しません。")

        self.progress_percent.emit(40)

        # 3. パッケージレベル検証 (進捗をリアルタイムに更新)
        self.progress_status.emit(f"📦 パッケージ検証を開始 (総件数: {total_packages:,} 件)...")
        
        # UIの詰まり防止のため、100個単位（または全体割合）ごとにメッセージを発行
        update_interval = max(1, total_packages // 20)  # 全体の5%刻みで通知

        for idx, pkg in enumerate(packages):
            if idx % update_interval == 0 or idx == total_packages - 1:
                pct = 40 + int((idx / total_packages) * 50)  # 40% -> 90% の範囲で進捗割り当て
                self.progress_status.emit(f"📦 パッケージ検証中: {idx + 1:,} / {total_packages:,} 件完了 ({pct}%)...")
                self.progress_percent.emit(pct)

            pkg_name = pkg.get("name", "")
            pkg_version = pkg.get("versionInfo", "")
            pkg_id = pkg.get("SPDXID", f"Pkg-{idx}")

            reasons_err = []
            reasons_warn = []

            # NTIA / CISA 共通必須
            if not pkg_name or pkg_name.strip().lower() in self.UNKNOWN_VALUES:
                reasons_err.append("ERR_NTIA_NAME_MISSING (Name欠落)")

            if not pkg_version or pkg_version.strip().lower() in self.UNKNOWN_VALUES:
                reasons_err.append("ERR_NTIA_VERSION_MISSING (Version欠落)")

            supplier = pkg.get("supplier", "")
            originator = pkg.get("originator", "")
            supplier_invalid = (not supplier) or any(u in supplier.lower() for u in self.UNKNOWN_VALUES)
            originator_invalid = (not originator) or any(u in originator.lower() for u in self.UNKNOWN_VALUES)

            if supplier_invalid and originator_invalid:
                reasons_err.append("ERR_NTIA_PROVIDER_MISSING (識別子Supplier/Originator欠落)")

            # CISA 2026 追加要件
            if self.profile.startswith("CISA"):
                ext_refs = pkg.get("externalRefs", [])
                has_purl_or_cpe = any(
                    ref.get("referenceType") in ["purl", "cpe22Type", "cpe23Type"]
                    for ref in ext_refs
                )
                if not has_purl_or_cpe:
                    reasons_warn.append("WRN_CISA_IDENTIFIER_MISSING (識別子purl/CPE欠落)")

                checksums = pkg.get("checksums", [])
                has_valid_hash = False
                if checksums:
                    for chk in checksums:
                        val = str(chk.get("checksumValue", "")).strip().lower()
                        if val and val not in self.UNKNOWN_VALUES:
                            has_valid_hash = True
                            break
                if not has_valid_hash:
                    reasons_warn.append("WRN_CISA_HASH_MISSING (Hash/アルゴリズム未記載)")

                lic_concluded = str(pkg.get("licenseConcluded", "")).strip().lower()
                lic_declared = str(pkg.get("licenseDeclared", "")).strip().lower()
                concluded_invalid = (not lic_concluded) or (lic_concluded in self.UNKNOWN_VALUES)
                declared_invalid = (not lic_declared) or (lic_declared in self.UNKNOWN_VALUES)

                if concluded_invalid and declared_invalid:
                    reasons_warn.append("WRN_CISA_LICENSE_MISSING (License未明記)")

            if reasons_err or reasons_warn:
                error_packages.append({
                    "index": idx,
                    "spdx_id": pkg_id,
                    "name": pkg_name or "Unknown",
                    "errors": reasons_err,
                    "warnings": reasons_warn
                })

        # 4. レポート生成
        self.progress_status.emit("📄 検証レポートを作成中...")
        self.progress_percent.emit(95)

        has_pkg_errors = any(len(p["errors"]) > 0 for p in error_packages)
        passed = (len(doc_errors) == 0) and (not has_pkg_errors)
        elapsed = time.time() - start_time

        report_html = self._generate_html_report(
            self.profile, passed, elapsed, doc_errors, doc_warnings, error_packages
        )

        self.progress_percent.emit(100)
        self.progress_status.emit(f"✅ 検証完了 (所要時間: {elapsed:.2f} 秒)")

        # 完了データを結果シグナルとして渡す
        self.finished_report.emit({
            "passed": passed,
            "report_html": report_html,
            "error_packages": error_packages
        })

    def _generate_html_report(self, profile, passed, elapsed, doc_errors, doc_warnings, error_packages):
        status_color = "#28a745" if passed else "#dc3545"
        status_text = "適合 (PASS)" if passed else "不適合 (FAIL)"

        html = f"""
        <div style="font-family: sans-serif; line-height: 1.5;">
          <h3>📋 SBOM適合性検証レポート [{profile}]</h3>
          <p><b>総合判定:</b> <span style="color: {status_color}; font-weight: bold; font-size: 1.1em;">{status_text}</span> 
          (検証時間: {elapsed:.3f} 秒)</p>
        """

        if doc_errors or doc_warnings:
            html += "<h4>📄 ドキュメントメタデータの検証結果</h4><ul>"
            for err in doc_errors:
                html += f"<li style='color: #dc3545;'>❌ <b>[ERROR]</b> {err}</li>"
            for warn in doc_warnings:
                html += f"<li style='color: #d97706;'>⚠️ <b>[WARN]</b> {warn}</li>"
            html += "</ul>"

        if error_packages:
            html += f"<h4>📦 パッケージ単位の不備・警告一覧 ({len(error_packages)}件)</h4>"
            html += "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse; width:100%; border: 1px solid #ddd;'>"
            html += "<tr bgcolor='#f8f9fa'><th>Pkg ID</th><th>パッケージ名</th><th>エラー項目 (Error)</th><th>警告項目 (Warning)</th></tr>"
            
            for p in error_packages:
                err_str = "<br>".join([f"<font color='#dc3545'>❌ {e}</font>" for e in p['errors']]) if p['errors'] else "-"
                warn_str = "<br>".join([f"<font color='#d97706'>⚠️ {w}</font>" for w in p['warnings']]) if p['warnings'] else "-"
                
                html += f"<tr>"
                html += f"<td><code>{p['spdx_id']}</code></td>"
                html += f"<td><b>{p['name']}</b></td>"
                html += f"<td>{err_str}</td>"
                html += f"<td>{warn_str}</td>"
                html += f"</tr>"
            html += "</table>"
        else:
            html += "<p style='color: #28a745;'>すべてのパッケージが指定された検証条件を満たしています。</p>"

        html += "</div>"
        return html