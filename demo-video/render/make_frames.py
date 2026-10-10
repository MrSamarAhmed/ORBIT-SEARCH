"""Generate HTML frames for the ORBIT Search demo video.

All rendered content is genuine: real project files (pygments-highlighted),
the real pytest output, and simple typographic cards. No fabricated product
content. Frames are authored for a 1920x1080 viewport and rendered natively by
headless Chrome, so no upscaling is involved.
"""
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer
from pygments.lexers.shell import BashSessionLexer

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "html"
OUT.mkdir(exist_ok=True)

ACCENT = "#7aa2ff"
BG = "#0b0e14"
PANEL = "#11151f"
TEXT = "#e8eaf0"
MUTED = "#98a2b3"

STYLE = f"""
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: 1920px; height: 1080px; }}
    body {{
      background: {BG}; color: {TEXT}; overflow: hidden;
      font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
      padding: 56px 80px;
    }}
    body.centered {{
      display: flex; align-items: center; justify-content: center;
      padding: 56px 100px;
    }}
    .eyebrow {{
      color: {ACCENT}; font-size: 28px; font-weight: 700;
      letter-spacing: 6px; text-transform: uppercase; margin-bottom: 14px;
    }}
    h1 {{ font-size: 48px; font-weight: 700; margin-bottom: 28px; }}
    .code-wrap {{
      background: {PANEL}; border: 1px solid #232a38; border-radius: 18px;
      padding: 34px 0; overflow: hidden;
    }}
    pre {{
      font-family: 'SF Mono', Menlo, Consolas, monospace;
      font-size: 29px; line-height: 1.5;
    }}
    pre .linenos {{ color: #4a5468; padding-right: 26px; }}
    .linenetable {{ border-collapse: collapse; }}
    .linenetable td.linenos {{
      color: #4a5468; text-align: right; vertical-align: top;
      padding: 0 30px 0 34px; width: 1%; white-space: nowrap;
    }}
    .linenetable td.code {{ padding: 0; vertical-align: top; }}
    .linenetable td.code pre {{ padding: 0; margin: 0; white-space: pre; }}
    .tree {{
      font-family: 'SF Mono', Menlo, monospace;
      font-size: 27px; line-height: 1.62;
    }}
    .tree .dir {{ color: {ACCENT}; font-weight: 700; }}
    .tree .note {{ color: {MUTED}; }}
    .term {{
      background: {PANEL}; border: 1px solid #232a38; border-radius: 18px;
      font-family: 'SF Mono', Menlo, monospace; font-size: 33px; line-height: 1.6;
      width: 1720px;
    }}
    .term .bar {{
      padding: 20px 34px; border-bottom: 1px solid #232a38;
      color: {MUTED}; font-size: 27px;
    }}
    .term .dots {{ color: #4a5468; }}
    .term pre {{ padding: 30px 34px; white-space: pre-wrap; }}
    .term .pass {{ color: #4cc38a; font-weight: 700; }}
    .term .cmd {{ color: {ACCENT}; }}
    .term .cmd::before {{ content: '$ '; color: {MUTED}; }}
"""


def page(title: str, body: str, cls: str = "") -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{STYLE}</style></head>
<body class="{cls}">{body}</body></html>"""


def code_block(rel: str, start_line: int = 1) -> str:
    src_lines = (ROOT / rel).read_text(encoding="utf-8").splitlines(keepends=True)
    src = "".join(src_lines[start_line - 1 : start_line - 1 + 17])
    fmt = HtmlFormatter(
        style="monokai", linenos="table", linenostart=start_line, linenospecial=0
    )
    return highlight(src, PythonLexer(), fmt)


for name, rel in [
    ("main", "app/main.py"),
    ("search", "app/search.py"),
    ("research", "app/research.py"),
]:
    body = (
        f'<div class="eyebrow">app / {Path(rel).name}</div>'
        f"<h1>{rel}</h1>"
        f'<div class="code-wrap"><pre>{code_block(rel)}</pre></div>'
    )
    (OUT / f"code_{name}.html").write_text(page(name, body), encoding="utf-8")

# A window into the real degraded-mode handling further down research.py.
research_src = (ROOT / "app/research.py").read_text(encoding="utf-8").splitlines()
degraded_at = next(
    i + 1 for i, line in enumerate(research_src) if '"status": "degraded"' in line
) - 12
body = (
    '<div class="eyebrow">app / research.py</div>'
    f"<h1>app/research.py &middot; lines {degraded_at}&ndash;{degraded_at + 16}</h1>"
    f'<div class="code-wrap"><pre>{code_block("app/research.py", degraded_at)}</pre></div>'
)
(OUT / "code_research_degraded.html").write_text(page("research_degraded", body), encoding="utf-8")

tree_entries = [
    line
    for line in (Path(__file__).resolve().parents[1] / "assets" / "tree.txt")
    .read_text()
    .splitlines()
    if "__pycache__" not in line
]
tree_lines = []
for entry in tree_entries:
    head, sep, rest = entry.partition("/")
    if sep:
        tree_lines.append(f'<div><span class="dir">{head}/</span>{rest}</div>')
    else:
        tree_lines.append(f"<div>{entry}</div>")
tree_body = (
    '<div class="eyebrow">Repository layout</div>'
    "<h1>Standalone ORBIT Search project</h1>"
    f'<div class="tree">{"".join(tree_lines)}</div>'
    f'<p class="note" style="margin-top:26px;color:{MUTED};font-size:27px">'
    "FastAPI backend &middot; SerpApi search &middot; Gemini planning + synthesis "
    "&middot; vanilla-JS workspace</p>"
)
(OUT / "tree.html").write_text(page("tree", tree_body), encoding="utf-8")

pytest_full = (
    Path(__file__).resolve().parents[1] / "assets" / "pytest_output.txt"
).read_text()
# Keep the genuine progress line and summary; the deprecation notice block is
# omitted because it contains local absolute paths.
pytest_lines = [line for line in pytest_full.splitlines() if line.strip()]
display = "\n".join([pytest_lines[0], pytest_lines[-1]])
passed_line = "56 passed, 8 skipped, 1 warning in 0.11s"
pytest_html = highlight(display, BashSessionLexer(), HtmlFormatter(nowrap=True))
pytest_html = pytest_html.replace(passed_line, f'<span class="pass">{passed_line}</span>')
term_body = f"""
<div class="term">
  <div class="bar">orbit-search &mdash; zsh
    <span class="dots">&mdash; automated test suite (all upstream HTTP mocked)</span></div>
  <pre><span class="cmd">.venv/bin/python -m pytest -q tests/test_search.py tests/test_research.py tests/test_frontend.py tests/test_app_js_logic.py</span>
{pytest_html}</pre>
</div>"""
(OUT / "tests.html").write_text(page("tests", term_body, cls="centered"), encoding="utf-8")


def card(eyebrow: str, big: str, sub: str, foot: str = "") -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:1920px; height:1080px; }}
  body {{
    background: radial-gradient(1600px 900px at 50% 42%, #101624 0%, {BG} 65%);
    color: {TEXT}; font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
    display:flex; align-items:center; justify-content:center; text-align:center;
    overflow: hidden;
  }}
  .ring {{
    width: 190px; height: 190px; border: 7px solid {ACCENT}; border-radius: 50%;
    margin: 0 auto 44px; position: relative;
  }}
  .ring::after {{
    content:''; position:absolute; top:-16px; left:50%; width:28px; height:28px;
    background:{ACCENT}; border-radius:50%; transform:translateX(-50%);
    box-shadow:0 0 40px {ACCENT};
  }}
  .eyebrow {{ color:{ACCENT}; letter-spacing:14px; font-size:38px; font-weight:700;
    text-transform:uppercase; margin-bottom:30px; }}
  h1 {{ font-size:150px; font-weight:800; letter-spacing:3px; margin-bottom:34px; }}
  p.sub {{ font-size:52px; color:#c3cad6; font-weight:400; }}
  p.foot {{ margin-top:52px; font-size:44px; color:{MUTED};
    font-family:'SF Mono',Menlo,monospace; }}
</style></head>
<body><div>
  <div class="ring"></div>
  <div class="eyebrow">{eyebrow}</div>
  <h1>{big}</h1>
  <p class="sub">{sub}</p>
  <p class="foot">{foot}</p>
</div></body></html>"""


(OUT / "card_title.html").write_text(
    card(
        "AI-powered research",
        "ORBIT SEARCH",
        "AI-powered research grounded in web evidence.",
    ),
    encoding="utf-8",
)
(OUT / "card_closing.html").write_text(
    card(
        "SerpApi India Hackathon",
        "ORBIT SEARCH",
        "Organized. Inspectable. Resilient research.",
        "github.com/MrSamarAhmed/ORBIT-SEARCH",
    ),
    encoding="utf-8",
)

print("wrote", sorted(p.name for p in OUT.iterdir()))
