# DynamicModel.md（改訂版） 2026/6/27

## 1. 概要（Overview）

DynamicModel は、SPDX JSON（SBOM）を固定クラスにマッピングせず、  
**動的にアクセス・探索・表示するための抽象レイヤー**である。

主な目的は以下の通り：
- JSON を固定クラスにマッピングしない
- SPDX 2.3 / 3.0 / 3.1 などのバージョン差異に強い
- NodeFactory が DynamicModel を使って DynamicNode を構築する
- UI（TreeView / 右ペイン）とは完全に独立している
- vendor extension（独自フィールド）をそのまま扱える  
- requirements.json のチェック（Missing / Unknown）に利用する  
- Raw JSON を完全に保持し、後続処理に提供

DynamicModel は SBOM の構造を歩くための API であり、
UI 表示やフィルタリングの責務は持たない。

---
## 2. 目的（Purpose）

DynamicModel の目的は以下の 3 点に集約される。

### 2.1 Vendor Extension の完全サポート  
SPDX には多くの vendor extension（独自フィールド）が存在する。

- CycloneDX 互換フィールド  
- GitHub SBOM 拡張  
- Microsoft Security Extension  
- SPDX 3.0 preview フィールド  
- 将来追加される未知のフィールド  

DynamicModel は JSON を固定クラスにマッピングしないため、  
**未知のフィールドでも損失なく保持できる。**

---

### 2.2 requirements.json の Missing / Unknown チェック  
DynamicModel は JSON の構造を完全に保持するため、  
requirements.json のチェックに利用できる。

- JSON に存在しない → Missing  
- Model に存在しない → Unknown  
- JSON と Model の両方に存在 → OK  

この仕組みにより、  
**SPDX のバージョン差異や vendor extension に強いチェックエンジン**を実現できる。

---

### 2.3 Raw JSON の完全保持  
DynamicModel は JsonElement を保持し、  
元の JSON を完全に再現できる。

これは以下の用途に利用される：

- 右ペインの Raw 表示  
- JSON Pointer の生成  
- 差分表示（将来機能）  
- チェック結果のハイライト  

---


## 3. 設計方針（Design Policy）

DynamicModel は以下の設計方針に基づく。

### ✔ 3.1 UI 非依存  
DynamicModel は UI 表示制御（TreeView の表示／非表示、右ペインの表示モード）を持たない。  
UI の制御は **SbomUiConfig + Converter + ViewModel** が担当する。

### ✔ 3.2 JSON 構造の忠実な保持  
DynamicModel は JSON の構造を変形しない。

- Document の Children を削らない  
- JSON の階層構造をそのまま保持  
- Raw JSON を保持し、再構築可能  

### ✔ 3.3 NodeFactory のためのデータソース  
DynamicModel は NodeFactory に JSON 構造を提供するだけであり、  
ノード分類（Document / Packages / Files など）は NodeFactory の責務。

---

## 4. クラス構造（Class Structure）

```csharp
public class DynamicModel
{
    private readonly JsonElement _root;

    public DynamicModel(JsonDocument document)
    {
        _root = document.RootElement;
    }

    public DynamicModel(JsonElement element)
    {
        _root = element;
    }

    public JsonValueKind ValueKind => _root.ValueKind;

    public IEnumerable<string> GetPropertyNames()
    {
        if (_root.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in _root.EnumerateObject())
                yield return prop.Name;
        }
    }

    public DynamicModel? GetProperty(string name)
    {
        if (_root.ValueKind == JsonValueKind.Object &&
            _root.TryGetProperty(name, out var value))
        {
            return new DynamicModel(value);
        }
        return null;
    }

    public IEnumerable<DynamicModel> GetArrayItems()
    {
        if (_root.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in _root.EnumerateArray())
                yield return new DynamicModel(item);
        }
    }

    public string? GetString()
        => _root.ValueKind == JsonValueKind.String ? _root.GetString() : null;

    public int? GetInt()
        => _root.ValueKind == JsonValueKind.Number ? _root.GetInt32() : null;

    public JsonElement Raw => _root;
}
```
## 5. JSON アクセス API（Access API）

DynamicModel は JSON の構造を動的に探索するための API を提供する。

### ✔ 5.1 プロパティ列挙  
`GetPropertyNames()`  
→ JSON オブジェクトのキー一覧を取得

### ✔ 5.2 プロパティ取得  
`GetProperty(name)`  
→ 指定キーの DynamicModel を返す

### ✔ 5.3 配列列挙  
`GetArrayItems()`  
→ JSON 配列の各要素を DynamicModel として返す

### ✔ 5.4 値取得  
`GetString()` / `GetInt()`  
→ JSON のプリミティブ値を取得

### ✔ 5.5 Raw JSON  
`Raw`  
→ JsonElement をそのまま返す

---

## 6. NodeFactory との関係（Integration with NodeFactory）

DynamicModel は NodeFactory のためのデータソースである。

NodeFactory は DynamicModel を使って DynamicNode を構築する：

```csharp
var model = new DynamicModel(jsonDocument);
var node = NodeFactory.BuildFromModel(model);
```

NodeFactory 内では：

```csharp
foreach (var prop in model.GetPropertyNames())
{
    var childModel = model.GetProperty(prop);
    var childNode = BuildFromModel(childModel);
    parent.Children.Add(childNode);
}
```

DynamicModel は **構造を提供するだけ**であり、  
ノード分類（Document / Packages / Files など）は NodeFactory の責務。

---

## 7. UI との関係（UI Independence）

DynamicModel は UI とは完全に独立している。

- TreeView の表示制御  
- 右ペインの表示モード  
- ノードの表示／非表示  

これらは **SbomUiConfig + Converter + ViewModel** が担当する。

DynamicModel は UI のために構造を変形しない。

---

## 8. 将来拡張（Future Extensions）

DynamicModel は以下の拡張を想定している。

- JSON Schema（spdx-schema-2-3.json）との比較  
- Missing / Unknown チェックの強化  
- Raw JSON の差分表示  
- JSON Pointer の生成  
- SPDX 3.0 / 3.1 への対応  
- vendor extension の自動検出  

---

# 🎉 まとめ

DynamicModel は SBOMCraft2 の「構造レイヤー」であり：

- vendor extension を保持  
- requirements.json のチェックに利用  
- Raw JSON を保持  
- NodeFactory に構造を提供  
- UI とは完全に独立  

という **明確な責務分離**を持つ。
