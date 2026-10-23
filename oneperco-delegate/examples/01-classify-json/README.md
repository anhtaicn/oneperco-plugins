# Example 01: classify customer messages (json mode, quarantined)

**What you type in Claude Code:**

> Dùng skill delegate: phân loại 3 tin nhắn khách hàng trong `examples/01-classify-json/prompts/`
> thành câu hỏi, đơn hàng hay khiếu nại, giao cho Antigravity chạy song song.

**What happens:** three `agy -p` jobs run in parallel in the quarantine project, with every tool
denied. Each returns JSON; the runner checks it against `schema.json` and saves only valid output
(`<logs>/msg-N.out.json`). Nothing in your repository changes.

**Expected result:** exit 0, no stray write, and the kinds `question`, `order`, `complaint`.

Run it yourself: `python examples/run_examples.py --only 01` (offline, fake executor) or
`python examples/run_examples.py --only 01 --live --project <your-quarantine-name>`.
