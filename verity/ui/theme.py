"""Design system: dark navy, electric violet, subtle cyan. One source of truth for colours and CSS."""

NAVY_900 = "#060A1C"
NAVY_800 = "#0A1030"
NAVY_700 = "#0F1738"
NAVY_600 = "#162049"
VIOLET = "#8B5CF6"
VIOLET_DEEP = "#6D28D9"
CYAN = "#22D3EE"
TEXT = "#E8EBFA"
MUTED = "#A3ADCB"

VERDICT_COLORS = {
    "VERIFIED": "#34D399",
    "INACCURATE": "#FBBF24",
    "FALSE": "#F87171",
    "INSUFFICIENT EVIDENCE": "#94A3B8",
}
NOT_CHECKED_COLOR = "#A5B4FC"
VERDICT_ICONS = {"VERIFIED": "✓", "INACCURATE": "!", "FALSE": "✕", "INSUFFICIENT EVIDENCE": "?"}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root {{
  --navy-900:{NAVY_900}; --navy-800:{NAVY_800}; --navy-700:{NAVY_700}; --navy-600:{NAVY_600};
  --violet:{VIOLET}; --violet-deep:{VIOLET_DEEP}; --cyan:{CYAN}; --text:{TEXT}; --muted:{MUTED};
  --ok:#34D399; --warn:#FBBF24; --bad:#F87171; --none:#94A3B8;
  --border: rgba(139,92,246,.22); --radius:16px;
}}
html, body, [data-testid="stAppViewContainer"], .stApp {{
  font-family:'Inter',system-ui,sans-serif; color:var(--text);
  background:
    radial-gradient(1100px 520px at 12% -10%, rgba(139,92,246,.20), transparent 60%),
    radial-gradient(900px 480px at 100% 0%, rgba(34,211,238,.10), transparent 60%),
    var(--navy-900) !important;
}}
[data-testid="stHeader"] {{ background:transparent; }}
#MainMenu, footer {{ visibility:hidden; }}
.block-container {{ padding-top:2.2rem; max-width:1180px; }}
h1,h2,h3,h4 {{ font-family:'Space Grotesk','Inter',sans-serif; letter-spacing:-.02em; color:var(--text); }}
a {{ color:var(--cyan); }} a:hover {{ color:#67E8F9; }}
:focus-visible {{ outline:2px solid var(--cyan) !important; outline-offset:2px; }}

/* sidebar */
[data-testid="stSidebar"] {{ background:linear-gradient(180deg,var(--navy-800),var(--navy-900)); border-right:1px solid var(--border); }}
.brand {{ display:flex; align-items:center; gap:.65rem; padding:.2rem 0 1rem; }}
.brand-mark {{ width:38px; height:38px; border-radius:11px; display:grid; place-items:center; font-weight:700; color:#fff;
  background:linear-gradient(135deg,var(--violet),var(--cyan)); box-shadow:0 6px 24px rgba(139,92,246,.45); font-family:'Space Grotesk',system-ui,sans-serif; }}
.brand-name {{ font-family:'Space Grotesk',system-ui,sans-serif; font-weight:700; font-size:1.2rem; line-height:1.1; }}
.brand-tag {{ font-size:.72rem; color:var(--muted); letter-spacing:.04em; }}
.keystat {{ display:flex; align-items:center; gap:.5rem; font-size:.82rem; color:var(--muted); padding:.15rem 0; }}
.dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
.dot.on {{ background:var(--ok); box-shadow:0 0 8px var(--ok); }} .dot.off {{ background:var(--bad); }}

.hero-compact {{ padding:.6rem 0 .9rem; font-size:1.05rem; color:var(--text); border-bottom:1px solid var(--border); margin-bottom:1rem; }}
/* hero */
.hero {{ position:relative; overflow:hidden; border:1px solid var(--border); border-radius:24px; padding:3rem 2.4rem 2.6rem;
  background:linear-gradient(135deg,rgba(22,32,73,.85),rgba(10,16,48,.9)); margin-bottom:1.6rem; }}
.hero::before, .hero::after {{ content:""; position:absolute; border-radius:50%; filter:blur(70px); opacity:.55; pointer-events:none; }}
.hero::before {{ width:380px; height:380px; background:var(--violet); top:-160px; right:-80px; animation:float 14s ease-in-out infinite; }}
.hero::after {{ width:300px; height:300px; background:var(--cyan); opacity:.22; bottom:-170px; left:20%; animation:float 18s ease-in-out infinite reverse; }}
.hero > * {{ position:relative; z-index:1; }}
.eyebrow {{ display:inline-flex; gap:.5rem; align-items:center; font-size:.78rem; font-weight:600; letter-spacing:.08em; text-transform:uppercase;
  color:var(--cyan); background:rgba(34,211,238,.08); border:1px solid rgba(34,211,238,.28); padding:.32rem .75rem; border-radius:999px; }}
.hero h1 {{ font-size:clamp(2rem,4.2vw,3.2rem); line-height:1.08; margin:1rem 0 .8rem; font-weight:700; max-width:22ch; }}
.grad {{ background:linear-gradient(90deg,#C4B5FD,var(--violet) 40%,var(--cyan)); -webkit-background-clip:text; background-clip:text; color:transparent; }}
.hero p {{ color:var(--muted); font-size:1.05rem; max-width:60ch; line-height:1.6; margin:0 0 1.2rem; }}
.pills {{ display:flex; flex-wrap:wrap; gap:.55rem; }}
.pill {{ font-size:.82rem; padding:.38rem .8rem; border-radius:999px; background:rgba(139,92,246,.12); border:1px solid var(--border); color:#D8CCFF; }}
@keyframes float {{ 0%,100% {{ transform:translate(0,0); }} 50% {{ transform:translate(-30px,24px); }} }}
@keyframes rise {{ from {{ opacity:0; transform:translateY(10px); }} to {{ opacity:1; transform:none; }} }}
@keyframes grow {{ from {{ width:0; }} }}

.steps {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; margin:.4rem 0 1.4rem; }}
.step {{ background:var(--navy-700); border:1px solid var(--border); border-radius:var(--radius); padding:1.1rem 1.2rem; transition:transform .2s, border-color .2s; }}
.step:hover {{ transform:translateY(-3px); border-color:rgba(139,92,246,.55); }}
.step-n {{ font-family:'Space Grotesk',system-ui,sans-serif; color:var(--cyan); font-weight:700; font-size:.85rem; letter-spacing:.1em; }}
.step h4 {{ margin:.35rem 0 .3rem; font-size:1.05rem; }} .step p {{ margin:0; color:var(--muted); font-size:.9rem; line-height:1.5; }}

/* upload + buttons */
[data-testid="stFileUploaderDropzone"] {{ background:rgba(15,23,56,.7); border:1.5px dashed rgba(139,92,246,.55); border-radius:var(--radius); padding:1.6rem; transition:all .2s; }}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color:var(--cyan); background:rgba(139,92,246,.10); box-shadow:0 0 0 4px rgba(34,211,238,.08); }}
.stButton > button, .stDownloadButton > button {{ border-radius:12px; font-weight:600; border:1px solid var(--border); background:var(--navy-600); color:var(--text); transition:all .18s; min-height:2.8rem; }}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color:var(--violet); transform:translateY(-1px); }}
.stButton > button[kind="primary"] {{ background:linear-gradient(135deg,var(--violet-deep),var(--violet) 55%,#22A6EE); border:none; color:#fff; box-shadow:0 8px 26px rgba(139,92,246,.4); }}
.stButton > button[kind="primary"]:hover {{ box-shadow:0 10px 32px rgba(139,92,246,.6); }}
.stButton > button:disabled {{ opacity:.45; }}

/* metrics */
.metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(125px,1fr)); gap:.8rem; margin:.4rem 0 1rem; }}
.metric {{ background:var(--navy-700); border:1px solid var(--border); border-radius:var(--radius); padding:1rem 1.1rem; animation:rise .5s both; }}
.metric .k {{ font-size:.74rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); }}
.metric .v {{ font-family:'Space Grotesk',system-ui,sans-serif; font-size:2rem; font-weight:700; line-height:1.15; }}
.metric.nc .v {{ color:#A5B4FC; }} .metric.ok .v {{ color:var(--ok); }} .metric.warn .v {{ color:var(--warn); }} .metric.bad .v {{ color:var(--bad); }} .metric.none .v {{ color:var(--none); }}

/* verdict cards */
.vc {{ position:relative; background:linear-gradient(180deg,rgba(22,32,73,.78),rgba(15,23,56,.92)); border:1px solid var(--border);
  border-left:5px solid var(--accent); border-radius:var(--radius); padding:1.1rem 1.3rem 1rem; margin:.9rem 0 .2rem; animation:rise .45s both; transition:box-shadow .2s, transform .2s; }}
.vc:hover {{ box-shadow:0 10px 34px rgba(0,0,0,.35), 0 0 0 1px var(--accent); transform:translateY(-1px); }}
.vc-head {{ display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; margin-bottom:.6rem; }}
.badge {{ display:inline-flex; align-items:center; gap:.4rem; font-weight:700; font-size:.78rem; letter-spacing:.06em; text-transform:uppercase;
  color:var(--accent); background:color-mix(in srgb, var(--accent) 14%, transparent); border:1px solid color-mix(in srgb, var(--accent) 55%, transparent); padding:.28rem .7rem; border-radius:999px; }}
.chip {{ font-size:.74rem; color:var(--muted); background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.09); padding:.22rem .6rem; border-radius:999px; }}
.chip.flag {{ color:#FDE68A; border-color:rgba(251,191,36,.4); background:rgba(251,191,36,.08); }}
.vc-id {{ margin-left:auto; font-family:'Space Grotesk',system-ui,sans-serif; color:var(--muted); font-size:.8rem; }}
.vc-claim {{ font-size:1.06rem; line-height:1.5; font-weight:500; margin:.1rem 0 .55rem; }}
.vc-quote {{ font-size:.84rem; color:var(--muted); border-left:2px solid rgba(255,255,255,.12); padding-left:.7rem; margin:.2rem 0 .7rem; font-style:italic; }}
.vc-correct {{ background:rgba(52,211,153,.07); border:1px solid rgba(52,211,153,.32); border-radius:12px; padding:.7rem .9rem; margin:.5rem 0; }}
.vc-correct .lab {{ font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; color:var(--ok); font-weight:700; }}
.vc-expl {{ color:#CBD2EA; font-size:.93rem; line-height:1.55; margin:.4rem 0 .8rem; }}
.meter-row {{ display:flex; flex-wrap:wrap; gap:1rem; align-items:center; }}
.meter {{ flex:1 1 220px; }} .meter .lab {{ display:flex; justify-content:space-between; font-size:.76rem; color:var(--muted); margin-bottom:.25rem; }}
.meter .track {{ height:8px; border-radius:99px; background:rgba(255,255,255,.08); overflow:hidden; }}
.meter .fill {{ height:100%; border-radius:99px; background:linear-gradient(90deg,var(--violet),var(--cyan)); animation:grow .9s both; }}
.src {{ background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.07); border-radius:12px; padding:.65rem .85rem; margin:.45rem 0; }}
.src .t {{ font-weight:600; font-size:.92rem; }} .src .d {{ color:var(--muted); font-size:.78rem; }}
.src .q {{ color:#CBD2EA; font-size:.84rem; margin-top:.3rem; }} .src .nq {{ color:var(--muted); font-size:.76rem; font-style:italic; }}
.stance {{ font-size:.68rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; padding:.1rem .45rem; border-radius:6px; margin-right:.4rem; }}
.stance.supports {{ background:rgba(52,211,153,.15); color:var(--ok); }} .stance.contradicts {{ background:rgba(248,113,113,.15); color:var(--bad); }}
.stance.updates {{ background:rgba(251,191,36,.15); color:var(--warn); }} .stance.neutral {{ background:rgba(148,163,184,.15); color:var(--none); }}
.notice {{ border:1px solid rgba(251,191,36,.35); background:rgba(251,191,36,.07); color:#FDE68A; border-radius:12px; padding:.7rem 1rem; margin:.4rem 0; font-size:.9rem; }}
.setup {{ border:1px solid rgba(248,113,113,.4); background:rgba(248,113,113,.07); border-radius:var(--radius); padding:1rem 1.2rem; }}
.empty {{ text-align:center; color:var(--muted); border:1px dashed var(--border); border-radius:var(--radius); padding:2.4rem 1rem; }}
.section-title {{ display:flex; align-items:center; gap:.6rem; margin:1.6rem 0 .4rem; }}
.section-title h3 {{ margin:0; }} .section-title::after {{ content:""; flex:1; height:1px; background:linear-gradient(90deg,var(--border),transparent); }}
[data-testid="stExpander"] {{ background:rgba(15,23,56,.5); border:1px solid var(--border); border-radius:12px; }}
[data-testid="stExpander"] summary {{ font-size:.9rem; }}
.stTabs [data-baseweb="tab"] {{ font-weight:600; }}
@media (max-width:720px) {{ .hero {{ padding:1.8rem 1.2rem; border-radius:18px; }} .block-container {{ padding-left:1rem; padding-right:1rem; }} .vc {{ padding:.95rem; }} }}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ animation:none !important; transition:none !important; }} }}
/* ===== Readability fixes: grey -> white, new upload button, white header icons ===== */

/* 1. All grey / muted text -> white */
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] small,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] [role="radiogroup"] label p,
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
[data-testid="stFileUploader"] label,
[data-testid="stFileUploader"] small,
[data-testid="stFileUploaderDropzoneInstructions"] span,
[data-testid="stFileUploaderDropzoneInstructions"] small,
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
.stCaption, small {{ color:#FFFFFF !important; opacity:1 !important; }}

/* sidebar title, tagline and version text */
[data-testid="stSidebar"] .brand-name,
[data-testid="stSidebar"] .brand-sub,
[data-testid="stSidebar"] div {{ color:#FFFFFF; }}

/* help (?) icons next to widget labels */
[data-testid="stTooltipIcon"] svg,
[data-testid="stSidebar"] svg {{ color:#FFFFFF !important; fill:#FFFFFF !important; opacity:1 !important; }}

/* 2. Upload button: violet -> cyan gradient with dark text (was white-on-white) */
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploader"] button {{
  background:linear-gradient(135deg,#8B5CF6,#22D3EE) !important;
  color:#FFFFFF !important; border:0 !important; font-weight:700 !important;
  box-shadow:0 6px 18px rgba(34,211,238,.35) !important;
}}
[data-testid="stFileUploaderDropzone"] button *,
[data-testid="stFileUploader"] button * {{ color:#FFFFFF !important; fill:#FFFFFF !important; }}
[data-testid="stFileUploaderDropzone"] button:hover {{ filter:brightness(1.12); transform:translateY(-1px); }}
[data-testid="stFileUploaderDropzone"] svg {{ color:#22D3EE !important; fill:#22D3EE !important; }}

/* 3. Top header icons (Share, star, edit, GitHub, menu) -> white */
[data-testid="stHeader"] button,
[data-testid="stHeader"] a,
[data-testid="stToolbar"] button,
[data-testid="stToolbar"] a,
[data-testid="stToolbar"] span,
[data-testid="stHeader"] svg,
[data-testid="stToolbar"] svg,
[data-testid="stExpandSidebarButton"] svg,
[data-testid="stSidebarCollapseButton"] svg {{ color:#FFFFFF !important; fill:#FFFFFF !important; opacity:1 !important; }}

/* 4. Model dropdown: dark box with white text instead of white box */
[data-baseweb="select"] > div {{ background:#141C3D !important; border:1px solid rgba(255,255,255,.25) !important; }}
[data-baseweb="select"] * {{ color:#FFFFFF !important; fill:#FFFFFF !important; }}
</style>
"""
