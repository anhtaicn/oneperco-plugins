"""Run a batch of headless Antigravity (`agy -p`) jobs in parallel and report loudly. Stdlib only.

    python run_agy.py jobs.json --logs <dir> [--repo <path>] [--max-parallel 6]

jobs.json is a list of objects:
    id            [A-Za-z0-9_.-]{1,64}, unique; names the files in --logs
    prompt | prompt_file   exactly one; prompt_file is relative to jobs.json's directory
    model         default gemini-3.8-flash-high (write) or gemini-3.8-flash-medium (json: flash-high with
                  --json-schema hung to the print timeout 3 of 3 times on 2026-10-07)
    mode          "write": --mode accept-edits --add-dir ...; the agent edits files itself. Edits are
                           auto-accepted; any other tool (a command, a fetch) runs only if the user's own
                           Antigravity permissions already allow it, since headless agy refuses what it
                           would have to ask about. Never skips permissions.
                  "json":  --project <quarantine> --sandbox --output-format stream-json --json-schema;
                           the agent only returns JSON, which this runner validates and saves
    add_dirs      write only; directories the agent may use (must exist)
    allowed_paths write only; repo-relative paths, directory prefixes or fnmatch globs the job may change
    project       json only, required: an Antigravity project whose permissionGrants deny every tool
    json_schema   json only, required: inline schema or a path to one (relative to jobs.json)
    timeout_s     default 1200; passed as --print-timeout (agy then exits 0 with partial output, which
                  this runner reports as TIMEOUT), and the runner kills the process tree KILL_GRACE_S later
    cwd           optional; default the repo root (write) or a fresh empty temp dir (json)

Writes to --logs: <id>.log (agy stdout+stderr), <id>.agy.log (agy's internal log via --log-file),
<id>.out.json (json jobs, only when the output passed the schema), summary.jsonl (the same JSON lines
as stdout: one `job` row per job, one `stray_write` row per changed path no job was allowed to touch,
one final `run` row).

Exit 0 all clean; 1 any job error, timeout, stray write or schema mismatch; 2 bad config or setup.
Never logs a prompt or a json job's output: rows hold ids, codes, exit codes, seconds and byte sizes.
The stray check only sees what `git status` sees: a write outside the repo or to an ignored path is
invisible to it.
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_MODEL = {"write": "gemini-3.8-flash-high", "json": "gemini-3.8-flash-medium"}
DEFAULT_TIMEOUT_S = 1200
KILL_GRACE_S = 30
CMDLINE_MAX = 32000  # Windows CreateProcess limit is 32,767 characters
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
JOB_KEYS = {"id", "prompt", "prompt_file", "model", "mode", "add_dirs", "allowed_paths", "project",
            "json_schema", "timeout_s", "cwd"}
SCHEMA_KEYS = {"type", "enum", "const", "properties", "required", "additionalProperties", "items",
               "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "pattern",
               "title", "description", "$schema"}
SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
# Seen in ~/.gemini/antigravity-cli/log: quota errors are explicit; "not logged into" is also logged as
# background noise by sessions that did authenticate, so it counts only without an applyAuthResult line.
QUOTA_RE = re.compile(r"RESOURCE_EXHAUSTED|Individual quota reached")
AUTH_RE = re.compile(r"not logged into Antigravity")
AUTH_OK_RE = re.compile(r"applyAuthResult")
# agy exits 0 when --print-timeout fires (seen 2026-10-07), printing this line and a partial result.
PRINT_TIMEOUT_RE = re.compile(r"^\[agy\] print timeout after", re.M)

_out_lock = threading.Lock()


class ConfigError(Exception):
    def __init__(self, code, job_id=None, detail=""):
        super().__init__(code)
        self.code, self.job_id, self.detail = code, job_id, detail


def safe_error(exc):
    """Name an exception without its message: str(TimeoutExpired) renders the cmd, which holds the prompt."""
    errno = getattr(exc, "errno", None)
    return type(exc).__name__ + (f" errno={errno}" if errno is not None else "")


# ---- JSON Schema subset ---------------------------------------------------------------------------

def schema_problems(schema, at="$"):
    """Config-time check: every keyword must be one this validator enforces, so none is silently skipped."""
    if not isinstance(schema, dict):
        return [f"{at}: not an object"]
    problems = [f"{at}: unsupported keyword {key}" for key in sorted(set(schema) - SCHEMA_KEYS)]
    types = schema.get("type")
    for name in types if isinstance(types, list) else ([types] if types is not None else []):
        if name not in SCHEMA_TYPES:
            problems.append(f"{at}: unknown type {name}")
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        problems.append(f"{at}: additionalProperties must be true or false")
    for key, sub in (schema.get("properties") or {}).items():
        problems += schema_problems(sub, f"{at}.{key}")
    if "items" in schema:
        problems += schema_problems(schema["items"], f"{at}[]")
    return problems


def _type_ok(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, {"object": dict, "array": list, "string": str}[name])


def validate(value, schema, at="$"):
    """Return [{path, keyword}] for every violation; values are never included."""
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_type_ok(value, name) for name in names):
            return [{"path": at, "keyword": "type"}]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append({"path": at, "keyword": "enum"})
    if "const" in schema and value != schema["const"]:
        errors.append({"path": at, "keyword": "const"})
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append({"path": at, "keyword": "minLength"})
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append({"path": at, "keyword": "maxLength"})
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append({"path": at, "keyword": "pattern"})
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append({"path": at, "keyword": "minimum"})
        if "maximum" in schema and value > schema["maximum"]:
            errors.append({"path": at, "keyword": "maximum"})
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append({"path": at, "keyword": "minItems"})
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append({"path": at, "keyword": "maxItems"})
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], f"{at}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required", []):
            if key not in value:
                errors.append({"path": f"{at}.{key}", "keyword": "required"})
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], f"{at}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append({"path": f"{at}.{key}", "keyword": "additionalProperties"})
    return errors


# ---- config ---------------------------------------------------------------------------------------

def _rel_ok(pattern):
    p = pattern.replace("\\", "/")
    return p not in ("", ".", "*", "**", "/") and not p.startswith("/") and ":" not in p \
        and ".." not in p.split("/")


def load_jobs(jobs_path):
    """Read and check jobs.json; raise ConfigError on the first problem."""
    try:
        jobs = json.loads(Path(jobs_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("BAD_JOBS_FILE", detail=safe_error(exc))
    if not isinstance(jobs, list) or not jobs:
        raise ConfigError("BAD_JOBS_FILE", detail="must be a non-empty list")
    base = Path(jobs_path).resolve().parent
    seen = set()
    out = []
    for job in jobs:
        if not isinstance(job, dict) or not ID_RE.match(str(job.get("id", ""))):
            raise ConfigError("BAD_ID", detail=str(job.get("id") if isinstance(job, dict) else type(job).__name__))
        jid = job["id"]
        if jid in seen:
            raise ConfigError("DUPLICATE_ID", jid)
        seen.add(jid)
        if set(job) - JOB_KEYS:
            raise ConfigError("UNKNOWN_KEY", jid, ",".join(sorted(set(job) - JOB_KEYS)))
        if ("prompt" in job) == ("prompt_file" in job):
            raise ConfigError("PROMPT_XOR_PROMPT_FILE", jid)
        if "prompt_file" in job:
            try:
                prompt = (base / job["prompt_file"]).read_text(encoding="utf-8")
            except OSError as exc:
                raise ConfigError("BAD_PROMPT_FILE", jid, safe_error(exc))
        else:
            prompt = job["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise ConfigError("EMPTY_PROMPT", jid)
        mode = job.get("mode")
        timeout_s = job.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s < 1:
            raise ConfigError("BAD_TIMEOUT", jid, str(timeout_s))
        spec = {"id": jid, "prompt": prompt, "mode": mode, "model": job.get("model", DEFAULT_MODEL.get(mode)),
                "timeout_s": timeout_s, "cwd": job.get("cwd"), "add_dirs": job.get("add_dirs", []),
                "allowed_paths": job.get("allowed_paths", []), "project": job.get("project"), "schema": None}
        if mode == "write":
            if "project" in job or "json_schema" in job:
                raise ConfigError("JSON_KEY_IN_WRITE_JOB", jid)
            for d in spec["add_dirs"]:
                if not Path(d).is_dir():
                    raise ConfigError("BAD_ADD_DIR", jid, str(d))
            for pattern in spec["allowed_paths"]:
                if not isinstance(pattern, str) or not _rel_ok(pattern):
                    raise ConfigError("BAD_ALLOWED_PATH", jid, str(pattern))
            spec["allowed_paths"] = [p.replace("\\", "/").rstrip("/") for p in spec["allowed_paths"]]
        elif mode == "json":
            if spec["add_dirs"] or spec["allowed_paths"]:
                raise ConfigError("FILES_IN_JSON_JOB", jid)
            if not isinstance(spec["project"], str) or not spec["project"]:
                raise ConfigError("JSON_JOB_NEEDS_PROJECT", jid)
            schema = job.get("json_schema")
            if isinstance(schema, str):
                try:
                    schema = json.loads((base / schema).read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise ConfigError("BAD_SCHEMA_FILE", jid, safe_error(exc))
            if not isinstance(schema, dict):
                raise ConfigError("JSON_JOB_NEEDS_SCHEMA", jid)
            problems = schema_problems(schema)
            if problems:
                raise ConfigError("UNSUPPORTED_SCHEMA", jid, "; ".join(problems))
            spec["schema"] = schema
        else:
            raise ConfigError("BAD_MODE", jid, str(mode))
        if spec["cwd"] is not None and not Path(spec["cwd"]).is_dir():
            raise ConfigError("BAD_CWD", jid, str(spec["cwd"]))
        out.append(spec)
    return out


def agy_command():
    """The agy launcher as an argv prefix. AGY_BIN may name a .py fake (tests), run with this Python."""
    exe = os.environ.get("AGY_BIN") or shutil.which("agy")
    if not exe or not Path(exe).is_file():
        raise ConfigError("AGY_NOT_FOUND", detail=str(exe))
    return [sys.executable, exe] if exe.endswith(".py") else [exe]


def build_cmd(agy, job, agy_log):
    cmd = agy + ["-p", job["prompt"], "--model", job["model"]]
    if job["mode"] == "write":
        cmd += ["--mode", "accept-edits"]
        for d in job["add_dirs"]:
            cmd += ["--add-dir", str(d)]
    else:
        cmd += ["--project", job["project"], "--sandbox", "--output-format", "stream-json",
                "--json-schema", json.dumps(job["schema"], separators=(",", ":"))]
    return cmd + ["--print-timeout", f"{job['timeout_s']}s", "--log-file", str(agy_log)]


# ---- git snapshot ---------------------------------------------------------------------------------

def git_root(repo):
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True)
    if proc.returncode != 0:
        raise ConfigError("NOT_A_GIT_REPO", detail=str(repo))
    return Path(proc.stdout.decode("utf-8").strip())


def git_snapshot(root):
    """{repo-relative path: (status XY, size, mtime_ns)} for every path git status lists."""
    proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                          capture_output=True)
    if proc.returncode != 0:
        raise ConfigError("GIT_STATUS_FAILED", detail=f"exit {proc.returncode}")
    fields = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
    snap = {}
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        xy, path = entry[:2], entry[3:]
        if xy[0] in "RC":
            i += 1  # -z puts a rename's or copy's source path in the next field
        try:
            st = os.stat(root / path)
            snap[path] = (xy, st.st_size, st.st_mtime_ns)
        except OSError:
            snap[path] = (xy, None, None)
    return snap


def is_allowed(path, patterns):
    return any(path == p or path.startswith(p + "/") or fnmatch.fnmatchcase(path, p) for p in patterns)


# ---- one job --------------------------------------------------------------------------------------

def kill_tree(proc):
    """agy starts a language server; kill the whole tree, not only agy itself."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    if proc.poll() is None:
        proc.kill()


def parse_stream(text):
    """agy stream-json: tool step_update events and the final result's structured_output."""
    tools_done, result = [], None
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("event") == "step_update":
            step = obj.get("step_update") or {}
            if step.get("step_type") == "tool" and step.get("state") == "DONE":
                tools_done.append(str(step.get("tool_name", "")))
        elif obj.get("event") == "result":
            result = (obj.get("result") or {}).get("structured_output")
    return tools_done, result


def run_job(job, agy, logs):
    jid = job["id"]
    log_path, agy_log, out_path = logs / f"{jid}.log", logs / f"{jid}.agy.log", logs / f"{jid}.out.json"
    for stale in (agy_log, out_path):
        stale.unlink(missing_ok=True)
    row = {"event": "job", "id": jid, "mode": job["mode"], "exit": None, "seconds": 0.0, "timed_out": False,
           "error": None}
    cmd = build_cmd(agy, job, agy_log)
    if os.name == "nt" and len(subprocess.list2cmdline(cmd)) > CMDLINE_MAX:
        row.update(error="CMD_TOO_LONG", detail=f"{len(subprocess.list2cmdline(cmd))} chars")
        return row
    tmp = tempfile.TemporaryDirectory(prefix="agy-json-") if job["mode"] == "json" and not job["cwd"] else None
    cwd = job["cwd"] or (tmp.name if tmp else str(job["repo"]))
    killed = False
    start = time.monotonic()
    try:
        with open(log_path, "wb") as log:
            try:
                proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=(os.name != "nt"))
            except OSError as exc:
                row.update(error="LAUNCH_FAILED", detail=safe_error(exc))
                return row
            try:
                row["exit"] = proc.wait(timeout=job["timeout_s"] + KILL_GRACE_S)
            except subprocess.TimeoutExpired as exc:
                kill_tree(proc)
                row["exit"] = proc.wait()
                killed = True
                row["detail"] = safe_error(exc)
    finally:
        row["seconds"] = round(time.monotonic() - start, 1)
        if tmp:
            tmp.cleanup()

    text = log_path.read_text(encoding="utf-8", errors="replace")
    internal = agy_log.read_text(encoding="utf-8", errors="replace") if agy_log.is_file() else ""
    row["log_bytes"] = log_path.stat().st_size
    row["timed_out"] = killed or bool(PRINT_TIMEOUT_RE.search(text))
    tools_done, result = parse_stream(text) if job["mode"] == "json" else ([], None)
    failed = row["timed_out"] or row["exit"] != 0 or (job["mode"] == "json" and result is None)
    # stdout holds the model's own reply, which may quote these words; trust it only when the job failed.
    if QUOTA_RE.search(internal) or (failed and QUOTA_RE.search(text)):
        row["error"] = "AGY_QUOTA"
    elif failed and AUTH_RE.search(text + internal) and not AUTH_OK_RE.search(internal):
        row["error"] = "AGY_AUTH"
    elif row["timed_out"]:
        row["error"] = "TIMEOUT"
    elif row["exit"] != 0:
        row["error"] = "EXIT_NONZERO"
    elif job["mode"] == "json":
        breached = [t for t in tools_done if t != "search_web"]
        row["searched"] = len(tools_done) - len(breached)
        if breached:
            row.update(error="TOOL_BREACH", tools=sorted(set(breached)))
        elif result is None:
            row["error"] = "NO_RESULT"
        else:
            problems = validate(result, job["schema"])
            if problems:
                row.update(error="SCHEMA_MISMATCH", schema_errors=problems[:10])
            else:
                out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                row["out_bytes"] = out_path.stat().st_size
    return row


# ---- batch ----------------------------------------------------------------------------------------

def emit(summary, row):
    line = json.dumps(row, ensure_ascii=False)
    with _out_lock:
        print(line, flush=True)
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # JSON lines are UTF-8 even where Windows pipes use a code page
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Run headless agy jobs in parallel.")
    ap.add_argument("jobs")
    ap.add_argument("--logs", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--max-parallel", type=int, default=6)
    args = ap.parse_args(argv)
    try:
        if args.max_parallel < 1:
            raise ConfigError("BAD_MAX_PARALLEL", detail=str(args.max_parallel))
        jobs = load_jobs(args.jobs)
        agy = agy_command()
        root = git_root(args.repo)
        logs = Path(args.logs).resolve()
        logs.mkdir(parents=True, exist_ok=True)
        before = git_snapshot(root)
    except ConfigError as exc:
        print(json.dumps({"event": "config_error", "code": exc.code, "id": exc.job_id, "detail": exc.detail}))
        return 2
    summary = logs / "summary.jsonl"
    summary.write_text("", encoding="utf-8")
    for job in jobs:
        job["repo"] = root
    start = time.monotonic()
    rows = []

    def one(job):
        row = run_job(job, agy, logs)
        emit(summary, row)
        return row

    with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
        rows = list(pool.map(one, jobs))

    try:
        after = git_snapshot(root)
    except ConfigError as exc:
        emit(summary, {"event": "stray_check_failed", "code": exc.code, "detail": exc.detail})
        after = None
    stray = []
    if after is not None:
        try:
            logs_rel = logs.relative_to(root).as_posix()
        except ValueError:
            logs_rel = None
        allowed = [p for job in jobs for p in job["allowed_paths"]]
        for path in sorted(set(before) | set(after)):
            if before.get(path) == after.get(path):
                continue
            if logs_rel and (path == logs_rel or path.startswith(logs_rel + "/")):
                continue
            if not is_allowed(path, allowed):
                stray.append(path)
                emit(summary, {"event": "stray_write", "path": path})
    failed = [r["id"] for r in rows if r["error"]]
    code = 1 if failed or stray or after is None else 0
    emit(summary, {"event": "run", "jobs": len(rows), "failed": len(failed), "failed_ids": failed,
                   "stray_writes": len(stray), "seconds": round(time.monotonic() - start, 1), "exit": code})
    return code


if __name__ == "__main__":
    sys.exit(main())
