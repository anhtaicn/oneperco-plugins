# oneperco-team-lite

A small AI team inside Claude Code. A **PM** turns your request into a short plan and an
acceptance checklist; **you approve it**; a **Builder** builds; a **Tester** from another model
family checks every item and must show evidence. At most two rounds, then a plain report in
Vietnamese. The AI's "done" is never taken on its word.

*Tiếng Việt:* Một nhóm AI nhỏ: PM lập kế hoạch và danh sách nghiệm thu, bạn duyệt, Builder làm,
rồi một AI khác họ (Codex hoặc Antigravity) kiểm từng mục và phải đưa bằng chứng. Tối đa hai vòng,
cuối cùng là báo cáo tiếng Việt dễ hiểu.

## Install

```text
/plugin install oneperco-team-lite --marketplace oneperco-com/oneperco-plugins
```

## What you need

- Claude Code on your own machine, Python 3 (standard library only) and git.
- For a Tester from another model family (recommended), one of: Codex CLI, logged in by you; or
  Antigravity CLI, logged in by you, with a quarantine project (the `oneperco-delegate` plugin's
  `quarantine` skill creates one). Without either, the Tester is a new, read-only Claude session,
  and the report says that this is less independent.
- Tested on Windows 11 with Codex CLI 0.146 and Antigravity CLI 1.4.4; macOS not yet.

## Skills

| Skill | Role |
|---|---|
| `team` | Runs the whole flow: PM, your approval, Builder, evidence, Tester, report |
| `pm` | Plan and acceptance checklist (`core/prompts/pm.md`) |
| `builder` | Builds only the approved plan; in round 2 fixes only the failed items |
| `tester` | Launches a fresh, read-only Tester through Codex, Antigravity or a new Claude session |

Start with: `/oneperco-team-lite:team <what you want built>`.

## How the rules are kept

A small orchestrator (`scripts/team.py`, no dependencies) keeps the state and refuses anything
the rules forbid ([core/SPEC.md](core/SPEC.md)):

1. The Tester is never the Builder, and is read-only.
2. Every round uses a new Tester session, with a stated reading budget.
3. At most two rounds; then the decision is yours.
4. Every item gets pass or fail with evidence. A pass without valid evidence counts as a fail.
5. The orchestrator runs the checklist's checks itself (command exit codes, file contents, localhost
   pages). A pass against a failed check counts as a fail.
6. The Builder's "done" is shown as a claim, never as evidence.

Your approval is bound to the checklist's fingerprint, so the checklist cannot change after you
approve it. Git save points are made before and after each Builder round.

## Three working examples

```bash
python examples/run_examples.py
python examples/run_examples.py --live --provider codex
```

| Example | Shows |
|---|---|
| [01-pass-first-round](examples/01-pass-first-round/) | A newsletter page passes in round 1, with evidence for all three items |
| [02-rework-then-pass](examples/02-rework-then-pass/) | Round 1 fails on a real check (even though the Tester wrote "pass"), the Builder fixes it, round 2 passes |
| [03-stop-after-two](examples/03-stop-after-two/) | Two failed rounds stop the run and hand you the decision; a pass with no evidence counts as a fail |

Offline, the Builder's edits are scripted and the Tester is a stand-in, so they need no account.
With `--live`, the real Tester CLI checks the work.

## What it runs, writes and sends (disclosure)

- **Processes:** `git` in your project; the checklist's own check commands, which you approved (run
  without a shell, each with a timeout); and the Tester CLI you have: `codex exec -s read-only`,
  `agy -p` in a quarantine project with `--sandbox`, or `claude -p` limited to Read, Grep and Glob.
  It never skips or bypasses a CLI's permission checks.
- **What leaves your machine:** the Tester prompt (the checklist, the check results with output
  tails, the diff of this run, and for Antigravity the changed files' text) goes to the provider you
  use, through your own login, under that provider's terms. Output lines that look like
  `KEY=value`, tokens or passwords are masked first, and `.env` files are never read or sent. The
  plugin itself opens no network connection except to `http://localhost` for `http_ok` checks, has
  no telemetry, and collects nothing.
- **Files written:** `.team/` in your project (state, checklist, evidence, the Tester's log and
  verdict, the report), added to `.git/info/exclude`; and git commits named
  `team-lite: before|after build round N`, which include your uncommitted work at that moment. It
  refuses to commit a `.env` file.

## Support and privacy

- Support: open an issue in this repository.
- Privacy: this plugin collects no data and runs no service of its own.

## License

MIT (see [LICENSE](LICENSE)). By Nguyen Xuan Tai, for [oneperco](https://oneperco.com).
