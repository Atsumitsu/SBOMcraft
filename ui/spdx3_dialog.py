from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLineEdit, QComboBox, QTextEdit, QDialogButtonBox, QLabel
)
from PySide6.QtGui import QColor

# ui/spdx3_dialog.py の該当部分の変更・追加
class Spdx3ExportDialog(QDialog):
    def __init__(self, existing_meta: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export to SPDX 3.0.1 (CISA 2026 Metadata)")
        self.resize(500, 480)

        self.existing_meta = existing_meta if existing_meta else {}
        self._parse_existing_meta()
        self.pink_style = "background-color: #ffcccc; color: #000000;"
        self.init_ui()

    def _parse_existing_meta(self):
        # 既存メタデータの解析部分
        creators = self.existing_meta.get("creators", [])
        if isinstance(creators, list) and creators:
            creator_str = creators[0]
        else:
            creator_str = self.existing_meta.get("creator", "")

        self.parsed_creator_type = "Organization"
        self.parsed_creator_name = creator_str
        if creator_str.startswith("Organization:"):
            self.parsed_creator_type = "Organization"
            self.parsed_creator_name = creator_str.replace("Organization:", "").strip()
        elif creator_str.startswith("Person:"):
            self.parsed_creator_type = "Person"
            self.parsed_creator_name = creator_str.replace("Person:", "").strip()
        elif creator_str.startswith("Tool:"):
            self.parsed_creator_type = "Tool"
            self.parsed_creator_name = creator_str.replace("Tool:", "").strip()

        self.parsed_tool_name = self.existing_meta.get("tool_name", "")
        if not self.parsed_tool_name:
            for c in (creators if isinstance(creators, list) else [creator_str]):
                if isinstance(c, str) and c.startswith("Tool:"):
                    self.parsed_tool_name = c
                    break
        if not self.parsed_tool_name:
            self.parsed_tool_name = "Tool: SBOMcraft-v0.6.2.0"

        self.parsed_doc_name = self.existing_meta.get("document_name", "SBOM-Document")
        self.parsed_created_date = self.existing_meta.get("created", "")
        self.parsed_comment = self.existing_meta.get("comment", "")
        
        # sbom_type の初期値取得（旧 generation_context からの移行も考慮）
        self.parsed_sbom_type = self.existing_meta.get("sbom_type", "")
        if not self.parsed_sbom_type:
            old_ctx = self.existing_meta.get("generation_context", "analyzed")
            self.parsed_sbom_type = "analyzed" if old_ctx == "after build" else old_ctx
            
        self.parsed_license = self.existing_meta.get("data_license", "CC0-1.0")

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        desc_label = QLabel(
            "CISA 2026 最小要件に準拠した SPDX 3.0.1 メタデータを入力してください。\n"
            "背景がピンク色の項目は、元のSBOMにデータが不足している箇所です。"
        )
        main_layout.addWidget(desc_label)

        form_layout = QFormLayout()

        # 1. ドキュメント名
        self.doc_name_input = QLineEdit()
        self.doc_name_input.setText(self.parsed_doc_name)
        if not self.parsed_doc_name:
            self.doc_name_input.setStyleSheet(self.pink_style)
        form_layout.addRow("Document Name *:", self.doc_name_input)

        # 2. 作成者名
        self.creator_input = QLineEdit()
        self.creator_input.setText(self.parsed_creator_name)
        if not self.parsed_creator_name:
            self.creator_input.setStyleSheet(self.pink_style)
        form_layout.addRow("Creator Name *:", self.creator_input)

        # 3. 作成者タイプ
        self.creator_type_combo = QComboBox()
        self.creator_type_combo.addItems(["Organization", "Person", "Tool"])
        if self.parsed_creator_type in ["Organization", "Person", "Tool"]:
            self.creator_type_combo.setCurrentText(self.parsed_creator_type)
        form_layout.addRow("Creator Type:", self.creator_type_combo)

        # 4. 生成ツール名
        self.tool_name_input = QLineEdit()
        self.tool_name_input.setText(self.parsed_tool_name)
        if not self.parsed_tool_name:
            self.tool_name_input.setStyleSheet(self.pink_style)
        form_layout.addRow("Tool Name *:", self.tool_name_input)

        # 5. 作成日時
        self.created_input = QLineEdit()
        self.created_input.setText(self.parsed_created_date)
        if not self.parsed_created_date:
            self.created_input.setStyleSheet(self.pink_style)
        form_layout.addRow("Created Date *:", self.created_input)

        # 6. SBOM Type (sbomType - SPDX 3.0.1 公式語彙) 【変更箇所】
        self.sbom_type_combo = QComboBox()
        self.sbom_type_combo.addItems([
            "analyzed", 
            "build", 
            "deployed", 
            "design", 
            "runtime", 
            "source"
        ])
        if self.parsed_sbom_type in ["analyzed", "build", "deployed", "design", "runtime", "source"]:
            self.sbom_type_combo.setCurrentText(self.parsed_sbom_type)
        else:
            self.sbom_type_combo.setCurrentText("analyzed")
        form_layout.addRow("SBOM Type (sbomType) *:", self.sbom_type_combo)

        # 7. データライセンス
        self.license_combo = QComboBox()
        self.license_combo.addItems(["CC0-1.0", "Apache-2.0", "MIT", "NOASSERTION"])
        self.license_combo.setCurrentText(self.parsed_license)
        form_layout.addRow("Data License:", self.license_combo)

        # 8. コメント
        self.comment_input = QTextEdit()
        self.comment_input.setPlainText(self.parsed_comment)
        self.comment_input.setMaximumHeight(70)
        form_layout.addRow("Comment / Note:", self.comment_input)

        main_layout.addLayout(form_layout)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def get_input_data(self) -> dict:
        creator_name = self.creator_input.text().strip()
        creator_type = self.creator_type_combo.currentText()
        formatted_creator = f"{creator_type}: {creator_name}" if creator_name else ""

        return {
            "document_name": self.doc_name_input.text().strip(),
            "creator": formatted_creator,
            "creator_name": creator_name,
            "creator_type": creator_type,
            "tool_name": self.tool_name_input.text().strip(),
            "created": self.created_input.text().strip(),
            "sbom_type": self.sbom_type_combo.currentText(),  # sbomTypeを返す
            "data_license": self.license_combo.currentText(),
            "comment": self.comment_input.toPlainText().strip()
        }
    