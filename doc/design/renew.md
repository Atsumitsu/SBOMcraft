# 🟦 **SBOMCraft2 LazyLoad TreeView ― 完全設計図（ゼロから作り直す版）**

---

## 🟥 1. 設計のゴール

- 巨大 JSON（packages が数千件）でも高速に動く  
- TreeView は最初は空の Children を持つ  
- 展開された瞬間に子ノードを生成する（LazyLoad）  
- XAML はシンプル  
- Converter や MultiBinding を使わない  
- デバッグが簡単  
- 前回の SBOMCraft の構造に近い  
- しかし巨大 JSON に強い

---

# 🟦 **2. 全体構造（最重要）**

```
DynamicNode
 ├─ DisplayName
 ├─ Value
 ├─ Children (List<DynamicNode>)
 ├─ LazyChildrenFactory (Func<List<DynamicNode>>)
 └─ GenerateChildren()  ← LazyLoad の本体

NodeFactory
 └─ JSON を解析して DynamicNode を作る
     └─ 子ノードは LazyChildrenFactory に入れる

TreeViewPane.xaml
 └─ ItemsSource = Root.Children
     └─ HierarchicalDataTemplate.ItemsSource = Children

TreeViewPane.xaml.cs
 └─ TreeViewItem_Expanded で LazyLoad を発火
```

これだけです。  
MultiBinding も Converter も不要です。

---

# 🟦 **3. DynamicNode（最小で美しい形）**

```csharp
public class DynamicNode
{
    public string DisplayName { get; set; }
    public string Value { get; set; }
    public string Path { get; set; }
    public int Depth { get; set; }
    public NodeType NodeType { get; set; }

    public List<DynamicNode> Children { get; set; } = new List<DynamicNode>();

    public Func<List<DynamicNode>> LazyChildrenFactory { get; set; }

    public void GenerateChildren()
    {
        if (LazyChildrenFactory != null && Children.Count == 0)
        {
            Children = LazyChildrenFactory();
        }
    }
}
```

### ✔ Children は必ず空の List  
### ✔ LazyChildrenFactory があれば GenerateChildren() で埋まる  
### ✔ これだけで LazyLoad が成立する

---

# 🟦 **4. NodeFactory（LazyLoad 対応版）**

```csharp
public static DynamicNode BuildRoot(JsonElement rootElement)
{
    var root = new DynamicNode
    {
        DisplayName = "Root",
        Path = "/",
        NodeType = NodeType.Object,
        Depth = 0,
        Children = new List<DynamicNode>()
    };

    root.LazyChildrenFactory = () =>
    {
        var list = new List<DynamicNode>();

        foreach (var prop in rootElement.EnumerateObject())
        {
            list.Add(BuildNode(prop.Name, prop.Value, "/" + prop.Name, 1));
        }

        return list;
    };

    return root;
}
```

### ✔ Root.Children は空  
### ✔ LazyChildrenFactory が子を生成する  
### ✔ 展開時に GenerateChildren() が呼ばれる

---

# 🟦 **5. TreeViewPane.xaml（シンプルで美しい）**

```xml
<TreeView ItemsSource="{Binding Root.Children}"
          ItemTemplateSelector="{StaticResource NodeSelector}"
          SelectedItemChanged="TreeView_SelectedItemChanged"
          TreeViewItem.Expanded="TreeViewItem_Expanded" />
```

### ✔ ItemsSource は Root.Children  
### ✔ HierarchicalDataTemplate の ItemsSource は Children  
### ✔ MultiBinding なし  
### ✔ Converter なし  
### ✔ ダミーノード不要

---

# 🟦 **6. TreeViewPane.xaml.cs（LazyLoad の発火）**

```csharp
private void TreeViewItem_Expanded(object sender, RoutedEventArgs e)
{
    if (e.OriginalSource is TreeViewItem item &&
        item.DataContext is DynamicNode node)
    {
        node.GenerateChildren();
    }
}
```

### ✔ 展開された瞬間に LazyLoad が発火  
### ✔ 子ノードが生成される  
### ✔ TreeView が更新される  
### ✔ これだけで LazyLoad が完成する

---

# 🟦 **7. ViewModel（最小構成）**

```csharp
public class SbomViewModel
{
    public DynamicNode Root { get; private set; }

    public void LoadSbom(string json)
    {
        var doc = JsonDocument.Parse(json);
        Root = NodeFactory.BuildRoot(doc.RootElement);
    }
}
```

---

# 🟦 **8. DataContext の設定（MainWindow）**

```csharp
TreeViewPaneControl.DataContext = vm;
```

---

# 🟦 **9. 完成した LazyLoad の動作フロー**

1. LoadSbom() が Root を作る  
2. Root.Children は空  
3. TreeView は Root.Children を描画しようとする  
4. Root が展開される  
5. TreeViewItem_Expanded が発火  
6. node.GenerateChildren() が呼ばれる  
7. LazyChildrenFactory が子ノードを生成  
8. TreeView が更新される  
9. 子ノードが表示される  
10. 子ノードを展開すると同じ流れで LazyLoad が発火する

---

# 🌟 **これが「ゼロからきれいに作る LazyLoad TreeView」の完全設計図です。**

- シンプル  
- 高速  
- 拡張しやすい  
- デバッグしやすい  
- 前回の SBOMCraft の構造に近い  
- 巨大 JSON に強い  
- 今までの問題がすべて消える
