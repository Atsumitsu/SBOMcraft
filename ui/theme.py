# ui/theme.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 XZ Manj
"""
SBOMcraft のテーマ（色・フォント・QSS）。ライト / ダーク / OS 追従に対応。

使い方（main.py）:
    app = QApplication(sys.argv)
    theme.apply_fonts(app)
    theme.apply_theme(app, "auto")      # "auto" | "light" | "dark"

コード側で色が必要なとき:
    t = theme.tokens()                  # 現在のテーマのトークン
    strong, bg, fg = theme.tone_colors("danger")

QSS から使える動的プロパティ（setProperty で付ける）:
    QPushButton   variant = "primary" | "ghost" | "danger"
    QLabel        role    = "muted" | "title" | "section" | "stat-value"
    QLabel        banner  = True, tone = "success" | "warning" | "danger" | "info"
    QLabel        chip    = True, tone = 同上
    QFrame        card    = True, tone = 同上（左端に色バー）
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass
from string import Template
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# デザイントークン
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tokens:
    name: str
    # 面・線・文字
    bg: str
    surface: str
    surface_alt: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_disabled: str
    # アクセント（主ボタン・選択・フォーカスだけに使う）
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    accent_soft: str
    hover: str
    code_bg: str
    # 状態色: 強い色 / 薄い背景 / 薄い背景の上の文字
    success: str
    success_bg: str
    success_fg: str
    warning: str
    warning_bg: str
    warning_fg: str
    danger: str
    danger_bg: str
    danger_fg: str
    info: str
    info_bg: str
    info_fg: str


LIGHT = Tokens(
    name="light",
    bg="#F6F7F9", surface="#FFFFFF", surface_alt="#F1F3F6",
    border="#E3E6EB", border_strong="#C9CED6",
    text="#1F2937", text_muted="#4B5563", text_disabled="#9CA3AF",
    accent="#2563EB", accent_hover="#1D4ED8", accent_pressed="#1E40AF", accent_text="#FFFFFF",
    accent_soft="#DBEAFE", hover="#EEF1F5", code_bg="#F6F8FA",
    success="#16A34A", success_bg="#E7F6EC", success_fg="#166534",
    warning="#D97706", warning_bg="#FEF3C7", warning_fg="#92400E",
    danger="#DC2626", danger_bg="#FDECEC", danger_fg="#991B1B",
    info="#0284C7", info_bg="#E0F2FE", info_fg="#075985",
)

DARK = Tokens(
    name="dark",
    bg="#0F1115", surface="#171A21", surface_alt="#1D212A",
    border="#2A2F3A", border_strong="#3A4150",
    text="#E6E8EB", text_muted="#9AA3B2", text_disabled="#5F6775",
    accent="#5B8DEF", accent_hover="#7AA2F3", accent_pressed="#4A7AD9", accent_text="#0B1020",
    accent_soft="#1E3358", hover="#222732", code_bg="#12151B",
    success="#4ADE80", success_bg="#12301F", success_fg="#86EFAC",
    warning="#FBBF24", warning_bg="#3A2C0B", warning_fg="#FCD34D",
    danger="#F87171", danger_bg="#3B1818", danger_fg="#FCA5A5",
    info="#38BDF8", info_bg="#0C2D44", info_fg="#7DD3FC",
)

# 比較結果の状態 → 色の系統（キーは DiffStatus.value。Enum そのものをキーにしないこと）
STATUS_TONES: Dict[str, str] = {
    "added": "success",
    "removed": "danger",
    "version_changed": "warning",
    "modified": "info",
    "unchanged": "neutral",
}

_TONES = ("success", "warning", "danger", "info")

_current: Tokens = LIGHT
_mode: str = "auto"
_applying = False
_signal_connected = False
_icon_cache: Dict[Tuple[str, str, int], QIcon] = {}


def tokens() -> Tokens:
    return _current


def mode() -> str:
    """"auto" / "light" / "dark"（ユーザーの選択。実際の配色は tokens().name）"""
    return _mode


def tone_colors(tone: str, t: Optional[Tokens] = None) -> Tuple[str, str, str]:
    """tone → (強い色, 薄い背景, 背景上の文字色)。"neutral" は無彩色。"""
    t = t or _current
    if tone in _TONES:
        return getattr(t, tone), getattr(t, f"{tone}_bg"), getattr(t, f"{tone}_fg")
    return t.border_strong, t.surface_alt, t.text_muted


def mix(a: str, b: str, ratio: float) -> str:
    """色 a に色 b を ratio（0〜1）だけ混ぜる。"""
    ca, cb = QColor(a), QColor(b)

    def f(x: int, y: int) -> int:
        return round(x * (1 - ratio) + y * ratio)

    return QColor(f(ca.red(), cb.red()), f(ca.green(), cb.green()), f(ca.blue(), cb.blue())).name()


def report_colors(t: Optional[Tokens] = None) -> Dict[str, str]:
    """core/compare_report.py（Qt 非依存の HTML 生成）に渡す配色。"""
    t = t or _current
    d = {
        "text": t.text, "muted": t.text_muted, "border": t.border_strong,
        "danger": t.danger_fg, "note": t.warning_fg,
        "old_bg": t.danger_bg, "new_bg": t.success_bg,
    }
    for status, tone in STATUS_TONES.items():
        _, bg, fg = tone_colors(tone, t)
        d[f"{status}_bg"], d[f"{status}_fg"] = bg, fg
    return d


# ---------------------------------------------------------------------------
# QSS
# ---------------------------------------------------------------------------

_QSS = Template(r"""
/* ---- ツールバー（メニューボタン） ---- */
QToolBar#MenuToolbar { background: $surface; border: none; border-bottom: 1px solid $border; spacing: 4px; padding: 4px 8px; }
QToolBar#MenuToolbar QToolButton { background: transparent; border: none; border-radius: 6px; padding: 4px 10px; }
QToolBar#MenuToolbar QToolButton:hover { background: $hover; }
QToolBar#MenuToolbar QToolButton:pressed, QToolBar#MenuToolbar QToolButton:open { background: $accent_soft; }
QToolButton::menu-indicator { image: none; width: 0px; }

/* ---- メニュー ---- */
QMenu { background: $surface; border: 1px solid $border_strong; padding: 6px; }
QMenu::item { padding: 6px 28px 6px 12px; border-radius: 4px; }
QMenu::item:selected { background: $accent_soft; color: $text; }
QMenu::item:disabled { color: $text_disabled; background: transparent; }
QMenu::separator { height: 1px; background: $border; margin: 5px 8px; }
QMenu::icon { padding-left: 6px; }

QToolTip { background: $surface; color: $text; border: 1px solid $border_strong; padding: 4px 6px; }

/* ---- ボタン ---- */
QPushButton { background: $surface; color: $text; border: 1px solid $border_strong; border-radius: 6px; padding: 5px 14px; min-height: 20px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $surface_alt; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { color: $text_disabled; background: $surface_alt; border-color: $border; }

QPushButton[variant="primary"] { background: $accent; color: $accent_text; border: 1px solid $accent; font-weight: bold; }
QPushButton[variant="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[variant="primary"]:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton[variant="primary"]:disabled { background: $accent_soft; color: $text_disabled; border-color: $accent_soft; }

QPushButton[variant="ghost"] { background: transparent; border: 1px solid transparent; color: $text_muted; }
QPushButton[variant="ghost"]:hover { background: $hover; color: $text; }
QPushButton[variant="ghost"]:disabled { background: transparent; color: $text_disabled; }

QPushButton[variant="danger"] { background: $danger_bg; color: $danger_fg; border: 1px solid $danger; }
QPushButton[variant="danger"]:hover { background: $danger; color: $surface; }

/* ---- 入力 ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: $surface; border: 1px solid $border_strong; border-radius: 6px; padding: 4px 8px; min-height: 20px; selection-background-color: $accent; selection-color: $accent_text; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; background: transparent; }
QComboBox::down-arrow { image: url($arrow_url); width: 12px; height: 12px; }
QLineEdit:disabled, QComboBox:disabled { background: $surface_alt; color: $text_disabled; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border_strong; selection-background-color: $accent_soft; selection-color: $text; outline: 0; }

QTextEdit, QPlainTextEdit, QTextBrowser { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 6px; selection-background-color: $accent; selection-color: $accent_text; }
QTextEdit:focus, QPlainTextEdit:focus { border-color: $accent; }

/* ---- ツリー・表 ---- */
QTreeView, QListView, QTableView, QTableWidget { background: $surface; alternate-background-color: $surface_alt; border: 1px solid $border; border-radius: 8px; outline: 0; gridline-color: transparent; selection-background-color: $accent_soft; selection-color: $text; }
QTreeView::item, QListView::item { padding: 3px 4px; border: none; }
QTableView::item { padding: 4px 8px; border: none; border-bottom: 1px solid $border; }
QTreeView::item:hover, QListView::item:hover, QTableView::item:hover { background: $hover; }
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected { background: $accent_soft; color: $text; }
QTreeView::item:selected:!active, QTableView::item:selected:!active { background: $accent_soft; color: $text; }

QHeaderView { background: $surface_alt; border: none; }
QHeaderView::section { background: $surface_alt; color: $text; border: none; border-bottom: 1px solid $border; padding: 6px 10px; font-weight: bold; }
QHeaderView::section:vertical { border-bottom: none; border-right: 1px solid $border; padding: 4px 8px; }
QTableCornerButton::section { background: $surface_alt; border: none; }

/* ---- タブ（下線式） ---- */
QTabWidget::pane { border: 1px solid $border; border-radius: 8px; background: $surface; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: $text; padding: 7px 14px; margin-right: 2px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { background: $hover; border-radius: 4px; }
QTabBar::tab:selected { color: $accent; border-bottom: 2px solid $accent; font-weight: bold; background: transparent; }

/* ---- スクロールバー ---- */
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $border_strong; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 4px; min-width: 28px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: $text_disabled; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ---- その他 ---- */
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 8px; }
QSplitter::handle:vertical { height: 8px; }
QSplitter::handle:hover { background: $accent_soft; }

QProgressBar { background: $surface_alt; border: none; border-radius: 4px; text-align: center; color: $text; min-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }

QGroupBox { background: $surface; border: 1px solid $border; border-radius: 8px; margin-top: 14px; padding: 12px 10px 8px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: $text_muted; font-weight: bold; }

QStatusBar { background: $surface; border-top: 1px solid $border; color: $text_muted; }
QStatusBar::item { border: none; }

/* ---- ラベルの役割 ---- */
QLabel[role="muted"] { color: $text_muted; }
QLabel[role="section"] { font-weight: bold; }
QLabel[role="title"] { font-size: 14pt; font-weight: bold; }
QLabel[role="card-caption"] { color: $text; font-weight: bold; }
QLabel[role="stat-value"] { font-size: 20pt; font-weight: bold; }

/* ---- カード ---- */
QFrame[card="true"] { background: $surface; border: 1px solid $border; border-radius: 8px; }
QFrame[card="true"]:hover { border-color: $border_strong; }
QFrame[card="true"][tone="neutral"] { border-left: 3px solid $border_strong; }
""")


def _arrow_url(t: Tokens) -> str:
    """コンボボックスの ▼ 用の画像（QSS は色を変えられないので、テーマ色で描いた PNG を一時フォルダに作る）。"""
    folder = os.path.join(tempfile.gettempdir(), "sbomcraft_theme")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"chevron_{t.text.lstrip('#')}.png")
    if not os.path.isfile(path):
        pm = QPixmap(24, 24)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(t.text), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)]))
        painter.end()
        pm.save(path, "PNG")
    return path.replace("\\", "/")


def build_qss(t: Optional[Tokens] = None) -> str:
    t = t or _current
    qss = _QSS.substitute(asdict(t), arrow_url=_arrow_url(t))
    extra = []
    for tone in _TONES:
        strong, bg, fg = tone_colors(tone, t)
        extra.append(f'QFrame[card="true"][tone="{tone}"] {{ border-left: 3px solid {strong}; }}')
        extra.append(
            f'QLabel[banner="true"][tone="{tone}"] {{ background: {bg}; color: {fg}; '
            f'border: 1px solid {strong}; border-radius: 6px; padding: 6px 10px; }}')
        extra.append(
            f'QLabel[chip="true"][tone="{tone}"] {{ background: {bg}; color: {fg}; '
            f'border-radius: 9px; padding: 1px 8px; font-weight: bold; }}')
    return qss + "\n".join(extra)


# ---------------------------------------------------------------------------
# パレット・フォント・アイコン
# ---------------------------------------------------------------------------

def build_palette(t: Optional[Tokens] = None) -> QPalette:
    t = t or _current
    p = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    roles = {
        R.Window: t.bg, R.WindowText: t.text,
        R.Base: t.surface, R.AlternateBase: t.surface_alt,
        R.ToolTipBase: t.surface, R.ToolTipText: t.text,
        R.Text: t.text, R.PlaceholderText: t.text_muted,
        R.Button: t.surface, R.ButtonText: t.text,
        R.BrightText: "#FFFFFF",
        R.Highlight: t.accent, R.HighlightedText: t.accent_text,
        R.Link: t.accent, R.LinkVisited: t.accent_pressed,
        R.Light: t.surface, R.Midlight: t.surface_alt,
        R.Mid: t.border, R.Dark: t.border_strong, R.Shadow: "#000000",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, role, QColor(t.text_disabled))
    return p


def _available(families):
    have = set(QFontDatabase.families())
    return [f for f in families if f in have]

_FONT_CHAINS = {
    "ja": ["Yu Gothic UI", "BIZ UDPGothic", "Meiryo UI", "Segoe UI"],
    "en": ["Segoe UI", "Yu Gothic UI", "BIZ UDPGothic", "Meiryo UI"],   # 日本語のパッケージ名が出ても崩れないよう後ろに残す
}

def apply_fonts(app, point_size: float = 10.0, lang: str = "ja") -> None:
    """UI フォント。Windows なら Yu Gothic UI → BIZ UDPGothic → Meiryo UI → Segoe UI の順に使う。"""
    font = app.font()
    fams = _available(["Yu Gothic UI", "BIZ UDPGothic", "Meiryo UI", "Segoe UI"])
    if fams:
        font.setFamilies(fams)
    font.setPointSizeF(point_size)
    app.setFont(font)


def mono_font(point_size: float = 10.0) -> QFont:
    """生 JSON・ハッシュ・SPDXID などの等幅フォント。"""
    font = QFont()
    fams = _available(["Cascadia Mono", "Consolas", "Courier New"])
    if fams:
        font.setFamilies(fams)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(point_size)
    return font


def icon(name: str, color: Optional[str] = None, size: int = 16) -> Optional[QIcon]:
    """icons/<name> の SVG（Lucide など単色）を、現在のテーマ色で塗ったアイコンにして返す。ファイルが無ければ None。"""
    if not name:
        return None
    path = os.path.join("icons", name)
    if not os.path.isfile(path):
        return None
    col = color or _current.text_muted
    key = (path, col, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    scale = 2                                   # 高 DPI 用に 2 倍で描く
    pm = QIcon(path).pixmap(QSize(size * scale, size * scale))
    if pm.isNull():
        return None
    painter = QPainter(pm)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pm.rect(), QColor(col))
    painter.end()
    pm.setDevicePixelRatio(scale)
    result = QIcon(pm)
    _icon_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# 適用
# ---------------------------------------------------------------------------

def _system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:                       # Qt 6.5 未満
        return False


def resolve(mode_name: str) -> Tokens:
    if mode_name == "dark":
        return DARK
    if mode_name == "light":
        return LIGHT
    return DARK if _system_is_dark() else LIGHT


def apply_theme(app: QApplication, mode_name: Optional[str] = None) -> Tokens:
    """テーマを適用する。mode_name が None なら現在の選択のまま再適用する。"""
    global _current, _mode, _applying, _signal_connected
    if mode_name is not None:
        _mode = mode_name if mode_name in ("auto", "light", "dark") else "auto"

    _applying = True
    try:
        app.setStyle("Fusion")
        # Windows のタイトルバーも追従させる（Qt 6.8+）。古い Qt では何もしない
        try:
            hints = app.styleHints()
            wanted = {"auto": Qt.ColorScheme.Unknown, "light": Qt.ColorScheme.Light,
                      "dark": Qt.ColorScheme.Dark}[_mode]
            if hasattr(hints, "setColorScheme") and hints.colorScheme() != wanted:
                hints.setColorScheme(wanted)
        except Exception:
            pass

        _current = resolve(_mode)
        _icon_cache.clear()
        from core import compare_report              # 遅延 import（core は Qt 非依存のまま保つ）
        compare_report.set_colors(report_colors(_current))
        app.setPalette(build_palette(_current))      # → ApplicationPaletteChange が各ウィジェットに届く
        app.setStyleSheet(build_qss(_current))
    finally:
        _applying = False

    if not _signal_connected:
        try:
            app.styleHints().colorSchemeChanged.connect(lambda *_: _on_system_scheme_changed(app))
            _signal_connected = True
        except AttributeError:
            pass
    return _current


def _on_system_scheme_changed(app: QApplication) -> None:
    if _mode == "auto" and not _applying:
        apply_theme(app)