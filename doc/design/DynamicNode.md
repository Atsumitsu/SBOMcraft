# 📘 DynamicNode.md（SBOMCraft2 正式仕様 / 完全改訂版）

## 1. 概要（Overview）

**DynamicNode は SBOM JSON の構造をノードとして表現するための内部データモデルである。**

- DynamicModel（JSON 抽象化レイヤー）から生成される  
- SBOM の論理構造（Document / Packages / Files / Relationships）を表現する  
- Raw JSON を保持し、右ペインの raw 表示やチェック処理に利用できる  
- UI（TreeView / 右ペイン）とは完全に独立している  

DynamicNode は **SBOM の構造を表す中間モデル**であり、  
UI 表示制御の責務は持たない。

---

## 2. 目的（Purpose）

DynamicNode の目的は以下の 4 点に集約される。

### 2.1 SBOM の論理構造をノードとして表現する  
DynamicNode は JSON の階層構造をノードとして表現し、  
NodeType によって論理分類を行う。

### 2.2 vendor extension（独自フィールド）を保持する  
DynamicNode は DynamicModel と同様に、  
未知のフィールドでもそのまま保持できる。

### 2.3 requirements.json の Missing / Unknown チェックに利用する  
DynamicNode は以下の情報を保持する：

- JSON に存在しない → Missing  
- Model に存在しない → Unknown  
- JSON と Model の両方に存在 → OK  

Missing / Unknown の判定は DynamicNode の構造情報を利用して行われる。

### 2.4 Raw JSON の保持  
DynamicNode は JsonElement を保持し、  
右ペインの raw 表示や JSON Pointer の生成に利用できる。

---

## 3. 設計方針（Design Policy）

DynamicNode は以下の設計方針に基づく。

### ✔ 3.1 UI 非依存  
DynamicNode は UI 表示制御（TreeView の表示／非表示、右ペインの表示モード）を持たない。  
UI の制御は **SbomUiConfig + Converter + ViewModel** が担当する。

### ✔ 3.2 JSON 構造の忠実な保持  
DynamicNode は JSON の構造を変形しない。

- Document の Children を削らない  
- JSON の階層構造をそのまま保持  
- Raw JSON を保持し、再構築可能  

### ✔ 3.3 NodeType による論理分類  
NodeType は SBOM の論理構造を表すための分類であり、  
UI 表示のための分類ではない。

### ✔ 3.4 NodeFactory によって生成される  
DynamicNode は NodeFactory によって構築され、  
DynamicNode 自身は JSON の解析ロジックを持たない。

---

## 4. プロパティ構造（Properties）

DynamicNode のプロパティは以下の通り。

```csharp
public class DynamicNode
{
    public string Name { get; set; }          // JSON のキー名
    public string Path { get; set; }          // JSON Pointer 形式のパス
    public string? Value { get; set; }        // プリミティブ値（文字列/数値など）
    public List<DynamicNode> Children { get; set; } = new();

    public NodeType NodeType { get; set; }    // Document / Packages / Files / Relationships など

    public bool IsMissing { get; set; }       // requirements.json に存在するが JSON に無い
    public bool IsUnknown { get; set; }       // JSON に存在するが requirements.json に無い

    public JsonElement RawJson { get; set; }  // 元の JSON を保持
}
```

### ✔ UI 用プロパティは持たない  
DynamicNode は UI のためのプロパティ（Icon, Color, DisplayName など）を持たない。  
必要な場合は ViewModel 側で生成する。

---

## 5. NodeType の分類（NodeType Classification）

NodeType は SBOM の論理構造を表すための列挙型である。

例：

```csharp
public enum NodeType
{
    Document,
    Packages,
    Files,
    Relationships,
    Other
}
```

### ✔ NodeType の判定は NodeFactory の責務  
DynamicNode 自身は NodeType の判定ロジックを持たない。

---

## 6. NodeFactory との関係（Integration with NodeFactory）

DynamicNode は NodeFactory によって生成される。

NodeFactory の責務：

- DynamicModel を走査して DynamicNode を構築  
- NodeType を判定  
- Path を生成  
- RawJson を設定  
- Missing / Unknown を設定  

DynamicNode の責務：

- NodeFactory が構築した構造を保持するだけ  
- UI 表示制御は行わない  

---

## 7. UI との関係（UI Independence）

DynamicNode は UI とは完全に独立している。

- TreeView の表示制御  
- 右ペインの表示モード  
- ノードの表示／非表示  

これらは **SbomUiConfig + Converter + ViewModel** が担当する。

DynamicNode は UI のために構造を変形しない。

---

## 8. 将来拡張（Future Extensions）

DynamicNode は以下の拡張を想定している。

- NodeType の拡張（SPDX 3.0 / 3.1 対応）  
- Missing / Unknown チェックの強化  
- Raw JSON の差分表示  
- JSON Pointer の生成  
- vendor extension の自動分類  

---

# 🎉 まとめ

DynamicNode は SBOMCraft2 の「構造モデル」であり：

- JSON の構造を忠実に保持  
- NodeType による論理分類  
- Missing / Unknown チェックに利用  
- Raw JSON を保持  
- UI とは完全に独立  

という **明確な責務分離**を持つ。
