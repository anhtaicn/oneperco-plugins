# Team mode core contract, version 1

The durable part of team mode. The `oneperco-team-lite` plugin implements it in
`scripts/team.py` (Python, stdlib) today; `packages/core` of OnePerCo OS loads the same prompts,
schemas and strings later and reimplements the state machine in TypeScript (PLAN.md section 7,
ruling 21). Changing anything in `core/` is a contract change: bump `contract_version` everywhere
and update both implementations.

## Files

| File | Who reads it | What it is |
|---|---|---|
| `prompts/pm.md` | the PM agent | Brief to plan and acceptance checklist |
| `prompts/builder.md` | the Builder agent | Build only the approved plan; "done" is a claim |
| `prompts/tester.md` | the Tester agent | Read-only, fresh, evidence for every item; placeholders `{{BUDGET}}`, `{{CHECKLIST}}`, `{{EVIDENCE}}`, `{{CONTENT}}` |
| `schemas/checklist.schema.json` | orchestrator | The PM's output, approved by the user |
| `schemas/verdict.schema.json` | orchestrator, Tester CLI | The Tester's raw output (strict-mode compatible: every object closed, every property required) |
| `locales/vi.json` | orchestrator | Every user-facing line of the report, Vietnamese with full diacritics |

Prompts are English (agents read them). Text fields ending in `_vi` are user-facing Vietnamese.

## States

```text
brief -> planned -> approved -> building -> built -> evidence_ready -> passed
                                   ^                       |
                                   |-- failed <-- (fail, round 1)
                                                           |-> needs_decision (fail, round 2;
                                                               or 2 invalid verdicts in a round)
```

| Command | From | To |
|---|---|---|
| `plan` | brief, planned | planned (a new plan clears the approval) |
| `approve(sha)` | planned | approved, only if `sha` is the SHA-256 of the stored checklist (canonical JSON: sorted keys, no spaces, UTF-8) |
| `build-start` | approved, failed | building; round + 1; save point "before" |
| `build-done(claim)` | building | built; the claim is stored, never used as evidence; save point "after" |
| `evidence` | built | evidence_ready |
| `test(provider)` / `verdict(raw, provider)` | evidence_ready | passed, failed or needs_decision |

Every command after `approve` re-hashes the checklist and refuses if it changed.

## Rules (PLAN.md section 7, rules 1 to 6)

1. **The Tester is never the Builder.** Providers: `codex` (`codex exec -s read-only`, native
   binary, never the npm shim), `antigravity` (`agy -p` in a quarantine project that denies every
   tool, `--sandbox`, a `gemini-*` model only), `claude-fresh` (a new `claude -p` session limited to
   Read, Grep and Glob; the fallback when the user has no second provider, and the report says it is
   less independent). `claude` as a Tester is refused (`TESTER_IS_BUILDER`).
2. **A fresh Tester every round.** No resume or continue flag is ever passed. The Tester prompt
   states its budget; the orchestrator cuts the diff and content to fit it (40,000 characters of
   diff for codex and claude-fresh; 8,000 of diff plus 14,000 of numbered file content for
   antigravity, which cannot read files).
3. **At most 2 rounds.** A fail in round 2 ends in `needs_decision`, with the user's options.
4. **Structured verdicts.** One entry per checklist id; an unknown or duplicate id makes the verdict
   invalid (the round is not consumed; a second invalid verdict in the same round ends in
   `needs_decision`). A missing id is a fail (`override: missing`). A `pass` with no valid evidence
   ref is a fail (`override: no_evidence`). Valid refs: an evidence id from this round's bundle, or
   `file:<path>:<first>-<last>` naming an existing project file (never `.env`), relative, inside
   the project, with `1 <= first <= last <= line count`.
5. **Evidence the user can see.** The orchestrator runs the machine checks itself:
   `command` (argv, no shell, its own timeout, exit code against `expect_exit`, a redacted output
   tail), `file_contains` (first line that contains the text), `http_ok` (localhost only, redirects
   not followed, 200 to 399). A `pass` on an item whose machine check failed is a fail
   (`override: check_failed`). The overall result is computed from the items, never read from the
   model. Screenshots come with the app (`webContents.capturePage`, M6); the plugin has none.
6. **The Builder's "done" is a claim.** It is stored per round and shown as a claim.

Save points: a git commit before and after every Builder round (message `team-lite: before|after
build round N`), refused when a `.env` file would be committed (`.env.example`, `.sample` and
`.template` are allowed). `.team/` is added to `.git/info/exclude`. Outside git there are no save
points and the report says so.

## Recorded verdict (`.team/round-N/verdict.json`)

```json
{"round": 1, "provider": "codex", "invalid_verdicts": 0, "overall": "fail", "summary_vi": "...",
 "items": [{"id": "C1", "result": "fail", "evidence": ["E1"], "invalid_refs": [],
            "reason_vi": "...", "override": "check_failed"}]}
```

## Evidence bundle (`.team/round-N/evidence.json`)

```json
{"contract_version": 1, "round": 1, "changed_files": ["index.html"], "diff_stat": "...", "diff": "...",
 "evidence": [{"id": "E1", "item": "C1", "kind": "command", "argv": ["check_page.py"], "expect_exit": 0,
               "exit": 0, "timed_out": false, "seconds": 0.3, "ok": true, "output_tail": "ok"}]}
```

The diff covers everything since the first round's "before" save point, so a fresh Tester sees the
whole change.
