"""The project's own check: exit 0 when index.html has a form, a required email field and a submit button."""

import re
import sys
from pathlib import Path

page = Path(__file__).with_name("index.html")
html = page.read_text(encoding="utf-8") if page.is_file() else ""
problems = []
if not re.search(r"<form\b", html, re.I):
    problems.append("no form")
email = re.search(r"<input\b[^>]*type=[\"']email[\"'][^>]*>", html, re.I)
if not email or not re.search(r"\brequired\b", email.group(0), re.I):
    problems.append("no required email field")
if not re.search(r"<button\b[^>]*type=[\"']submit[\"']", html, re.I):
    problems.append("no submit button")
print("ok" if not problems else "; ".join(problems))
sys.exit(1 if problems else 0)
