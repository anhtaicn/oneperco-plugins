# Example 01: passes in the first round

**What you type in Claude Code:**

> /oneperco-team-lite:team Làm cho mình một trang đăng ký nhận tin: có ô nhập email và nút Đăng ký.
> Email chỉ gửi về trang của mình thôi.

**What happens:** the PM writes a 3-item checklist ([../shared/checklist.json](../shared/checklist.json)):
the project's own check must exit 0, the button must say "Đăng ký", and a reviewer must confirm the
form posts only to `/subscribe`. You approve it. The Builder writes `index.html`. The orchestrator
runs the two machine checks itself (E1, E2), and a fresh Tester from another model family checks
all three items, citing E1, E2 and lines 6 to 10 of `index.html`.

**Expected result:** state `passed` after round 1, and a Vietnamese report starting
"Kết quả: ĐẠT".

Run it yourself: `python examples/run_examples.py --only 01` (offline, scripted Builder and Tester),
or `--live --provider codex` to use a real Tester.
