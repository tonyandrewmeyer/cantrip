# Sprint-charm prompts

Paste these into Cantrip in order. Wait for each autonomous run
to complete before pasting the next. Replace `<NAME>` and
`<WORKLOAD>` with your target.

## 1 — Kick off sprint mode

```
Sprint build: <NAME>

Build me the smallest possible <NAME> charm for <WORKLOAD>.
Use sprint mode — skip tests, skip COS, skip ops-tracing.
Target is a packed .charm file, nothing more.
```

The `Sprint build:` prefix is load-bearing: it's what the planner
matches on to dispatch the sprint-mode guidance into the subagent.
Without that prefix Cantrip takes the full path with tests and
observability.

## 2 — Only if packing fails

```
The pack failed. Read the error output, make the smallest possible
fix to charmcraft.yaml or requirements.txt that lets packing
succeed, then re-pack. Do not add features.
```

This keeps Cantrip in "make it pack" mode rather than pulling in
libraries or deps to fix a deeper issue — those are out of scope
for the sprint.

## 3 — Confirm done

```
/tasks
```

Then run the verifier:

```bash
python /path/to/cantrip/cookbook/build-a-sprint-charm/verify.py .
```

## Optional — commit

```
git_init, git_add everything, git_commit with the message
"Sprint build of <NAME>".
```

Sprint mode's final step is already a commit (see
`_SPRINT_GUIDANCE`); this prompt is only needed if Cantrip
stopped at packing and didn't auto-commit.
