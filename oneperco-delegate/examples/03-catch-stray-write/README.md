# Example 03: acceptance catches a write the job was not allowed to make

**What you type in Claude Code:**

> Dùng skill delegate: chạy đề bài `examples/03-catch-stray-write/prompts/note.txt`, chỉ cho phép
> ghi `drafts/note.md`, rồi cho mình biết nghiệm thu bắt được gì.

**What happens:** the prompt (deliberately sloppy) asks for two files, but the job list allows one.
The executor writes both; nothing stops it, because `write` mode has no sandbox. The runner's
`git status` comparison finds the extra file and reports it.

**Expected result:** exit 1 with one `stray_write` row for `notes-extra.txt`. Claude tells you the
batch is not accepted, and why, instead of passing on the executor's "done".

Run it yourself: `python examples/run_examples.py --only 03` (offline) or add `--live`.
