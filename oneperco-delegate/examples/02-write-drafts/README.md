# Example 02: draft two product descriptions (write mode, with a checker)

**What you type in Claude Code:**

> Dùng skill delegate: viết mô tả 3 dòng cho trà xanh và cà phê theo các đề bài trong
> `examples/02-write-drafts/prompts/`, giao Antigravity viết song song, rồi nghiệm thu bằng
> `checker.py`.

**What happens:** two `agy -p` jobs run in parallel with `--mode accept-edits`. Each may change one
file only (`allowed_paths`). The runner compares `git status` before and after, and `checker.py`
checks each draft's shape (3 bullet lines) and its numbers (only those in the facts).

**Expected result:** exit 0, no stray write, and `checker.py` exits 0 for both drafts. Claude still
reads every line against the facts before using it.

Run it yourself: `python examples/run_examples.py --only 02` (offline) or add `--live`.
