"""Offline tests for run_agy.py with a fake agy (AGY_BIN points at a generated .py), plus one mutant per
case: each mutant is a one-line change to a copy of run_agy.py that the named case must catch.

    python test_run_agy.py      # exit 0 = suite green and every mutant caught

Cases: success (write + json, argv shape), non-zero exit, timeout (process tree killed), stray_write,
schema mismatch, prompt leak, agy quota/auth, tool breach, config errors.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "run_agy.py"
MARK = "PROMPTMARK-" + uuid.uuid4().hex[:12]
SCHEMA = {"type": "object", "properties": {"label": {"type": "string", "enum": ["ok", "fine"]},
                                           "n": {"type": "integer", "minimum": 0}},
          "required": ["label", "n"], "additionalProperties": False}

FAKE_AGY = r'''
import json, os, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
def opt(name):
    return args[args.index(name) + 1] if name in args else None

prompt = opt("-p") or ""
tag = next((t[4:] for t in prompt.split() if t.startswith("TAG=")), "x")
dos = [t[3:] for t in prompt.split() if t.startswith("DO=")]
record = os.environ.get("FAKE_AGY_RECORD")
if record:
    shown = ["<prompt>" if a == prompt else a for a in args]
    Path(record, tag + ".json").write_text(json.dumps({"argv": shown, "cwd": os.getcwd()}))
internal = ["I1007 x.go:1] error getting token source: You are not logged into Antigravity.",
            "I1007 auth.go:198] applyAuthResult: email=fake@example.invalid, authMethod=consumer"]
code = 0
def step(tool):
    print(json.dumps({"event": "step_update", "step_update": {"step_type": "tool", "tool_name": tool, "state": "DONE"}}))
def result(obj):
    print(json.dumps({"event": "result", "result": {"structured_output": obj}}))
for do in dos:
    if do.startswith("write:"):
        path = Path(os.getcwd(), do[6:])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("written by fake agy\n")
    elif do == "exit3":
        code = 3
    elif do == "sleep":
        subprocess.Popen([sys.executable, "-c", "import sys, time; time.sleep(3); open(sys.argv[1], 'w').write('orphan')",
                          os.environ["FAKE_AGY_ORPHAN"]])
        time.sleep(60)
    elif do == "json_good":
        print(json.dumps({"event": "step_update", "step_update": {"step_type": "model", "state": "DONE"}}))
        result({"label": "ok", "n": 2})
    elif do == "json_missing":
        result({"label": "ok"})
    elif do == "json_enum":
        result({"label": "nope", "n": 2})
    elif do == "breach":
        step("read_file")
        result({"label": "ok", "n": 2})
    elif do == "search":
        step("search_web")
        result({"label": "ok", "n": 2})
    elif do == "quota":
        internal.append("E1007 errorreport.go:224] agent executor error: generating and executing: RESOURCE_EXHAUSTED "
                        "(code 429): Individual quota reached.")
        code = 1
    elif do == "auth":
        internal = internal[:1]
        code = 1
    elif do == "auth_noise":
        code = 1
    elif do == "sayquota":
        print("Handled the RESOURCE_EXHAUSTED branch of the client as asked.")
    elif do == "printtimeout":
        print("[agy] print timeout after 2m30s with turn in progress; returning partial output")
log_file = opt("--log-file")
if log_file:
    Path(log_file).write_text("\n".join(internal) + "\n")
print("fake agy finished")
sys.exit(code)
'''

# (name, old text in run_agy.py, replacement, prefix of the case that must fail)
MUTANTS = [
    ("write mode drops accept-edits", 'cmd += ["--mode", "accept-edits"]', 'cmd += []', "success:"),
    ("json mode drops --sandbox", '"--project", job["project"], "--sandbox", ', '"--project", job["project"], ',
     "success:"),
    ("positive exit codes ignored", 'elif row["exit"] != 0:', 'elif row["exit"] < 0:', "nonzero:"),
    ("timeout kills only agy, not its tree", '["taskkill", "/T", "/F",', '["taskkill", "/F",', "timeout:"),
    ("agy's own print timeout (exit 0) passes", "killed or bool(PRINT_TIMEOUT_RE.search(text))", "killed", "timeout:"),
    ("snapshot ignores content changes", "snap[path] = (xy, st.st_size, st.st_mtime_ns)", "snap[path] = (xy, None, None)",
     "stray:"),
    ("required keys not checked", 'for key in schema.get("required", []):', 'for key in schema.get("required_", []):',
     "schema:"),
    ("errors rendered with str(exc)", 'return type(exc).__name__ + (f" errno={errno}" if errno is not None else "")',
     "return str(exc)", "leak:"),
    ("login noise read as AGY_AUTH", "and not AUTH_OK_RE.search(internal):", ":", "agy errors:"),
    ("tool DONE events not seen", 'step.get("state") == "DONE"', 'step.get("state") == "DONE_"', "breach:"),
    ("duplicate ids accepted", "if jid in seen:", "if jid in ():", "config:"),
]


class Suite:
    def __init__(self, mod, verbose):
        self.mod, self.verbose, self.failed, self.outputs = mod, verbose, [], []

    def check(self, name, condition, detail=""):
        if self.verbose:
            print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  {detail}"))
        if not condition:
            self.failed.append(name)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.KILL_GRACE_S = 0
    return mod


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_ctx(tmp):
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "base.txt").write_text("base\n")
    (repo / "dirty.txt").write_text("committed\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "dirty.txt").write_text("committed\nalready dirty before the run\n")
    for name in ("scratch", "record"):
        (tmp / name).mkdir()
    fake = tmp / "fake_agy.py"
    fake.write_text(FAKE_AGY, encoding="utf-8")
    os.environ["AGY_BIN"] = str(fake)
    os.environ["FAKE_AGY_RECORD"] = str(tmp / "record")
    os.environ["FAKE_AGY_ORPHAN"] = str(tmp / "orphan.txt")
    return {"tmp": tmp, "repo": repo, "scratch": tmp / "scratch", "record": tmp / "record", "orphan": tmp / "orphan.txt"}


def run_batch(s, ctx, name, jobs, logs=None, files=None):
    d = ctx["tmp"] / name
    d.mkdir()
    for fname, text in (files or {}).items():
        (d / fname).write_text(text, encoding="utf-8")
    jobs_path = d / "jobs.json"
    jobs_path.write_text(jobs if isinstance(jobs, str) else json.dumps(jobs), encoding="utf-8")
    logs = logs or d / "logs"
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = s.mod.main([str(jobs_path), "--logs", str(logs), "--repo", str(ctx["repo"])])
    s.outputs.append(out.getvalue() + err.getvalue())
    rows = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    return code, rows, logs


def row(rows, jid):
    return next((r for r in rows if r.get("event") == "job" and r.get("id") == jid), {})


def recorded(ctx, tag):
    path = ctx["record"] / f"{tag}.json"
    return json.loads(path.read_text()) if path.is_file() else {"argv": [], "cwd": None}


def test_success(s, ctx):
    code, rows, logs = run_batch(s, ctx, "success", [
        {"id": "w1", "mode": "write", "prompt": f"TAG=w1 DO=write:out/w1.txt {MARK}", "allowed_paths": ["out/w1.txt"],
         "add_dirs": [str(ctx["scratch"])], "timeout_s": 60},
        {"id": "w2", "mode": "write", "prompt_file": "p_w2.txt", "allowed_paths": ["out/w2.txt"], "timeout_s": 60},
        {"id": "j1", "mode": "json", "prompt": f"TAG=j1 DO=json_good {MARK}", "project": "quarantine-x",
         "json_schema": SCHEMA, "timeout_s": 60},
    ], files={"p_w2.txt": f"TAG=w2 DO=write:out/w2.txt {MARK}"})
    s.check("success: exit 0", code == 0, rows)
    s.check("success: every job clean", all(row(rows, j).get("error") is None and row(rows, j).get("exit") == 0
                                            and row(rows, j).get("timed_out") is False for j in ("w1", "w2", "j1")), rows)
    s.check("success: prompt_file is read relative to jobs.json", (ctx["repo"] / "out/w2.txt").is_file())
    out = logs / "j1.out.json"
    s.check("success: json output saved", out.is_file() and json.loads(out.read_text()) == {"label": "ok", "n": 2})
    final = rows[-1] if rows else {}
    s.check("success: final run row", final.get("event") == "run" and final.get("exit") == 0
            and final.get("stray_writes") == 0, final)
    summary = [json.loads(line) for line in (logs / "summary.jsonl").read_text().splitlines()]
    s.check("success: summary.jsonl holds the stdout rows", summary == rows)
    w1 = recorded(ctx, "w1")
    argv = w1["argv"]
    s.check("success: write argv", argv[argv.index("--mode") + 1] == "accept-edits"
            and not any(a.startswith("--dangerously") for a in argv) and "--project" not in argv
            and argv[argv.index("--add-dir") + 1] == str(ctx["scratch"])
            and argv[argv.index("--model") + 1] == "gemini-3.8-flash-high"
            and argv[argv.index("--print-timeout") + 1] == "60s" and "--log-file" in argv
            and Path(w1["cwd"]).resolve() == ctx["repo"].resolve(), w1)
    j1 = recorded(ctx, "j1")
    argv = j1["argv"]
    s.check("success: json argv", not any(a.startswith("--dangerously") for a in argv) and "--mode" not in argv
            and "--add-dir" not in argv
            and "--sandbox" in argv and argv[argv.index("--project") + 1] == "quarantine-x"
            and argv[argv.index("--output-format") + 1] == "stream-json"
            and argv[argv.index("--model") + 1] == "gemini-3.8-flash-medium"
            and json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA, j1)
    s.check("success: json job ran in a throwaway dir outside the repo",
            j1["cwd"] and Path(j1["cwd"]).resolve() != ctx["repo"].resolve() and not Path(j1["cwd"]).exists(), j1)


def test_nonzero(s, ctx):
    code, rows, _ = run_batch(s, ctx, "nonzero", [
        {"id": "e1", "mode": "write", "prompt": f"TAG=e1 DO=exit3 {MARK}", "timeout_s": 60},
        {"id": "e2", "mode": "write", "prompt": f"TAG=e2 DO=sayquota {MARK}", "timeout_s": 60},
    ])
    s.check("nonzero: exit 1", code == 1)
    s.check("nonzero: job row has exit 3 and EXIT_NONZERO",
            row(rows, "e1").get("exit") == 3 and row(rows, "e1").get("error") == "EXIT_NONZERO", rows)
    s.check("nonzero: quota words in a working reply are not AGY_QUOTA", row(rows, "e2").get("error") is None, rows)


def test_timeout(s, ctx):
    start = time.monotonic()
    code, rows, _ = run_batch(s, ctx, "timeout", [
        {"id": "t1", "mode": "write", "prompt": f"TAG=t1 DO=sleep {MARK}", "timeout_s": 1},
        {"id": "t2", "mode": "write", "prompt": f"TAG=t2 DO=printtimeout {MARK}", "timeout_s": 60}])
    took = time.monotonic() - start
    r = row(rows, "t1")
    s.check("timeout: exit 1, TIMEOUT, timed_out", code == 1 and r.get("error") == "TIMEOUT"
            and r.get("timed_out") is True, rows)
    s.check("timeout: agy's own print timeout exits 0 but is still TIMEOUT",
            row(rows, "t2").get("exit") == 0 and row(rows, "t2").get("error") == "TIMEOUT", rows)
    s.check("timeout: killed promptly", took < 20, took)
    time.sleep(4.5)
    s.check("timeout: process tree killed (no orphan grandchild)", not ctx["orphan"].exists())


def test_stray(s, ctx):
    runlogs = ctx["repo"] / "runlogs"
    code, rows, _ = run_batch(s, ctx, "stray", [
        {"id": "s1", "mode": "write", "prompt": f"TAG=s1 DO=write:out/s1.txt DO=write:stray/s1.txt {MARK}",
         "allowed_paths": ["out/s1.txt"], "timeout_s": 60},
        {"id": "s2", "mode": "write", "prompt": f"TAG=s2 DO=write:dirty.txt {MARK}", "allowed_paths": ["out/"],
         "timeout_s": 60},
        {"id": "s3", "mode": "write", "prompt": f"TAG=s3 DO=write:notes/a/b.md {MARK}", "allowed_paths": ["notes/*/*.md"],
         "timeout_s": 60},
    ], logs=runlogs)
    stray = sorted(r["path"] for r in rows if r.get("event") == "stray_write")
    s.check("stray: exit 1", code == 1)
    s.check("stray: exactly the unlisted paths (incl. a file already dirty before the run)",
            stray == ["dirty.txt", "stray/s1.txt"], stray)
    s.check("stray: jobs themselves clean", all(row(rows, j).get("error") is None for j in ("s1", "s2", "s3")), rows)


def test_schema(s, ctx):
    code, rows, logs = run_batch(s, ctx, "schema", [
        {"id": "m1", "mode": "json", "prompt": f"TAG=m1 DO=json_missing {MARK}", "project": "q", "json_schema": SCHEMA,
         "timeout_s": 60},
        {"id": "m2", "mode": "json", "prompt": f"TAG=m2 DO=json_enum {MARK}", "project": "q", "json_schema": SCHEMA,
         "timeout_s": 60},
        {"id": "m3", "mode": "json", "prompt": f"TAG=m3 DO=noresult {MARK}", "project": "q", "json_schema": SCHEMA,
         "timeout_s": 60},
    ])
    s.check("schema: exit 1", code == 1)
    s.check("schema: missing required key", row(rows, "m1").get("error") == "SCHEMA_MISMATCH"
            and {"path": "$.n", "keyword": "required"} in row(rows, "m1").get("schema_errors", []), rows)
    s.check("schema: enum violation", row(rows, "m2").get("error") == "SCHEMA_MISMATCH"
            and {"path": "$.label", "keyword": "enum"} in row(rows, "m2").get("schema_errors", []), rows)
    s.check("schema: no result event", row(rows, "m3").get("error") == "NO_RESULT", rows)
    s.check("schema: no output file for a bad result", not (logs / "m1.out.json").exists())
    v = s.mod.validate
    s.check("schema: unit cases", v({"label": "ok", "n": 1, "x": 1}, SCHEMA) == [{"path": "$.x", "keyword": "additionalProperties"}]
            and v({"label": "ok", "n": True}, SCHEMA) == [{"path": "$.n", "keyword": "type"}]
            and v(None, {"type": ["string", "null"]}) == [] and v([1, "a"], {"type": "array", "items": {"type": "integer"}})
            == [{"path": "$[1]", "keyword": "type"}])


def test_agy_errors(s, ctx):
    code, rows, _ = run_batch(s, ctx, "agyerr", [
        {"id": "q1", "mode": "write", "prompt": f"TAG=q1 DO=quota {MARK}", "timeout_s": 60},
        {"id": "a1", "mode": "write", "prompt": f"TAG=a1 DO=auth {MARK}", "timeout_s": 60},
        {"id": "a2", "mode": "write", "prompt": f"TAG=a2 DO=auth_noise {MARK}", "timeout_s": 60},
    ])
    s.check("agy errors: exit 1", code == 1)
    s.check("agy errors: quota", row(rows, "q1").get("error") == "AGY_QUOTA", rows)
    s.check("agy errors: not logged in", row(rows, "a1").get("error") == "AGY_AUTH", rows)
    s.check("agy errors: login noise in a working session is not AGY_AUTH", row(rows, "a2").get("error") == "EXIT_NONZERO",
            rows)


def test_breach(s, ctx):
    code, rows, _ = run_batch(s, ctx, "breach", [
        {"id": "b1", "mode": "json", "prompt": f"TAG=b1 DO=breach {MARK}", "project": "q", "json_schema": SCHEMA,
         "timeout_s": 60},
        {"id": "b2", "mode": "json", "prompt": f"TAG=b2 DO=search {MARK}", "project": "q", "json_schema": SCHEMA,
         "timeout_s": 60},
    ])
    s.check("breach: exit 1", code == 1)
    s.check("breach: a DONE tool other than search_web", row(rows, "b1").get("error") == "TOOL_BREACH"
            and row(rows, "b1").get("tools") == ["read_file"], rows)
    s.check("breach: search_web only is counted, not failed",
            row(rows, "b2").get("error") is None and row(rows, "b2").get("searched") == 1, rows)


def test_config(s, ctx):
    good = {"mode": "write", "prompt": "TAG=cfg DO=write:x.txt", "timeout_s": 60}
    cases = [
        ("DUPLICATE_ID", [dict(good, id="c1"), dict(good, id="c1")]),
        ("JSON_JOB_NEEDS_PROJECT", [{"id": "c2", "mode": "json", "prompt": "TAG=cfg", "json_schema": SCHEMA}]),
        ("UNSUPPORTED_SCHEMA", [{"id": "c3", "mode": "json", "prompt": "TAG=cfg", "project": "q",
                                 "json_schema": {"oneOf": [{"type": "string"}]}}]),
        ("JSON_KEY_IN_WRITE_JOB", [dict(good, id="c4", json_schema=SCHEMA)]),
        ("BAD_ALLOWED_PATH", [dict(good, id="c5", allowed_paths=["*"])]),
        ("BAD_ALLOWED_PATH", [dict(good, id="c6", allowed_paths=["../outside.txt"])]),
        ("PROMPT_XOR_PROMPT_FILE", [dict(good, id="c7", prompt_file="p.txt")]),
        ("BAD_MODE", [dict(good, id="c8", mode="shell")]),
    ]
    for i, (expected, jobs) in enumerate(cases):
        code, rows, _ = run_batch(s, ctx, f"config{i}", jobs)
        s.check(f"config: {expected} -> exit 2", code == 2 and rows and rows[0].get("code") == expected, rows)
    saved = os.environ["AGY_BIN"]
    os.environ["AGY_BIN"] = str(ctx["tmp"] / "no_such_agy.exe")
    try:
        code, rows, _ = run_batch(s, ctx, "config_noagy", [dict(good, id="c9")])
    finally:
        os.environ["AGY_BIN"] = saved
    s.check("config: AGY_NOT_FOUND -> exit 2", code == 2 and rows and rows[0].get("code") == "AGY_NOT_FOUND", rows)
    s.check("config: agy never launched on a config error", not (ctx["record"] / "cfg.json").exists())


CASES = [test_success, test_nonzero, test_timeout, test_stray, test_schema, test_agy_errors, test_breach, test_config]


def suite(mod, verbose):
    s = Suite(mod, verbose)
    with tempfile.TemporaryDirectory(prefix="test-run-agy-", ignore_cleanup_errors=True) as tmp:
        ctx = make_ctx(Path(tmp).resolve())
        for case in CASES:
            prefix = case.__name__[5:].replace("_", " ") + ":"
            try:
                case(s, ctx)
            except Exception as exc:  # a mutant may crash a case; that counts as caught, never as a pass
                s.check(f"{prefix} crashed", False, f"{type(exc).__name__}: {exc}")
        logs_text = "".join(p.read_text(encoding="utf-8", errors="replace")
                            for p in Path(tmp).rglob("*") if p.is_file() and p.parent.name in ("logs", "runlogs"))
        s.check("leak: prompt never appears in runner output or logs",
                not any(MARK in out for out in s.outputs) and MARK not in logs_text)
    return s.failed


def main():
    failed = suite(load(SRC, "run_agy_under_test"), verbose=True)
    print(f"\nsuite: {'FAILED ' + str(len(failed)) if failed else 'ALL PASSED'}\n")
    src = SRC.read_text(encoding="utf-8")
    survived = []
    with tempfile.TemporaryDirectory(prefix="run-agy-mutants-") as tmp:
        for i, (name, old, new, case) in enumerate(MUTANTS):
            if src.count(old) != 1:
                print(f"MUTANT BROKEN {name}: anchor found {src.count(old)} times")
                survived.append(name)
                continue
            path = Path(tmp) / f"run_agy_m{i}.py"
            path.write_text(src.replace(old, new), encoding="utf-8")
            hits = [f for f in suite(load(path, f"run_agy_m{i}"), verbose=False) if f.startswith(case)]
            print(f"MUTANT {'CAUGHT  ' if hits else 'SURVIVED'} {name}  ({case} {len(hits)} failing)")
            if not hits:
                survived.append(name)
    print(f"\nmutants: {len(MUTANTS) - len(survived)}/{len(MUTANTS)} caught")
    return 1 if failed or survived else 0


if __name__ == "__main__":
    sys.exit(main())
