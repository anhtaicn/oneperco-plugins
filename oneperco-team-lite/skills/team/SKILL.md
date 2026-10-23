---
name: team
description: Run a small AI team on a building task - a PM plans and writes an acceptance checklist, the user approves it, a Builder builds, and a Tester from another model family (Codex or Antigravity when installed) checks every item with evidence, at most two rounds, ending in a plain Vietnamese report. Use when the user wants something built and checked ("lam giup minh... va kiem tra", "team mode", "nhom AI"), or does not trust an AI's "done".
---

# Team mode lite: PM, approval, Builder, Tester, report

You run the team. A deterministic orchestrator, `team.py`, owns the rules: you call it at every
step and never work around a refusal. Talk to the user in their language (Vietnamese with full
diacritics if they write Vietnamese), in plain words, without jargon. The user is not a coder.

Set these once:
- `TEAM` = `python "${CLAUDE_PLUGIN_ROOT}/scripts/team.py" --project "<project root>"`
  (if `python` is missing: `py -3` on Windows, `python3` on macOS).
- The project root is the folder the user is working in. Ask if it is unclear.

Every `TEAM` command prints one JSON line. `"ok": false` means refused: read `code`, fix the cause
or tell the user; never edit `.team/` by hand.

## 1. Start

1. `TEAM doctor`. Note `tester_order` (the Tester providers this machine has, best first). If it has
   only `claude-fresh`, tell the user in one line that the check will be less independent, and that
   installing Codex or Antigravity CLI gives a Tester from another AI family.
2. If the folder is not a git repository, ask before `git init` (save points need git).
3. Write the user's brief, in their words, to a temporary file and run `TEAM init --brief-file <f>`.
   A `RUN_IN_PROGRESS` refusal means an unfinished run: ask whether to continue it (`TEAM status`)
   or start over (`--force`).

## 2. PM: plan and checklist

Use the `pm` skill. It writes `.team/pm_checklist.json`. Then `TEAM plan --file .team/pm_checklist.json`.
On `INVALID_CHECKLIST`, fix the listed problems and run it again.

## 3. The user approves

Show the plan and the checklist in plain words: for each item, what it means and how it will be
checked ("chạy lệnh kiểm `npm test`", "xem tệp `index.html` có chữ ...", "một AI khác đọc code và
xác nhận ..."). Then ask one question with two answers (Duyệt / Sửa lại). Only on a clear yes run
`TEAM approve --sha <sha from the plan step>`. If they want changes, go back to step 2.

## 4. Builder

`TEAM build-start` (it commits a save point first; on `ENV_FILE_WOULD_BE_COMMITTED`, help the user
add `.env` to `.gitignore`, then retry). Use the `builder` skill. When it is done, write its claim to
a temporary file and run `TEAM build-done --claim-file <f>`.

## 5. Evidence and Tester

1. `TEAM evidence`: the orchestrator runs the checklist's machine checks itself.
2. Use the `tester` skill: it runs `TEAM test --provider <p>` with the first provider in
   `tester_order` that works. You never judge your own work and never write or edit a verdict.

## 6. Result

Run `TEAM report` and show the user the content of `.team/report.md` as it is (it is already in
Vietnamese), then:
- `passed`: done. Mention the save points in one line.
- `failed` (after round 1): tell the user which items failed and that the Builder will fix only
  those, then go back to step 4 (`build-start` starts round 2; its output lists `fix_items`).
- `needs_decision`: stop. Present the report's three options and wait. Never start a third round.

Never call the work done before the report says ĐẠT. The Builder's "done" is a claim, not a result.
