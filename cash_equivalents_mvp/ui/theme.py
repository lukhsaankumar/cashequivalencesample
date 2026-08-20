"""IG Wealth Management visual identity: palette + logo, matching the branding used in the
Cash and Cash Equivalents report workbook/PDF (navy wordmark, light-blue parallelogram mark).
Recreated as inline SVG since no logo asset file was supplied — this is the same organization's
own internal tool, styled to match its own existing report materials.
"""
from __future__ import annotations

# --- Palette, sampled from the report PDF / IG brand mark ---
NAVY = "#0F1B4C"
NAVY_DEEP = "#0A1338"
BLUE_LIGHT = "#8FD0EC"
BLUE_MID = "#3E9BD6"
BG = "#F5F7FB"
SURFACE = "#FFFFFF"
BORDER = "#E2E7F0"
MUTED = "#5B6478"
SUCCESS = "#1E8E5A"
SUCCESS_BG = "#E7F5EE"
WARNING = "#B8790E"
WARNING_BG = "#FBF1DF"
DANGER = "#C0392B"
DANGER_BG = "#FCEAE8"
INFO = "#3E7BD6"
INFO_BG = "#EAF1FC"

IG_LOGO_SVG = """
<svg width="220" height="62" viewBox="0 0 620 175" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="IG Wealth Management">
  <polygon points="120,8 300,8 195,167 15,167" fill="#8FD0EC"/>
  <rect x="46" y="38" width="46" height="128" fill="#0F1B4C"/>
  <path d="M170 38
           C122 38 92 72 92 104
           C92 138 124 168 172 168
           C204 168 226 156 238 138
           L238 96
           L166 96
           L166 122
           L196 122
           L196 128
           C188 138 178 142 168 142
           C144 142 128 126 128 103
           C128 80 144 64 170 64
           C186 64 198 70 208 82
           L232 60
           C216 44 196 38 170 38 Z" fill="#0F1B4C"/>
  <rect x="150" y="94" width="34" height="30" fill="#3E9BD6"/>
  <text x="322" y="78" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="54" letter-spacing="2" fill="#0F1B4C">WEALTH</text>
  <text x="322" y="140" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="54" letter-spacing="1" fill="#0F1B4C">MANAGEMENT</text>
</svg>
"""


def inject_global_css() -> str:
    return f"""
<style>
:root {{
    --ig-navy: {NAVY};
    --ig-navy-deep: {NAVY_DEEP};
    --ig-blue-light: {BLUE_LIGHT};
    --ig-blue-mid: {BLUE_MID};
    --ig-bg: {BG};
    --ig-surface: {SURFACE};
    --ig-border: {BORDER};
    --ig-muted: {MUTED};
}}

.stApp {{
    background: var(--ig-bg);
}}
[data-testid="stSidebar"] {{
    background: var(--ig-navy-deep);
    border-right: 1px solid var(--ig-border);
}}
[data-testid="stSidebar"] * {{
    color: #E8ECF7 !important;
}}
[data-testid="stSidebar"] .ig-sidebar-title {{
    color: #FFFFFF !important;
    font-weight: 700;
    letter-spacing: 0.02em;
}}
[data-testid="stSidebarNav"] {{
    display: none;
}}

h1, h2, h3 {{
    color: var(--ig-navy) !important;
    font-family: Arial, Helvetica, sans-serif;
}}
p, li, label, span {{
    font-family: Arial, Helvetica, sans-serif;
}}

.ig-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 28px;
    background: var(--ig-surface);
    border-bottom: 3px solid var(--ig-blue-light);
    margin: -1rem -1rem 1.5rem -1rem;
}}
.ig-header-right {{
    text-align: right;
    color: var(--ig-muted);
    font-size: 0.85rem;
}}
.ig-page-title {{
    color: var(--ig-navy);
    font-size: 1.6rem;
    font-weight: 800;
    margin-bottom: 0.1rem;
}}
.ig-page-subtitle {{
    color: var(--ig-muted);
    font-size: 0.95rem;
    margin-bottom: 1.4rem;
}}

.ig-card {{
    background: var(--ig-surface);
    border: 1px solid var(--ig-border);
    border-radius: 10px;
    padding: 18px 20px;
    box-shadow: 0 1px 3px rgba(15,27,76,0.04);
    margin-bottom: 14px;
}}
.ig-card h4 {{
    margin: 0 0 10px 0;
    color: var(--ig-navy);
    font-size: 1.02rem;
    font-weight: 700;
}}

.ig-metric-row {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 1.2rem; }}
.ig-metric {{
    flex: 1 1 150px;
    background: var(--ig-surface);
    border: 1px solid var(--ig-border);
    border-left: 4px solid var(--ig-blue-mid);
    border-radius: 8px;
    padding: 14px 16px;
}}
.ig-metric .label {{ color: var(--ig-muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
.ig-metric .value {{ color: var(--ig-navy); font-size: 1.6rem; font-weight: 800; margin-top: 2px; }}

.ig-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.02em;
}}
.ig-badge-success {{ background: {SUCCESS_BG}; color: {SUCCESS}; }}
.ig-badge-warning {{ background: {WARNING_BG}; color: {WARNING}; }}
.ig-badge-danger  {{ background: {DANGER_BG}; color: {DANGER}; }}
.ig-badge-info    {{ background: {INFO_BG}; color: {INFO}; }}
.ig-badge-muted   {{ background: #EEF1F6; color: var(--ig-muted); }}

.ig-divider {{ border: none; border-top: 1px solid var(--ig-border); margin: 1.1rem 0; }}

div[data-testid="stButton"] > button {{
    background: var(--ig-navy);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-weight: 600;
    padding: 0.5rem 1.1rem;
}}
div[data-testid="stButton"] > button:hover {{
    background: var(--ig-blue-mid);
    color: #fff;
}}
div[data-testid="stDownloadButton"] > button {{
    background: #fff;
    color: var(--ig-navy);
    border: 1.5px solid var(--ig-navy);
    border-radius: 6px;
    font-weight: 600;
}}
div[data-testid="stDownloadButton"] > button:hover {{
    background: var(--ig-navy);
    color: #fff;
}}

[data-testid="stMetricValue"] {{ color: var(--ig-navy); }}
</style>
"""
