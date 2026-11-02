"""Design tokens shared by the desktop UI: colors, fonts, spacing."""
from __future__ import annotations

import customtkinter as ctk

FAMILY = "Microsoft YaHei UI"
MONO = "Consolas"

# 每项都是 (浅色, 深色)，CTk 切换外观模式时会自动取对应的值。
BG = ("#F4F6F9", "#0F1115")
SURFACE = ("#FFFFFF", "#171A20")
SURFACE_ALT = ("#F7F9FC", "#1E2128")
HOVER = ("#ECEFF5", "#1E2128")
BORDER = ("#E5E8EE", "#262A33")
TEXT = ("#0F172A", "#F3F5F9")
TEXT_MUTED = ("#64748B", "#98A2B3")
TEXT_FAINT = ("#94A3B8", "#748094")
ACCENT = ("#2563EB", "#4C8DFF")
ACCENT_HOVER = ("#1D4ED8", "#6BA1FF")
ACCENT_SOFT = ("#E8EFFD", "#1B2A45")
ACCENT_LINE = ("#BFD2F5", "#2C3E5E")
ACCENT_TEXT = ("#FFFFFF", "#0A1628")
ON_ACCENT = ("#FFFFFF", "#0A1628")
SUCCESS = ("#0E9F6E", "#34D399")
SUCCESS_SOFT = ("#E6F6EF", "#123127")
WARNING = ("#B7791F", "#F0B429")
WARNING_SOFT = ("#FBF3E2", "#33280F")
DANGER = ("#DC2626", "#F87171")
DANGER_SOFT = ("#FDECEC", "#361A1C")
DISABLED = ("#E9EDF4", "#20242C")
DISABLED_TEXT = ("#A3ADBD", "#5A6473")

RADIUS_CARD = 14
RADIUS_CONTROL = 8
RADIUS_PILL = 999

FONT_TITLE = 20
FONT_SECTION = 15
FONT_BODY = 13
FONT_SMALL = 12
FONT_TINY = 11

_fonts: dict[tuple, ctk.CTkFont] = {}


def font(size=FONT_BODY, weight="normal", family=FAMILY):
    """Cache CTkFont instances so theme switches reuse one object per spec."""
    key = (family, size, weight)
    if key not in _fonts:
        _fonts[key] = ctk.CTkFont(family=family, size=size, weight=weight)
    return _fonts[key]


def is_dark():
    return ctk.get_appearance_mode() == "Dark"


def pick(color):
    """Resolve a (light, dark) token for classic Tk widgets that need one color."""
    if isinstance(color, (tuple, list)):
        return color[1] if is_dark() else color[0]
    return color


def tone(name):
    return {
        "muted": TEXT_MUTED,
        "text": TEXT,
        "accent": ACCENT,
        "success": SUCCESS,
        "warning": WARNING,
        "danger": DANGER,
    }[name]


def treeview_palette():
    """Treeview is a classic ttk widget: it needs explicit recoloring."""
    if is_dark():
        return {
            "background": "#171A20", "foreground": "#E6EAF2", "heading": "#14171C",
            "heading_text": "#98A2B3", "selected": "#1E3A63", "selected_text": "#F2F6FF",
            "stripe": "#1B1F26", "muted_row": "#F0B429", "failed_row": "#F87171",
            "ok_row": "#34D399",
        }
    return {
        "background": "#FFFFFF", "foreground": "#1B2434", "heading": "#F7F9FC",
        "heading_text": "#64748B", "selected": "#E3ECFD", "selected_text": "#123E8C",
        "stripe": "#FAFBFD", "muted_row": "#8A6416", "failed_row": "#C02B2B",
        "ok_row": "#0B7F58",
    }
