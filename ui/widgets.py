# ui/widgets.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""テーマ対応の小さな共通部品（統計カード・ツリーの指摘バッジ）。"""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout,
)

from ui import theme

# ツリー項目に付ける「検証の指摘」。値は (level, 表示テキスト)。level は "error" / "warning"
ISSUE_ROLE = Qt.ItemDataRole.UserRole + 10

# parser.py がノード名の先頭に付けている絵文字（📦 📁 ℹ️ など）
_LEADING_EMOJI = re.compile("^[\U0001F000-\U0001FFFF\u2139\u2600-\u27BF\uFE0F\u200D\\s]+")


def strip_leading_emoji(name: str) -> str:
    return _LEADING_EMOJI.sub("", name or "")


class StatCard(QFrame):
    """数字を大きく見せる統計カード。左端の色バーは tone（success / warning / danger / info / neutral）で決まる。"""

    clicked = Signal()

    def __init__(self, caption: str, tone: str = "neutral", parent=None):
        super().__init__(parent)
        self.setProperty("card", True)
        self.setProperty("tone", tone)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)

        self._caption = QLabel(caption)
        self._caption.setProperty("role", "card-caption")
        self._value = QLabel("0")
        self._value.setProperty("role", "stat-value")
        self._sub = QLabel(" ")
        self._sub.setProperty("role", "muted")
        for w in (self._caption, self._value, self._sub):
            lay.addWidget(w)

    def set_value(self, value, sub: str = "") -> None:
        self._value.setText(str(value))
        self._sub.setText(sub or " ")           # 高さを揃えるため空文字にしない

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class TreeIssueDelegate(QStyledItemDelegate):
    """ISSUE_ROLE が設定された行に、左端の色バーと、名前の右に指摘バッジを描く（行全体は塗らない）。"""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() != 0:
            return
        issue = index.data(ISSUE_ROLE)
        if not issue:
            return
        level, text = issue[0], issue[1]
        tone = "danger" if level == "error" else "warning"
        strong, bg, fg = theme.tone_colors(tone)

        widget = option.widget
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = widget.style() if widget else QApplication.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 左端の色バー（ビューポートの左端に揃える）
        left = widget.viewport().rect().left() if widget else option.rect.left()
        painter.fillRect(QRect(left, option.rect.top() + 2, 3, option.rect.height() - 4), QColor(strong))

        # バッジ（入りきらなければ省略、狭すぎれば描かない）
        x = text_rect.left() + fm.horizontalAdvance(opt.text) + 12
        max_w = option.rect.right() - x - 6
        if max_w > 48:
            label = fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w - 14)
            h = fm.height() + 2
            r = QRectF(x, option.rect.center().y() - h / 2 + 0.5, fm.horizontalAdvance(label) + 14, h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(r, h / 2, h / 2)
            painter.setPen(QColor(fg))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()
