# SBOM 適合性検証ルール仕様書  
**NTIA / CISA 2025 対応（core_validator.py 準拠版）**

本ドキュメントは、本ソフトウェアに実装されている **NTIA 最小要件** および  
**CISA 2025 最小要件（11項目）** に基づく SBOM 適合性検証ロジックの仕様をまとめたものです。

内容は `core_validator.py` の実装に完全準拠しています。


## 1. 検証プロファイル

| プロファイル | 概要 | 主なチェック対象 |
| --- | --- | --- |
| **NTIA** | NTIA Minimum Elements に基づく最小限の SBOM 要素 | Name / Version / Supplier / Originator |
| **CISA** | CISA 2025 最小要件（11項目）に基づく高度な検証 | NTIA 要件＋メタデータ＋識別子＋ハッシュ＋ライセンス＋依存関係＋生成コンテキスト |


## 2. Custom 高速エンジンの検証ルール（コード準拠）

### 2.1 NTIA / CISA 共通（パッケージ基本情報）

| 項目 | 判定 | 判定条件 | エラー表記 |
| --- | --- | --- | --- |
| **Name** | Error | `"name"` が空または存在しない | `Name欠落` |
| **VersionInfo** | Error | `"versionInfo"` が空または存在しない | `Version欠落` |
| **Supplier / Originator** | Error | 両方が `"NOASSERTION"` または不在 | `識別子(Supplier/Originator)欠落` |


## 3. CISA 追加要件（11項目）

CISA プロファイル選択時のみ適用。


## 3.1 ドキュメントメタデータ検証（creationInfo / comment）

| CISA項目 | 判定 | 判定条件 | エラー表記 |
| --- | --- | --- | --- |
| **Author** | Error | creators に `"Person:"` または `"Organization:"` が存在しない | `SBOM作成者の指定がありません` |
| **Tool Name / Version** | Error | `"Tool:"` が存在しない、または Tool 名に記号・数字が含まれない | `生成ツール名またはバージョン情報がありません` |
| **Timestamp** | Error | `"creationInfo"."created"` が空または不在 | `タイムスタンプがありません` |
| **Generation Context** | Error | comment または creators に `source`, `build`, `run`, `deploy` などの文脈キーワードが存在しない | `生成コンテキストが記述されていません` |


## 3.2 パッケージ単位の検証

| CISA項目 | 判定 | 判定条件 | エラー表記 |
| --- | --- | --- | --- |
| **Hashes** | Error | `"checksums"` が空または不在 | `Hash未記載(CISA必須要件不適合)` |
| **License** | Warning | `"licenseConcluded"` と `"licenseDeclared"` が両方 `"NOASSERTION"` | `License未明記(NOASSERTION)` |
| **Identifiers (purl/CPE)** | Error | externalRefs に purl / cpe22Type / cpe23Type / SECURITY / PACKAGE-MANAGER が存在しない | `ソフトウェア識別子(purl/CPE)欠落` |


## 3.3 SBOM 全体構造の検証

| CISA項目 | 判定 | 判定条件 | エラー表記 |
| --- | --- | --- | --- |
| **Relationships** | Error | `"relationships"` が 0 件 | `relationships フィールドが空です` |


## 4. Custom 高速エンジンの特性

### ✔ CISA 11項目に完全対応  
`core_validator.py` のロジックは CISA 2025 の 11項目すべてを網羅。

### ✔ NOASSERTION の扱い

| 項目 | 判定 |
| --- | --- |
| Supplier / Originator | **Error** |
| Hash | **Error** |
| License | **Warning（適合パス）** |

### ✔ Generation Context  
旧仕様では Warning → **コードでは Error に格上げ**

### ✔ Tool 名の判定ロジック  
`Tool:` の後ろに **数字または記号（-, _, /, space）** が含まれない場合、  
バージョン情報なしとみなし **Error**。


## 5. SPDX Official エンジン（補足）

- SPDXコミュニティが開発・提供する公式の `ntia-conformance-checker` ライブラリを利用
- NTIA → 標準チェック  
- CISA → `(file_path, True, 'fsct3-min')` を指定  
- NOASSERTION → **すべて不適合扱い**  
- 巨大 SBOM → 処理が重い  


## 6. 旧仕様からの変更点（差分）

| 項目 | 旧仕様 | 新仕様（コード準拠） |
| --- | --- | --- |
| Hash の判定 | Warning | **Error** |
| Generation Context | Warning | **Error** |
| Tool 名の判定 | `"Tool:" があればOK` | **記号 or 数字が含まれないと Error** |
| Author の判定 | Person/Organization が必要 | 変更なし |
| License の判定 | Warning | 変更なし |


---
このドキュメントは `core_validator.py` の実装内容と完全に一致するように調整されています。




