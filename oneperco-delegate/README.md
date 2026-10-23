# oneperco-delegate

Hand bulk, machine-checkable work from Claude Code to the Antigravity CLI (`agy -p`), run it in
parallel, and accept the results with validators you run yourself, never with the executor's own
report. Claude plans and accepts; the Google plan you already pay for does the volume.

*Tiếng Việt:* Claude lập kế hoạch và nghiệm thu, còn Antigravity (gói Google bạn đang có) làm phần
việc hàng loạt kiểm được bằng máy. Không tin bản tự báo cáo: chỉ tin bộ kiểm.

## Install

```text
/plugin install oneperco-delegate --marketplace anhtaicn/oneperco-plugins
```

## What you need

- Claude Code, on your own machine.
- Antigravity CLI installed, and logged in once by you (`agy`).
- Python 3 (standard library only) and git. Tested on Windows 11 with agy 1.4.4; macOS not yet.

## Skills

| Skill | Use it to |
|---|---|
| `delegate` | Route a job (script, delegate, or keep for Claude), write the work order and `jobs.json`, run the batch with `scripts/run_agy.py`, and accept it |
| `quarantine` | Create an isolated Antigravity project with every tool denied, for jobs that read untrusted text |

## Three working examples

Each runs offline with a fake executor (no account), or live with `--live`:

```bash
python examples/run_examples.py
python examples/run_examples.py --live --project <your-quarantine-name>
```

| Example | Shows |
|---|---|
| [01-classify-json](examples/01-classify-json/) | Three messages classified in parallel; output saved only when it passes the JSON schema |
| [02-write-drafts](examples/02-write-drafts/) | Two drafts written in parallel, each allowed one file, checked by a checker for shape and numbers |
| [03-catch-stray-write](examples/03-catch-stray-write/) | The runner catches a file the job was not allowed to write and refuses the batch (exit 1) |

## What it runs, writes and sends (disclosure)

- **Processes:** `agy` (your installed Antigravity CLI), `git status` / `git rev-parse` on your
  repository, and `python` for the scripts. Nothing else, and only when you ask for a batch.
- **What leaves your machine:** the prompts of the jobs you approve go to Google through your own
  `agy` login, under your own Google plan's terms. The plugin itself opens no network connection,
  has no telemetry, and collects nothing.
- **Permissions:** `write` jobs run with `--mode accept-edits`: file edits are accepted, and any
  other tool runs only if your own Antigravity permissions already allow it. There is no sandbox in
  this mode, so use it only on trusted input. `json` jobs run in the quarantine project with
  `--sandbox` and every tool denied. The plugin never skips permission checks.
- **Files written:** the batch logs folder you name (`summary.jsonl`, one log per job, `*.out.json`
  for valid JSON output), the files your `write` jobs are allowed to change, and, only after you
  agree, one project file under `~/.gemini/config/projects/` plus one empty folder (the
  `quarantine` skill). Logs hold ids, exit codes and sizes, never your prompts; agy's own internal
  log may hold them, so keep the logs folder outside your repository for untrusted content.
- **Known limits:** the stray-write check sees only what `git status` sees, and after the fact;
  `search_web` cannot be disabled per project (a result that used it is reported).

## Learn more

The full Vietnamese guide and the worked example behind this kit (about 15,630 YouTube channels
screened with Claude barely opening one) are on
[nguyenxuantai.com](https://nguyenxuantai.com/tai-viet/giao-viec-cho-gemini-tu-claude-code?utm_source=claude-directory&utm_medium=readme&utm_campaign=oneperco-delegate).

## Support and privacy

- Support: open an issue in this repository.
- Privacy: this plugin collects no data and runs no service of its own.

## License

Code MIT, skills and templates CC BY 4.0 (see [LICENSE](LICENSE)). By Nguyen Xuan Tai, for
[oneperco](https://oneperco.com).
