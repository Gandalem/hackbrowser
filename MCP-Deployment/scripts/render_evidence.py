#!/usr/bin/env python3
"""Render actual CI/CD command output as a presentation-friendly PNG evidence image."""
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

if len(sys.argv) != 4:
    raise SystemExit("usage: render_evidence.py INPUT_LOG OUTPUT_PNG TITLE")
source, output, title = sys.argv[1:]
lines = Path(source).read_text(encoding="utf-8", errors="replace").splitlines()
# Avoid reproducing credential-bearing URLs even if introduced by future log changes.
redacted = []
for line in lines:
    if "/share/" in line or "PRIVATE KEY" in line or "MCP_LOGIN_PASSWORD" in line:
        redacted.append("[REDACTED: credential-bearing output]")
    else:
        redacted.append(line)
lines = redacted[-58:] or ["No log output captured"]
font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
font = ImageFont.truetype(font_path, 17)
heading = ImageFont.truetype(font_path, 25)
width = 1536
line_height = 25
height = max(400, min(1900, 115 + len(lines) * line_height))
canvas = Image.new("RGB", (width, height), "#101827")
draw = ImageDraw.Draw(canvas)
draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=22, fill="#172237", outline="#334155", width=2)
draw.text((52, 43), title, font=heading, fill="#e2e8f0")
for i, line in enumerate(lines):
    y = 102 + i * line_height
    if y > height - 35:
        break
    short = line[:134]
    color = "#86efac" if ("PASS" in line or "OK" in line or "success" in line.lower()) else "#e2e8f0"
    if "FAIL" in line or "ERROR" in line or "failed" in line.lower():
        color = "#fca5a5"
    draw.text((52, y), short, font=font, fill=color)
Path(output).parent.mkdir(parents=True, exist_ok=True)
canvas.save(output, optimize=True)
print("Evidence image saved:", output)
