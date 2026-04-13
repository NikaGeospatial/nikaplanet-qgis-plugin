# Centralized dark / light stylesheets for the NikaPlanet dock panel.
#
# Dark palette follows the "Cosmic Cartographer" design system (DESIGN.md).
# Light palette mirrors the capabilities-mobile mockup.

# ── colour tokens ──────────────────────────────────────────────────────

DARK = {
    "bg":               "#0c1220",
    "surface":          "#05151d",
    "surface_low":      "#0d1e25",
    "surface_high":     "#1c2c34",
    "surface_highest":  "#27373f",
    "on_surface":       "#d4e5f0",
    "on_surface_dim":   "#6a7a90",
    "primary":          "#4ecdc4",
    "primary_grad_end": "#6de0d4",
    "primary_dark":     "#006863",
    "primary_hover":    "#7eeee6",
    "accent":           "#4bdbd1",
    "card_bg":          "#0d1e25",
    "card_border":      "rgba(63,73,72,0.15)",
    "text":             "#e8ecf2",
    "text_dim":         "#6a7a90",
    "divider":          "rgba(78,205,196,0.25)",
    "btn_outline_fg":   "#d4e5f0",
    "btn_outline_bdr":  "rgba(63,73,72,0.35)",
}

LIGHT = {
    "bg":               "#f5f6f8",
    "surface":          "#ffffff",
    "surface_low":      "#f0f1f3",
    "surface_high":     "#e8eaed",
    "surface_highest":  "#dadce0",
    "on_surface":       "#1a1a1a",
    "on_surface_dim":   "#6b7280",
    "primary":          "#3b82f6",
    "primary_grad_end": "#60a5fa",
    "primary_dark":     "#1d4ed8",
    "primary_hover":    "#93c5fd",
    "accent":           "#3b82f6",
    "card_bg":          "#ffffff",
    "card_border":      "rgba(0,0,0,0.10)",
    "text":             "#1a1a1a",
    "text_dim":         "#6b7280",
    "divider":          "rgba(0,0,0,0.08)",
    "btn_outline_fg":   "#1a1a1a",
    "btn_outline_bdr":  "rgba(0,0,0,0.18)",
}


def _stylesheet(c: dict) -> str:
    """Build the full QSS string for a given colour dict *c*."""
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

/* ── login page ────────────────────────────────────────────────────── */
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
    color: {c["bg"]};
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
#npWorkersTitle {{
    color: {c["text"]};
    font-size: 14pt;
    font-weight: 700;
}}
#npRefreshBtn {{
    background-color: {c["primary"]};
    color: {c["bg"]};
    border: none;
    border-radius: 6px;
    font-size: 9pt;
    font-weight: 700;
    padding: 6px 14px;
}}
#npRefreshBtn:hover {{
    background-color: {c["primary_hover"]};
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
#npVersionLabel {{
    color: {c["text_dim"]};
    font-size: 9pt;
    padding: 3px 0;
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
