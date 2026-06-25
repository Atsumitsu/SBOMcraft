# DynamicModel 設計書

## 1. 目的

DynamicModel は、SPDX JSON（SBOM）を固定クラスにマッピングせず、  
**動的にアクセス・探索・表示するための抽象レイヤー**である。

主な目的は以下の通り：

- SPDX のバージョン変更に強い構造を実現する  
- vendor extension（独自フィールド）をそのまま扱える  
- TreeView 表示用の階層構造を生成する  
- requirements.json のチェック（Missing / Unknown）に利用する  
- JsonDocument を保持し、元の JSON 構造を完全に再現する

---

## 2. 全体構造

DynamicModel は以下の 2 つの責務を持つ：

1. **JSON の階層構造を動的に探索する（JsonDocument ベース）**
2. **TreeView 用の中間モデル（DynamicNode）を生成する**

JsonDocument
↓（保持）
DynamicModel
↓（階層を列挙）
DynamicNode（UI 用）
↓（バインド）
TreeView（WPF）


---

## 3. クラス構成

### 3.1 DynamicModel

```csharp
class DynamicModel
{
    JsonDocument _doc;

    JsonElement Root { get; }

    bool TryGet(string path, out JsonElement value);
    IEnumerable<DynamicNode> EnumerateChildren(JsonElement element);
}
```

### 3.2 DynamicNode（TreeView 用）

```csharp
class DynamicNode
{
    string Name { get; set; }
    string? Value { get; set; }
    string Path { get; set; }
    List<DynamicNode> Children { get; set; }
}
```
## 4. 機能要件
### 4.1 JSON の種類判定
DynamicModel は JsonElement の種類を判定できる必要がある：

Object

Array

Primitive（string, number, bool, null）

### 4.2 パスアクセス
任意のパスで JSON にアクセスできる：

例：

packages[0].SPDXID

files[2].checksums[1].algorithm

documentNamespace

### 4.3 子要素の列挙（TreeView 用）
DynamicModel は JsonElement の子要素を列挙し、
DynamicNode のリストとして返す。

### 4.4 JSON のパス生成
TreeView のノードをクリックしたときに
元の JSON の位置を特定するため、
各 DynamicNode は JSON 内のパスを保持する。

## 5. Node 生成ロジック
### 5.1 Object の場合
コード
{
  "name": "example",
  "version": "1.0",
  "annotations": [ ... ]
}
→ 子ノードは各プロパティ名

### 5.2 Array の場合
コード
"packages": [
  { ... },
  { ... }
]
→ 子ノードは [0], [1] のようなインデックス

### 5.3 Primitive の場合
コード
"SPDXID": "SPDXRef-Package"
→ Value に格納し、Children は空

### 5.4 TreeView のトップ構造（SBOM ノード）
SBOMCraft の TreeView は、SPDX JSON の構造をそのまま表示するのではなく、
ユーザーが理解しやすい論理構造に再編成して表示する。

トップノードは固定で “SBOM” とする
```
コード
SBOM
 ├─ Document
 ├─ Packages
 ├─ Files
 └─ Relationships
```
Document は JSON の root properties をまとめたノード

SPDX JSON のルートにある以下のようなフィールド：

SPDXID

name

spdxVersion

documentNamespace

creationInfo

…など

これらを Document ノードの子としてまとめる。

Packages / Files / Relationships は JSON の array をそのまま展開
例：
```
Packages
 ├─ [0]
 │    ├─ SPDXID
 │    ├─ name
 │    └─ ...
 └─ [1]
```
この構造は DynamicNode の生成ロジックで決定する

DynamicModel は JSON の構造を提供するだけで、
TreeView の構造（どこをトップにするか）は DynamicNode が決める。

## 6. DynamicModel の API 詳細
### 6.1 TryGet
```
bool TryGet(string path, out JsonElement value)
```
. で object のプロパティを辿る

[n] で array の要素を辿る

存在しない場合は false

### 6.2 EnumerateChildren
コード
IEnumerable<DynamicNode> EnumerateChildren(JsonElement element)
Object → properties を列挙

Array → index を列挙

Primitive → 子なし

## 7. TreeView との連携
DynamicNode は WPF の TreeView にそのままバインドできる：

xml
<TreeView ItemsSource="{Binding RootNodes}">
    <TreeView.ItemTemplate>
        <HierarchicalDataTemplate ItemsSource="{Binding Children}">
            <TextBlock Text="{Binding Name}" />
        </HierarchicalDataTemplate>
    </TreeView.ItemTemplate>
</TreeView>


## 8. SchemaLoader との連携
DynamicModel は SchemaLoader のフィールド一覧と照合し：

- Schema にある → JSON に無い → Missing

- JSON にある → Schema に無い → Unknown

両方にある → OK

というチェックが可能。


### 8.1 Unknown Fields（スキーマに存在しない項目）の扱い
DynamicModel が列挙した JSON のフィールドが、
SchemaLoader が保持するフィールド一覧に存在しない場合、
そのフィールドは Unknown Field として扱う。

Unknown Field は TreeView 上で以下のように表示する：

```
(Unknown) フィールド名
```
例：

```
Document
 ├─ SPDXID
 ├─ name
 ├─ (Unknown) myCompany:extraField
 └─ creationInfo
```
Unknown Fields の目的：

- vendor extension（独自フィールド）を可視化する
- スキーマに無い項目をユーザーに知らせる
- モデル拡張の判断材料にする
- requirements.json のチェック対象に含める

Unknown Fields の判定は以下の 2 つの情報を使う：

- DynamicModel → JSON の実データ
- SchemaLoader → スキーマのフィールド一覧

DynamicNode は Unknown を視覚的に区別できるように
IsUnknown フラグを持つことができる。

## 9. 将来拡張
- SPDX 3.0 対応
- JSON 編集機能
- ノードの検索
- ノードの折りたたみ状態の保持
- JSON の差分表示
- requirements.json の自動修正

## 10. まとめ
DynamicModel は SBOMCraft の中核であり：
- JSON の脳
- TreeView の土台
- requirements チェックの基盤
- 将来の SPDX バージョンにも耐える柔軟な設計

として機能する。
