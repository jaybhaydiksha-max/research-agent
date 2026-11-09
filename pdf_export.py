"""Turn the agent's Markdown report into a clean, readable PDF (uses reportlab).

Supports headings, paragraphs, bullet and numbered lists (with nesting), simple tables,
bold/italic/inline code, clickable links and horizontal rules.
"""
import io
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Used only when no Unicode font is found on the machine (standard PDF fonts are Latin-1 only).
_LATIN1_FALLBACK = {
    "\u20b9": "Rs.",   # rupee sign
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u2022": "-", "\u00a0": " ", "\u2192": "->",
}

_FONT_CACHE: dict = {}


def _setup_fonts() -> tuple[str, str]:
    """Return (regular_font, bold_font). Prefers a Unicode TTF family so symbols like the rupee sign work."""
    if "fonts" in _FONT_CACHE:
        return _FONT_CACHE["fonts"]

    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        [os.path.join(windir, "Fonts", f) for f in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")],
        [f"/System/Library/Fonts/Supplemental/{f}" for f in ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf")],
        [f"/usr/share/fonts/truetype/dejavu/{f}" for f in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf")],
    ]
    fonts = ("Helvetica", "Helvetica-Bold")
    for paths in candidates:
        if not all(os.path.exists(p) for p in paths):
            continue
        try:
            names = ("ReportFont", "ReportFont-Bold", "ReportFont-Italic", "ReportFont-BoldItalic")
            for name, path in zip(names, paths):
                pdfmetrics.registerFont(TTFont(name, path))
            pdfmetrics.registerFontFamily(
                names[0], normal=names[0], bold=names[1], italic=names[2], boldItalic=names[3]
            )
            fonts = (names[0], names[1])
            break
        except Exception:
            continue
    _FONT_CACHE["fonts"] = fonts
    return fonts


def _styles(font: str, bold: str) -> dict:
    base = ParagraphStyle(
        "base", fontName=font, fontSize=10.5, leading=15.5,
        textColor=colors.HexColor("#222222"), alignment=TA_LEFT, spaceAfter=6,
    )
    return {
        "body": base,
        "h1": ParagraphStyle("h1", parent=base, fontName=bold, fontSize=21, leading=26,
                             textColor=colors.HexColor("#0f1b3d"), spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName=bold, fontSize=14.5, leading=19,
                             textColor=colors.HexColor("#1a3c8c"), spaceBefore=14, spaceAfter=6, keepWithNext=1),
        "h3": ParagraphStyle("h3", parent=base, fontName=bold, fontSize=12, leading=16,
                             spaceBefore=10, spaceAfter=4, keepWithNext=1),
        "sub": ParagraphStyle("sub", parent=base, fontSize=9, leading=12,
                              textColor=colors.HexColor("#777777"), spaceAfter=10),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9, leading=12, spaceAfter=0),
        "cellh": ParagraphStyle("cellh", parent=base, fontName=bold, fontSize=9, leading=12, spaceAfter=0),
    }


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)|(https?://[^\s<>\"]+)")


def _link_sub(m: re.Match) -> str:
    if m.group(2):
        return f'<a href="{m.group(2)}" color="#1a56db">{m.group(1)}</a>'
    url, trail = m.group(3), ""
    while url and url[-1] in ".,;:)]'":
        trail, url = url[-1] + trail, url[:-1]
    return f'<a href="{url}" color="#1a56db">{url}</a>{trail}'


def markdown_to_pdf(md_text: str, title: str = "Research Report", subtitle: str = "") -> bytes:
    """Convert Markdown text to PDF bytes."""
    font, bold = _setup_fonts()
    unicode_ok = font != "Helvetica"
    S = _styles(font, bold)

    def clean(text: str) -> str:
        if unicode_ok:
            return text
        for k, v in _LATIN1_FALLBACK.items():
            text = text.replace(k, v)
        return text.encode("latin-1", "replace").decode("latin-1")

    def inline(raw: str) -> str:
        t = escape(clean(raw))
        t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
        return _LINK.sub(_link_sub, t)

    def para(raw: str, style: ParagraphStyle, bullet: str | None = None) -> Paragraph:
        try:
            return Paragraph(inline(raw), style, bulletText=bullet)
        except Exception:  # malformed markup: fall back to plain text
            return Paragraph(escape(clean(raw)), style, bulletText=bullet)

    list_styles: dict = {}

    def list_style(level: int, numbered: bool) -> ParagraphStyle:
        key = (level, numbered)
        if key not in list_styles:
            indent = (20 if numbered else 16) + 14 * level
            list_styles[key] = ParagraphStyle(
                f"li{level}{numbered}", parent=S["body"], leftIndent=indent,
                bulletIndent=indent - 14, spaceAfter=3,
            )
        return list_styles[key]

    if not re.search(r"^#\s", md_text, re.M):
        md_text = f"# {title}\n\n{md_text}"

    avail = A4[0] - 40 * mm
    lines = md_text.replace("\r\n", "\n").split("\n")
    flow: list = []
    buf: list[str] = []
    sub_added = not subtitle
    i = 0

    def flush():
        if buf:
            flow.append(para(" ".join(buf), S["body"]))
            buf.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        s = line.strip()

        if not s:
            flush()
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", s)
        if m:
            flush()
            level = len(m.group(1))
            flow.append(para(m.group(2), S["h1"] if level == 1 else S["h2"] if level == 2 else S["h3"]))
            if level == 1 and not sub_added:
                flow.append(Paragraph(escape(clean(subtitle)), S["sub"]))
                sub_added = True
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush()
            flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc"),
                                   spaceBefore=6, spaceAfter=8))
            i += 1
            continue

        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) or c == "" for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                ncol = max(len(r) for r in rows)
                data = [
                    [para(c, S["cellh"] if r == 0 else S["cell"]) for c in row + [""] * (ncol - len(row))]
                    for r, row in enumerate(rows)
                ]
                table = Table(data, colWidths=[avail / ncol] * ncol, repeatRows=1)
                table.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9cfda")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2fb")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]))
                flow.extend([table, Spacer(1, 8)])
            continue

        m = re.match(r"^(\s*)[-*+\u2022]\s+(.*)$", line)
        if m:
            flush()
            level = min(len(m.group(1).expandtabs(4)) // 2, 3)
            flow.append(para(m.group(2), list_style(level, False), bullet="\u2022"))
            i += 1
            continue

        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if m:
            flush()
            level = min(len(m.group(1).expandtabs(4)) // 2, 3)
            flow.append(para(m.group(3), list_style(level, True), bullet=f"{m.group(2)}."))
            i += 1
            continue

        buf.append(s)
        i += 1
    flush()

    short_title = clean(title)[:90]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(20 * mm, 10 * mm, short_title)
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm, title=title, author="Research Agent",
    )
    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
