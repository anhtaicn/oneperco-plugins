"""Checker for example 02, filled in from templates/checker.py.

    python checker.py <repo root> <job-id>      # JSON lines; exit 0 clean, 1 any error, 2 usage
"""

import json
import re
import sys
from pathlib import Path

JOBS = {
    "tra-xanh": {"path": "drafts/tra-xanh.md", "numbers": {"100", "15", "89.000"}},
    "ca-phe": {"path": "drafts/ca-phe.md", "numbers": {"500", "120.000"}},
}


def check(root, spec):
    path = root / spec["path"]
    if not path.is_file():
        return [("NO_FILE", spec["path"])]
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = []
    if len(lines) != 3:
        errors.append(("LINE_COUNT", len(lines)))
    for i, line in enumerate(lines, 1):
        if not line.startswith("- "):
            errors.append(("NOT_A_BULLET", i))
        if len(line.split()) > 26:
            errors.append(("LINE_TOO_LONG", i))
    for number in sorted(set(re.findall(r"\d[\d.,]*\d|\d", "\n".join(lines))) - spec["numbers"]):
        errors.append(("NUMBER_NOT_ALLOWED", number))
    return errors


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in JOBS:
        print(json.dumps({"event": "usage", "allowed": sorted(JOBS)}))
        return 2
    job_id = sys.argv[2]
    errors = check(Path(sys.argv[1]), JOBS[job_id])
    for code, detail in errors:
        print(json.dumps({"event": "job_error", "job": job_id, "code": code, "detail": str(detail)}))
    print(json.dumps({"event": "job_check", "job": job_id, "errors": len(errors)}))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
