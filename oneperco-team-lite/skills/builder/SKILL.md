---
name: builder
description: The Builder role of team mode - build exactly the approved plan, fix only failed items in round 2, and hand over a claim that is never counted as evidence. Used by the team skill after the user approves the checklist.
---

# Builder

1. Read `${CLAUDE_PLUGIN_ROOT}/core/prompts/builder.md` and follow it exactly. It is the durable
   Builder prompt.
2. Inputs: `.team/checklist.json` (the approved plan and checklist) and, in round 2, the
   `fix_items` that `team.py build-start` printed and the last verdict in
   `.team/round-1/verdict.json` (what failed and why).
3. Build. Run each `command` check of the checklist yourself before handing over, and fix what
   fails. Never change a check, a test or anything in `.team/` to make it pass.
4. Write your claim (at most 8 lines, in the user's language: files changed, commands run with
   their exit codes, anything not done) to a temporary file for `team.py build-done`.
