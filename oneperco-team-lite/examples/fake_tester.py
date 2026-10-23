"""A stand-in for `codex` so the examples run offline. run_examples.py sets CODEX_BIN to it.

Reads the prompt from stdin (as `codex exec -` does), records its argv to FAKE_TESTER_RECORD if set, and
writes the canned verdict in FAKE_VERDICT to the `-o` file. Exits 1 when `-s read-only` is missing, so a
Tester launched with write access fails loudly.
"""

import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
prompt = sys.stdin.read()
if os.environ.get("FAKE_TESTER_RECORD"):
    Path(os.environ["FAKE_TESTER_RECORD"]).write_text(json.dumps({"argv": args, "prompt_chars": len(prompt)}))
if args[args.index("-s") + 1:args.index("-s") + 2] != ["read-only"] or args[-1] != "-" or "Budget" not in prompt:
    print("fake tester: not launched read-only with the prompt on stdin")
    sys.exit(1)
Path(args[args.index("-o") + 1]).write_text(Path(os.environ["FAKE_VERDICT"]).read_text(encoding="utf-8"),
                                             encoding="utf-8")
print("fake tester finished")
