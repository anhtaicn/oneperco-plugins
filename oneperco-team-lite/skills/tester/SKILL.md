---
name: tester
description: The Tester role of team mode - launch a fresh, read-only Tester from another model family (Codex, then Antigravity, then a fresh Claude session as the fallback) through its own CLI and record its verdict with evidence. Used by the team skill after `team.py evidence`; never judges the work in the Builder's own session.
---

# Tester

You do not test. You launch a Tester that is not you, and you never write, edit or summarise its
verdict before the orchestrator records it. The durable Tester prompt is
`${CLAUDE_PLUGIN_ROOT}/core/prompts/tester.md`; `team.py` fills it in.

1. Take `tester_order` from `team.py doctor` (codex, antigravity, claude-fresh: best first).
2. Run `team.py test --provider <first>`, adding:
   - for `antigravity`: `--quarantine <name>` with a name from the doctor's
     `providers.antigravity.quarantine_projects` (if there is none, skip antigravity; the
     `oneperco-delegate` plugin's `quarantine` skill can create one), and never a non-`gemini-*`
     `--model`;
   - `--model <m>` only when the user asked for a model, or after `MODEL_UNSUPPORTED` (its `detail`
     lists the models the user's Codex offers: pick one and say which).
   It can take several minutes: run it in the background if your tools allow, and wait.
3. On `TESTER_FAILED`, read `error`:
   - `QUOTA`: tell the user that provider's quota is used up, then try the next provider.
   - `AUTH`: the user must log in to that CLI themselves (`codex login`, or run `agy` once); try the
     next provider meanwhile.
   - `NOT_FOUND`, `SHIM_ONLY`, `NEEDS_QUARANTINE`, `TIMEOUT`, `NO_RESULT`, `EXIT_NONZERO`,
     `TOOL_BREACH`: try the next provider and tell the user in one line.
4. On `INVALID_VERDICT`, run the same command again once (a new session). A second invalid verdict
   ends the run in `needs_decision`; that is the rule, not an error to work around.
5. Never pass `claude` as the provider: it is refused, because the Builder may not test its own work.
