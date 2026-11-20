"""Validate the embedded JavaScript in the MCP Apps screenshot HTML.

Only a standalone inline script is supported: fail on external script tags so
CI cannot silently skip the actual UI logic.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
import tempfile

WIDGET = Path(__file__).resolve().parent.parent / "services/hackbrowser/screenshot_widget.html"


class ScriptExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.active = False

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        if self.active or any(name == "src" for name, _ in attrs):
            raise ValueError("Only self-contained inline JavaScript is allowed")
        self.active = True
        self.scripts.append("")

    def handle_data(self, data):
        if self.active:
            self.scripts[-1] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False


def main():
    parser = ScriptExtractor()
    parser.feed(WIDGET.read_text(encoding="utf-8"))
    if parser.active or len(parser.scripts) != 1 or not parser.scripts[0].strip():
        raise ValueError("Expected exactly one complete inline screenshot script")

    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "screenshot_widget.js"
        output.write_text(parser.scripts[0], encoding="utf-8")
        subprocess.run(["node", "--check", str(output)], check=True)
    print("JavaScript syntax: PASS")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"JavaScript syntax: FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
