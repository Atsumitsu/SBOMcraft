# 📋 SBOM 適合性検証ルール技術仕様書 (NTIA / CISA 2026 準拠)

本ドキュメントは、本システム（SBOMcraft）に実装されている **NTIA 最小要件（NTIA Minimum Elements）** および **CISA 2026 拡張最小要件（2026 Minimum Elements for an SBOM 準拠）** に対する自動適合性検証（バリデーション）エンジンの判定ロジック、データ未特定値（`NOASSERTION` / `unknown` 等）の取り扱い規定、およびエラーハンドリングの仕様を定義する技術仕様書である。

---

## 1. 検証プロファイル（規格）の定義

システムは、検証目的に応じて以下の検証プロファイル（ポリシー設定）を提供する。

| プロファイル | 準拠規格・ベースライン | 主な検証対象・スコープ |
| --- | --- | --- |
| **NTIA** | NTIA Minimum Elements for an SBOM | コンポーネントを識別するための必須最低限のメタデータ（名称、バージョン、提供者識別等）。 |
| **CISA 2026** | **2026 Minimum Elements for an SBOM** (CISA/国際パートナー合同ガイドライン) | NTIA要件に加え、作成者デジタル署名、生成ツールのバージョン情報、生成コンテキスト、ハッシュ値・ライセンス情報、およびネストされた依存関係グラフの網羅性（Coverage）の検証。 |

---

## 2. バリデーションルールおよび判定基準

検証エンジンは、SPDXドキュメントのルート要素および内包される全パッケージ要素（`packages` 配列）に対して静的解析ルールを適用する。

### 2.1. NTIA / CISA 2026 共通必須要件（パッケージ単位）

以下の項目は、選択されたプロファイルに関わらずすべてのパッケージ要素において必須（判定区分: **Error**）となる。1件でも不備が検出された場合、当該SBOM全体の適合性判定は **「不適合 (Failed)」** となる。

* **コンポーネント名 (Name)**

* **判定区分**: Error


* **ロジック**: パッケージオブジェクト内に `name` キーが存在しない、または値が空文字列（`""`）の場合。


* **エラーコード / メッセージ**: `ERR_NTIA_NAME_MISSING` / Name欠落




* **バージョン情報 (Version)**

* **判定区分**: Error


* **ロジック**: パッケージオブジェクト内に `versionInfo` キーが存在しない、または値が空文字列（`""`）の場合。


* **エラーコード / メッセージ**: `ERR_NTIA_VERSION_MISSING` / Version欠落




* **作成者/提供者 (Supplier / Producer)**

* **判定区分**: Error


* **ロジック**: `supplier` および `originator` の双方のフィールドにおいて、値が存在しない、または未特定を示す値（`NOASSERTION` / `Organization: unknown` 等）である場合。


* **仕様補足**: ソフトウェアの出所（Provenance）の特定はサプライチェーンセキュリティの根幹をなすため、厳格な Error として処理する。


* **エラーコード / メッセージ**: `ERR_NTIA_PROVIDER_MISSING` / 識別子(Supplier/Originator)欠落





---

### 2.2. CISA 2026 追加拡張要件

プロファイルとして **CISA 2026** が指定された場合、上記 2.1 に加えて以下のメタデータおよび構造検証が実行される。2026年改定における新設・拡張項目を含めて検証する。

#### A. ドキュメントレベル（メタデータ）の検証項目

| 要件項目 | 判定区分 | 判定条件・詳細ロジック | エラーコード / 画面表示メッセージ |
| --- | --- | --- | --- |
| **A. SBOM作成者 (Author)**<br> | **Error**<br> | `creationInfo.creators` 配列内に `Person:` または `Organization:` で始まる識別文字列が1件も含まれない（または `unknown` の指定のみ）場合。 | `ERR_CISA_AUTHOR_MISSING`<br><br>A. SBOM作成者 (Author) の指定がありません。 |
| **I. 生成ツール名 (Tool Name)**<br> | **Error**<br> | `creationInfo.creators` 配列内に `Tool:` で始まる識別文字列が1件も含まれない場合。 | `ERR_CISA_TOOL_MISSING`<br><br>I. 生成ツール名 (Tool Name) の指定がありません。 |
| **I-2. 生成ツールバージョン (Tool Version)**<br> | **Warning** | `creationInfo.creators` 内の `Tool:` 文字列内に、バージョン番号（数字、ハイフン、スラッシュ等）が含まれない場合。 | `WRN_CISA_TOOL_VERSION_MISSING`<br><br>I. 生成ツールのバージョン (Tool Version) が明記されていない可能性があります。 |
| **J. タイムスタンプ (Timestamp)**<br> | **Error**<br> | `creationInfo.created` フィールドが存在しない、または ISO 8601 形式としてパースできない場合。 | `ERR_CISA_TIMESTAMP_MISSING`<br><br>J. タイムスタンプ (Timestamp) の指定がありません。 |
| **K. 生成コンテキスト (Generation Context)**<br> | **Warning**<br> | ドキュメントルートまたは `creationInfo` の `comment` フィールドに `before build` / `build` / `after build` 等の生成段階を示すキーワードが含まれない場合。 | `WRN_CISA_CONTEXT_MISSING`<br><br>K. SBOM生成コンテキスト (Generation Context) の明記が推奨されます。 |
| **H. 依存関係の網羅性 (Relationships Coverage)**<br> | **Error**<br> | ドキュメントルート直下の `relationships` 配列のデータ件数が **0件** である場合。 | `ERR_CISA_RELATION_EMPTY`<br><br>H. 依存関係グラフ (Relationships) が1件も存在しません。 |

#### B. パッケージレベルおよびコンテキスト構造の検証項目

| 要件項目 | 判定区分 | 判定条件・詳細ロジック | エラーコード / 画面表示メッセージ |
| --- | --- | --- | --- |
| **E. ソフトウェア識別子 (Identifiers)**<br> | **Warning**<br> | 各パッケージ内の `externalRefs` を走査し、`referenceType` に `purl` または `cpe22Type` / `cpe23Type` の定義が1件も含まれていない場合。 | `WRN_CISA_IDENTIFIER_MISSING`<br><br>識別子(purl/CPE)欠落 |
| **F. ハッシュ値・アルゴリズム (Hashes & Algorithm)**<br> | **Warning**<br> | `checksums` 配列が存在しない、空、または要素内のハッシュ値・判定結果が `NOASSERTION` / `NONE` の場合。メタパッケージ等の影響を考慮し **Warning（適合パス）** と判定。 | `WRN_CISA_HASH_MISSING`<br><br>Hash/アルゴリズム未記載 |
| **G. ライセンス情報 (License)**<br> | **Warning**<br> | `licenseConcluded` および `licenseDeclared` の双方が `NOASSERTION` / `NONE` / 不在の場合。**Warning（適合パス）** と判定。 | `WRN_CISA_LICENSE_MISSING`<br><br>License未明記(NOASSERTION) |

---

## 3. データ未定義・保留値 (`NOASSERTION`, `NONE`, `unknown`) の取り扱い規定

CISA 2026 実務において、ツールによる生成限界やソースコードの制約により情報が特定できないケースが存在する。実務上の誤検知（False Positive）抑制と厳格なセキュリティ管理の両立を図るため、本システムでは未定義値・保留値の取り扱いを以下の原則に基づいて規定する。

### 3.1. 定義語（予約語）一覧および対象表記

* **`NOASSERTION`**: SPDX規格で定義された「作成者が情報を確認・確定しようとしたが特定しない、または確認を明示的に保留した」状態。


* **`NONE`**: SPDX規格で定義された「該当する要素やデータが提示・存在しないことが確認されている」状態。
* **`unknown` / `UNKNOWN**`: 「提供者（Producer/Supplier）や作成者が不明」であることを示す文字列（小文字/大文字問わず）。



### 3.2. フィールド別判定マトリクス

| フィールド | 判定値 (キーの値) | 判定区分 | 理由・運用方針 |
| --- | --- | --- | --- |
| **Supplier / Producer**<br> | `NOASSERTION`<br><br>`Organization: unknown`<br><br>`Person: unknown`<br><br>`NONE` | **不適合 (Error)**<br> | コンポーネントの提供元・開発組織の特定はサプライチェーン脆弱性対応（VEX連携等）の絶対条件であるため、未特定表記は一切許容しない。 |
| **Author (ドキュメント作成者)**<br> | `Organization: unknown`<br><br>`Person: unknown` | **不適合 (Error)**<br> | SBOM自体の作成責任者を明確化する規定に違反するため不適合とする。 |
| **Cryptographic Hash**<br> | `NOASSERTION`<br><br>`NONE` | **警告 (Warning)**<br> | ソースコードパッケージや仮想メタパッケージなど、実行可能バイナリハッシュを計算できない構造的要因を考慮し、適合判定自体は通す（Warning）。 |
| **License**<br> | `NOASSERTION`<br><br>`NONE` | **警告 (Warning)**<br> | 社内開発コードや依存関係の末端ライブラリにおけるライセンス未定義ケースを考慮し、警告として記録・提示する。 |
| **Generation Context**<br> | 未記載 | **警告 (Warning)**<br> | SPDX 2.3等においてコメントフィールドへの記載が標準化されているが、データフォーマット未統一のため警告扱いとする。 |