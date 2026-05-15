from __future__ import annotations

# Centralized dark / light stylesheets for the NikaPlanet dock panel.
#
# Palettes track the NIKA Design System Plum-Dark (canonical brand dark) and
# Plum-Light (canonical brand default) themes — oklch tokens converted to
# sRGB hex. See github.com/NikaGeospatial/nika-design-system.

import os as _os
import tempfile as _tempfile

# ── branch arrow icons (generated once per theme) ─────────────────────

_arrow_cache: dict[str, tuple[str, str]] = {}


def _get_arrow_paths(c: dict) -> tuple[str, str]:
    """Return (collapsed_svg_path, expanded_svg_path) for the given palette."""
    key = c["text_dim"] + c["primary"]
    if key in _arrow_cache:
        return _arrow_cache[key]

    d = _tempfile.mkdtemp(prefix="np_arrows_")

    right = _os.path.join(d, "right.svg")
    with open(right, "w") as f:
        f.write(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            f'<polygon points="2,0 9,5 2,10" fill="{c["text_dim"]}"/></svg>'
        )

    down = _os.path.join(d, "down.svg")
    with open(down, "w") as f:
        f.write(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            f'<polygon points="0,2 10,2 5,9" fill="{c["primary"]}"/></svg>'
        )

    # QSS url() requires forward slashes on all platforms (including Windows).
    right = right.replace("\\", "/")
    down = down.replace("\\", "/")

    _arrow_cache[key] = (right, down)
    return right, down


# ── colour tokens ──────────────────────────────────────────────────────

# NIKA Plum-Dark — deep aubergine paper, warm cream ink, lime accent.
DARK = {
    "bg":               "#0e0511",  # bg
    "surface":          "#1e1021",  # bg-2 (cards / surface)
    "surface_low":      "#1e1021",  # bg-2
    "surface_high":     "#2d1d31",  # bg-3
    "surface_highest":  "#3d2b41",  # bg-4
    "on_surface":       "#f5f2e7",  # ink (warm cream)
    "on_surface_dim":   "#817683",  # ink-3
    "primary":          "#abf051",  # accent (lime / chartreuse)
    "primary_grad_end": "#cccd00",
    "primary_dark":     "#203501",  # accent-soft
    "primary_hover":    "#b8fe60",
    "on_primary":       "#0e0511",  # text on lime — deep plum
    "accent":           "#abf051",
    "card_bg":          "#1e1021",
    "card_border":      "rgba(48,35,51,0.65)",  # rule
    "text":             "#f5f2e7",
    "text_dim":         "#817683",
    "divider":          "rgba(171,240,81,0.28)",
    "btn_outline_fg":   "#bcb7ab",  # ink-2
    "btn_outline_bdr":  "rgba(48,35,51,0.65)",
    "notice":           "#e1791b",  # warn
}

# NIKA Plum-Light — pale lilac paper, deep aubergine ink, brass accent.
LIGHT = {
    "bg":               "#fbf9fc",
    "surface":          "#ffffff",
    "surface_low":      "#f4f0f5",  # bg-2
    "surface_high":     "#ece5ed",
    "surface_highest":  "#dcd4de",
    "on_surface":       "#170d19",  # ink (deep aubergine)
    "on_surface_dim":   "#807683",  # ink-3
    "primary":          "#eba941",  # accent (brass)
    "primary_grad_end": "#f0ba59",
    "primary_dark":     "#d79628",
    "primary_hover":    "#d79628",
    "on_primary":       "#170d19",  # text on brass — deep aubergine
    "accent":           "#eba941",
    "card_bg":          "#ffffff",
    "card_border":      "rgba(23,13,25,0.10)",
    "text":             "#170d19",
    "text_dim":         "#807683",
    "divider":          "rgba(235,169,65,0.22)",
    "btn_outline_fg":   "#170d19",
    "btn_outline_bdr":  "rgba(23,13,25,0.18)",
    "notice":           "#b75f0b",
}


def _stylesheet(c: dict) -> str:
    """Build the full QSS string for a given colour dict *c*."""
    arrow_right, arrow_down = _get_arrow_paths(c)
    return f"""
/* ── root container ────────────────────────────────────────────────── */
#npRoot {{
    background-color: {c["bg"]};
}}

/* ── header bar ────────────────────────────────────────────────────── */
#npHeader {{
    background: transparent;
}}
#npHeaderTitle {{
    color: {c["text"]};
    font-size: 11pt;
    font-weight: 700;
    letter-spacing: 1.5px;
}}
#npThemeToggle {{
    background: transparent;
    border: none;
    font-size: 13pt;
    padding: 4px;
    color: {c["text_dim"]};
}}
#npThemeToggle:hover {{
    color: {c["primary"]};
}}
#npUserChip {{
    background-color: {c["surface_high"]};
    color: {c["text"]};
    border-radius: 14px;
    font-size: 10pt;
    font-weight: 700;
    padding: 2px 0px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}}
#npUserChip::menu-indicator {{
    width: 0px;
    height: 0px;
    image: none;
}}
#npUserMenu {{
    background-color: {c["surface_low"]};
    color: {c["text"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    padding: 4px 0px;
    font-size: 9pt;
}}
#npUserMenu::item {{
    padding: 6px 20px;
}}
#npUserMenu::item:selected {{
    background-color: {c["surface_high"]};
    color: {c["primary"]};
}}

/* ── login page ────────────────────────────────────────────────────── */
#npLogo {{
    color: {c["primary"]};
    font-size: 22pt;
    font-weight: 600;
}}
#npLogoDivider {{
    background-color: {c["primary"]};
    border: none;
}}
#npHeading {{
    color: {c["text"]};
    font-size: 16pt;
    font-weight: bold;
}}
#npSubtitle {{
    color: {c["text_dim"]};
    font-size: 10pt;
}}
#npSignIn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c["primary"]}, stop:1 {c["primary_grad_end"]});
    color: {c["on_primary"]};
    border: none;
    border-radius: 8px;
    font-size: 10pt;
    font-weight: bold;
    padding: 0 24px;
}}
#npSignIn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c["primary_hover"]}, stop:1 {c["primary_grad_end"]});
}}
#npFooterLinks, #npFooterVersion {{
    color: {c["text_dim"]};
    font-size: 9pt;
}}

/* ── capability cards ──────────────────────────────────────────────── */
#npCapCard {{
    background-color: {c["card_bg"]};
    border: 1px solid {c["card_border"]};
    border-radius: 12px;
}}
#npCapCard:hover {{
    border-color: {c["primary"]};
}}
#npCapIcon {{
    color: {c["primary"]};
    font-size: 20pt;
}}
#npCapTitle {{
    color: {c["text"]};
    font-size: 12pt;
    font-weight: 700;
}}
#npCapDesc {{
    color: {c["text_dim"]};
    font-size: 9pt;
}}

/* ── workers page ──────────────────────────────────────────────────── */
#npRefreshBtn {{
    background: transparent;
    color: {c["text_dim"]};
    border: 1px solid {c["btn_outline_bdr"]};
    border-radius: 6px;
    font-size: 12pt;
    padding: 0;
}}
#npRefreshBtn:hover {{
    border-color: {c["primary"]};
    color: {c["primary"]};
}}
#npFiltersToggle {{
    background: transparent;
    color: {c["text_dim"]};
    border: 1px solid {c["btn_outline_bdr"]};
    border-radius: 6px;
    font-size: 9pt;
    font-weight: 600;
    padding: 5px 12px;
}}
#npFiltersToggle:hover {{
    border-color: {c["primary"]};
    color: {c["primary"]};
}}
#npFiltersToggle:checked {{
    background: {c["surface_high"]};
    border-color: {c["primary"]};
    color: {c["primary"]};
}}
#npResetFiltersBtn {{
    background: transparent;
    color: {c["text_dim"]};
    border: 1px solid {c["btn_outline_bdr"]};
    border-radius: 6px;
    font-size: 8pt;
    font-weight: 600;
    padding: 3px 10px;
}}
#npResetFiltersBtn:hover {{
    border-color: {c["primary"]};
    color: {c["primary"]};
}}
#npLogoutBtn {{
    background: transparent;
    color: {c["btn_outline_fg"]};
    border: 1px solid {c["btn_outline_bdr"]};
    border-radius: 6px;
    font-size: 9pt;
    font-weight: 700;
    padding: 6px 14px;
}}
#npLogoutBtn:hover {{
    border-color: {c["primary"]};
    color: {c["primary"]};
}}
#npTeamHeading {{
    color: {c["text"]};
    font-size: 12pt;
    font-weight: 700;
}}
#npWorkerCard {{
    background-color: {c["card_bg"]};
    border: 1px solid {c["card_border"]};
    border-radius: 10px;
}}
#npWorkerName {{
    color: {c["text"]};
    font-size: 10pt;
    font-weight: 600;
}}
#npWorkerDesc {{
    color: {c["text_dim"]};
    font-size: 9pt;
}}
#npChevron {{
    background: transparent;
    border: none;
    color: {c["text_dim"]};
    font-size: 12pt;
}}
#npVersionSep {{
    background-color: {c["divider"]};
}}
#npBackBtn {{
    background: transparent;
    border: none;
    color: {c["text_dim"]};
    font-size: 9pt;
    font-weight: 600;
    padding: 4px 0;
}}
#npBackBtn:hover {{
    color: {c["primary"]};
}}
#npEmptyLabel {{
    color: {c["text_dim"]};
    font-size: 10pt;
}}
#npVerBadge {{
    background-color: {c["primary"]};
    color: {c["on_primary"]};
    border-radius: 4px;
    font-size: 8pt;
    font-weight: 700;
    padding: 3px 8px;
}}
#npVersionBtn {{
    background: transparent;
    border: none;
    color: {c["text_dim"]};
    font-size: 9pt;
    padding: 0;
    text-align: left;
}}
#npVersionBtn:hover {{
    color: {c["primary"]};
}}

/* ── tab bar ──────────────────────────────────────────────────────── */
#npTabBtn {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {c["text_dim"]};
    font-size: 10pt;
    font-weight: 600;
    padding: 6px 16px;
}}
#npTabBtn:checked {{
    color: {c["primary"]};
    border-bottom-color: {c["primary"]};
}}
#npTabBtn:hover {{
    color: {c["primary"]};
}}

/* ── run dialog ────────────────────────────────────────────────────── */
#npRunDialog {{
    background-color: {c["bg"]};
}}
#npRunFormLabel {{
    color: {c["text"]};
    font-size: 10pt;
}}
#npRunDialogTitle {{
    color: {c["text"]};
    font-size: 14pt;
    font-weight: 700;
}}
#npRunDialogVersion {{
    color: {c["text_dim"]};
    font-size: 9pt;
}}
#npRunDialogDesc {{
    color: {c["text_dim"]};
    font-size: 10pt;
}}
#npRunInput {{
    background-color: {c["surface_low"]};
    color: {c["text"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 10pt;
}}
#npRunInput:focus {{
    border-color: {c["primary"]};
}}
#npBrowseBtn {{
    background-color: {c["surface_high"]};
    color: {c["text"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    font-size: 9pt;
    padding: 6px 12px;
}}
#npBrowseBtn:hover {{
    border-color: {c["primary"]};
    color: {c["primary"]};
}}
#npRunCombo {{
    background-color: {c["surface_low"]};
    color: {c["text"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 10pt;
}}
#npRunCombo:focus {{
    border-color: {c["primary"]};
}}
#npRunCombo QAbstractItemView {{
    background-color: {c["surface_low"]};
    color: {c["text"]};
    selection-background-color: {c["primary"]};
    selection-color: {c["on_primary"]};
}}
#npRunCheckbox {{
    color: {c["text"]};
    font-size: 10pt;
    spacing: 6px;
}}
#npRunCheckbox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {c["card_border"]};
    border-radius: 3px;
    background-color: {c["surface_low"]};
}}
#npRunCheckbox::indicator:checked {{
    background-color: {c["primary"]};
    border-color: {c["primary"]};
}}
#npSubmitRunBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c["primary"]}, stop:1 {c["primary_grad_end"]});
    color: {c["on_primary"]};
    border: none;
    border-radius: 8px;
    font-size: 10pt;
    font-weight: bold;
}}
#npSubmitRunBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c["primary_hover"]}, stop:1 {c["primary_grad_end"]});
}}

/* ── log view ─────────────────────────────────────────────────────── */
#npLogSectionLabel {{
    color: {c["primary"]};
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
}}
#npVersionBadge {{
    background-color: {c["primary"]};
    color: {c["on_primary"]};
    border-radius: 4px;
    font-size: 9pt;
    font-weight: 700;
    padding: 2px 8px;
}}
#npSessionId {{
    color: {c["text_dim"]};
    font-size: 9pt;
    font-family: monospace;
}}
#npStatusCard {{
    background-color: {c["surface_high"]};
    border-radius: 8px;
}}
#npStatusValue {{
    color: {c["text"]};
    font-size: 10pt;
    font-weight: 700;
}}
#npDurationValue {{
    color: {c["text"]};
    font-size: 10pt;
    font-weight: 700;
}}
#npLogTabLabel {{
    color: {c["primary"]};
    font-size: 10pt;
    font-weight: 600;
    border-bottom: 2px solid {c["primary"]};
    padding-bottom: 4px;
    max-width: 60px;
}}
#npLogArea {{
    background-color: {c["surface_low"]};
    color: {c["text"]};
    border: 1px solid {c["card_border"]};
    border-radius: 8px;
    font-family: monospace;
    font-size: 9pt;
    padding: 10px;
}}
#npCancelBtn {{
    background: transparent;
    color: #e74c3c;
    border: 1px solid #c0392b;
    border-radius: 8px;
    font-size: 10pt;
    font-weight: bold;
}}
#npCancelBtn:hover {{
    background-color: rgba(231, 76, 60, 0.1);
    border-color: #e74c3c;
}}
#npCancelBtn:disabled {{
    color: {c["text_dim"]};
    border-color: {c["card_border"]};
}}
#npStatusBadge {{
    color: {c["primary"]};
    font-size: 9pt;
    font-weight: 700;
}}

/* ── outputs file browser ──────────────────────────────────────────── */
#npOutputsNotice {{
    color: {c["notice"]};
    font-size: 9pt;
    font-style: italic;
    padding: 2px 4px;
}}
#npOutputsTree {{
    background-color: {c["surface_low"]};
    color: {c["text"]};
    border: 1px solid {c["card_border"]};
    border-radius: 8px;
    font-size: 9pt;
    padding: 4px;
    outline: none;
}}
#npOutputsTree::item {{
    padding: 4px 2px;
    border-radius: 4px;
}}
#npOutputsTree::item:selected {{
    background-color: {c["surface_high"]};
    color: {c["primary"]};
}}
#npOutputsTree::item:hover {{
    background-color: {c["surface_high"]};
}}
#npOutputsTree::branch {{
    background: transparent;
}}
#npOutputsTree::branch:has-children:!has-siblings:closed,
#npOutputsTree::branch:closed:has-children:has-siblings {{
    image: url({arrow_right});
    padding: 2px;
}}
#npOutputsTree::branch:open:has-children:!has-siblings,
#npOutputsTree::branch:open:has-children:has-siblings {{
    image: url({arrow_down});
    padding: 2px;
}}
#npOutputsTree QHeaderView::section {{
    background-color: {c["surface_low"]};
    color: {c["text_dim"]};
    border: none;
    border-bottom: 1px solid {c["divider"]};
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 4px 6px;
}}
#npOutputsMenu {{
    background-color: {c["surface_low"]};
    color: {c["text"]};
    border: 1px solid {c["card_border"]};
    border-radius: 6px;
    padding: 4px 0px;
    font-size: 9pt;
}}
#npOutputsMenu::item {{
    padding: 6px 20px;
}}
#npOutputsMenu::item:selected {{
    background-color: {c["surface_high"]};
    color: {c["primary"]};
}}

/* ── detail tabs ──────────────────────────────────────────────────── */
#npDetailTabs::pane {{
    border: none;
    background: transparent;
}}
#npDetailTabs > QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {c["text_dim"]};
    font-size: 9pt;
    font-weight: 600;
    padding: 6px 14px;
    min-width: 70px;
}}
#npDetailTabs > QTabBar::tab:selected {{
    color: {c["primary"]};
    border-bottom-color: {c["primary"]};
}}
#npDetailTabs > QTabBar::tab:hover {{
    color: {c["primary"]};
}}
#npDetailTabs > QTabBar::tab:disabled {{
    color: {c["surface_high"]};
}}

/* ── scroll area ───────────────────────────────────────────────────── */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background: {c["surface_high"]};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""


DARK_STYLESHEET = _stylesheet(DARK)
LIGHT_STYLESHEET = _stylesheet(LIGHT)
