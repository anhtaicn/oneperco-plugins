"""Create an isolated ("quarantine") Antigravity project for `json` jobs. Stdlib only.

    python make_quarantine.py --name <name> --folder <empty dir outside any repo> [--yes] [--projects-dir <dir>]

Without --yes it writes nothing: it prints the file it would create and exits 3, so the user can agree
first. With --yes it creates the empty folder if needed and writes <projects-dir>/<uuid>.json.
The project denies every tool at the tool level, which overrides the user's global Antigravity
permissions (verified with a canary, agy 1.4.x). It never edits the global config or another project.

Exit 0 created (or an identical quarantine already exists), 2 bad input, 3 needs --yes.
"""

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from doctor import QUARANTINE_DENY, projects_dir, quarantine_projects  # noqa: E402

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def inside_git_repo(folder):
    probe = folder if folder.is_dir() else folder.parent
    while not probe.is_dir():
        probe = probe.parent
    proc = subprocess.run(["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"], capture_output=True)
    return proc.returncode == 0 and proc.stdout.strip() == b"true"


def project_file(name, folder):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "projectResources": {"resources": [{"folderUri": folder.as_uri()}]},
        "settings": {
            "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_OFF",
            "nonWorkspaceFileAccessPolicy": "AGENT_SETTING_POLICY_DENY",
            "internetAccessPolicy": "AGENT_SETTING_POLICY_DENY",
            "enableTerminalSandbox": True,
        },
        "isWorkspaceOnly": True,
        "permissionGrants": {"permissionGrants": {"deny": sorted(QUARANTINE_DENY)}},
    }


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # JSON lines are UTF-8 even where Windows pipes use a code page
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Create a quarantine Antigravity project.")
    ap.add_argument("--name", required=True)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--projects-dir")
    args = ap.parse_args(argv)

    def out(**row):
        print(json.dumps({"event": "quarantine", **row}, ensure_ascii=False))

    if not NAME_RE.match(args.name):
        out(status="bad_name", name=args.name)
        return 2
    folder = Path(args.folder).expanduser().resolve()
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        out(status="folder_not_empty")
        return 2
    if inside_git_repo(folder):
        out(status="folder_inside_git_repo")
        return 2
    target_dir = projects_dir(args.projects_dir)
    existing, _ = quarantine_projects(target_dir)
    if args.name in existing:
        out(status="exists", name=args.name)
        return 0
    data = project_file(args.name, folder)
    target = target_dir / f"{data['id']}.json"
    if not args.yes:
        out(status="needs_confirmation", would_write=str(target), would_create_folder=not folder.exists(),
            content=data)
        return 3
    folder.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    out(status="created", name=args.name, file=str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
