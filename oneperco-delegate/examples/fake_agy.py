"""A stand-in for `agy` so the examples run offline, with no account. run_examples.py sets AGY_BIN to it.

FAKE_AGY_PLAN names a JSON file: a list of {"match": <text in the prompt>, "write": {path: text},
"result": <structured output>}. The first entry whose `match` is in the prompt is played: files are
written relative to the working directory (write mode), and `result` is printed as agy's stream-json
result event (json mode). Exits 1 when no entry matches.
"""

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else ""
plan = json.loads(Path(os.environ["FAKE_AGY_PLAN"]).read_text(encoding="utf-8"))
entry = next((e for e in plan if e["match"] in prompt), None)
if entry is None:
    print("fake agy: no plan entry matches this prompt")
    sys.exit(1)
for rel, text in (entry.get("write") or {}).items():
    path = Path.cwd() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
if "result" in entry:
    print(json.dumps({"event": "step_update", "step_update": {"step_type": "model", "state": "DONE"}}))
    print(json.dumps({"event": "result", "result": {"structured_output": entry["result"]}}))
if "--log-file" in args:
    Path(args[args.index("--log-file") + 1]).write_text("I0000 fake.go:1] applyAuthResult: fake\n")
print("fake agy finished")
