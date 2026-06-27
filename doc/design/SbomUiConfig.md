# 📘 SbomUiConfig.md（SBOMCraft2 UI 設定ファイル仕様）

## 1. 概要（Overview）

**SbomUiConfig は SBOMCraft2 の UI 挙動を外部設定ファイルで制御するための仕組みである。**

- TreeView の表示制御  
- 右ペインの表示モード  
- ノードの表示／非表示  
- UI のハードコーディング排除  
- SPDX 2.3 / 3.0 / 3.1 などのバージョン差異に強い  

SbomUiConfig は **UI 層の責務**であり、  
DynamicModel / DynamicNode / NodeFactory とは完全に独立している。

---

## 2. 目的（Purpose）

SbomUiConfig の目的は以下の 4 点に集約される。

### 2.1 TreeView の表示制御を外部化する  
- Document の Children を表示するか  
- Packages / Files / Relationships を表示するか  
- 特定ノードを非表示にするか  

これらをコードではなく設定ファイルで制御する。

---

### 2.2 右ペインの表示モードを制御する  
右ペインは以下の 3 モードを持つ：

- **standard**：Key/Value の 2 カラム表示  
- **raw**：JSON の Raw 表示  
- **hidden**：右ペインを非表示  

これをノードタイプごとに設定できる。

---

### 2.3 UI のハードコーディングを排除する  
UI の挙動をコードに埋め込むのではなく、  
設定ファイルで柔軟に制御することで：

- SPDX バージョン差異に強くなる  
- vendor extension に対応しやすくなる  
- UI の変更が容易になる  

---

### 2.4 NodeFactory / DynamicNode と責務を分離する  
SbomUiConfig は UI のための設定であり、  
DynamicNode の構造や NodeFactory の生成ロジックには影響しない。

---

## 3. 設定ファイルの構造（Config Structure）

SbomUiConfig は JSON 形式で記述される。

### ✔ topLevel  
TreeView のトップレベルノードの表示制御。

### ✔ rightPane  
右ペインの表示モード制御。

### ✔ version  
設定ファイルのバージョン。

---

## 4. 設定ファイルの例（Example）

```json
{
  "version": 1,

  "topLevel": {
    "document": {
      "showInTree": true,
      "showChildrenInTree": false,
      "rightPaneMode": "standard"
    },
    "packages": {
      "showInTree": true,
      "showChildrenInTree": true,
      "rightPaneMode": "standard"
    },
    "files": {
      "showInTree": true,
      "showChildrenInTree": true,
      "rightPaneMode": "standard"
    },
    "relationships": {
      "showInTree": true,
      "showChildrenInTree": true,
      "rightPaneMode": "raw"
    }
  }
}
```

---

## 5. 各項目の説明（Field Description）

### 5.1 showInTree  
```
true  → TreeView に表示する  
false → TreeView に表示しない  
```

### 5.2 showChildrenInTree  
```
true  → 子ノードを展開する  
false → 子ノードを非表示にする  
```

Document の Children を非表示にする場合などに利用。

### 5.3 rightPaneMode  
```
standard → Key/Value の 2 カラム表示  
raw      → JSON の Raw 表示  
hidden   → 右ペインを非表示  
```

---

## 6. ConfigLoader（読み込み処理）

SbomUiConfig は起動時に読み込まれる。

```csharp
public static SbomUiConfig Load()
{
    var json = File.ReadAllText("sbomcraft.config.json");
    return JsonSerializer.Deserialize<SbomUiConfig>(json);
}
```

MainWindow では以下のように注入される：

```csharp
_uiConfig = ConfigLoader.Load();
_vm = new MainViewModel(_uiConfig);
DataContext = _vm;
```

---

## 7. TreeView との連携（Integration with TreeView）

TreeView の表示制御は **ChildrenFilterConverter** が担当する。

```xml
<HierarchicalDataTemplate
    ItemsSource="{Binding Path=., Converter={StaticResource ChildrenFilterConverter}}">
```

Converter 内では：

```csharp
if (!cfg.ShowChildrenInTree)
    return Array.Empty<DynamicNode>();
```

DynamicNode の構造は変えず、  
UI 側で表示制御を行う。

---

## 8. 右ペインとの連携（Integration with Right Pane）

右ペインの表示は ViewModel が制御する。

```csharp
switch (config.RightPaneMode)
{
    case "standard":
        ShowStandard(node);
        break;
    case "raw":
        ShowRaw(node.RawJson);
        break;
    case "hidden":
        HidePane();
        break;
}
```

DynamicNode の構造は変えない。

---

## 9. 責務分離（Responsibility Separation）

| レイヤー | 役割 |
|---------|------|
| **DynamicModel** | JSON の構造を抽象化 |
| **NodeFactory** | DynamicNode を構築 |
| **DynamicNode** | SBOM の構造モデル |
| **SbomUiConfig** | UI の表示制御 |
| **Converter** | TreeView の表示制御 |
| **ViewModel** | 右ペインの表示制御 |

SbomUiConfig は UI のみを制御し、  
構造モデルには影響しない。

---

## 10. 将来拡張（Future Extensions）

SbomUiConfig は以下の拡張を想定している。

- SPDX 3.0 / 3.1 の新しいノードタイプ追加  
- vendor extension の UI 表示制御  
- ノードごとのアイコン設定  
- ノードごとの色設定  
- 右ペインのカスタムテンプレート  
- TreeView の並び順制御  

---

# 🎉 まとめ

SbomUiConfig は SBOMCraft2 の UI を柔軟に制御するための設定ファイルであり：

- TreeView の表示制御  
- 右ペインの表示モード  
- UI のハードコーディング排除  
- DynamicNode / NodeFactory との責務分離  
- SPDX バージョン差異への強さ  

を実現する
