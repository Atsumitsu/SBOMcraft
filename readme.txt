SBOMcraft
==================

作者: XZ manj
ライセンス: MIT License

概要
----
SBOMcraft は、SPDX JSON / SPDX Lite / CISA Minimum Elements に対応した
Windows 向け SBOM ビューア & チェッカーです。

巨大 SBOM（100MB〜200MB級）でもストリーミングで読み込み、
TreeView による高速ナビゲーションを可能にします。

主な機能
--------
- SPDX 2.3 JSON の読み込み
- 巨大 SBOM のストリーミング処理
- TreeView による Packages / Files / Relationships 表示
- DocumentRoot メタデータ表示
- CISA Minimum Elements チェック（予定）
- CRA 対応項目の確認（予定）
- モダンな WPF UI

動作環境
--------
- Windows 10 / 11 (x64)
- 本バージョンは Self-contained のため .NET ランタイム不要

使い方
------
1. SBOMcraft.exe を実行します。
2. 「Open SBOM」から SPDX JSON ファイルを選択します。
3. 左側の TreeView でパッケージやファイルを展開できます。

既知の問題
----------
- 大規模 SBOM の初回読み込みに時間がかかる場合があります。
- 一部の SPDX 拡張項目は未対応です。

変更履歴
--------
変更履歴
--------
v0.3.1.0
- 表示関連の修正
v0.2.0.0
- Self-contained (win-x64) ビルドに対応
- 巨大 SBOM の読み込み安定性を改善
- UI の微調整とアイコン更新
- About ダイアログの情報追加

ライセンス
----------
MIT License
Copyright (c) XZ manj
