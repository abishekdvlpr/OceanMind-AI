"""OceanMind AI presentation system.

This module is presentation-only. It deliberately imports nothing from the
RAG, database, ingestion, or analysis layers.  The redesign keeps the existing
Streamlit architecture and changes only visual hierarchy/styling.
"""

BRAND = {
    "name": "OceanMind AI",
    "tagline": "AI-Driven Unified Marine Intelligence Platform",
    "page_title": "OceanMind AI - Unified Marine Intelligence",
    "platform": "OceanMind AI Platform",
    "event": "Developed for Smart India Hackathon 2026",
    "footer_line": "AI • ARGO • Oceanography • Fisheries • Biodiversity",
    "icon": "◉",
}

PALETTE = {
    "bg": "#F2F7F9",
    "surface": "#FFFFFF",
    "surface_2": "#EEF6F7",
    "surface_3": "#E7F1F4",
    "border": "#D8E6EA",
    "border_strong": "#C7DCE2",
    "text": "#102F3A",
    "text_muted": "#5D737C",
    "text_dim": "#87999F",
    "navy": "#082F3E",
    "deep_blue": "#0E6075",
    "accent": "#1677A6",
    "accent_2": "#218C7A",
    "accent_3": "#65C3C8",
    "coral": "#D9785F",
    "success": "#168267",
    "warning": "#B7791F",
    "danger": "#C65353",
    "demo": "#7857A8",
}

CATEGORICAL = [
    "#1677A6", "#218C7A", "#D9785F", "#0E6075", "#65C3C8",
    "#4C8C6F", "#9F7A35", "#6C7FA6", "#4D9BB5", "#8A6F9C",
]
SEQUENTIAL = [
    [0.0, "#F2F8FA"], [0.22, "#D6EEF1"], [0.50, "#65C3C8"],
    [0.75, "#1677A6"], [1.0, "#082F3E"],
]
DIVERGING = "RdBu_r"
FONT_STACK = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


def inject_theme():
    p = PALETTE
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

:root {{
  --om-bg: {p['bg']}; --om-surface: {p['surface']}; --om-soft: {p['surface_2']};
  --om-border: {p['border']}; --om-text: {p['text']}; --om-muted: {p['text_muted']};
  --om-navy: {p['navy']}; --om-blue: {p['accent']}; --om-teal: {p['accent_2']};
}}
html, body, [class*="css"] {{ font-family: {FONT_STACK}; }}
.stApp {{
  color: {p['text']};
  background:
    radial-gradient(900px 420px at 101% -4%, rgba(101,195,200,.15), transparent 64%),
    radial-gradient(680px 360px at 6% 6%, rgba(22,119,166,.08), transparent 68%),
    linear-gradient(180deg, #F7FAFB 0%, {p['bg']} 22%, #EFF5F7 100%);
}}
[data-testid="stHeader"] {{ background: rgba(242,247,249,.78); backdrop-filter: blur(12px); }}
[data-testid="stAppViewContainer"] > .main {{ padding-top: .25rem; }}
.block-container {{ padding-top: 1.5rem; padding-bottom: 6rem; max-width: 1480px; }}
h1,h2,h3,h4 {{ color:{p['text']}; letter-spacing:-.025em; font-weight:700; }}
p,span,label,li {{ color:{p['text']}; }}
hr {{ border-color:{p['border']}; }}

/* Hero: marine-science identity, not a marketing splash */
.om-hero {{
  position:relative; overflow:hidden;
  min-height:188px;
  padding:2.15rem 2.35rem;
  border:1px solid {p['border_strong']}; border-radius:24px;
  background:
    linear-gradient(112deg, rgba(255,255,255,.995) 0%, rgba(255,255,255,.985) 40%, rgba(239,249,250,.965) 69%, rgba(220,244,247,.94) 100%);
  box-shadow:0 16px 45px rgba(8,47,62,.08);
  margin-bottom:1rem;
}}
.om-hero::before {{
  content:""; position:absolute; inset:0 0 0 34%; pointer-events:none; z-index:0;
  background-image:url("data:image/webp;base64,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");
  background-repeat:no-repeat;
  background-position:right center;
  background-size:cover;
  opacity:.94;
  -webkit-mask-image:linear-gradient(90deg, transparent 0%, rgba(0,0,0,.08) 7%, rgba(0,0,0,.70) 27%, #000 45%, #000 100%);
  mask-image:linear-gradient(90deg, transparent 0%, rgba(0,0,0,.08) 7%, rgba(0,0,0,.70) 27%, #000 45%, #000 100%);
}}
/* Intentionally no hero ring pseudo-element: the previous clipped ring read visually as a stray "C". */
.om-hero::after {{ content:none; display:none; }}
.om-hero > * {{ position:relative; z-index:1; }}
.om-hero-eyebrow {{
  display:inline-flex; align-items:center; gap:.45rem; padding:.34rem .72rem;
  font-size:.67rem; font-weight:750; letter-spacing:.12em; text-transform:uppercase;
  color:{p['deep_blue']}; background:#E4F2F4; border:1px solid #C9E5E9; border-radius:999px;
  margin-bottom:.85rem;
}}
.om-hero-eyebrow::before {{ content:""; width:7px; height:7px; border-radius:50%; background:{p['accent_2']}; }}
.om-hero h1 {{ margin:0; font-size:3rem; line-height:1.02; font-weight:800; color:{p['navy']}; max-width:720px; }}
.om-hero p {{ margin:.72rem 0 0; font-size:1.02rem; line-height:1.55; color:{p['text_muted']}; max-width:650px; }}

@media (max-width: 900px) {{
  .om-hero {{ min-height:184px; padding:1.7rem 1.45rem; }}
  .om-hero::before {{ inset:0 0 0 20%; opacity:.55; background-position:64% center; }}
  .om-hero h1 {{ font-size:2.35rem; }}
}}

/* Dataset/domain ribbon */
.om-domain-strip {{
  display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem; margin:.15rem 0 1.25rem;
}}
.om-domain {{
  display:flex; align-items:center; gap:.72rem; padding:.78rem .9rem; min-height:62px;
  background:rgba(255,255,255,.82); border:1px solid {p['border']}; border-radius:14px;
  box-shadow:0 5px 18px rgba(8,47,62,.035);
}}
.om-domain-icon {{ width:34px; height:34px; border-radius:10px; display:flex; align-items:center; justify-content:center; color:#fff; font-weight:800; font-size:.74rem; }}
.om-domain:nth-child(1) .om-domain-icon {{ background:{p['accent']}; }}
.om-domain:nth-child(2) .om-domain-icon {{ background:{p['accent_2']}; }}
.om-domain:nth-child(3) .om-domain-icon {{ background:{p['coral']}; }}
.om-domain:nth-child(4) .om-domain-icon {{ background:{p['deep_blue']}; }}
.om-domain strong {{ display:block; font-size:.82rem; color:{p['text']}; }}
.om-domain small {{ display:block; margin-top:.08rem; font-size:.7rem; color:{p['text_dim']}; }}

/* Section headers */
.om-section {{
  display:flex; align-items:center; gap:.8rem; margin:1.85rem 0 .9rem; padding-left:.15rem;
}}
.om-section::before {{ content:""; width:4px; height:22px; border-radius:4px; background:linear-gradient(180deg,{p['accent']},{p['accent_2']}); }}
.om-section h3 {{ margin:0; font-size:1.08rem; font-weight:760; color:{p['navy']}; }}
.om-section span {{ font-size:.8rem; color:{p['text_dim']}; }}

/* Platform cards */
.om-card {{
  --tone:{p['accent']}; position:relative; overflow:hidden; height:100%;
  background:linear-gradient(180deg,#FFFFFF 0%,#FAFCFD 100%);
  border:1px solid {p['border']}; border-radius:17px; padding:1.12rem 1.2rem 1.08rem;
  box-shadow:0 8px 24px rgba(8,47,62,.045);
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}}
.om-card::before {{ content:""; position:absolute; left:0; top:0; right:0; height:3px; background:var(--tone); opacity:.95; }}
.om-card:hover {{ transform:translateY(-2px); border-color:#BFD8DE; box-shadow:0 13px 32px rgba(8,47,62,.085); }}
.om-card.tone-ocean {{ --tone:#1677A6; }} .om-card.tone-aqua {{ --tone:#65C3C8; }}
.om-card.tone-navy {{ --tone:#0E6075; }} .om-card.tone-health {{ --tone:#2A9B87; }}
.om-card.tone-bio {{ --tone:#218C7A; }} .om-card.tone-fish {{ --tone:#D9785F; }}
.om-card.tone-ai {{ --tone:#536F8A; }} .om-card.tone-alert {{ --tone:#C48A36; }}
.om-card-top {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:.78rem; }}
.om-card-label {{ font-size:.68rem; font-weight:760; letter-spacing:.095em; text-transform:uppercase; color:{p['text_muted']}; }}
.om-card-icon {{ width:30px; height:30px; display:flex; align-items:center; justify-content:center; border-radius:9px; background:color-mix(in srgb, var(--tone) 10%, white); font-size:.95rem; }}
.om-card-value {{ color:{p['navy']}; font-size:1.72rem; line-height:1.05; font-weight:760; letter-spacing:-.035em; }}
.om-card-value.om-muted {{ color:#71858D; font-weight:650; }}
.om-card-sub {{ margin-top:.5rem; font-size:.76rem; line-height:1.45; color:{p['text_muted']}; }}
.om-chip {{ display:inline-flex; margin-left:.32rem; padding:.16rem .46rem; font-size:.56rem; font-weight:760; letter-spacing:.07em; text-transform:uppercase; border-radius:999px; vertical-align:middle; }}
.om-chip-live {{ color:#126D58; background:#E6F4EF; border:1px solid #C7E6DA; }}
.om-chip-demo {{ color:#76549D; background:#F1EBF8; border:1px solid #DED0EE; }}
.om-card-demo {{ border-style:dashed; }}

/* Query focus panel */
.om-query-intro {{
  position:relative; overflow:hidden; margin:.25rem 0 1rem; padding:1.25rem 1.35rem;
  background:linear-gradient(125deg,#E8F5F6 0%,#F6FBFB 58%,#EEF5F8 100%);
  border:1px solid #CFE4E8; border-radius:18px;
}}
.om-query-intro::after {{ content:"ASK  •  ANALYZE  •  VERIFY"; position:absolute; right:1.2rem; top:1.2rem; font-size:.59rem; letter-spacing:.16em; font-weight:800; color:#82A0A9; }}
.om-query-intro h4 {{ margin:0; font-size:1.18rem; color:{p['navy']}; }}
.om-query-intro p {{ margin:.35rem 0 .75rem; max-width:760px; font-size:.82rem; color:{p['text_muted']}; }}
.om-query-chips {{ display:flex; gap:.45rem; flex-wrap:wrap; }}
.om-query-chips span {{ padding:.28rem .55rem; border-radius:999px; font-size:.65rem; font-weight:650; color:{p['deep_blue']}; background:#fff; border:1px solid #D6E7EA; }}

/* Status */
.om-pill {{ display:inline-flex; align-items:center; gap:.46rem; width:100%; padding:.48rem .72rem; border-radius:10px; font-size:.77rem; font-weight:600; }}
.om-pill-ok {{ color:#126D58; background:#EAF6F2; border:1px solid #CAE7DD; }}
.om-pill-err {{ color:#A53E3E; background:#FBEEEE; border:1px solid #F0CCCC; }}
.om-pill-warn {{ color:#986313; background:#FBF5E8; border:1px solid #EEDFB9; }}
.om-dot {{ width:7px; height:7px; border-radius:50%; background:currentColor; }}

/* Sidebar */
[data-testid="stSidebar"] {{ background:linear-gradient(180deg,#F8FBFC 0%,#EDF5F7 100%); border-right:1px solid #D5E4E8; }}
[data-testid="stSidebar"] .block-container {{ padding-top:1rem; }}
.om-brand {{
  position:relative; display:flex; align-items:center; gap:.72rem; padding:1rem .9rem; margin:0 0 1rem;
  border-radius:16px; background:linear-gradient(145deg,{p['navy']},#0C566A); box-shadow:0 10px 28px rgba(8,47,62,.13);
}}
/* Keep the sidebar brand crisp; remove the clipped decorative ring that looked like a stray "C". */
.om-brand::after {{ content:none; display:none; }}
.om-brand-mark {{ width:38px; height:38px; border-radius:11px; display:flex; align-items:center; justify-content:center; color:#fff; background:linear-gradient(145deg,#1D8FB0,#43B9B0); font-size:1rem; box-shadow:inset 0 0 0 1px rgba(255,255,255,.18); }}
.om-brand-text strong {{ display:block; color:#fff; font-size:.96rem; }}
.om-brand-text small {{ color:#B9D6DE; font-size:.68rem; }}
.om-navlabel {{ margin:1.05rem 0 .48rem; font-size:.61rem; font-weight:780; letter-spacing:.13em; text-transform:uppercase; color:#7A929B; }}
[data-testid="stSidebar"] p,[data-testid="stSidebar"] span,[data-testid="stSidebar"] label {{ color:{p['text']} !important; }}
[data-testid="stSidebar"] .stButton > button {{
  min-height:2.42rem; border-radius:10px; border:1px solid #D2E1E5; background:rgba(255,255,255,.78); color:{p['text']};
  font-size:.77rem; font-weight:590; text-align:left; justify-content:flex-start; box-shadow:none;
}}
[data-testid="stSidebar"] .stButton > button:hover {{ background:#E4F2F4; border-color:#BBD8DE; color:{p['deep_blue']}; }}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
  color:#fff; border:none; justify-content:center; font-weight:680;
  background:linear-gradient(120deg,{p['deep_blue']},{p['accent']}); box-shadow:0 7px 17px rgba(14,96,117,.16);
}}
[data-testid="stSidebar"] [data-testid="stExpander"] {{ background:rgba(255,255,255,.62); }}

/* Native metrics */
[data-testid="stMetric"] {{ background:#fff; border:1px solid {p['border']}; border-radius:13px; padding:.78rem .92rem; box-shadow:0 4px 16px rgba(8,47,62,.035); }}
[data-testid="stMetricLabel"] p {{ font-size:.66rem !important; letter-spacing:.075em; text-transform:uppercase; color:{p['text_dim']} !important; font-weight:700; }}
[data-testid="stMetricValue"] {{ font-size:1.35rem !important; font-weight:720; color:{p['navy']}; }}

/* Chat and bottom query */
[data-testid="stChatMessage"] {{ background:#fff; border:1px solid {p['border']}; border-radius:16px; padding:1rem 1.15rem; margin-bottom:.8rem; box-shadow:0 5px 18px rgba(8,47,62,.035); }}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {{ line-height:1.62; }}
[data-testid="stBottomBlockContainer"] {{ background:linear-gradient(180deg,rgba(242,247,249,0) 0%,rgba(242,247,249,.95) 28%,{p['bg']} 52%); padding-top:1.2rem; }}
[data-testid="stChatInput"] {{ border-radius:17px !important; border:1px solid #BBD8DE !important; background:#fff !important; box-shadow:0 10px 34px rgba(8,47,62,.11) !important; }}
[data-testid="stChatInput"]:focus-within {{ border-color:{p['accent']} !important; box-shadow:0 0 0 3px rgba(22,119,166,.09),0 12px 36px rgba(8,47,62,.12) !important; }}
[data-testid="stChatInput"] textarea {{ font-size:.93rem; color:{p['text']} !important; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ gap:.32rem; background:#EEF5F7; border:1px solid #D7E5E9; padding:.28rem; border-radius:12px; }}
.stTabs [data-baseweb="tab"] {{ background:transparent; border:none; border-radius:9px; padding:.52rem .92rem; color:{p['text_muted']}; font-size:.8rem; font-weight:600; }}
.stTabs [aria-selected="true"] {{ color:{p['deep_blue']} !important; background:#fff !important; box-shadow:0 2px 8px rgba(8,47,62,.07); }}

/* Inputs, expanders, tables */
[data-testid="stExpander"] {{ background:#fff; border:1px solid {p['border']}; border-radius:12px; }}
[data-testid="stExpander"] summary {{ font-size:.82rem; font-weight:620; color:{p['text']}; }}
[data-testid="stDataFrame"] {{ border:1px solid {p['border']}; border-radius:11px; overflow:hidden; }}
.stSelectbox div[data-baseweb="select"] > div,
.stTextInput div[data-baseweb="input"] > div,
.stNumberInput div[data-baseweb="input"] > div {{ background:#fff; border-color:{p['border']}; border-radius:10px; }}
.stDownloadButton > button {{ background:#F7FAFB; color:{p['deep_blue']}; border:1px solid #CFE0E4; border-radius:10px; font-size:.8rem; font-weight:620; }}
.stDownloadButton > button:hover {{ background:#EAF5F6; border-color:#AFCFD6; color:{p['navy']}; }}

/* Alerts/info */
[data-testid="stAlert"] {{ border-radius:12px; border-width:1px; }}

/* Empty states */
.om-empty {{
  position:relative; overflow:hidden; text-align:center; padding:2.35rem 1.5rem;
  border:1px dashed #BDD7DD; border-radius:18px;
  background:
    radial-gradient(390px 160px at 50% 110%,rgba(101,195,200,.15),transparent 70%),
    linear-gradient(180deg,#F8FCFD 0%,#EEF6F7 100%);
}}
.om-empty::after {{ content:""; position:absolute; inset:0; pointer-events:none; opacity:.22; background-image:repeating-radial-gradient(ellipse at 85% 125%,transparent 0 19px,rgba(22,119,166,.14) 20px 21px); }}
.om-empty > * {{ position:relative; z-index:1; }}
.om-empty-icon {{ width:50px; height:50px; margin:0 auto .75rem; display:flex; align-items:center; justify-content:center; border-radius:15px; background:#DDF0F2; font-size:1.5rem; }}
.om-empty h4 {{ margin:0 0 .38rem; font-size:1rem; color:{p['navy']}; }}
.om-empty p {{ margin:0 auto; max-width:620px; color:{p['text_muted']}; font-size:.82rem; line-height:1.5; }}

.om-tips {{ background:#EDF7F8; border:1px solid #CFE4E8; border-left:3px solid {p['accent']}; border-radius:12px; padding:1rem 1.2rem; margin-top:.7rem; }}
.om-tips h4 {{ margin:0 0 .45rem; font-size:.9rem; color:{p['deep_blue']}; }}
.om-tips li {{ font-size:.81rem; color:{p['text_muted']}; margin-bottom:.25rem; }}

/* Footer */
.om-footer {{ margin-top:2.7rem; padding:1.45rem 0 .5rem; border-top:1px solid {p['border']}; text-align:center; }}
.om-footer strong {{ display:block; font-size:.9rem; color:{p['navy']}; }}
.om-footer span {{ display:block; margin-top:.25rem; font-size:.72rem; color:{p['text_dim']}; }}

@keyframes omFade {{ from {{opacity:0;transform:translateY(6px)}} to {{opacity:1;transform:none}} }}
.om-hero,.om-card,.om-empty,.om-domain {{ animation:omFade .32s ease both; }}
@media (prefers-reduced-motion:reduce) {{ .om-hero,.om-card,.om-empty,.om-domain{{animation:none}} .om-card:hover{{transform:none}} }}
@media (max-width:900px) {{
  .block-container {{ padding-left:1rem; padding-right:1rem; }}
  .om-hero {{ padding:1.55rem 1.35rem; min-height:150px; }}
  .om-hero h1 {{ font-size:2.25rem; }}
  .om-hero::before {{ inset:0 0 0 32%; opacity:.24; }}
  .om-domain-strip {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
  .om-query-intro::after {{ display:none; }}
}}
@media (max-width:560px) {{
  .om-domain-strip {{ grid-template-columns:1fr; }}
  .om-section {{ align-items:flex-start; flex-wrap:wrap; gap:.45rem; }}
}}
</style>
"""


def hero(title=None, subtitle=None, eyebrow="Smart India Hackathon 2026"):
    return f"""
<div class="om-hero">
  <div class="om-hero-eyebrow">{eyebrow}</div>
  <h1>{title or BRAND['name']}</h1>
  <p>{subtitle or BRAND['tagline']}</p>
</div>
"""


def domain_strip():
    return """
<div class="om-domain-strip">
  <div class="om-domain"><div class="om-domain-icon">A</div><div><strong>Oceanography</strong><small>ARGO observations</small></div></div>
  <div class="om-domain"><div class="om-domain-icon">O</div><div><strong>Biodiversity</strong><small>OBIS occurrences</small></div></div>
  <div class="om-domain"><div class="om-domain-icon">F</div><div><strong>Fisheries</strong><small>ICAR-CMFRI domain</small></div></div>
  <div class="om-domain"><div class="om-domain-icon">AI</div><div><strong>Cross-domain Intelligence</strong><small>Natural-language analysis</small></div></div>
</div>
"""


def query_intro():
    return """
<div class="om-query-intro">
  <h4>Ask OceanMind</h4>
  <p>Explore oceanographic, biodiversity and fisheries evidence in plain language. The existing engine selects data, validates SQL and grounds the response in source observations.</p>
  <div class="om-query-chips"><span>Ocean conditions</span><span>Species occurrence</span><span>Fisheries</span><span>Cross-domain</span></div>
</div>
"""


def _tone_for_label(label):
    l = (label or "").lower()
    if "temperature" in l: return "tone-ocean"
    if "salinity" in l: return "tone-aqua"
    if "float" in l: return "tone-navy"
    if "health" in l: return "tone-health"
    if "biodiversity" in l: return "tone-bio"
    if "fisher" in l: return "tone-fish"
    if "ai" in l: return "tone-ai"
    if "alert" in l: return "tone-alert"
    return "tone-ocean"


def metric_card(label, value, sub="", icon="", demo=False, muted=False):
    """Presentation-only KPI card. Data values are supplied unchanged by dashboard.py."""
    l = (label or "").lower()
    if demo:
        chip_text, chip_cls = "Demo", "om-chip-demo"
    elif "ai status" in l:
        chip_text, chip_cls = "Local", "om-chip-live"
    elif "biodiversity" in l:
        chip_text, chip_cls = "Source", "om-chip-live"
    elif "fisher" in l:
        chip_text, chip_cls = "Dataset", "om-chip-live"
    else:
        chip_text, chip_cls = "Observed", "om-chip-live"
    chip = f'<span class="om-chip {chip_cls}">{chip_text}</span>'
    tone = _tone_for_label(label)
    return f"""
<div class="om-card {tone} {'om-card-demo' if demo else ''}">
  <div class="om-card-top"><span class="om-card-label">{label}</span><span class="om-card-icon">{icon}</span></div>
  <div class="om-card-value {'om-muted' if muted else ''}">{value}</div>
  <div class="om-card-sub">{sub} {chip}</div>
</div>
"""


def section_header(title, note=""):
    return f'<div class="om-section"><h3>{title}</h3><span>{note}</span></div>'


def status_pill(text, state="ok"):
    cls = {"ok":"om-pill-ok","error":"om-pill-err","warn":"om-pill-warn"}.get(state,"om-pill-ok")
    return f'<div class="om-pill {cls}"><span class="om-dot"></span>{text}</div>'


def sidebar_brand():
    return f"""
<div class="om-brand">
  <div class="om-brand-mark">{BRAND['icon']}</div>
  <div class="om-brand-text"><strong>{BRAND['name']}</strong><small>Unified Marine Intelligence</small></div>
</div>
"""


def nav_label(text):
    return f'<div class="om-navlabel">{text}</div>'


def empty_state(icon, title, body):
    return f"""
<div class="om-empty"><div class="om-empty-icon">{icon}</div><h4>{title}</h4><p>{body}</p></div>
"""


def footer():
    return f"""
<div class="om-footer"><strong>{BRAND['name']}</strong><span>{BRAND['event']}</span><span>{BRAND['footer_line']}</span></div>
"""


def style_figure(fig, height=None):
    """Apply the light scientific chart theme. Never changes underlying data."""
    p = PALETTE
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FBFDFE",
        font=dict(family=FONT_STACK,color=p["text_muted"],size=12),
        title_font=dict(size=15,color=p["navy"],family=FONT_STACK), title_x=.01,
        margin=dict(l=10,r=10,t=52,b=10),
        legend=dict(bgcolor="rgba(255,255,255,.94)",bordercolor=p["border"],borderwidth=1,font=dict(size=11,color=p["text_muted"])),
        hoverlabel=dict(bgcolor="#FFFFFF",bordercolor=p["accent"],font=dict(family=FONT_STACK,color=p["text"],size=12)),
    )
    fig.update_xaxes(gridcolor="#E7EFF2",zerolinecolor="#DCE7EA",linecolor=p["border"],tickfont=dict(color=p["text_dim"],size=11),title_font=dict(color=p["text_muted"],size=12))
    fig.update_yaxes(gridcolor="#E7EFF2",zerolinecolor="#DCE7EA",linecolor=p["border"],tickfont=dict(color=p["text_dim"],size=11),title_font=dict(color=p["text_muted"],size=12))
    if height: fig.update_layout(height=height)
    return fig
