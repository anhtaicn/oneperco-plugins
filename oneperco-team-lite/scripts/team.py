"""Team mode lite: the deterministic state machine of core/SPEC.md (contract v1). Stdlib only.

    python team.py [--project <dir>] <command> [options]

Commands (each prints one JSON line; exit 0 ok, 1 refused or failed, 2 usage):
  init --brief-file F [--force]   start a run                                        -> brief
  plan --file F                   validate the PM's checklist and store it           -> planned
  approve --sha S                 the user approved the checklist whose SHA-256 is S -> approved
  build-start                     save point "before" (round 1, or round 2 after a fail) -> building
  build-done --claim-file F       store the Builder's claim, save point "after"      -> built
  evidence                        run every machine check of the approved checklist  -> evidence_ready
  tester-prompt --provider P      write the Tester prompt for this round (fresh-session input)
  test --provider P [--model M] [--quarantine Q] [--timeout S]   run a fresh read-only Tester, record it
  verdict --file F --provider P   record a raw verdict produced elsewhere (examples, tests)
  report                          render the Vietnamese report (.team/report.md)
  status | doctor
After a verdict: all items pass -> passed; a fail in round 1 -> failed; a fail in round 2 -> needs_decision.
State lives in <project>/.team/ (excluded from git). Output tails are redacted before they reach a Tester.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
import tester_cli  # noqa: E402

CONTRACT = 1
CORE = Path(__file__).resolve().parent.parent / "core"
MAX_ROUNDS = 2
MAX_INVALID_VERDICTS = 2
TAIL_CHARS = 3000
DIFF_CHARS = {"codex": 40000, "claude-fresh": 40000, "antigravity": 8000}
CONTENT_CHARS = 14000  # antigravity only: it cannot read files, and Windows caps the command line at 32k
TESTER_PROVIDERS = tester_cli.PROVIDERS
ENV_RE = re.compile(r"(^|/)\.env(\.[^/]+)?$")
ENV_OK_RE = re.compile(r"\.env\.(example|sample|template)$")
SECRET_RE = re.compile(r"(?i)([A-Za-z0-9_]*(?:key|token|secret|password|passwd)[A-Za-z0-9_]*\s*[=:]\s*)\S+")
FILE_REF_RE = re.compile(r"^file:(.+):(\d+)-(\d+)$")
TRANSITIONS = {
    "plan": {"brief", "planned"},
    "approve": {"planned"},
    "build-start": {"approved", "failed"},
    "build-done": {"building"},
    "evidence": {"built"},
    "tester-prompt": {"evidence_ready"},
    "test": {"evidence_ready"},
    "verdict": {"evidence_ready"},
}


class Refused(Exception):
    def __init__(self, code, **detail):
        super().__init__(code)
        self.code, self.detail = code, detail


# ---- JSON Schema subset (the same keywords as the delegate kit's runner) -------------------------

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
    """Return ["<path> <keyword>"] for every violation; values are never included."""
    types = schema.get("type")
    if types is not None and not any(_type_ok(value, t) for t in (types if isinstance(types, list) else [types])):
        return [f"{at} type"]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{at} enum")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{at} const")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            errors.append(f"{at} length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{at} pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            errors.append(f"{at} range")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            errors.append(f"{at} items")
        for i, item in enumerate(value):
            errors += validate(item, schema.get("items", {}), f"{at}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        errors += [f"{at}.{key} required" for key in schema.get("required", []) if key not in value]
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], f"{at}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{at}.{key} additionalProperties")
    return errors


def load_schema(name):
    return json.loads((CORE / "schemas" / name).read_text(encoding="utf-8"))


def checklist_problems(checklist):
    problems = validate(checklist, load_schema("checklist.schema.json"))
    if problems:
        return problems
    ids = [item["id"] for item in checklist["checklist"]]
    if len(ids) != len(set(ids)):
        problems.append("$.checklist duplicate id")
    need = {"command": ["argv"], "file_contains": ["path", "text"], "http_ok": ["url"], "review": ["look_for_vi"]}
    for item in checklist["checklist"]:
        check = item["check"]
        problems += [f"{item['id']} needs {key}" for key in need[check["kind"]] if key not in check]
        if check["kind"] == "file_contains" and not _inside_rel(check["path"]):
            problems.append(f"{item['id']} path must be relative, inside the project")
    return problems


def sha_of(checklist):
    return hashlib.sha256(json.dumps(checklist, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


# ---- state --------------------------------------------------------------------------------------

class Run:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.dir = self.project / ".team"
        self.state_path = self.dir / "state.json"

    def load(self):
        if not self.state_path.is_file():
            raise Refused("NO_RUN", hint="init first")
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state):
        self.dir.mkdir(exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def round_dir(self, state):
        path = self.dir / f"round-{state['round']}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def checklist(self):
        return json.loads((self.dir / "checklist.json").read_text(encoding="utf-8"))


def require(state, command):
    if state["state"] not in TRANSITIONS[command]:
        raise Refused("BAD_TRANSITION", command=command, state=state["state"],
                      allowed_from=sorted(TRANSITIONS[command]))


# ---- git save points ------------------------------------------------------------------------------

def git(project, *args, check=True):
    proc = subprocess.run(["git", "-C", str(project), *args], capture_output=True)
    if check and proc.returncode != 0:
        raise Refused("GIT_FAILED", args=list(args[:2]), exit=proc.returncode)
    return proc


def is_git_repo(project):
    return git(project, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() == b"true"


def exclude_team_dir(project):
    exclude = Path(git(project, "rev-parse", "--git-path", "info/exclude").stdout.decode("utf-8").strip())
    if not exclude.is_absolute():
        exclude = project / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    text = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if "/.team/" not in text.splitlines():
        exclude.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "/.team/\n", encoding="utf-8")


def changed_paths(project):
    out = git(project, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.decode("utf-8", "replace")
    fields, paths, i = out.split("\0"), [], 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if entry:
            paths.append(entry[3:])
            if entry[0] in "RC":
                i += 1
    return paths


def savepoint(project, label):
    """Commit everything (never a .env file) and return the short HEAD hash, or None outside git."""
    if not is_git_repo(project):
        return None
    exclude_team_dir(project)
    envs = [p for p in changed_paths(project) if ENV_RE.search(p) and not ENV_OK_RE.search(p)]
    if envs:
        raise Refused("ENV_FILE_WOULD_BE_COMMITTED", files=len(envs),
                      hint="add .env to .gitignore, then run again")
    git(project, "add", "-A")
    if git(project, "diff", "--cached", "--quiet", check=False).returncode != 0:
        ident = []
        if not git(project, "config", "user.email", check=False).stdout.strip():
            ident = ["-c", "user.name=team-lite", "-c", "user.email=team-lite@localhost"]
        git(project, *ident, "commit", "-q", "-m", f"team-lite: {label}")
    head = git(project, "rev-parse", "--short", "HEAD", check=False)
    return head.stdout.decode("utf-8").strip() if head.returncode == 0 else None


# ---- evidence -------------------------------------------------------------------------------------

def _inside_rel(rel):
    p = rel.replace("\\", "/")
    return bool(p) and not p.startswith("/") and ":" not in p and ".." not in p.split("/")


def redact(text):
    return SECRET_RE.sub(lambda m: m.group(1) + "***", text)


def run_command(project, check, work, eid):
    argv = list(check["argv"])
    program = shutil.which(argv[0], path=os.environ.get("PATH")) or (
        str(project / argv[0]) if (project / argv[0]).is_file() else None)
    row = {"kind": "command", "argv": list(check["argv"]), "expect_exit": check.get("expect_exit", 0)}
    if not program:
        return {**row, "exit": None, "ok": False, "error": "NOT_FOUND", "program": argv[0]}
    timeout = check.get("timeout_s", 300)
    log = work / f"{eid}.log"
    argv[0] = program
    if program.endswith(".py"):
        argv = [sys.executable] + argv
    try:
        code, timed_out, seconds = tester_cli.run_process(argv, project, log, timeout)
    except tester_cli.TesterError as exc:
        return {**row, "exit": None, "ok": False, "error": exc.code}
    tail = redact(log.read_text(encoding="utf-8", errors="replace")[-TAIL_CHARS:])
    ok = not timed_out and code == row["expect_exit"]
    return {**row, "exit": code, "timed_out": timed_out, "seconds": seconds, "ok": ok, "output_tail": tail}


def run_file_contains(project, check):
    path = project / check["path"]
    row = {"kind": "file_contains", "path": check["path"], "text": check["text"]}
    if not path.is_file():
        return {**row, "ok": False, "found": False, "missing": True}
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if check["text"] in line:
            return {**row, "ok": True, "found": True, "line": n}
    return {**row, "ok": False, "found": False}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a 3xx counts as an answer; never follow it off localhost


def run_http_ok(check):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(check["url"], timeout=10) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        return {"kind": "http_ok", "url": check["url"], "status": None, "ok": False,
                "error": tester_cli.safe_error(exc)}
    return {"kind": "http_ok", "url": check["url"], "status": status, "ok": 200 <= status < 400}


def collect_evidence(run, state):
    checklist = run.checklist()
    work = run.round_dir(state)
    evidence = []
    for item in checklist["checklist"]:
        check = item["check"]
        if check["kind"] == "review":
            continue
        eid = f"E{len(evidence) + 1}"
        if check["kind"] == "command":
            row = run_command(run.project, check, work, eid)
        elif check["kind"] == "file_contains":
            row = run_file_contains(run.project, check)
        else:
            row = run_http_ok(check)
        evidence.append({"id": eid, "item": item["id"], **row})
    bundle = {"contract_version": CONTRACT, "round": state["round"], "evidence": evidence,
              "changed_files": [], "diff_stat": "", "diff": ""}
    # The whole change since the first round: a fresh Tester re-checks every item, not only the rework.
    before = state["savepoints"][0]["before"] if state["savepoints"] else None
    if before and is_git_repo(run.project):
        rng = [f"{before}..HEAD", "--", ".", ":(exclude).team"]
        bundle["changed_files"] = git(run.project, "diff", "--name-only", *rng).stdout.decode("utf-8").split()
        bundle["diff_stat"] = git(run.project, "diff", "--stat", *rng).stdout.decode("utf-8", "replace")
        bundle["diff"] = redact(git(run.project, "diff", *rng).stdout.decode("utf-8", "replace"))
    (work / "evidence.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle


# ---- tester prompt and verdict --------------------------------------------------------------------

def numbered(project, rel, budget):
    path = project / rel
    if not path.is_file() or ENV_RE.search(rel):
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    text = f"=== {rel} ({len(lines)} lines) ===\n" + "\n".join(f"{n:4}| {line}" for n, line in enumerate(lines, 1))
    return text[:budget] + ("\n[cut: over budget]" if len(text) > budget else "")


def tester_prompt(run, state, provider):
    checklist = run.checklist()
    bundle = json.loads((run.round_dir(state) / "evidence.json").read_text(encoding="utf-8"))
    diff_cap = DIFF_CHARS[provider]
    diff = bundle["diff"][:diff_cap] + ("\n[diff cut: over budget]" if len(bundle["diff"]) > diff_cap else "")
    shown = {k: v for k, v in bundle.items() if k != "diff"}
    evidence = "```json\n" + json.dumps(shown, ensure_ascii=False, indent=2) + "\n```\n\nDiff of this round:\n```diff\n" \
        + diff + "\n```"
    files = sorted(set(bundle["changed_files"]) | {i["check"]["path"] for i in checklist["checklist"]
                                                     if i["check"].get("path")})
    if provider == "antigravity":
        budget = (f"You cannot read files: everything you may use is in this prompt. The project content below "
                  f"is cut at {CONTENT_CHARS} characters; an item you cannot check from it fails.")
        parts, left = [], CONTENT_CHARS
        for rel in files:
            if left <= 0:
                break
            block = numbered(run.project, rel, left)
            parts.append(block)
            left -= len(block)
        content = "Files with line numbers (cite them as file:<path>:<first>-<last>):\n\n" + "\n\n".join(p for p in parts if p)
    else:
        budget = ("Read at most 20 files and about 200 KB in total, starting with the changed files. The bundle and "
                  "diff below are already inside that budget.")
        content = ("You may read the project's files (read-only). The project root is your working directory. "
                   "Changed in this round: " + (", ".join(bundle["changed_files"]) or "(no git history: see the plan)")
                   + ".")
    items = [{"id": i["id"], "text_vi": i["text_vi"], "check": i["check"]} for i in checklist["checklist"]]
    template = (CORE / "prompts" / "tester.md").read_text(encoding="utf-8")
    prompt = (template.replace("{{BUDGET}}", budget)
              .replace("{{CHECKLIST}}", "```json\n" + json.dumps(items, ensure_ascii=False, indent=2) + "\n```")
              .replace("{{EVIDENCE}}", evidence).replace("{{CONTENT}}", content))
    path = run.round_dir(state) / f"tester_prompt.{provider}.md"
    path.write_text(prompt, encoding="utf-8")
    return prompt, path


def valid_ref(ref, project, evidence_ids):
    if ref in evidence_ids:
        return True
    match = FILE_REF_RE.match(ref)
    if not match:
        return False
    rel, first, last = match.group(1).replace("\\", "/"), int(match.group(2)), int(match.group(3))
    path = project / rel
    if not _inside_rel(rel) or not path.is_file() or ENV_RE.search(rel):
        return False
    count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return 1 <= first <= last <= count


def judge(raw, checklist, bundle, project):
    """Apply rule 4 and rule 5 to a raw verdict. Return (items, overall) or raise Refused if malformed."""
    problems = validate(raw, load_schema("verdict.schema.json"))
    ids = [i["id"] for i in checklist["checklist"]]
    if not problems:
        got = [i["id"] for i in raw["items"]]
        if len(got) != len(set(got)):
            problems.append("$.items duplicate id")
        problems += [f"$.items unknown id {i}" for i in sorted(set(got) - set(ids))]
    if problems:
        raise Refused("INVALID_VERDICT", problems=problems[:10])
    by_id = {i["id"]: i for i in raw["items"]}
    evidence_ids = {e["id"] for e in bundle["evidence"]}
    items = []
    for item in checklist["checklist"]:
        entry = by_id.get(item["id"])
        if entry is None:
            items.append({"id": item["id"], "result": "fail", "evidence": [], "reason_vi": "",
                          "override": "missing"})
            continue
        refs = [r for r in entry["evidence"] if valid_ref(r, project, evidence_ids)]
        machine = [e for e in bundle["evidence"] if e["item"] == item["id"]]
        result, override = entry["result"], None
        if result == "pass" and any(not e["ok"] for e in machine):
            result, override = "fail", "check_failed"
        elif result == "pass" and not refs:
            result, override = "fail", "no_evidence"
        items.append({"id": item["id"], "result": result, "evidence": refs,
                      "invalid_refs": [r for r in entry["evidence"] if r not in refs],
                      "reason_vi": entry["reason_vi"], "override": override})
    overall = "pass" if all(i["result"] == "pass" for i in items) else "fail"
    return items, overall


def record_verdict(run, state, raw, provider):
    checklist = run.checklist()
    bundle = json.loads((run.round_dir(state) / "evidence.json").read_text(encoding="utf-8"))
    entry = state["rounds"][-1]
    try:
        items, overall = judge(raw, checklist, bundle, run.project)
    except Refused:
        entry["invalid_verdicts"] += 1
        if entry["invalid_verdicts"] >= MAX_INVALID_VERDICTS:
            state["state"] = "needs_decision"
            state["stop_reason"] = "tester_invalid"
        run.save(state)
        raise
    entry.update(provider=provider, items=items, overall=overall, summary_vi=raw.get("summary_vi", ""))
    (run.round_dir(state) / "verdict.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")
    if overall == "pass":
        state["state"] = "passed"
    elif state["round"] < MAX_ROUNDS:
        state["state"] = "failed"
    else:
        state["state"] = "needs_decision"
        state["stop_reason"] = "two_fails"
    run.save(state)
    return {"overall": overall, "state": state["state"],
            "failed_items": [i["id"] for i in items if i["result"] == "fail"],
            "overrides": {i["id"]: i["override"] for i in items if i["override"]}}


# ---- report ---------------------------------------------------------------------------------------

def render_report(run, state):
    vi = json.loads((CORE / "locales" / "vi.json").read_text(encoding="utf-8"))

    def t(key, **kw):
        return vi[key].format(**kw)

    checklist = run.checklist() if (run.dir / "checklist.json").is_file() else None
    lines = []
    if checklist:
        lines += [f"# {t('report.title', title=checklist['title_vi'])}", "", t("report.goal", goal=checklist["goal_vi"]), ""]
    status = state["state"]
    if status in ("passed", "needs_decision"):
        lines.append(t(f"report.result.{status}"))
    elif status == "failed":
        lines.append(t("report.result.failed", round=state["round"]))
    else:
        lines.append(t("report.result.in_progress", state=t(f"state.{status}", round=state["round"])))
    last = state["rounds"][-1] if state["rounds"] and state["rounds"][-1].get("items") else None
    if last and checklist:
        bundle = json.loads((run.dir / f"round-{last['round']}" / "evidence.json").read_text(encoding="utf-8"))
        evidence = {e["id"]: e for e in bundle["evidence"]}
        texts = {i["id"]: i["text_vi"] for i in checklist["checklist"]}
        lines += ["", t("report.items")]
        for item in last["items"]:
            lines.append(t(f"report.item.{item['result']}", id=item["id"], text=texts[item["id"]]))
            if item["reason_vi"]:
                lines.append(t("report.item.reason", reason=item["reason_vi"]))
            said = [describe(evidence[r], vi) if r in evidence else describe_ref(r, vi) for r in item["evidence"]]
            said += [describe(e, vi) for e in bundle["evidence"] if e["item"] == item["id"] and e["id"] not in item["evidence"]]
            if said:
                lines.append(t("report.item.evidence", evidence="; ".join(said)))
            if item["override"]:
                lines.append(t(f"report.item.override.{item['override']}"))
        if last.get("summary_vi"):
            lines += ["", t("report.summary", summary=last["summary_vi"])]
        lines += ["", t("report.tester", provider=t(f"provider.{last['provider']}"), round=last["round"])]
        if last["provider"] == "claude-fresh":
            lines.append(t("report.tester.same_family"))
    if state["savepoints"]:
        before, after = state["savepoints"][0].get("before"), state["savepoints"][-1].get("after")
        if before or after:
            lines.append(t("report.savepoints", before=before or "-", after=after or "-"))
        else:
            lines.append(t("report.savepoints.none"))
    if state.get("claims"):
        lines.append(t("report.claim"))
    if status == "needs_decision":
        lines += ["", t("report.decision.options")]
    lines += ["", t("report.screenshots")]
    text = "\n".join(lines) + "\n"
    (run.dir / "report.md").write_text(text, encoding="utf-8")
    return text


def describe(e, vi):
    if e["kind"] == "command":
        cmd = " ".join(Path(e["argv"][0]).name if i == 0 else a for i, a in enumerate(e["argv"]))
        if e.get("error") == "NOT_FOUND":
            return vi["evidence.command.not_found"].format(program=e.get("program", ""))
        if e.get("timed_out"):
            return vi["evidence.command.timeout"].format(cmd=cmd, seconds=e.get("seconds"))
        key = "evidence.command.ok" if e["ok"] else "evidence.command.fail"
        return vi[key].format(cmd=cmd, exit=e["exit"], expect=e["expect_exit"])
    if e["kind"] == "file_contains":
        key = "ok" if e["ok"] else ("missing" if e.get("missing") else "fail")
        return vi[f"evidence.file_contains.{key}"].format(path=e["path"], text=e["text"], line=e.get("line"))
    return vi["evidence.http_ok.ok" if e["ok"] else "evidence.http_ok.fail"].format(
        url=e["url"], status=e.get("status") or e.get("error"))


def describe_ref(ref, vi):
    match = FILE_REF_RE.match(ref)
    return vi["evidence.file_ref"].format(path=match.group(1), first=match.group(2), last=match.group(3))


# ---- doctor ---------------------------------------------------------------------------------------

def doctor():
    found = {}
    for provider, resolve in tester_cli.RESOLVERS.items():
        try:
            argv = resolve()
            found[provider] = {"found": True, "exe": argv[-1]}
        except tester_cli.TesterError as exc:
            found[provider] = {"found": False, "error": exc.code}
    if found["codex"]["found"]:
        try:
            found["codex"]["logged_in"] = tester_cli.codex_logged_in(tester_cli.resolve_codex())
        except (OSError, subprocess.SubprocessError):
            found["codex"]["logged_in"] = False
    if found["antigravity"]["found"]:
        found["antigravity"]["quarantine_projects"] = quarantine_projects()
    order = [p for p in ("codex", "antigravity") if found[p]["found"]
             and found[p].get("logged_in", True) and found[p].get("quarantine_projects", [None])]
    order += ["claude-fresh"] if found["claude-fresh"]["found"] else []
    return {"python": sys.version.split()[0], "git": bool(shutil.which("git")), "providers": found,
            "tester_order": order}


def quarantine_projects():
    """Antigravity projects that deny every tool (the same test as the delegate plugin's doctor)."""
    deny_all = {"command(*)", "read_file(*)", "write_file(*)", "read_url(*)", "execute_url(*)", "mcp(*)"}
    folder = Path(os.environ.get("AGY_PROJECTS_DIR") or Path.home() / ".gemini" / "config" / "projects")
    names = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            deny = set(data["permissionGrants"]["permissionGrants"]["deny"] or [])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if deny_all <= deny and isinstance(data.get("name"), str):
            names.append(data["name"])
    return names


# ---- commands -------------------------------------------------------------------------------------

def read_json_file(path, code):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(code, error=tester_cli.safe_error(exc))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # JSON lines are UTF-8 even where Windows pipes use a code page
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Team mode lite state machine.")
    ap.add_argument("--project", default=".")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("--brief-file", required=True)
    p.add_argument("--force", action="store_true")
    sub.add_parser("plan").add_argument("--file", required=True)
    sub.add_parser("approve").add_argument("--sha", required=True)
    sub.add_parser("build-start")
    sub.add_parser("build-done").add_argument("--claim-file", required=True)
    sub.add_parser("evidence")
    sub.add_parser("tester-prompt").add_argument("--provider", required=True)
    p = sub.add_parser("test")
    p.add_argument("--provider", required=True)
    p.add_argument("--model")
    p.add_argument("--quarantine")
    p.add_argument("--timeout", type=int, default=900)
    p = sub.add_parser("verdict")
    p.add_argument("--file", required=True)
    p.add_argument("--provider", required=True)
    sub.add_parser("report")
    sub.add_parser("status")
    sub.add_parser("doctor")
    args = ap.parse_args(argv)
    run = Run(args.project)
    try:
        out = dispatch(run, args)
        print(json.dumps({"event": args.command, "ok": True, **out}, ensure_ascii=False))
        return 0
    except Refused as exc:
        print(json.dumps({"event": args.command, "ok": False, "code": exc.code, **exc.detail}, ensure_ascii=False))
        return 1


def dispatch(run, args):
    cmd = args.command
    if cmd == "doctor":
        return doctor()
    if cmd == "init":
        if run.state_path.is_file() and not args.force:
            current = run.load()["state"]
            if current not in ("passed", "needs_decision"):
                raise Refused("RUN_IN_PROGRESS", state=current, hint="finish it, or pass --force")
        brief = Path(args.brief_file).read_text(encoding="utf-8").strip()
        if not brief:
            raise Refused("EMPTY_BRIEF")
        if run.dir.is_dir():
            shutil.rmtree(run.dir)
        state = {"contract_version": CONTRACT, "state": "brief", "round": 0, "brief": brief,
                 "checklist_sha": None, "approved_sha": None, "savepoints": [], "rounds": [], "claims": []}
        run.save(state)
        return {"state": "brief"}
    state = run.load()
    if cmd == "status":
        return {"state": state["state"], "round": state["round"], "checklist_sha": state["checklist_sha"],
                "approved": state["approved_sha"] == state["checklist_sha"] and state["approved_sha"] is not None}
    if cmd == "report":
        text = render_report(run, state)
        return {"state": state["state"], "report": str(run.dir / "report.md"), "chars": len(text)}
    require(state, cmd)
    if cmd == "plan":
        checklist = read_json_file(args.file, "BAD_CHECKLIST_FILE")
        problems = checklist_problems(checklist)
        if problems:
            raise Refused("INVALID_CHECKLIST", problems=problems[:10])
        (run.dir / "checklist.json").write_text(json.dumps(checklist, ensure_ascii=False, indent=2), encoding="utf-8")
        state.update(state="planned", checklist_sha=sha_of(checklist), approved_sha=None)
        run.save(state)
        return {"state": "planned", "sha": state["checklist_sha"], "items": len(checklist["checklist"])}
    if cmd == "approve":
        current = sha_of(run.checklist())
        if args.sha != state["checklist_sha"] or current != state["checklist_sha"]:
            raise Refused("SHA_MISMATCH", hint="the checklist changed after it was shown; show it again")
        state.update(state="approved", approved_sha=current)
        run.save(state)
        return {"state": "approved"}
    if sha_of(run.checklist()) != state["approved_sha"]:
        raise Refused("CHECKLIST_CHANGED_AFTER_APPROVAL")
    if cmd == "build-start":
        state["round"] += 1
        state["savepoints"].append({"round": state["round"], "before": savepoint(run.project,
                                                                                  f"before build round {state['round']}"),
                                    "after": None})
        state["rounds"].append({"round": state["round"], "invalid_verdicts": 0})
        state["state"] = "building"
        run.save(state)
        last = state["rounds"][-2] if len(state["rounds"]) > 1 else None
        return {"state": "building", "round": state["round"], "savepoint": state["savepoints"][-1]["before"],
                "fix_items": [i["id"] for i in last["items"] if i["result"] == "fail"] if last else []}
    if cmd == "build-done":
        claim = Path(args.claim_file).read_text(encoding="utf-8").strip()
        claim_path = run.round_dir(state) / "builder_claim.md"
        claim_path.write_text(claim + "\n", encoding="utf-8")
        state["claims"].append({"round": state["round"], "file": claim_path.name})
        state["savepoints"][-1]["after"] = savepoint(run.project, f"after build round {state['round']}")
        state["state"] = "built"
        run.save(state)
        return {"state": "built", "savepoint": state["savepoints"][-1]["after"]}
    if cmd == "evidence":
        bundle = collect_evidence(run, state)
        state["state"] = "evidence_ready"
        run.save(state)
        return {"state": "evidence_ready", "evidence": [{"id": e["id"], "item": e["item"], "ok": e["ok"]}
                                                        for e in bundle["evidence"]],
                "changed_files": len(bundle["changed_files"])}
    provider = args.provider
    if provider not in TESTER_PROVIDERS:
        raise Refused("TESTER_IS_BUILDER" if provider == "claude" else "BAD_PROVIDER", provider=provider,
                      allowed=list(TESTER_PROVIDERS))
    if cmd == "tester-prompt":
        prompt, path = tester_prompt(run, state, provider)
        return {"prompt_file": str(path), "chars": len(prompt)}
    if cmd == "verdict":
        raw = read_json_file(args.file, "BAD_VERDICT_FILE")
        return record_verdict(run, state, raw, provider)
    prompt, _ = tester_prompt(run, state, provider)
    schema = CORE / "schemas" / "verdict.schema.json"
    try:
        raw, seconds = tester_cli.run_tester(provider, prompt, run.project, schema, run.round_dir(state),
                                             model=args.model, timeout_s=args.timeout, quarantine=args.quarantine)
    except tester_cli.TesterError as exc:
        raise Refused("TESTER_FAILED", provider=provider, error=exc.code, detail=exc.detail)
    (run.round_dir(state) / "verdict.raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
    return {"seconds": seconds, **record_verdict(run, state, raw, provider)}


if __name__ == "__main__":
    sys.exit(main())
