# Example 03: two fails stop the run and hand the decision to you

**What you type in Claude Code:** the same brief as example 01.

**What happens:** in round 1 the form sends emails to another website and the email field is not
required; the Tester fails C1 and C3. In round 2 the Builder fixes C1 but not C3. This time the
Tester writes "pass" for C3 with no evidence at all; the orchestrator counts that as a fail (rule
4). After two rounds the run stops instead of looping (rule 3).

**Expected result:** final state `needs_decision`, and a Vietnamese report that says
"CẦN BẠN QUYẾT ĐỊNH" with your three options.

Run it yourself: `python examples/run_examples.py --only 03`, or add `--live --provider codex`.
