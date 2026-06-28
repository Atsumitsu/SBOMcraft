# 📘 **NodeFactory 設計ドキュメント（Markdown 版）**


# NodeFactory 設計概要

SBOMCraft の `NodeFactory` は、SPDX JSON を内部モデル `DynamicNode` に変換する  
「データ構造生成レイヤー」です。  
UI（TreeView / DetailsPane）とは完全に分離されており、  
**JSON → DynamicNode（データ構造）** の責務のみを持ちます。

---

## 🎯 NodeFactory の役割

NodeFactory の主な役割は以下の 4 つです。

1. **SPDX JSON を DynamicNode に変換する**
2. **NodeType を自動判定し、ノードの意味を付与する**
3. **LazyChildrenFactory による遅延ロード（Lazy Loading）を設定する**
4. **Document.RawJson を「トップレベルだけの JSON」に再構築する**

UI ロジック（TreeView や DetailsPane）は一切含みません。

---

## 🧩 NodeFactory の処理フロー

NodeFactory の処理は以下の順序で行われます。

### 1. SBOM ルートノードの作成

```csharp
var sbomNode = DynamicNode.CreateContainerNode("SBOM", "/");
sbomNode.Depth = 0;
```

### 2. Document ノードの作成

```csharp
var documentNode = DynamicNode.CreateContainerNode("Document", "/document");
documentNode.NodeType = NodeType.Document;
documentNode.Depth = 1;
```

### 3. Document の子ノードをすべて生成（Depth=2）

SPDX JSON のトップレベル項目を Document の子として追加します。

```csharp
foreach (var prop in rootElement.EnumerateObject())
{
    var child = BuildNode(prop.Name, prop.Value, "/document/" + prop.Name, 2);
    documentNode.AddChild(child);
}
```

### 4. Document.RawJson を「トップレベルだけの JSON」に再構築

```csharp
documentNode.RawJson = JsonSerializer.Serialize(topLevel, new JsonSerializerOptions
{
    WriteIndented = true
});
```

### 5. TopLevel 設定に基づき、特定ノードを SBOM 直下に昇格

```csharp
docChild.GenerateChildren();
documentNode.Children.Remove(docChild);
AdjustDepth(docChild, -1);
sbomNode.AddChild(docChild);
```

---

## 🏷️ BuildNode の役割

SPDX JSON の各要素を NodeType に応じて処理します。

```csharp
switch (element.ValueKind)
{
    case JsonValueKind.Object:
        return BuildObjectNode(...);

    case JsonValueKind.Array:
        return BuildArrayNode(...);

    default:
        return BuildValueNode(...);
}
```

---

## 🧱 BuildObjectNode の設計

Object ノードは **Container** として扱われます。

- NodeType = Object
- RawJson は Depth=2 の場合は空（巨大 JSON のため）
- LazyChildrenFactory により子ノードを遅延生成

```csharp
node.NodeType = NodeType.Object;

node.LazyChildrenFactory = () =>
{
    var list = new List<DynamicNode>();
    foreach (var prop in element.EnumerateObject())
        list.Add(BuildNode(prop.Name, prop.Value, path + "/" + prop.Name, depth + 1));
    return list;
};
```

---

## 🧱 BuildArrayNode の設計（最重要）

Array ノードは、SPDX の主要セクションに応じて NodeType を自動判定します。

### 親ノードの NodeType 自動判定

```csharp
arrayNode.NodeType = name.ToLowerInvariant() switch
{
    "packages" => NodeType.Packages,
    "files" => NodeType.Files,
    "relationships" => NodeType.Relationships,
    "hasextractedlicensinginfos" => NodeType.ExtractedLicenses,
    _ => NodeType.Array
};
```

### 子ノードの NodeType 自動付与

```csharp
childNode.NodeType = arrayNode.NodeType switch
{
    NodeType.Packages => NodeType.PackageItem,
    NodeType.Files => NodeType.FileItem,
    NodeType.Relationships => NodeType.RelationshipItem,
    NodeType.ExtractedLicenses => NodeType.ExtractedLicenseItem,
    _ => childNode.NodeType
};
```

### Lazy Loading による子ノード生成

```csharp
arrayNode.LazyChildrenFactory = () =>
{
    var list = new List<DynamicNode>();
    foreach (var item in element.EnumerateArray())
        list.Add(BuildNode(...));
    return list;
};
```

---

## 🧱 BuildValueNode の設計

プリミティブ値は Value として扱われます。

```csharp
node.NodeType = NodeType.Value;
node.RawJson = element.GetRawText();
```

---

## 🌀 Lazy Loading の設計思想

NodeFactory は **すべての子ノードを即時生成しません**。  
代わりに LazyChildrenFactory を設定し、必要になったときにだけ生成します。

### Lazy Loading のメリット

- 巨大な SPDX JSON を高速に読み込める  
- TreeView 展開時にのみ子ノードを生成  
- DetailsPane で選択されたときにも子ノードを生成  
- メモリ消費を抑えられる  

### Lazy Loading の注意点

UI 側で子ノードを使う前に必ず

```csharp
node.GenerateChildren();
```

を呼ぶ必要があります。

---

## 📦 NodeFactory と NodeCategory の関係

NodeFactory は **NodeType を付与する層**  
NodeCategory は **表示ロジックを抽象化する層**

この 2 層構造により、

- NodeFactory は JSON → データ構造の生成に集中  
- DetailsPane は NodeCategory に基づき汎用ロジックで表示  

という役割分担が成立します。

---

## 🚀 NodeFactory の設計がもたらすメリット

- SPDX の新しいフィールドにも柔軟に対応可能  
- TreeView と DetailsPane のロジックが簡素化  
- NodeCategory による抽象化でハードコーディングが激減  
- SBOMCraft の拡張性が大幅に向上  
- Lazy Loading により巨大 SBOM でも高速に動作  

---

## 📌 まとめ

NodeFactory は SBOMCraft の「データ構造生成レイヤー」であり、  
SPDX JSON を DynamicNode に変換する中心的なコンポーネントです。

- NodeType の自動判定  
- Lazy Loading  
- Document.RawJson の再構築  
- TopLevel ノードの昇格  

などの機能により、  
SBOMCraft の UI は柔軟かつ高速に動作します。

NodeCategory と組み合わせることで、  
SBOMCraft はより拡張しやすく、保守しやすい構造になります。
