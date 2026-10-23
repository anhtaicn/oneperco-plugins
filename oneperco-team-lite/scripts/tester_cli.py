"""Launch a fresh, read-only Tester through a provider's own CLI and return its raw verdict. Stdlib only.

Providers (core/SPEC.md, rule 1):
  codex         codex exec -s read-only --ephemeral --output-schema <schema> -o <file> -      (prompt on stdin)
  antigravity   agy -p <prompt> --project <quarantine> --sandbox --output-format stream-json --json-schema <schema>
                (gemini-* models only; the quarantine denies every tool, so the prompt carries the content)
  claude-fresh  claude -p --output-format json --json-schema <schema> --allowedTools Read,Grep,Glob (stdin)
Every executable is resolved to a real file and started with shell=False. An npm .cmd/.ps1 shim is never
run: codex is resolved to the native binary inside its npm package. No resume flag is ever passed, so
every call is a new session, and --bare is never passed. This module never logs the prompt, but a Tester
CLI may echo it into its own output (.team/round-N/tester.log), which stays in the local project.
CODEX_BIN, AGY_BIN and CLAUDE_BIN override the lookup (tests point them at .py fakes).
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROVIDERS = ("codex", "antigravity", "claude-fresh")
DEFAULT_AGY_MODEL = "gemini-3.8-flash-medium"  # flash-high with --json-schema hung in the kit's tests
CMDLINE_MAX = 32000
KILL_GRACE_S = 30
QUOTA_RE = re.compile(r"RESOURCE_EXHAUSTED|Individual quota reached|usage limit|rate limit", re.I)
AUTH_RE = re.compile(r"not logged in|Please run .*login|authentication", re.I)
MODEL_RE = re.compile(r"model is not supported|model_not_found|unknown model|does not exist or you do not have access", re.I)
SHIM_SUFFIXES = {".cmd", ".bat", ".ps1", ".js"}


class TesterError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def safe_error(exc):
    errno = getattr(exc, "errno", None)
    return type(exc).__name__ + (f" errno={errno}" if errno is not None else "")


# ---- executables ----------------------------------------------------------------------------------

def _override(var):
    value = os.environ.get(var)
    if not value:
        return None
    if not Path(value).is_file():
        raise TesterError("NOT_FOUND", var)
    return [sys.executable, value] if value.endswith(".py") else [value]


def _is_native(path):
    if path.suffix.lower() in SHIM_SUFFIXES:
        return False
    if os.name == "nt":
        return path.suffix.lower() == ".exe"
    with open(path, "rb") as fh:
        return fh.read(2) != b"#!"


def resolve_codex():
    """The native codex binary, never the npm shim (E6: the .ps1 shim broke on a path with spaces)."""
    override = _override("CODEX_BIN")
    if override:
        return override
    found = shutil.which("codex")
    if not found:
        raise TesterError("NOT_FOUND", "codex")
    path = Path(found).resolve()
    if _is_native(path):
        return [str(path)]
    roots = [path.parent / "node_modules" / "@openai" / "codex", path.parent.parent]
    name = "codex.exe" if os.name == "nt" else "codex"
    for root in roots:
        if root.is_dir():
            for candidate in sorted(root.glob(f"**/vendor/**/{name}")):
                if candidate.is_file() and candidate.parent.name in ("bin", "codex"):
                    return [str(candidate)]
    raise TesterError("SHIM_ONLY", "codex")


def resolve_agy():
    override = _override("AGY_BIN")
    if override:
        return override
    found = shutil.which("agy")
    if not found or not _is_native(Path(found)):
        raise TesterError("NOT_FOUND", "agy")
    return [found]


def resolve_claude():
    override = _override("CLAUDE_BIN")
    if override:
        return override
    found = shutil.which("claude")
    if not found:
        raise TesterError("NOT_FOUND", "claude")
    path = Path(found).resolve()
    if _is_native(path):
        return [str(path)]
    cli = path.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    node = shutil.which("node")
    if cli.is_file() and node:
        return [node, str(cli)]
    raise TesterError("SHIM_ONLY", "claude")


RESOLVERS = {"codex": resolve_codex, "antigravity": resolve_agy, "claude-fresh": resolve_claude}


def codex_models():
    """Model slugs the user's Codex lists for itself (its own cache), to suggest one with --model."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        cache = json.loads((home / "models_cache.json").read_text(encoding="utf-8"))
        return [m["slug"] for m in cache.get("models", []) if m.get("visibility") == "list" and m.get("slug")]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def codex_logged_in(codex):
    proc = subprocess.run(codex + ["login", "status"], capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
    return proc.returncode == 0


# ---- processes ------------------------------------------------------------------------------------

def kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    if proc.poll() is None:
        proc.kill()


def run_process(argv, cwd, log_path, timeout_s, stdin_text=None):
    """Run argv with shell=False, stdout+stderr to log_path. Return (exit, timed_out, seconds)."""
    if os.name == "nt" and len(subprocess.list2cmdline(argv)) > CMDLINE_MAX:
        raise TesterError("CMD_TOO_LONG", str(len(subprocess.list2cmdline(argv))))
    start = time.monotonic()
    with open(log_path, "wb") as log:
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                    start_new_session=(os.name != "nt"))
        except OSError as exc:
            raise TesterError("LAUNCH_FAILED", safe_error(exc))
        if stdin_text is not None:
            try:
                proc.stdin.write(stdin_text.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                pass  # the process exited early; its exit code and log tell why
        timed_out = False
        try:
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            code = proc.wait()
            timed_out = True
    return code, timed_out, round(time.monotonic() - start, 1)


# ---- providers ------------------------------------------------------------------------------------

def _classify_failure(text):
    if MODEL_RE.search(text):
        return "MODEL_UNSUPPORTED"
    if QUOTA_RE.search(text):
        return "QUOTA"
    if AUTH_RE.search(text):
        return "AUTH"
    return "EXIT_NONZERO"


def _parse_json_text(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                return None
    return None


def run_codex(prompt, project, schema_path, work, model, timeout_s):
    out = work / "tester.last.json"
    out.unlink(missing_ok=True)
    argv = resolve_codex() + ["exec", "-s", "read-only", "-C", str(project), "--ephemeral", "--skip-git-repo-check",
                              "--color", "never", "--output-schema", str(schema_path), "-o", str(out)]
    if model:
        argv += ["-m", model]
    argv.append("-")
    code, timed_out, seconds = run_process(argv, project, work / "tester.log", timeout_s + KILL_GRACE_S, prompt)
    log = (work / "tester.log").read_text(encoding="utf-8", errors="replace")
    if timed_out:
        raise TesterError("TIMEOUT", f"{seconds}s")
    if code != 0:
        failure = _classify_failure(log)
        raise TesterError(failure, ",".join(codex_models()) if failure == "MODEL_UNSUPPORTED" else f"exit {code}")
    raw = _parse_json_text(out.read_text(encoding="utf-8")) if out.is_file() else None
    if raw is None:
        raise TesterError("NO_RESULT")
    return raw, seconds


def run_antigravity(prompt, project, schema_path, work, model, timeout_s, quarantine):
    model = model or DEFAULT_AGY_MODEL
    if not model.startswith("gemini-"):
        raise TesterError("SAME_FAMILY_MODEL", model)  # agy also serves Claude models; the Tester must differ
    if not quarantine:
        raise TesterError("NEEDS_QUARANTINE")
    schema = json.dumps(json.loads(Path(schema_path).read_text(encoding="utf-8")), separators=(",", ":"))
    agy_log = work / "tester.agy.log"
    argv = resolve_agy() + ["-p", prompt, "--model", model, "--project", quarantine, "--sandbox",
                            "--output-format", "stream-json", "--json-schema", schema,
                            "--print-timeout", f"{timeout_s}s", "--log-file", str(agy_log)]
    with tempfile.TemporaryDirectory(prefix="team-tester-") as empty:
        code, timed_out, seconds = run_process(argv, empty, work / "tester.log", timeout_s + KILL_GRACE_S)
    text = (work / "tester.log").read_text(encoding="utf-8", errors="replace")
    internal = agy_log.read_text(encoding="utf-8", errors="replace") if agy_log.is_file() else ""
    tools, raw = [], None
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
                tools.append(str(step.get("tool_name", "")))
        elif obj.get("event") == "result":
            raw = (obj.get("result") or {}).get("structured_output")
    if timed_out or re.search(r"^\[agy\] print timeout after", text, re.M):
        raise TesterError("TIMEOUT", f"{seconds}s")
    if code != 0 or raw is None:
        if QUOTA_RE.search(internal):
            raise TesterError("QUOTA")
        if "not logged into Antigravity" in internal and "applyAuthResult" not in internal:
            raise TesterError("AUTH")
        raise TesterError("EXIT_NONZERO" if code != 0 else "NO_RESULT", f"exit {code}")
    breached = sorted({t for t in tools if t != "search_web"})
    if breached:
        raise TesterError("TOOL_BREACH", ",".join(breached))
    return raw, seconds


def run_claude_fresh(prompt, project, schema_path, work, model, timeout_s):
    schema = json.dumps(json.loads(Path(schema_path).read_text(encoding="utf-8")), separators=(",", ":"))
    argv = resolve_claude() + ["-p", "--output-format", "json", "--json-schema", schema,
                               "--allowedTools", "Read,Grep,Glob",
                               "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent"]
    if model:
        argv += ["--model", model]
    code, timed_out, seconds = run_process(argv, project, work / "tester.log", timeout_s, prompt)
    text = (work / "tester.log").read_text(encoding="utf-8", errors="replace")
    if timed_out:
        raise TesterError("TIMEOUT", f"{seconds}s")
    envelope = _parse_json_text(text)
    if code != 0 or not isinstance(envelope, dict) or envelope.get("is_error"):
        raise TesterError(_classify_failure(text), f"exit {code}")
    raw = envelope.get("structured_output")
    if raw is None and isinstance(envelope.get("result"), str):
        raw = _parse_json_text(envelope["result"])
    if raw is None:
        raise TesterError("NO_RESULT")
    return raw, seconds


def run_tester(provider, prompt, project, schema_path, work, model=None, timeout_s=900, quarantine=None):
    """Return (raw verdict, seconds) or raise TesterError."""
    work.mkdir(parents=True, exist_ok=True)
    if provider == "codex":
        return run_codex(prompt, project, schema_path, work, model, timeout_s)
    if provider == "antigravity":
        return run_antigravity(prompt, project, schema_path, work, model, timeout_s, quarantine)
    if provider == "claude-fresh":
        return run_claude_fresh(prompt, project, schema_path, work, model, timeout_s)
    raise TesterError("BAD_PROVIDER", provider)
