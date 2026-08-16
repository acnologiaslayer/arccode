#!/usr/bin/env python3
"""Render a Markdown file to a print-styled HTML for PDF export.

Usage: md_to_html.py [SRC.md [OUT.html]]
Defaults to the vision doc if no args are given.
"""
import sys
import markdown

_DEFAULT = "/mnt/c/Users/arcma/OneDrive/Desktop/agent-harness-vision-and-method.md"
SRC = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC.rsplit(".", 1)[0] + ".html"

md_text = open(SRC, encoding="utf-8").read()
html_body = markdown.markdown(
    md_text,
    extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
)

CSS = """
@page { size: A4; margin: 22mm 20mm; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  color: #1a1416; line-height: 1.55; font-size: 11pt; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h1 {
  font-size: 24pt; font-weight: 700; letter-spacing: -0.5px; margin: 0 0 6px;
  color: #0f0b0c; border-bottom: 3px solid #e5121b; padding-bottom: 10px;
}
h2 {
  font-size: 15pt; font-weight: 700; margin: 26px 0 10px; color: #0f0b0c;
  padding-left: 10px; border-left: 4px solid #e5121b;
  page-break-after: avoid;
}
h3 { font-size: 12pt; font-weight: 700; margin: 18px 0 6px; color: #7a0a0a; page-break-after: avoid; }
p { margin: 0 0 9px; }
a { color: #b00711; text-decoration: none; }
strong { color: #0f0b0c; }
em { color: #52424a; }
ul, ol { margin: 0 0 10px; padding-left: 22px; }
li { margin: 2px 0; }
hr { border: none; border-top: 1px solid #e3d4d6; margin: 22px 0; }
blockquote {
  margin: 12px 0; padding: 10px 16px; background: #fdf3f3;
  border-left: 4px solid #e5121b; color: #3a2a2e; border-radius: 4px;
}
blockquote p { margin: 0; }
code {
  font-family: 'Consolas', 'SF Mono', monospace; font-size: 9.5pt;
  background: #f4ecec; color: #b00711; padding: 1px 5px; border-radius: 3px;
}
pre {
  background: #14100f; color: #ece0e0; padding: 14px 16px; border-radius: 6px;
  font-size: 9pt; line-height: 1.5; margin: 10px 0;
  page-break-inside: avoid;
  white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere;
}
pre code { background: none; color: #ece0e0; padding: 0;
  white-space: pre-wrap; word-wrap: break-word; overflow-wrap: anywhere; }
table {
  border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 10pt;
  page-break-inside: avoid;
}
th, td { border: 1px solid #e3d4d6; padding: 7px 10px; text-align: left; vertical-align: top; }
th { background: #2a1e1e; color: #fff; font-weight: 600; }
tr:nth-child(even) td { background: #faf5f5; }
h2, h3 { page-break-inside: avoid; }
"""

_title = next((ln.lstrip("# ").strip() for ln in md_text.splitlines()
               if ln.startswith("# ")), "Document")
full = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{_title}</title>
<style>{CSS}</style></head><body>{html_body}</body></html>"""

open(OUT, "w", encoding="utf-8").write(full)
print("wrote", OUT, len(full), "bytes")
