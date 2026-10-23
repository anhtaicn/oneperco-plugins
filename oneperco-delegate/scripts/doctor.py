"""Check what a delegation batch needs and print one JSON line. Stdlib only; reads, never writes.

    python doctor.py [--projects-dir <dir>]

Reports: the Python version, git, agy (AGY_BIN or PATH), and the Antigravity projects that are fit to be a
quarantine (every tool in QUARANTINE_DENY denied). Exit 0 when git and agy are found, 1 otherwise.
Never prints a project's folder or any other path inside the user's home beyond the agy executable.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

QUARANTINE_DENY = {"command(*)", "read_file(*)", "write_file(*)", "read_url(*)", "execute_url(*)", "mcp(*)"}


def projects_dir(override=None):
    return Path(override or os.environ.get("AGY_PROJECTS_DIR") or Path.home() / ".gemini" / "config" / "projects")


def quarantine_projects(folder):
    """Names of projects whose permissionGrants deny every tool in QUARANTINE_DENY."""
    names, unreadable = [], 0
    if not folder.is_dir():
        return names, unreadable
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            deny = set((((data.get("permissionGrants") or {}).get("permissionGrants") or {}).get("deny")) or [])
        except (OSError, ValueError, AttributeError):
            unreadable += 1
            continue
        if QUARANTINE_DENY <= deny and isinstance(data.get("name"), str):
            names.append(data["name"])
    return names, unreadable


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # JSON lines are UTF-8 even where Windows pipes use a code page
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Check the delegation prerequisites.")
    ap.add_argument("--projects-dir")
    args = ap.parse_args(argv)
    agy = os.environ.get("AGY_BIN") or shutil.which("agy")
    names, unreadable = quarantine_projects(projects_dir(args.projects_dir))
    row = {"event": "doctor", "python": sys.version.split()[0], "git": bool(shutil.which("git")),
           "agy": agy if agy and Path(agy).is_file() else None, "quarantine_projects": names,
           "unreadable_project_files": unreadable}
    row["ok"] = bool(row["git"] and row["agy"])
    print(json.dumps(row, ensure_ascii=False))
    return 0 if row["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
