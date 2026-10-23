---
name: delegate
description: Hand a batch of bulk, machine-checkable work (classify, extract, convert, draft many files) from Claude Code to the Antigravity CLI (agy -p) running in parallel, then accept the results with validators instead of the executor's own report. Use when the user asks to "giao viec cho Gemini", delegate or batch work to Antigravity, or save Claude quota on a large repetitive job.
---

# Delegate a batch to Antigravity, then accept it

You (Claude) are the brain: you route, write the work order, run the batch and accept it. The
Antigravity CLI is the hands. Never trust its own report; trust only validators you run yourself.
Talk to the user in their language (Vietnamese with full diacritics if they write Vietnamese). The
work order and prompts stay in English, because the executor reads them.

Plugin files: `${CLAUDE_PLUGIN_ROOT}/scripts/` and `${CLAUDE_PLUGIN_ROOT}/templates/`.
Python: use `python`; if it is missing, `py -3` on Windows or `python3` on macOS.

## 1. Route first (stop at the first yes)

1. Can a script do it with no model (parse, filter, dedupe, count, validate)? Write the script. Done.
2. Is "done" checkable by a machine (schema, test, checker exit 0, match against a source file)?
   Delegate it, if the batch is large enough to repay about 15 Claude turns of setup and review.
3. Does "done" need judgement no script can check? Do it yourself (or a Claude subagent). Do not
   delegate it.

Never delegate: judgement, acceptance, security review, diagnosing a bug, or anything that acts
outside the machine (sending mail, posting, deploying). Say so plainly if the user asks.

## 2. Check the machine

Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py"`. It prints one JSON line.
- `agy` is null: tell the user to install Antigravity CLI and log in with `agy` once (a login only
  they can do), then stop.
- `git` false: the stray-write check needs a git repository. Ask before running `git init`.
- A `json` job needs a name from `quarantine_projects`. None listed: use the `quarantine` skill first.

## 3. Pick a mode per job

| Mode | When | What it can do |
|---|---|---|
| `json` | The executor reads anything untrusted (web pages, emails, comments, transcripts), or the output is data | Nothing on disk: it runs in the quarantine project with every tool denied and returns JSON that the runner checks against your schema. Your script writes the files. |
| `write` | Trusted inputs only; the executor must create files (drafts, images, code) | `--mode accept-edits`: file edits are accepted; any other tool runs only if the user's own Antigravity permissions already allow it. There is no sandbox. |

Never put secrets, `.env` content or other people's personal data in a prompt.

## 4. Write the work order and the jobs

1. Copy `templates/work_order.md` into a scratch folder outside the repo (or a gitignored one) and
   fill every `<...>`. Pre-assign every id, path and cross-link so jobs never wait on each other.
2. Copy `templates/checker.py` next to it and fill in the shape and provenance rules. The executor
   may run it; you run it again at acceptance.
3. Write `jobs.json` (see `templates/jobs.example.json`). Each `write` job lists the exact
   `allowed_paths` it may change. Each `json` job names the quarantine `project` and a `json_schema`
   in the supported subset (type, enum, const, properties, required, additionalProperties as a
   boolean, items, min/max lengths, items and values, pattern).
4. Models: `gemini-3.8-flash-high` for `write`, `gemini-3.8-flash-medium` for `json` (the high model
   with a schema hung in tests). Names depend on the account: check with `agy models`.

Show the user the job list in one short message (how many jobs, which mode, which files will change)
and wait for a yes before the first run of a new kind of batch.

## 5. Run

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/run_agy.py" <scratch>/jobs.json --logs <scratch>/logs --repo <repo> --max-parallel 6
```

Do not edit the repository while it runs: the runner cannot tell who wrote a file, so your own edit
would be reported as a `stray_write`. Run it in the background if it may take over two minutes.
Exit codes: 0 clean; 1 a job error, timeout, stray write or schema mismatch; 2 bad config.
Job errors: `AGY_QUOTA` (quota used up: tell the user when to retry), `AGY_AUTH` (the user must log
in again), `TIMEOUT`, `EXIT_NONZERO`, `TOOL_BREACH`, `NO_RESULT`, `SCHEMA_MISMATCH`,
`LAUNCH_FAILED`, `CMD_TOO_LONG` (move the prompt to a `prompt_file`).

## 6. Accept (you, never the executor)

1. The final `run` row says `failed: 0` and `stray_writes: 0`. Investigate every `stray_write`.
2. Run the checker on every output yourself; each must exit 0.
3. Text: read every claim against its source. Watch for dropped scope ("on a subset" becoming "on
   all"), "some" stretched to "all", numbers spelled out in words to dodge a digit rule, and the
   same point repeated across parallel jobs.
4. Code: read every new module and try its error paths (timeout, 4xx, wrong encoding, swallowed
   exceptions, `str(exc)` leaking data).
5. Run the project's own checks (for example `npm test`), then commit.
6. Add one row to a copy of `templates/LEDGER.md` kept next to the batches: jobs, model, seconds,
   checker results, stray writes, defects found in review, Claude tokens against a "Claude alone"
   estimate. The ledger is the evidence for keeping or dropping a rule.

## 7. Report to the user

In their language, short: what was produced, where, what the validators said (with the exit codes),
what you fixed in review, and anything not done. Never call a batch done because the executor said
so.
