# 📘 requirements-check.md（SBOMCraft2 チェック仕様）

## 1. 概要（Overview）

**requirements.json は SBOM に対して行う必須チェック項目を定義する設定ファイルである。**

SBOMCraft2 のチェックエンジンは requirements.json を読み込み、  
SBOM JSON（DynamicModel / DynamicNode）と比較して以下を判定する：

- **Missing**：SBOM に存在しない必須項目  
- **Unknown**：SBOM に存在するが requirements.json に定義されていない項目  
- **OK**：SBOM に存在し、requirements.json にも定義されている項目  

requirements.json は UI とは独立した **チェックエンジンの仕様**である。

---

## 2. 目的（Purpose）

requirements.json の目的は以下の 3 点に集約される。

### 2.1 SBOM の最低限の品質保証  
NTIA / CISA / CRA などの SBOM 最低要件をチェックする。

### 2.2 SPDX バージョン差異に強いチェック  
SPDX 2.3 / 3.0 / 3.1 などの差異を吸収し、  
固定クラスに依存しない柔軟なチェックを実現する。

### 2.3 vendor extension（独自フィールド）への対応  
DynamicModel が未知フィールドを保持するため、  
Unknown チェックが可能。

---

## 3. requirements.json の構造（Structure）

### ✔ トップレベルは `"Sets"`  
複数のチェックセット（NTIA / CISA / CRA）を定義できる。

```json
{
  "Sets": {
    "NTIA": {
      "required": [
        "Document.name",
        "Document.spdxVersion",
        "Package.name",
        "Package.versionInfo"
      ],
      "recommended": [
        "Package.externalRefs"
      ]
    },
    "CISA": {
      "inherits": "NTIA",
      "required": [
        "Package.licenseDeclared",
        "Document.dataLicense"
      ],
      "recommended": [
        "Package.originator"
      ]
    }
  }
}
```

---

## 4. フィールドパスの仕様（Field Path Specification）

requirements.json のフィールドパスは以下の形式：

```
<RootType>.<Property>.<SubProperty>...
```

例：

- `Document.name`
- `Package.versionInfo`
- `Relationship.relatedSpdxElement`

### ✔ RootType は NodeType と一致する  
- Document  
- Package  
- File  
- Relationship  

### ✔ 大文字小文字は厳密一致  
DynamicModel の JSON プロパティ名と一致する必要がある。

---

## 5. チェックエンジンの動作（Check Engine Behavior）

チェックエンジンは以下の手順で動作する。

---

### 5.1 セットの解決（Inheritance Resolution）

CISA のように `"inherits": "NTIA"` を持つ場合：

1. NTIA の required/recommended をコピー  
2. CISA の required/recommended を上書き追加  
3. 重複は除外  

---

### 5.2 DynamicNode との比較

DynamicNode は NodeFactory によって構築され、  
以下の情報を持つ：

- Name  
- Path  
- NodeType  
- RawJson  
- Children  

チェックエンジンは requirements.json のフィールドパスを  
DynamicNode の構造と比較する。

---

### 5.3 Missing 判定

以下の条件で Missing：

- requirements.json に定義されている  
- DynamicNode に存在しない  

例：

```
Package.licenseDeclared → SBOM に無い → Missing
```

DynamicNode の `IsMissing = true` が設定される。

---

### 5.4 Unknown 判定

以下の条件で Unknown：

- DynamicNode に存在する  
- requirements.json に定義されていない  

例：

```
Package.customVendorField → requirements.json に無い → Unknown
```

DynamicNode の `IsUnknown = true` が設定される。

---

### 5.5 OK 判定

以下の条件で OK：

- requirements.json に定義されている  
- DynamicNode に存在する  

---

## 6. チェック結果の構造（Result Structure）

チェック結果は以下の構造を持つ：

```csharp
public class RequirementResult
{
    public string FieldPath { get; set; }
    public RequirementStatus Status { get; set; } // OK / Missing / Unknown
    public string? ActualValue { get; set; }
    public string? Comment { get; set; }
}
```

---

## 7. DynamicNode への反映（Integration with DynamicNode）

DynamicNode は以下のフラグを持つ：

```csharp
public bool IsMissing { get; set; }
public bool IsUnknown { get; set; }
```

チェックエンジンは判定結果を DynamicNode に反映する。

UI はこのフラグを利用して：

- Missing → 赤  
- Unknown → 黄  
- OK → 青  

などの色分けを行う。

---

## 8. UI との責務分離（UI Independence）

requirements.json は **UI とは完全に独立**している。

- TreeView の表示制御 → SbomUiConfig  
- 右ペインの表示制御 → SbomUiConfig  
- ノードの表示／非表示 → Converter  

チェックエンジンは構造モデル（DynamicNode）にのみ影響する。

---

## 9. 将来拡張（Future Extensions）

requirements.json は以下の拡張を想定している：

- 値の定義に合わせたチェック
- CRA（Cyber Resilience Act）要件の追加  
- SPDX 3.0 / 3.1 の新フィールド対応  
- vendor extension の自動分類  
- 正規表現によるフィールドマッチ  
- 条件付き要件（例：Package.downloadLocation が null の場合）  

---

# 🎉 まとめ

requirements.json チェック仕様は SBOMCraft2 の品質保証の中心であり：

- Missing / Unknown / OK の 3 種類の判定  
- DynamicNode の構造を利用  
- UI とは完全に独立  
- vendor extension に強い  
- SPDX バージョン差異に強い  
- NTIA / CISA / CRA などの要件を柔軟に定義可能  

という特徴を持つ。
