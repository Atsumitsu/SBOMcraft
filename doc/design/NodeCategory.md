# 📘 **NodeCategory 設計ドキュメント**

## NodeCategory 設計概要

SBOMCraft では、SPDX JSON をツリー構造として扱うために `DynamicNode` クラスを使用しています。  
従来は `NodeType` を細かく分類していましたが、種類が増えるほど表示ロジックが複雑化し、  
メンテナンス性が低下する問題がありました。

そこで、`NodeType` を用途別に抽象化した **NodeCategory** を導入し、  
表示ロジックを大幅に簡素化・汎用化しています。

---

## 🎯 NodeCategory の目的

- NodeType の細分化によるハードコーディングを減らす  
- files / relationships / extractedLicenses などの新しい種類にも自動対応する  
- DetailsPane（右ペイン）の表示ロジックを汎用化する  
- TreeView と DetailsPane の挙動を統一し、拡張しやすい構造にする  

---

## 🏷️ NodeCategory の分類

NodeCategory は「表示方法」に基づいて分類されます。

| Category | 説明 | 対応する NodeType |
|---------|------|--------------------|
| **Document** | SPDX ドキュメント本体 | Document |
| **Container** | 子ノードを持つ構造体（Object / Array / Packages / Files など） | Object, Array, Packages, Files, Relationships, ExtractedLicenses |
| **Item** | Container の子要素（PackageItem / FileItem など） | PackageItem, FileItem, RelationshipItem, ExtractedLicenseItem |
| **Value** | プリミティブ値（文字列・数値など） | Value |
| **Unknown** | 未分類 | Unknown |

---

## 🧩 NodeCategory 実装コード

```csharp
public enum NodeCategory
{
    Document,
    Container,
    Item,
    Value,
    Unknown
}

public NodeCategory Category
{
    get
    {
        return NodeType switch
        {
            NodeType.Document => NodeCategory.Document,
            NodeType.Value => NodeCategory.Value,

            NodeType.PackageItem or
            NodeType.FileItem or
            NodeType.RelationshipItem or
            NodeType.ExtractedLicenseItem
                => NodeCategory.Item,

            NodeType.Packages or
            NodeType.Files or
            NodeType.Relationships or
            NodeType.ExtractedLicenses or
            NodeType.Object or
            NodeType.Array
                => NodeCategory.Container,

            _ => NodeCategory.Unknown
        };
    }
}
```

---

## 🏗️ NodeType の自動付与（BuildArrayNode）

SPDX の主要セクションに応じて NodeType を自動判定します。

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

子ノードの NodeType も自動付与します。

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

---

## 🖥️ DetailsPane の表示ロジック（NodeCategory ベース）

NodeCategory によって表示方法を統一します。

```csharp
switch (node.Category)
{
    case NodeCategory.Document:
        BuildDocumentDetails(node);
        break;

    case NodeCategory.Container:
    case NodeCategory.Item:
        node.GenerateChildren();
        AddRow("Name", node.Name);
        AddRow("Path", node.Path);
        foreach (var child in node.Children)
            AddChildRow(child);
        break;

    case NodeCategory.Value:
        AddRow("Name", node.Name);
        AddRow("Value", node.Value ?? "(null)");
        AddRow("Path", node.Path);
        break;

    default:
        AddRow("Name", node.Name);
        AddRow("Path", node.Path);
        break;
}
```

---

## 📦 AddChildRow の汎用化

```csharp
switch (child.Category)
{
    case NodeCategory.Value:
        AddRow(child.Name, child.Value ?? "(null)");
        break;

    case NodeCategory.Container:
    case NodeCategory.Item:
        child.GenerateChildren();
        AddRow(child.Name, $"({child.NodeType})");
        foreach (var sub in child.Children)
            AddRow("  " + sub.Name, sub.Value ?? "(object)");
        break;

    default:
        AddRow(child.Name, "(unknown)");
        break;
}
```

---

## 🚀 NodeCategory 導入の効果

- files / relationships / extractedLicenses が自動的に対応  
- PackageItem / FileItem / RelationshipItem の表示が統一される  
- ハードコーディングが激減  
- SBOMCraft の構造がより拡張しやすくなる  
- SPDX の新しいフィールドにも柔軟に対応可能  

---

## 📌 まとめ

NodeCategory は SBOMCraft の表示ロジックを大幅に簡素化し、  
SPDX の複雑な構造を自然に扱えるようにするための抽象化レイヤーです。

- NodeType → 具体的な種類  
- NodeCategory → 表示方法の分類  

という役割分担により、  
SBOMCraft の UI はより強力で、より保守しやすくなります。
