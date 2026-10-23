---
name: quarantine
description: Set up an isolated Antigravity project in which every tool is denied, so `agy -p` jobs that read untrusted text can only return JSON. Use before the first `json` job of the delegate skill, or when the user asks how to run Antigravity safely on untrusted input.
---

# Set up the quarantine project

Why: the user's global Antigravity permissions may allow every command, file and URL. A project file
whose `permissionGrants.deny` lists every tool blocks them at the tool level and overrides the global
setting, without touching the user's other projects. Known limits: `search_web` cannot be turned off
per project (treat any result that used it as tainted), and `--mode plan` makes the model write a plan
instead of answering, so never use it here.

Talk to the user in their language. Python: `python`, else `py -3` (Windows) or `python3` (macOS).

1. Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py"`. If `quarantine_projects` already lists a
   name, use it and stop.
2. Pick a name (default `agy-quarantine`) and an empty folder outside every git repository (default
   `<home>/agy-quarantine`).
3. Dry run: `python "${CLAUDE_PLUGIN_ROOT}/scripts/make_quarantine.py" --name <name> --folder <folder>`.
   It exits 3 and prints the file it would write under `~/.gemini/config/projects/`.
4. Tell the user in one short message that this writes one new file in Antigravity's settings
   folder and creates one empty folder, and that it changes nothing else. Wait for a yes.
5. Run the same command with `--yes`. Exit 0 means created (or the same quarantine already exists).
6. Run the doctor again and confirm the name is listed.
