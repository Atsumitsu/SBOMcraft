## 1. DynamicNode の責務（何を担当するか）
DynamicNode は以下を担当する：

- TreeView に表示するための階層構造を表現する
- JSON のどの位置を指しているか（Path）を保持する
- 値（プリミティブ）か、子ノード（object/array）かを区別する
- Unknown / Missing などの“データ属性”を保持する
- UI に渡すための純粋なデータモデルである

逆に、DynamicNode が 担当しないこと：
- 色
- アイコン
- フォント
- 表示スタイル
- UI ロジック

これらは XAML（UI 層）で決める

##2. DynamicNode の構造（確定版）
```csharp
class DynamicNode
{
    public string Name { get; set; }            // 表示名（SBOM, Document, [0], SPDXID など）
    public string Path { get; set; }            // JSON 内のパス
    public string? Value { get; set; }          // プリミティブ値（object/array の場合は null）
    public List<DynamicNode> Children { get; set; } = new();

    // データ属性（UI ではなくロジック側の責務）
    public bool IsUnknown { get; set; }         // スキーマに無いフィールド
    public bool IsMissing { get; set; }         // スキーマにあるのに JSON に無い（必要なら）
    public bool IsRequired { get; set; }        // requirements.json で必須（必要なら）
}
```
✔ UI 情報は一切持たない
- → MVVM の分離が保たれる
- → Node は JSON の“意味”だけを持つ
- → XAML 側で DataTrigger により色やアイコンを決められる

## 3. TreeView の構造は DynamicNode が決める
DynamicModel は JSON を読むだけ。
TreeView の構造（どこをトップにするか）は DynamicNode の責務。

✔ トップノードは固定で “SBOM”
```
SBOM
 ├─ Document
 ├─ Packages
 ├─ Files
 └─ Relationships
```
✔ Document は root properties をまとめたノード
SPDXID, name, spdxVersion, creationInfo など。

✔ Packages / Files / Relationships は array を展開

[0], [1] のようにインデックスで表示。

## 4. Unknown Fields の扱い（Node の責務）
Unknown の判定は：

DynamicModel → JSON の実データ

SchemaLoader → スキーマのフィールド一覧

この 2 つの照合で決まる。

DynamicNode は Unknown を示す IsUnknown フラグだけ持つ。

UI 表示（赤文字、⚠ アイコンなど）は XAML 側で決める。

## 5. DynamicNode が持つべき“最小限の情報”
- Name（表示名）
- Path（JSON の位置）
- Value（プリミティブ値）
- Children（階層構造）
- IsUnknown / IsMissing / IsRequired（データ属性）

これ以上は持たない。
特に UI 情報は絶対に持たない。

### 5.1 DynamicNode の分類ルール（確定版）
DynamicNode の生成時に、root のプロパティを以下のように分類する。

### ① Document に入れる項目（メタ情報）
- SPDXID
- name
- spdxVersion
- dataLicense
- documentNamespace
- creationInfo
- documentDescribes
- comment
- annotations
- externalDocumentRefs
- その他の “メタ情報”

### ② Document と同列にする項目（大項目）
- packages
- files
- relationships
- hasExtractedLicensingInfos
- snippets（もしあれば）
- otherLicenses（SPDX 3.0 で追加される可能性）
## 6. DynamicNode の生成ロジック（概要）
1. トップノード “SBOM” を作る
2. その下に Document / Packages / Files / Relationships を作る
3. Document → root properties を列挙
4. Packages → array → [0] → object → properties
5. Unknown → IsUnknown = true
6. Missing → IsMissing = true（必要なら）



## 🎉 まとめ：DynamicNode の設計方針（要点）
UI とは完全に分離されたデータ構造

TreeView の構造（SBOM → Document / Packages / Files / Relationships）を決めるのは Node

Unknown / Missing はフラグで持つ（UI 情報は持たない）

DynamicModel は JSON を読むだけ、Node が TreeView の骨格を作る

UI の色・アイコンは XAML で後から決める

この設計は MVVM の原則に完全に沿っていて、
SBOMCraft の拡張性・保守性を最大化します。

