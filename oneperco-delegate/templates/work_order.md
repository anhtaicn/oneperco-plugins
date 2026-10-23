# <NN> — Work order: <batch name> (Gemini, headless `agy -p`)

> Written <YYYY-MM-DD> by Claude (brain). Asked for by: <who asked for this batch, and when>.
> Executor: one headless `agy -p` run per job through `run_agy.py`
> (`<model>`, mode `<write|json>`), in parallel.
> Acceptance: Claude, never the executor's own report (section 6).

<!-- Fill every <...>; delete what does not apply.
     Pre-assign every id, slug, path and cross-reference between jobs here, so parallel runs never wait
     on each other. Keep it in English: the executor reads it. -->

## 1. What you are producing

<One paragraph: the output, who reads it, why it exists. Name the one thing each job delivers.>

Read before working, in this order (only these):
1. `<path>`: <why: style to match, schema, examples>
2. `<path>`: <the only data you may use>
3. Your brief in section 4.

## 2. Hard rules

You MUST:
- Write exactly one new file, `<output path pattern with {id}>`, and nothing else.
- <Shape: fields, lengths, ranges, format>.
- <Data: every number/fact comes from `<source file>`, in the same sentence as its link/record id>.
- Run `python "<checker path>" <id>` and fix your output until it exits 0 (at most three rounds).

You MUST NOT:
- Edit, create or delete any other file. No git, no build, no deploy, no network fetches.
- Add any fact, number, date, name, quote or URL that is not in the sources listed in your brief.
- Describe our own results beyond what `<results source>` states. Label reasoning as reasoning.
- <Banned claims for this project, e.g. a hypothesis known to be false>.

STOP and report (do not guess) if:
- An input file is missing, or does not say what this work order says it does.
- The checker fails on something outside your output file.
- <Project-specific stop conditions>.

Expected result, to check yourself against: <numbers, e.g. "exactly 1 new file, 300 to 600 words,
0 numbers outside the allowed list">.

## 3. Style

<Voice, length, structure; one example to match, by path.>

## 4. Briefs

### 4.1 `<id>`

- Output: `<path>`
- Sources you may use: `<record ids or file sections>`
- Cross-links: `<pre-assigned peer ids/slugs>`
- Points to make: <bullets>

<!-- one subsection per job -->

## 5. Report back (your final reply)

Id, output path, the checker's last output line, every number or fact used with its source, and
anything you could not do. If the checker still fails after three rounds, list the remaining codes;
do not delete the output.

## 6. Acceptance (Claude, not the executor)

1. `run_agy.py` exit 0: no job error, no timeout, no `stray_write`.
2. Claude runs `python "<checker path>" <id>` for every job and it exits 0.
3. Claude reads every output claim by claim against its sources, above all sentences that describe our
   own results, and outside facts with no record. Code: probe the failure paths (timeout, 4xx, bad
   charset) directly.
4. <Project gate, e.g. `npm test`>, commit, <deploy if in scope>.
5. One row in `templates/LEDGER.md` (copy it next to your batches).

## 7. Result (<date>)

<Filled in by Claude after acceptance: timings, validator results, review defects found and fixed.>
