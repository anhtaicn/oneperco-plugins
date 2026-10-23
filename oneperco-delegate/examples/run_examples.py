"""Run the three examples and compare each with its expect.json. Stdlib only.

    python run_examples.py [--only 01] [--live --project <quarantine name>] [--keep]

Offline (default) the executor is fake_agy.py, so no account is needed. --live runs the real `agy`
(example 01 also needs --project). Each example runs in a fresh temporary git repository; nothing is
written to this folder. Prints one JSON line per example; exit 0 when every example matches.
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
RUNNER = HERE.parent / "scripts" / "run_agy.py"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=example@example.invalid", "-c", "user.name=example",
                    *args], check=True, capture_output=True)


def prepare(example, tmp, project):
    repo, scratch = tmp / "repo", tmp / "scratch"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "README.md").write_text("example repository\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    shutil.copytree(example, scratch)
    jobs = (scratch / "jobs.json").read_text(encoding="utf-8")
    jobs = jobs.replace("{{REPO}}", repo.as_posix()).replace("{{PROJECT}}", project or "")
    (scratch / "jobs.json").write_text(jobs, encoding="utf-8")
    return repo, scratch


def run_one(example, live, project, keep):
    expect = json.loads((example / "expect.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix=f"delegate-{example.name[:2]}-"))
    problems = []
    try:
        repo, scratch = prepare(example, tmp, project if live else "fake-quarantine")
        env = dict(os.environ)
        if not live:
            env["AGY_BIN"] = str(HERE / "fake_agy.py")
            env["FAKE_AGY_PLAN"] = str(example / "fake_plan.json")
        logs = tmp / "logs"
        proc = subprocess.run([sys.executable, str(RUNNER), str(scratch / "jobs.json"), "--logs", str(logs),
                               "--repo", str(repo)], capture_output=True, env=env)
        rows = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.startswith("{")]
        if proc.returncode != expect["exit"]:
            problems.append(f"runner exit {proc.returncode}, expected {expect['exit']}")
            problems += [json.dumps(r) for r in rows if r.get("event") == "config_error"]
        stray = sorted(r["path"] for r in rows if r.get("event") == "stray_write")
        if stray != sorted(expect["stray_writes"]):
            problems.append(f"stray writes {stray}, expected {expect['stray_writes']}")
        errors = {r["id"]: r["error"] for r in rows if r.get("event") == "job" and r.get("error")}
        if errors != expect["errors"]:
            problems.append(f"job errors {errors}, expected {expect['errors']}")
        for jid, fields in expect.get("outputs", {}).items():
            out = logs / f"{jid}.out.json"
            got = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
            if got is None or any(got.get(k) != v for k, v in fields.items()):
                problems.append(f"{jid} output {got}, expected {fields}")
        for jid in expect.get("checker", []):
            check = subprocess.run([sys.executable, str(scratch / "checker.py"), str(repo), jid], capture_output=True)
            if check.returncode != 0:
                problems.append(f"checker {jid} exit {check.returncode}: {check.stdout.decode('utf-8').strip()}")
        if problems and keep:
            problems.append(f"kept {tmp}")
    finally:
        if not (problems and keep):
            shutil.rmtree(tmp, ignore_errors=True)
    return problems


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # JSON lines are UTF-8 even where Windows pipes use a code page
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Run the delegate examples.")
    ap.add_argument("--only")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder of a failing example")
    args = ap.parse_args(argv)
    examples = sorted(p for p in HERE.iterdir() if p.is_dir() and (p / "expect.json").is_file()
                      and (not args.only or p.name.startswith(args.only)))
    if not examples:
        print(json.dumps({"event": "usage", "detail": "no example matches --only"}))
        return 2
    failed = 0
    for example in examples:
        if args.live and "{{PROJECT}}" in (example / "jobs.json").read_text(encoding="utf-8") and not args.project:
            print(json.dumps({"event": "example", "name": example.name, "ok": False,
                              "problems": ["--live needs --project <quarantine name> for this example"]}))
            failed += 1
            continue
        problems = run_one(example, args.live, args.project, args.keep)
        failed += bool(problems)
        print(json.dumps({"event": "example", "name": example.name, "live": args.live, "ok": not problems,
                          "problems": problems}, ensure_ascii=False))
    print(json.dumps({"event": "examples", "total": len(examples), "failed": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
