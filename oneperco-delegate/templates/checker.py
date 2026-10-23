"""Per-job checker for a delegation batch: <batch name>. Copy to the batch's scratch dir and fill in.

    python checker.py <job-id>      # JSON lines; exit 0 clean, 1 any error, 2 usage

The executor runs it to fix its own output; Claude runs it again at acceptance. It checks shape and
data provenance only. It cannot tell a true sentence from a false one: Claude's claim-by-claim read
stays part of acceptance (HUONG-DAN.md section 9).
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(r"<absolute repo or scratch root>")
# Pre-assigned in the work order: job id -> output path (and any per-job expectation).
JOBS = {
    "<job-id>": {"path": ROOT / "<output path>"},
}
ALLOWED_NUMBERS_FILE = ROOT / "<file listing the only numbers the output may use, or delete this>"


def check(job_id, spec):
    """Return [(code, detail)]; empty means clean."""
    path = spec["path"]
    if not path.is_file():
        return [("NO_FILE", str(path))]
    text = path.read_text(encoding="utf-8")
    errors = []
    # --- shape (replace with this batch's rules) ---
    words = len(re.findall(r"\b\w[\w'-]*\b", text))
    if not 100 <= words <= 2000:
        errors.append(("WORDS_OUT_OF_RANGE", words))
    # --- provenance: every number must come from the allowed list ---
    if ALLOWED_NUMBERS_FILE.is_file():
        allowed = set(json.loads(ALLOWED_NUMBERS_FILE.read_text(encoding="utf-8")))
        for number in sorted(set(re.findall(r"\d[\d,.]*%?", text)) - allowed):
            errors.append(("NUMBER_NOT_ALLOWED", number))
    # --- banned claims (regex catches wording, not meaning; Claude still reads) ---
    for pattern in [r"<banned phrase regex>"]:
        if re.search(pattern, text, re.I):
            errors.append(("BANNED_CLAIM", pattern))
    return errors


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        print(json.dumps({"event": "usage", "allowed": sorted(JOBS)}))
        return 2
    job_id = sys.argv[1]
    errors = check(job_id, JOBS[job_id])
    for code, detail in errors:
        print(json.dumps({"event": "job_error", "job": job_id, "code": code, "detail": str(detail)}, ensure_ascii=False))
    print(json.dumps({"event": "job_check", "job": job_id, "errors": len(errors)}))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
