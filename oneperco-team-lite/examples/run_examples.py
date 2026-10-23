"""Run the three team-mode examples end to end and compare each with its expect.json. Stdlib only.

    python run_examples.py [--only 01] [--live --provider codex|antigravity|claude-fresh [--quarantine Q] [--model M]] [--keep]

Each example copies shared/project into a fresh temporary git repository and drives scripts/team.py
through init, plan, approve, then up to two rounds of build-start, the round's files (a scripted
Builder), build-done, evidence and test, then report. Offline the Tester is fake_tester.py playing the
example's verdict.roundN.json; --live launches the real Tester CLI. Prints one JSON line per example;
exit 0 when every example matches.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEAM = HERE.parent / "scripts" / "team.py"
SHARED = HERE / "shared"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=example@example.invalid", "-c", "user.name=example",
                    *args], check=True, capture_output=True)


def team(project, *args, env=None):
    proc = subprocess.run([sys.executable, str(TEAM), "--project", str(project), *args], capture_output=True,
                          env=env)
    lines = [line for line in proc.stdout.decode("utf-8").splitlines() if line.startswith("{")]
    return proc.returncode, (json.loads(lines[-1]) if lines else {"raw": proc.stdout.decode("utf-8", "replace")})


def run_one(example, args):
    expect = json.loads((example / "expect.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix=f"team-{example.name[:2]}-"))
    project, problems, rounds = tmp / "project", [], []
    try:
        shutil.copytree(SHARED / "project", project)
        git(project, "init", "-q")
        git(project, "add", ".")
        git(project, "commit", "-q", "-m", "base")
        env = dict(os.environ)
        provider = args.provider if args.live else "codex"
        if not args.live:
            env["CODEX_BIN"] = str(HERE / "fake_tester.py")

        def step(*cmd):
            code, row = team(project, *cmd, env=env)
            if code != 0:
                raise RuntimeError(f"{cmd[0]} refused: {row}")
            return row

        step("init", "--brief-file", str(SHARED / "brief.txt"))
        sha = step("plan", "--file", str(SHARED / "checklist.json"))["sha"]
        step("approve", "--sha", sha)
        for n in (1, 2):
            step("build-start")
            for src in (example / f"round{n}").iterdir():
                shutil.copy2(src, project / src.name)
            claim = tmp / "claim.md"
            claim.write_text(f"Đã sửa index.html (vòng {n}).\n", encoding="utf-8")
            step("build-done", "--claim-file", str(claim))
            step("evidence")
            env["FAKE_VERDICT"] = str(example / f"verdict.round{n}.json")
            test = ["test", "--provider", provider] + (["--quarantine", args.quarantine] if args.quarantine else []) \
                + (["--model", args.model] if args.model else [])
            row = step(*test)
            rounds.append({k: row.get(k) for k in ("overall", "failed_items", "overrides")})
            if row["state"] in ("passed", "needs_decision"):
                break
        final = step("status")["state"]
        step("report")
        report = (project / ".team" / "report.md").read_text(encoding="utf-8")
        want = expect["live_final_state"] if args.live else expect["final_state"]
        if final != want:
            problems.append(f"final state {final}, expected {want}")
        if not args.live and rounds != expect["rounds"]:
            problems.append(f"rounds {rounds}, expected {expect['rounds']}")
        problems += [f"report lacks {s!r}" for s in expect["report_contains"] if not args.live and s not in report]
        log = subprocess.run(["git", "-C", str(project), "log", "--format=%s"], capture_output=True).stdout.decode()
        if "team-lite: after build round 1" not in log:
            problems.append("no save point commit after round 1")
    except (RuntimeError, OSError, subprocess.CalledProcessError, KeyError) as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        if problems and args.keep:
            problems.append(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return problems, rounds


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # JSON lines are UTF-8 even where Windows pipes use a code page
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Run the team-mode examples.")
    ap.add_argument("--only")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--provider", default="codex")
    ap.add_argument("--quarantine")
    ap.add_argument("--model")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder of a failing example")
    args = ap.parse_args(argv)
    examples = sorted(p for p in HERE.iterdir() if (p / "expect.json").is_file()
                      and (not args.only or p.name.startswith(args.only)))
    failed = 0
    for example in examples:
        problems, rounds = run_one(example, args)
        failed += bool(problems)
        print(json.dumps({"event": "example", "name": example.name, "live": args.live,
                          "provider": args.provider if args.live else "fake", "ok": not problems,
                          "rounds": rounds, "problems": problems}, ensure_ascii=False))
    print(json.dumps({"event": "examples", "total": len(examples), "failed": failed}))
    return 1 if failed or not examples else 0


if __name__ == "__main__":
    sys.exit(main())
