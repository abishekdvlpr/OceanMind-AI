# --- theme.py ---
"""
OceanMind AI design system.

This module is PRESENTATION ONLY. It imports nothing from the data, database,
RAG or ingestion layers and is imported only by dashboard.py, so it can never
affect backend behaviour.

Exports:
    PALETTE            - colour tokens
    BRAND              - product naming strings
    inject_theme()     - writes the global stylesheet (call once, early)
    hero()             - landing hero markup
    metric_card()      - premium KPI card markup
    section_header()   - consistent section heading markup
    status_pill()      - inline status chip markup
    style_figure(fig)  - applies the dark Plotly theme to any figure
    CATEGORICAL, SEQUENTIAL, DIVERGING - Plotly colour ramps
"""

# =========================================================================
# Brand
# =========================================================================
BRAND = {
    "name": "OceanMind AI",
    "tagline": "AI-Driven Unified Ocean Intelligence Platform",
    "page_title": "OceanMind AI - Ocean Intelligence Platform",
    "platform": "OceanMind AI Platform",
    "event": "Developed for Smart India Hackathon 2026",
    "footer_line": "Powered by AI • ARGO • Oceanographic Data • Fisheries • Biodiversity",
    "icon": "🌊",
}

# =========================================================================
# Colour tokens
# =========================================================================
PALETTE = {
    "bg": "#070B14",           # page base - near black navy
    "surface": "#0F1724",      # elevated card
    "surface_2": "#141F31",    # hover / nested
    "border": "#1E2B3F",
    "border_soft": "#18243550",
    "text": "#E8EEF6",
    "text_muted": "#8CA0B8",
    "text_dim": "#5A6B82",
    "accent": "#22D3EE",       # cyan - primary accent
    "accent_2": "#2DD4BF",     # teal
    "accent_3": "#38BDF8",     # ocean blue
    "accent_deep": "#0E7490",
    "success": "#34D399",
    "warning": "#FBBF24",
    "danger": "#F87171",
    "demo": "#A78BFA",         # violet - reserved for DEMO-labelled tiles
}

# Plotly ramps
CATEGORICAL = [
    "#22D3EE", "#2DD4BF", "#38BDF8", "#818CF8", "#A78BFA",
    "#34D399", "#FBBF24", "#FB7185", "#60A5FA", "#F472B6",
]
SEQUENTIAL = [
    [0.0, "#0B2740"], [0.25, "#0E7490"], [0.5, "#22D3EE"],
    [0.75, "#5EEAD4"], [1.0, "#CCFBF1"],
]
DIVERGING = "RdBu_r"

FONT_STACK = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


# =========================================================================
# Global stylesheet
# =========================================================================
def inject_theme():
    """Return the full <style> block. Selectors use stable data-testid hooks."""
    p = PALETTE
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ---------- Base ---------- */
html, body, [class*="css"] {{
    font-family: {FONT_STACK};
}}
.stApp {{
    background:
        radial-gradient(1200px 600px at 15% -10%, #0C2036 0%, transparent 55%),
        radial-gradient(900px 500px at 105% 0%, #08313A 0%, transparent 50%),
        {p['bg']};
    color: {p['text']};
}}
[data-testid="stAppViewContainer"] > .main {{
    padding-top: 0.5rem;
}}
[data-testid="stHeader"] {{
    background: transparent;
}}
.block-container {{
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1480px;
}}
h1, h2, h3, h4 {{
    color: {p['text']};
    letter-spacing: -0.02em;
    font-weight: 700;
}}
p, span, label, li {{ color: {p['text']}; }}
hr {{ border-color: {p['border']}; }}

/* ---------- Hero ---------- */
.om-hero {{
    position: relative;
    background: linear-gradient(135deg, rgba(34,211,238,0.10) 0%, rgba(45,212,191,0.05) 45%, rgba(15,23,36,0.0) 100%);
    border: 1px solid {p['border']};
    border-radius: 20px;
    padding: 2.5rem 2.75rem;
    margin-bottom: 1.75rem;
    overflow: hidden;
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
}}
.om-hero::after {{
    content: "";
    position: absolute; inset: 0;
    background: radial-gradient(600px 220px at 88% 10%, rgba(34,211,238,0.16), transparent 70%);
    pointer-events: none;
}}
.om-hero-eyebrow {{
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: {p['accent']};
    background: rgba(34,211,238,0.10);
    border: 1px solid rgba(34,211,238,0.28);
    border-radius: 999px;
    padding: 0.3rem 0.85rem;
    margin-bottom: 1rem;
}}
.om-hero h1 {{
    margin: 0;
    font-size: 3.1rem;
    font-weight: 800;
    line-height: 1.05;
    letter-spacing: -0.035em;
    background: linear-gradient(100deg, #FFFFFF 10%, {p['accent']} 55%, {p['accent_2']} 95%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}}
.om-hero p {{
    margin: 0.7rem 0 0 0;
    font-size: 1.08rem;
    font-weight: 300;
    color: {p['text_muted']};
    max-width: 46rem;
}}

/* ---------- Metric cards ---------- */
.om-card {{
    background: linear-gradient(160deg, {p['surface']} 0%, #0C1420 100%);
    border: 1px solid {p['border']};
    border-radius: 16px;
    padding: 1.15rem 1.25rem;
    height: 100%;
    transition: border-color .18s ease, transform .18s ease, box-shadow .18s ease;
}}
.om-card:hover {{
    border-color: rgba(34,211,238,0.42);
    transform: translateY(-2px);
    box-shadow: 0 10px 34px rgba(0,0,0,0.45);
}}
.om-card-top {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 0.7rem;
}}
.om-card-label {{
    font-size: 0.74rem;
    font-weight: 600;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: {p['text_dim']};
}}
.om-card-icon {{ font-size: 1.05rem; opacity: 0.9; }}
.om-card-value {{
    font-size: 1.85rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    line-height: 1.1;
    color: {p['text']};
}}
.om-card-value.om-muted {{ color: {p['text_dim']}; font-weight: 600; }}
.om-card-sub {{
    margin-top: 0.4rem;
    font-size: 0.78rem;
    color: {p['text_muted']};
}}
.om-chip {{
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    padding: 0.16rem 0.5rem;
    border-radius: 999px;
    text-transform: uppercase;
}}
.om-chip-demo {{
    color: {p['demo']};
    background: rgba(167,139,250,0.12);
    border: 1px solid rgba(167,139,250,0.35);
}}
.om-chip-live {{
    color: {p['success']};
    background: rgba(52,211,153,0.12);
    border: 1px solid rgba(52,211,153,0.32);
}}
.om-card-demo {{ border-style: dashed; border-color: rgba(167,139,250,0.30); }}

/* ---------- Section headers ---------- */
.om-section {{
    display: flex; align-items: baseline; gap: 0.7rem;
    margin: 2.1rem 0 1rem 0;
}}
.om-section h3 {{ margin: 0; font-size: 1.18rem; font-weight: 700; }}
.om-section span {{ font-size: 0.84rem; color: {p['text_dim']}; }}

/* ---------- Status pills ---------- */
.om-pill {{
    display: inline-flex; align-items: center; gap: 0.45rem;
    font-size: 0.8rem; font-weight: 500;
    padding: 0.42rem 0.8rem;
    border-radius: 10px;
    width: 100%;
}}
.om-pill-ok      {{ color:{p['success']}; background:rgba(52,211,153,0.10); border:1px solid rgba(52,211,153,0.28); }}
.om-pill-err     {{ color:{p['danger']};  background:rgba(248,113,113,0.10); border:1px solid rgba(248,113,113,0.28); }}
.om-pill-warn    {{ color:{p['warning']}; background:rgba(251,191,36,0.10);  border:1px solid rgba(251,191,36,0.28); }}
.om-dot {{ width:7px; height:7px; border-radius:50%; background:currentColor; box-shadow:0 0 8px currentColor; }}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #0A101C 0%, #070B14 100%);
    border-right: 1px solid {p['border']};
}}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.4rem; }}
.om-brand {{
    display: flex; align-items: center; gap: 0.7rem;
    padding-bottom: 1.1rem; margin-bottom: 1.1rem;
    border-bottom: 1px solid {p['border']};
}}
.om-brand-mark {{
    width: 38px; height: 38px; border-radius: 11px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.25rem;
    background: linear-gradient(140deg, {p['accent']}, {p['accent_deep']});
    box-shadow: 0 4px 16px rgba(34,211,238,0.28);
}}
.om-brand-text strong {{
    display: block; font-size: 1.02rem; font-weight: 700;
    letter-spacing: -0.01em; color: {p['text']};
}}
.om-brand-text small {{
    display: block; font-size: 0.68rem; letter-spacing: 0.05em;
    color: {p['text_dim']}; text-transform: uppercase;
}}
.om-navlabel {{
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: {p['text_dim']};
    margin: 1.35rem 0 0.6rem 0;
}}

/* ---------- Buttons ---------- */
[data-testid="stSidebar"] .stButton > button {{
    background: {p['surface']};
    color: {p['text_muted']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    font-size: 0.83rem;
    font-weight: 500;
    text-align: left;
    padding: 0.6rem 0.85rem;
    transition: all .16s ease;
    line-height: 1.35;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: {p['surface_2']};
    border-color: rgba(34,211,238,0.45);
    color: {p['text']};
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, {p['accent']}, {p['accent_deep']});
    color: #04141A;
    font-weight: 650;
    border: none;
    text-align: center;
    box-shadow: 0 4px 16px rgba(34,211,238,0.22);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
    filter: brightness(1.08);
}}

/* ---------- Native metrics ---------- */
[data-testid="stMetric"] {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 13px;
    padding: 0.85rem 1rem;
}}
[data-testid="stMetricLabel"] p {{
    font-size: 0.72rem !important;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: {p['text_dim']} !important;
    font-weight: 600;
}}
[data-testid="stMetricValue"] {{
    font-size: 1.42rem !important;
    font-weight: 700;
    color: {p['text']};
    letter-spacing: -0.02em;
}}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0.4rem;
    background: transparent;
    border-bottom: 1px solid {p['border']};
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    border: none;
    border-radius: 9px 9px 0 0;
    padding: 0.6rem 1.05rem;
    font-size: 0.87rem;
    font-weight: 550;
    color: {p['text_dim']};
}}
.stTabs [aria-selected="true"] {{
    color: {p['accent']} !important;
    background: rgba(34,211,238,0.07);
    box-shadow: inset 0 -2px 0 {p['accent']};
}}

/* ---------- Chat ---------- */
[data-testid="stChatMessage"] {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 14px;
    padding: 1rem 1.15rem;
    margin-bottom: 0.85rem;
}}
[data-testid="stChatInput"] textarea {{ font-size: 0.94rem; }}
[data-testid="stBottomBlockContainer"] {{
    background: linear-gradient(180deg, rgba(7,11,20,0) 0%, {p['bg']} 32%);
}}

/* ---------- Expanders, tables, inputs ---------- */
[data-testid="stExpander"] {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 12px;
}}
[data-testid="stExpander"] summary {{ font-size: 0.87rem; font-weight: 550; }}
[data-testid="stDataFrame"] {{
    border: 1px solid {p['border']};
    border-radius: 11px;
}}
.stSelectbox div[data-baseweb="select"] > div {{
    background: {p['surface']};
    border-color: {p['border']};
    border-radius: 10px;
}}
.stDownloadButton > button {{
    background: {p['surface_2']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    font-size: 0.83rem;
    font-weight: 550;
}}
.stDownloadButton > button:hover {{
    border-color: rgba(34,211,238,0.5);
    color: {p['accent']};
}}

/* ---------- Empty / info / error states ---------- */
.om-empty {{
    text-align: center;
    padding: 2.6rem 1.5rem;
    border: 1px dashed {p['border']};
    border-radius: 16px;
    background: rgba(15,23,36,0.45);
}}
.om-empty-icon {{ font-size: 2.3rem; margin-bottom: 0.6rem; opacity: 0.75; }}
.om-empty h4 {{ margin: 0 0 0.4rem 0; font-size: 1.05rem; }}
.om-empty p {{ margin: 0; color: {p['text_muted']}; font-size: 0.88rem; }}

.om-tips {{
    background: rgba(34,211,238,0.05);
    border: 1px solid rgba(34,211,238,0.20);
    border-left: 3px solid {p['accent']};
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
    margin-top: 0.75rem;
}}
.om-tips h4 {{ margin: 0 0 0.5rem 0; font-size: 0.95rem; color: {p['accent']}; }}
.om-tips ul {{ margin: 0.4rem 0 0 1.1rem; padding: 0; }}
.om-tips li {{ font-size: 0.86rem; color: {p['text_muted']}; margin-bottom: 0.28rem; }}

/* ---------- Footer ---------- */
.om-footer {{
    margin-top: 3rem; padding-top: 1.6rem;
    border-top: 1px solid {p['border']};
    text-align: center;
}}
.om-footer strong {{
    display: block; font-size: 0.98rem; font-weight: 700;
    color: {p['text']}; letter-spacing: -0.01em;
}}
.om-footer span {{ display: block; font-size: 0.8rem; color: {p['text_dim']}; margin-top: 0.3rem; }}

/* ---------- Motion ---------- */
@keyframes omFade {{ from {{ opacity: 0; transform: translateY(7px); }} to {{ opacity: 1; transform: none; }} }}
.om-hero, .om-card, .om-empty {{ animation: omFade .34s ease both; }}
@media (prefers-reduced-motion: reduce) {{
    .om-hero, .om-card, .om-empty {{ animation: none; }}
    .om-card:hover {{ transform: none; }}
}}
</style>
"""


# =========================================================================
# Markup helpers
# =========================================================================
def hero(title=None, subtitle=None, eyebrow="Smart India Hackathon 2026"):
    return f"""
<div class="om-hero">
    <div class="om-hero-eyebrow">{eyebrow}</div>
    <h1>{title or BRAND['name']}</h1>
    <p>{subtitle or BRAND['tagline']}</p>
</div>
"""


def metric_card(label, value, sub="", icon="", demo=False, muted=False):
    """
    A KPI tile. `demo=True` renders a dashed border and a visible DEMO chip so
    illustrative values are never mistaken for live measurements.
    """
    chip = '<span class="om-chip om-chip-demo">Demo</span>' if demo else \
           '<span class="om-chip om-chip-live">Live</span>'
    return f"""
<div class="om-card {'om-card-demo' if demo else ''}">
    <div class="om-card-top">
        <span class="om-card-label">{label}</span>
        <span class="om-card-icon">{icon}</span>
    </div>
    <div class="om-card-value {'om-muted' if muted else ''}">{value}</div>
    <div class="om-card-sub">{sub} &nbsp;{chip}</div>
</div>
"""


def section_header(title, note=""):
    return f'<div class="om-section"><h3>{title}</h3><span>{note}</span></div>'


def status_pill(text, state="ok"):
    cls = {"ok": "om-pill-ok", "error": "om-pill-err", "warn": "om-pill-warn"}.get(state, "om-pill-ok")
    return f'<div class="om-pill {cls}"><span class="om-dot"></span>{text}</div>'


def sidebar_brand():
    return f"""
<div class="om-brand">
    <div class="om-brand-mark">{BRAND['icon']}</div>
    <div class="om-brand-text">
        <strong>{BRAND['name']}</strong>
        <small>Ocean Intelligence</small>
    </div>
</div>
"""


def nav_label(text):
    return f'<div class="om-navlabel">{text}</div>'


def empty_state(icon, title, body):
    return f"""
<div class="om-empty">
    <div class="om-empty-icon">{icon}</div>
    <h4>{title}</h4>
    <p>{body}</p>
</div>
"""


def footer():
    return f"""
<div class="om-footer">
    <strong>{BRAND['name']}</strong>
    <span>{BRAND['event']}</span>
    <span>{BRAND['footer_line']}</span>
</div>
"""


# =========================================================================
# Plotly theming
# =========================================================================
def style_figure(fig, height=None):
    """Apply the dark ocean theme to a Plotly figure. Never alters the data."""
    p = PALETTE
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,36,0.55)",
        font=dict(family=FONT_STACK, color=p["text_muted"], size=12),
        title_font=dict(size=15, color=p["text"], family=FONT_STACK),
        title_x=0.01,
        margin=dict(l=10, r=10, t=52, b=10),
        legend=dict(
            bgcolor="rgba(15,23,36,0.75)",
            bordercolor=p["border"],
            borderwidth=1,
            font=dict(size=11, color=p["text_muted"]),
        ),
        hoverlabel=dict(
            bgcolor=p["surface_2"],
            bordercolor=p["accent"],
            font=dict(family=FONT_STACK, color=p["text"], size=12),
        ),
    )
    fig.update_xaxes(
        gridcolor="rgba(30,43,63,0.65)",
        zerolinecolor="rgba(30,43,63,0.9)",
        linecolor=p["border"],
        tickfont=dict(color=p["text_dim"], size=11),
        title_font=dict(color=p["text_muted"], size=12),
    )
    fig.update_yaxes(
        gridcolor="rgba(30,43,63,0.65)",
        zerolinecolor="rgba(30,43,63,0.9)",
        linecolor=p["border"],
        tickfont=dict(color=p["text_dim"], size=11),
        title_font=dict(color=p["text_muted"], size=12),
    )
    if height:
        fig.update_layout(height=height)
    return fig
