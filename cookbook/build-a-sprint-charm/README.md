# Build a sprint charm

**The fastest path from zero to a packed charm.** Sprint mode skips
tests, COS integration, and ops-tracing in favour of shipping a
working `.charm` file in under a minute. It's the right recipe for:

- A throwaway demo charm you're going to rebuild properly later.
- Reproducing a packing bug without the ceremony.
- Onboarding — proves your toolchain works end-to-end before you
  take the full path.

Not right for anything you'd deploy beyond a dev environment. Use
[`build-a-stateful-charm/`](../build-a-stateful-charm/README.md) when
you're ready for tests and observability.

## What you need

- **Cantrip** installed (`uv sync --dev && uv pip install -e .`
  from the Cantrip repo, or whatever you usually do).
- **charmcraft** on `$PATH` — sprint mode calls it directly.
- **A Canonical-style container runtime** for destructive-mode
  packing. The usual `concierge` or a manual `sudo snap install
  lxd` and `lxd init --auto` is enough.
- **No Juju controller needed** — sprint mode stops at packing;
  deploying is a separate recipe.

## What you get

A charm directory with this shape:

```
<charm-dir>/
├── charmcraft.yaml     # base: ubuntu@24.04, plugin: charm, no build-snaps
├── requirements.txt    # only: ops>=3,<4
├── src/
│   └── charm.py        # default charmcraft-init scaffold, minimally edited
├── pyproject.toml
└── <name>_*.charm      # the packed charm
```

Any `ops-scenario`, `ops-tracing`, `tests/`, or COS-integration
boilerplate is deliberately absent — that's the whole point of
sprint mode.

## Walkthrough

1. Pick an empty directory for your charm:
   ```bash
   mkdir ~/charms/hello-sprint && cd ~/charms/hello-sprint
   ```

2. Start Cantrip in that directory:
   ```bash
   cantrip .
   ```

3. Paste the prompts from [`prompts.md`](prompts.md) one at a time.
   Wait for each autonomous run to finish before the next paste.

4. When Cantrip reports the charm is packed, verify the shape:
   ```bash
   python /path/to/cantrip/cookbook/build-a-sprint-charm/verify.py .
   ```

   You should see `OK — sprint-mode shape verified.` with an exit
   code of 0. Failures are printed as short reasons.

## How the verifier works

[`verify.py`](verify.py) is a short script that loads the charm
directory and asserts the sprint-mode invariants:

- `charmcraft.yaml` exists and sets `base: ubuntu@24.04`.
- At least one part uses the `charm` plugin (not `uv`).
- `build-snaps:` is absent from every part (sprint mode removes it
  because it slows packing).
- `requirements.txt` exists and contains exactly one `ops` pin in
  the `>=3,<4` range (no `ops-tracing`, no `ops-scenario`, no
  third-party deps the scaffold would otherwise add).
- `src/charm.py` exists.

Failure messages quote the line or file that tripped the assertion
so you can fix the charm and re-run.

## Why this recipe is in the cookbook

Sprint mode is the shape Cantrip's autonomous loop commits to for
the `Sprint build:` task title prefix (see
`src/cantrip/agent/subagent.py:_SPRINT_GUIDANCE`). Having the
shape spelled out as a verifier gives us two protections:

1. **Teaching artifact** — a user who reads `verify.py` learns
   exactly what sprint mode guarantees.
2. **Regression fixture** — if a future planner change drifts
   from these shapes (extra deps creep in, base version bumps,
   plugin switches back to `uv`), the verifier catches it.

## Related

- [Sprint-mode guidance](../../src/cantrip/agent/subagent.py)
  (`_SPRINT_GUIDANCE` constant) — the in-agent prompt that drives
  this recipe.
- `design/AGENT.md` § *Subagent Pattern* for the full picture of
  how Cantrip dispatches sprint vs full builds.
