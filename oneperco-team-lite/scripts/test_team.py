"""Offline tests for team.py and tester_cli.py, plus one mutant per rule: each mutant is a one-line change
to a copy of the scripts that the named case must catch.

    python test_team.py      # exit 0 = suite green and every mutant caught

Cases cover section 7 rules 1 to 6 (core/SPEC.md): the approval binding, transitions, the .env refusal,
the verdict overrides, evidence refs, invalid verdicts, the Tester launch argv, and output redaction.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
EXAMPLES = PLUGIN / "examples"

FAKE_CLI = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
stdin = sys.stdin.read()
Path(os.environ["FAKE_RECORD"]).write_text(json.dumps({"argv": args}))
verdict = Path(os.environ["FAKE_VERDICT"]).read_text(encoding="utf-8")
if "-o" in args:
    Path(args[args.index("-o") + 1]).write_text(verdict, encoding="utf-8")
elif "--output-format" in args and args[args.index("--output-format") + 1] == "stream-json":
    print(json.dumps({"event": "result", "result": {"structured_output": json.loads(verdict)}}))
else:
    print(json.dumps({"type": "result", "is_error": False, "structured_output": json.loads(verdict)}))
'''

# (name, file, old text, replacement, prefix of the case that must fail)
MUTANTS = [
    ("pass without evidence stands", "team.py", 'elif result == "pass" and not refs:', "elif False:", "verdict:"),
    ("pass against a failed check stands", "team.py",
     'if result == "pass" and any(not e["ok"] for e in machine):', "if False:", "verdict:"),
    ("a third round is allowed", "team.py", "MAX_ROUNDS = 2", "MAX_ROUNDS = 3", "rounds:"),
    ("claude may test its own work", "team.py", "if provider not in TESTER_PROVIDERS:",
     'if provider not in TESTER_PROVIDERS + ("claude",):', "provider:"),
    ("approval not bound to the checklist", "team.py", 'if sha_of(run.checklist()) != state["approved_sha"]:',
     "if False:", "approval:"),
    ("a .env file gets committed", "team.py", "    if envs:", "    if False:", "env:"),
    ("file ref lines unchecked", "team.py", "return 1 <= first <= last <= count", "return True", "refs:"),
    ("output tails not redacted", "team.py", 'return SECRET_RE.sub(lambda m: m.group(1) + "***", text)',
     "return text", "redact:"),
    ("codex Tester gets write access", "tester_cli.py", '"exec", "-s", "read-only"', '"exec", "-s", "workspace-write"',
     "launch:"),
    ("agy Tester may use a Claude model", "tester_cli.py", 'if not model.startswith("gemini-"):', "if False:",
     "launch:"),
]


class Suite:
    def __init__(self, scripts, tmp, verbose):
        self.team, self.tmp, self.verbose, self.failed, self.n = scripts / "team.py", tmp, verbose, [], 0

    def check(self, name, condition, detail=""):
        if self.verbose:
            print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  {detail}"))
        if not condition:
            self.failed.append(name)

    def project(self, files=None):
        self.n += 1
        root = self.tmp / f"p{self.n}"
        shutil.copytree(EXAMPLES / "shared" / "project", root)
        for rel, text in (files or {}).items():
            (root / rel).write_text(text, encoding="utf-8")
        for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "base"]):
            subprocess.run(["git", "-C", str(root), "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                           check=True, capture_output=True)
        return root

    def run(self, project, *args, env=None):
        proc = subprocess.run([sys.executable, str(self.team), "--project", str(project), *args], capture_output=True,
                              env=env)
        lines = [line for line in proc.stdout.decode("utf-8").splitlines() if line.startswith("{")]
        try:
            return proc.returncode, json.loads(lines[-1])
        except (IndexError, ValueError):
            return proc.returncode, {"crash": proc.stderr.decode("utf-8", "replace")[-300:]}

    def to_evidence(self, project, html, checklist=None, rounds=1, verdicts=()):
        """Drive a run to evidence_ready in the given round; earlier rounds get the given raw verdicts."""
        self.run(project, "init", "--brief-file", str(EXAMPLES / "shared" / "brief.txt"))
        path = checklist or EXAMPLES / "shared" / "checklist.json"
        _, row = self.run(project, "plan", "--file", str(path))
        self.run(project, "approve", "--sha", row.get("sha", ""))
        for n in range(1, rounds + 1):
            self.run(project, "build-start")
            (project / "index.html").write_text(html, encoding="utf-8")
            claim = project.parent / f"claim{self.n}.md"
            claim.write_text("done\n", encoding="utf-8")
            self.run(project, "build-done", "--claim-file", str(claim))
            self.run(project, "evidence")
            if n < rounds:
                self.verdict(project, verdicts[n - 1])

    def verdict(self, project, raw, provider="codex"):
        path = project.parent / f"verdict{self.n}-{os.urandom(3).hex()}.json"
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return self.run(project, "verdict", "--file", str(path), "--provider", provider)


GOOD = (EXAMPLES / "01-pass-first-round" / "round1" / "index.html").read_text(encoding="utf-8")
NO_REQUIRED = GOOD.replace(" required", "")


def all_pass(refs3="file:index.html:6-10"):
    return {"items": [{"id": "C1", "result": "pass", "evidence": ["E1"], "reason_vi": "x"},
                      {"id": "C2", "result": "pass", "evidence": ["E2"], "reason_vi": "x"},
                      {"id": "C3", "result": "pass", "evidence": [refs3] if refs3 else [], "reason_vi": "x"}],
            "summary_vi": "x"}


def test_approval(s):
    p = s.project()
    s.run(p, "init", "--brief-file", str(EXAMPLES / "shared" / "brief.txt"))
    _, row = s.run(p, "plan", "--file", str(EXAMPLES / "shared" / "checklist.json"))
    code, out = s.run(p, "approve", "--sha", "0" * 64)
    s.check("approval: wrong sha refused", code == 1 and out.get("code") == "SHA_MISMATCH", out)
    s.run(p, "approve", "--sha", row["sha"])
    stored = json.loads((p / ".team" / "checklist.json").read_text(encoding="utf-8"))
    stored["checklist"][0]["text_vi"] = "đổi sau khi duyệt"
    (p / ".team" / "checklist.json").write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    code, out = s.run(p, "build-start")
    s.check("approval: checklist edited after approval refused",
            code == 1 and out.get("code") == "CHECKLIST_CHANGED_AFTER_APPROVAL", out)


def test_transitions(s):
    p = s.project()
    s.run(p, "init", "--brief-file", str(EXAMPLES / "shared" / "brief.txt"))
    code, out = s.run(p, "evidence")
    s.check("transitions: evidence before build refused", code == 1 and out.get("code") == "BAD_TRANSITION", out)
    code, out = s.run(p, "init", "--brief-file", str(EXAMPLES / "shared" / "brief.txt"))
    s.check("transitions: init over a run in progress refused", out.get("code") == "RUN_IN_PROGRESS", out)
    bad = json.loads((EXAMPLES / "shared" / "checklist.json").read_text(encoding="utf-8"))
    bad["checklist"][0]["check"] = {"kind": "http_ok", "url": "https://example.com/"}
    path = p.parent / "bad_checklist.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    code, out = s.run(p, "plan", "--file", str(path))
    s.check("transitions: a non-localhost URL is refused", out.get("code") == "INVALID_CHECKLIST", out)


def test_env(s):
    p = s.project({".env": "API_KEY=abc\n"})
    s.run(p, "init", "--brief-file", str(EXAMPLES / "shared" / "brief.txt"))
    _, row = s.run(p, "plan", "--file", str(EXAMPLES / "shared" / "checklist.json"))
    s.run(p, "approve", "--sha", row["sha"])
    (p / ".env").write_text("API_KEY=changed\n", encoding="utf-8")
    code, out = s.run(p, "build-start")
    s.check("env: a modified .env blocks the save point", code == 1 and out.get("code") == "ENV_FILE_WOULD_BE_COMMITTED", out)
    q = s.project()
    (q / ".env.local").write_text("TOKEN=abc\n", encoding="utf-8")
    s.run(q, "init", "--brief-file", str(EXAMPLES / "shared" / "brief.txt"))
    _, row = s.run(q, "plan", "--file", str(EXAMPLES / "shared" / "checklist.json"))
    s.run(q, "approve", "--sha", row["sha"])
    code, out = s.run(q, "build-start")
    s.check("env: an untracked .env.local blocks the save point", out.get("code") == "ENV_FILE_WOULD_BE_COMMITTED", out)


def test_verdict(s):
    p = s.project()
    s.to_evidence(p, NO_REQUIRED)
    code, out = s.verdict(p, all_pass())
    s.check("verdict: a pass against a failed check becomes a fail",
            out.get("overrides", {}).get("C1") == "check_failed" and out.get("overall") == "fail", out)
    q = s.project()
    s.to_evidence(q, GOOD)
    code, out = s.verdict(q, all_pass(refs3=None))
    s.check("verdict: a pass with no evidence becomes a fail",
            out.get("overrides", {}).get("C3") == "no_evidence" and out.get("state") == "failed", out)
    r = s.project()
    s.to_evidence(r, GOOD)
    raw = all_pass()
    raw["items"] = raw["items"][:2]
    code, out = s.verdict(r, raw)
    s.check("verdict: a missing item is a fail", out.get("overrides", {}).get("C3") == "missing", out)
    t = s.project()
    s.to_evidence(t, GOOD)
    code, out = s.verdict(t, all_pass())
    s.check("verdict: all items with evidence pass", code == 0 and out.get("state") == "passed", out)
    report = (t / ".team" / "report.md").read_text(encoding="utf-8") if s.run(t, "report")[0] == 0 else ""
    s.check("verdict: the report is Vietnamese and says ĐẠT", "Kết quả: ĐẠT" in report, report[:200])


def test_refs(s):
    for name, ref in (("past the last line", "file:index.html:6-99"), ("outside the project", "file:../x.html:1-1"),
                      ("a .env file", "file:.env:1-1"), ("an unknown evidence id", "E9")):
        p = s.project({".env": "A=1\n"} if ".env" in ref else None)
        s.to_evidence(p, GOOD)
        code, out = s.verdict(p, all_pass(refs3=ref))
        s.check(f"refs: {name} is not evidence", out.get("overrides", {}).get("C3") == "no_evidence", out)


def test_invalid(s):
    p = s.project()
    s.to_evidence(p, GOOD)
    raw = all_pass()
    raw["items"].append({"id": "C9", "result": "pass", "evidence": ["E1"], "reason_vi": "x"})
    code, out = s.verdict(p, raw)
    s.check("invalid: an unknown id makes the verdict invalid", out.get("code") == "INVALID_VERDICT", out)
    code, out = s.run(p, "status")
    s.check("invalid: the round is not consumed", out.get("state") == "evidence_ready", out)
    s.verdict(p, {"items": "nope"})
    code, out = s.run(p, "status")
    s.check("invalid: a second invalid verdict stops the run", out.get("state") == "needs_decision", out)


def test_rounds(s):
    p = s.project()
    fail = all_pass()
    fail["items"][0]["result"] = "fail"
    s.to_evidence(p, NO_REQUIRED, rounds=2, verdicts=[fail])
    code, out = s.verdict(p, fail)
    s.check("rounds: a fail in round 2 needs the user's decision", out.get("state") == "needs_decision", out)
    code, out = s.run(p, "build-start")
    s.check("rounds: no third round", code == 1 and out.get("code") == "BAD_TRANSITION", out)


def test_provider(s):
    p = s.project()
    s.to_evidence(p, GOOD)
    code, out = s.verdict(p, all_pass(), provider="claude")
    s.check("provider: claude cannot test its own work", out.get("code") == "TESTER_IS_BUILDER", out)
    code, out = s.run(p, "test", "--provider", "claude")
    s.check("provider: not even through test", out.get("code") == "TESTER_IS_BUILDER", out)


def test_launch(s):
    fake = s.tmp / "fake_cli.py"
    fake.write_text(FAKE_CLI, encoding="utf-8")
    record, verdict = s.tmp / "record.json", s.tmp / "fake_verdict.json"
    verdict.write_text(json.dumps(all_pass(), ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, CODEX_BIN=str(fake), AGY_BIN=str(fake), CLAUDE_BIN=str(fake), FAKE_RECORD=str(record),
               FAKE_VERDICT=str(verdict))
    for provider, extra, check in (
        ("codex", [], lambda a: a[:3] == ["exec", "-s", "read-only"] and a[-1] == "-" and "--ephemeral" in a),
        ("antigravity", ["--quarantine", "q"], lambda a: a[a.index("--project") + 1] == "q" and "--sandbox" in a
         and a[a.index("--model") + 1].startswith("gemini-")),
        ("claude-fresh", [], lambda a: a[a.index("--allowedTools") + 1] == "Read,Grep,Glob" and "--bare" not in a),
    ):
        p = s.project()
        s.to_evidence(p, GOOD)
        code, out = s.run(p, "test", "--provider", provider, *extra, env=env)
        argv = json.loads(record.read_text())["argv"] if record.is_file() else []
        record.unlink(missing_ok=True)
        s.check(f"launch: {provider} passes", code == 0 and out.get("state") == "passed", out)
        s.check(f"launch: {provider} argv", check(argv) and not any(a.startswith("--dangerously") or "bypass" in a
                                                                    or a in ("--resume", "--continue", "-c")
                                                                    for a in argv), argv)
    p = s.project()
    s.to_evidence(p, GOOD)
    code, out = s.run(p, "test", "--provider", "antigravity", "--quarantine", "q", "--model", "claude-opus-4-6-thinking",
                      env=env)
    s.check("launch: antigravity refuses a Claude model", out.get("error") == "SAME_FAMILY_MODEL", out)


def test_redact(s):
    p = s.project({"leak.py": "print('API_KEY=supersecret123')\n"})
    checklist = json.loads((EXAMPLES / "shared" / "checklist.json").read_text(encoding="utf-8"))
    checklist["checklist"][0]["check"] = {"kind": "command", "argv": ["leak.py"]}
    path = p.parent / f"leak_checklist{s.n}.json"
    path.write_text(json.dumps(checklist, ensure_ascii=False), encoding="utf-8")
    s.to_evidence(p, GOOD, checklist=path)
    bundle = (p / ".team" / "round-1" / "evidence.json").read_text(encoding="utf-8")
    s.check("redact: secrets in output tails are masked", "supersecret123" not in bundle and "API_KEY=***" in bundle,
            bundle[:300])


CASES = [test_approval, test_transitions, test_env, test_verdict, test_refs, test_invalid, test_rounds, test_provider,
         test_launch, test_redact]


def run_suite(scripts, verbose):
    with tempfile.TemporaryDirectory(prefix="team-test-") as tmp:
        s = Suite(scripts, Path(tmp), verbose)
        for case in CASES:
            try:
                case(s)
            except Exception as exc:  # a mutant may crash a case; that counts as caught, never as a pass
                s.failed.append(f"{case.__name__[5:]}: crashed {type(exc).__name__}")
        return s.failed


def main():
    if hasattr(sys.stdout, "reconfigure"):  # JSON lines are UTF-8 even where Windows pipes use a code page
        sys.stdout.reconfigure(encoding="utf-8")
    failed = run_suite(HERE, verbose=True)
    print("\nsuite: " + ("ALL PASSED" if not failed else f"{len(failed)} FAILED"))
    if failed:
        return 1
    survived = []
    with tempfile.TemporaryDirectory(prefix="team-mutants-") as tmp:
        for i, (name, file, old, new, case) in enumerate(MUTANTS):
            root = Path(tmp) / f"m{i}"
            shutil.copytree(PLUGIN / "core", root / "core")
            shutil.copytree(HERE, root / "scripts", ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
            src = (root / "scripts" / file).read_text(encoding="utf-8")
            if src.count(old) != 1:
                print(f"MUTANT BROKEN {name}: anchor found {src.count(old)} times")
                survived.append(name)
                continue
            (root / "scripts" / file).write_text(src.replace(old, new), encoding="utf-8")
            hits = [f for f in run_suite(root / "scripts", verbose=False) if f.startswith(case)]
            print(f"MUTANT {'CAUGHT  ' if hits else 'SURVIVED'} {name}  ({case} {len(hits)} failing)")
            if not hits:
                survived.append(name)
    print(f"\nmutants: {len(MUTANTS) - len(survived)}/{len(MUTANTS)} caught")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
