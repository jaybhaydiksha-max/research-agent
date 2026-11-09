"""Light / dark theme CSS and the trace table for the Streamlit app.

Mode "Auto" injects only neutral polish and lets Streamlit's own theme (system setting or the
Settings menu) decide the colors. "Light" and "Dark" override the main colors.
"""
import html
from string import Template

PALETTES = {
    "Light": dict(
        scheme="light", bg="#ffffff", side="#f4f6fa", text="#1f2430", muted="#5b6575",
        card="#f7f8fb", border="#dfe3ea", input="#ffffff", accent="#2f6fed", on_accent="#ffffff",
    ),
    "Dark": dict(
        scheme="dark", bg="#0e1117", side="#161b26", text="#e6e8ee", muted="#9aa4b2",
        card="#1a2030", border="#2b3447", input="#141a26", accent="#6ea8fe", on_accent="#0b1220",
    ),
}

# Neutral styling that works on top of any theme.
BASE_CSS = """
.block-container { padding-top: 2.2rem; max-width: 1100px; }
[data-testid="stMetric"] { border: 1px solid rgba(128,128,128,.28); border-radius: 12px; padding: 12px 16px; }
.trace-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.trace-table th, .trace-table td { border: 1px solid rgba(128,128,128,.28); padding: 6px 10px;
  text-align: left; vertical-align: top; word-break: break-word; }
.trace-table th { background: rgba(128,128,128,.12); }
.trace-table code { font-size: .8rem; }
"""

THEMED_CSS = Template("""
:root, .stApp { color-scheme: $scheme; }
.stApp, [data-testid="stAppViewContainer"] { background-color: $bg !important; color: $text !important; }
[data-testid="stHeader"] { background-color: $bg !important; }
[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child { background-color: $side !important; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp p, .stApp li,
.stApp label, .stApp span, .stApp summary, .stApp td, .stApp th { color: $text !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: $muted !important; }
[data-testid="stMetric"] { background-color: $card !important; border-color: $border !important; }
[data-testid="stMetricLabel"] * { color: $muted !important; }
.stApp hr { border-color: $border !important; }
.stApp a { color: $accent !important; }
.stApp input, .stApp textarea, [data-baseweb="input"], [data-baseweb="base-input"],
[data-baseweb="select"] > div { background-color: $input !important; color: $text !important; border-color: $border !important; }
.stApp input::placeholder { color: $muted !important; opacity: 1; }
div[data-baseweb="popover"] > div, ul[role="listbox"], [data-baseweb="menu"] { background-color: $card !important; }
li[role="option"], li[role="option"] * { color: $text !important; }
.stButton > button, .stDownloadButton > button { background-color: $card !important; color: $text !important; border: 1px solid $border !important; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: $accent !important; }
.stButton > button[kind="primary"], [data-testid="stBaseButton-primary"] { background-color: $accent !important; border-color: $accent !important; }
.stButton > button[kind="primary"] *, [data-testid="stBaseButton-primary"] * { color: $on_accent !important; }
button[data-baseweb="tab"] * { color: $muted !important; }
button[data-baseweb="tab"][aria-selected="true"] * { color: $accent !important; }
[data-testid="stExpander"], [data-testid="stStatus"], details { background-color: $card !important; border-color: $border !important; }
.trace-table th { background-color: $card !important; }
.trace-table th, .trace-table td { border-color: $border !important; }
code { background-color: $card !important; color: $text !important; }
""")


def get_css(mode: str) -> str:
    """Return a <style> block for the chosen mode: Auto, Light or Dark."""
    css = BASE_CSS
    if mode in PALETTES:
        css += THEMED_CSS.substitute(PALETTES[mode])
    return f"<style>{css}</style>"


def _cut(value, limit: int) -> str:
    text = " ".join(str(value or "").split())  # single line, so Markdown never breaks the HTML block
    return text if len(text) <= limit else text[:limit] + "…"


def trace_table_html(events: list[dict], limit: int = 180) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(str(e['step']))}</td>"
        f"<td><code>{html.escape(str(e['tool']))}</code></td>"
        f"<td>{html.escape(_cut(e['args'], limit))}</td>"
        f"<td>{html.escape(_cut(e['result'], limit))}</td></tr>"
        for e in events
    )
    return (
        '<table class="trace-table"><thead><tr><th>Step</th><th>Tool</th>'
        f"<th>Arguments</th><th>Result (shortened)</th></tr></thead><tbody>{rows}</tbody></table>"
    )
