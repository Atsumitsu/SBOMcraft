# 📝 変更履歴 (Changelog)

SBOMcraft のすべての重要な変更はこのファイルに記録されます。
フォーマットは [Keep a Changelog](https://keepachangelog.com/ja/1.0.0/) に基づいています。

---

## [Unreleased]

---
## [v0.6.0.1] - 2026-09-22

### 変更 (Changed)
* **CISA 2026 最小要件適合性チェック**:
  * ハッシュアルゴリズム強度の検証ルール追加 (ERR_CISA_WEAK_HASH_ALGORITHM)
  * エラーログ・レポート画面への修正提案 (fix_suggestion) の追加
  * 署名・暗号検証に関するスコープ注記の明示
  * HTMLレポートの表示拡張

## [v0.6.0.0] - 2026-09-14

### 追加 (Added)
* **CISA 2026 最小要件適合性チェック**:
  * 最新の CISA 2026 規格（23要素）に対応した検証ロジックを実装。
  * `Tool Version`（生成ツールのバージョン情報）、`Generation Context`（ビルドコンテキスト）、`Relationships Coverage`（依存関係グラフの網羅性）の自動検証ルールを追加。
* **リアルタイム検証進捗表示 (`ValidationWorker`)**:
  * `QThread` による非同期バックグラウンド処理を導入。超巨大なSBOMファイル検証時でもUIがフリーズ（応答なし）せず、リアルタイムに進捗状況ログを出力する機能を実装。

### 変更 (Changed)
* **外部ライブラリ依存の整理**:
  * `ntia-conformance-checker` への依存および外部プロセス呼び出しを完全に削除し、O(N) で動作する超高速な自作検証エンジンに一元化。
* **データ未定義値 (`NOASSERTION`, `unknown` 等) の判定平準化**:
  * `Supplier` / `Originator` の未特定判定は厳格に **Error** (不適合) 化。
  * `Hash` および `License` の未特定判定はメタパッケージ等を考慮して **Warning** (警告・適合パス) へ分類整理。
* **ドキュメント更新**:
  * `VALIDATION_RULE.md` を CISA 2026 最新要件およびデータ未定義値の取り扱い方針に合わせて全面改訂。



