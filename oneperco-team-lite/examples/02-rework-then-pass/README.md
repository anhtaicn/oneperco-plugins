# Example 02: fails on real evidence, is reworked, then passes

**What you type in Claude Code:** the same brief as example 01.

**What happens:** in round 1 the Builder forgets to make the email field required. The project's
own check exits 1 (evidence E1). In this example the round-1 Tester even writes "pass" for that
item; the orchestrator overrides it to "fail", because a pass can never stand against a failed
machine check (rule 5). The Builder fixes only C1, a new Tester session checks again, and round 2
passes.

**Expected result:** round 1 fails on C1 (override `check_failed`), round 2 passes, final state
`passed`, and the report says "Vòng 2/2".

Run it yourself: `python examples/run_examples.py --only 02`, or add `--live --provider codex`.
