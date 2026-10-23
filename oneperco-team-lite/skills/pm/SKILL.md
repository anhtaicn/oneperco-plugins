---
name: pm
description: The PM role of team mode - turn a non-coder's brief into a short plan and an acceptance checklist (contract v1 JSON) that another AI can check. Used by the team skill; use directly when the user asks for a plan and acceptance criteria before any building.
---

# PM: plan and acceptance checklist

1. Read `${CLAUDE_PLUGIN_ROOT}/core/prompts/pm.md` and follow it exactly. It is the durable PM
   prompt; this skill only adds where to put the result.
2. Read `${CLAUDE_PLUGIN_ROOT}/core/schemas/checklist.schema.json` for the exact shape.
3. Read the brief (`.team/state.json`, field `brief`, if a run exists) and look at the project
   folder (read-only) to choose real checks: an existing test or build command, the files that will
   change, the dev server's localhost URL if there is one.
4. Ask the user at most 3 short questions if the brief leaves out something that changes what gets
   built. Never plan on a guess.
5. Write the JSON to `.team/pm_checklist.json` in the project. Check it yourself before handing it
   on: 3 to 8 items, ids `C1`..., every `command` check an argv array with no shell operators, every
   `review` item with `look_for_vi`, and Vietnamese with full diacritics in every `_vi` field.
