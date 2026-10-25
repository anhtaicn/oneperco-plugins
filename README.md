# oneperco plugins for Claude Code

Two plugins for people who build software with the AI plans they already pay for, and want proof
that the work is right instead of an AI saying "done".

| Plugin | What it does |
|---|---|
| [oneperco-delegate](oneperco-delegate/) | Hands bulk, machine-checkable work from Claude Code to the Antigravity CLI in parallel, then accepts it with validators |
| [oneperco-team-lite](oneperco-team-lite/) | A PM, a Builder and a read-only Tester from another model family: plan, your approval, build, a checked verdict with evidence, a Vietnamese report |

## Install

In Claude Code, add this repository as a plugin marketplace, then install either plugin:

```text
/plugin marketplace add oneperco-com/oneperco-plugins
/plugin install oneperco-delegate@oneperco
/plugin install oneperco-team-lite@oneperco
```

From a local copy instead: `/plugin marketplace add ./path/to/this/folder`.

Neither plugin has telemetry or a service of its own. Each README lists exactly what it runs,
writes and sends. Support: open an issue in this repository.
