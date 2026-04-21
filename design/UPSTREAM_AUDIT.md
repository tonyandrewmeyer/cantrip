# Upstream Ecosystem Audit Log

Cantrip's generated charms, prompts, skills, and tool wrappers must keep up
with the upstream charm ecosystem (`canonical/operator`, `canonical/jubilant`,
`canonical/charmcraft`, `canonical/rockcraft`, `jnsgruk/concierge`,
charmlibs). When upstream changes guidance — a new test pattern, a renamed
field, a deprecated API — Cantrip's outputs need to follow.

This file is the running log of when each upstream repository was last
audited, what commit served as the cutoff, and how to repeat the sweep.
ROADMAP §37 captures the *findings*; this file captures the *bookkeeping*
so the next audit knows exactly where to start.

## Audit cadence

Run the sweep roughly once per quarter, or sooner if a downstream incident
points at stale guidance. Each sweep:

1. Look at every commit in the upstream repo since the recorded cutoff.
   For `canonical/operator`, focus on `^docs:`-prefixed commits — they are
   the public guidance changes that map to Cantrip's prompts and skills.
   Other repos (jubilant, charmcraft, etc.) need a wider net since they
   don't separate doc commits from code commits as cleanly.
2. Triage each commit: actionable for Cantrip vs. cosmetic. Record the
   actionable ones as ROADMAP items under the appropriate §37.x heading
   with the source commit hash in parens.
3. Update the cutoff in this file to the newest commit you reviewed
   (regardless of whether it produced an action item).
4. Commit the bookkeeping change in the same commit — or an immediately
   adjacent one — as the ROADMAP edits, so the cutoff and the new items
   land together.

## Cutoffs by repository

| Repository | Last audited | Cutoff commit | Notes |
|------------|--------------|---------------|-------|
| `canonical/operator` | 2026-04-21 | `df731e5` (`docs: update tutorials and example charms to match Charmcraft 4.2`) | Filtered to `^docs:` commits. Picked up Charmcraft 4.2 / Ubuntu 24.04, pytest-jubilant 2.0 official, the new CI how-to, and the COS Lite cross-model integration test pattern. The previous sweep (initial seed of §37.1) used `4bff400` (2026-03-31) as the cutoff. |
| `canonical/jubilant` | not yet audited | — | §37.2 placeholder. |
| `canonical/charmcraft` | not yet audited | — | §37.5 placeholder. |
| `canonical/rockcraft` | not yet audited | — | §37.5 placeholder. |
| `jnsgruk/concierge` | not yet audited | — | §37.3 placeholder. |
| charmlibs (data-platform-libs, observability-libs, traefik-k8s, grafana-agent, loki-k8s, prometheus-k8s, catalogue-k8s) | not yet audited | — | §37.4 placeholder. |

## Re-running the operator audit

```bash
# 1. Shallow clone (or pull a fresh copy) of canonical/operator.
git clone --depth=200 --filter=blob:none \
  https://github.com/canonical/operator.git /tmp/operator-audit
cd /tmp/operator-audit

# 2. List docs commits since the cutoff. Replace <CUTOFF> with the hash from
#    the table above. Iterate the limit if 200 isn't deep enough.
git log --oneline --grep='^docs' -i <CUTOFF>..HEAD

# 3. For anything that looks actionable, inspect the diff.
git show <hash> --stat
git show <hash> -- docs/

# 4. Append findings to ROADMAP §37.1 (or a sibling subsection) with the
#    source commit hash, then update the table above to the newest commit
#    you reviewed.
```

## What this log is *not*

- Not a substitute for ROADMAP §37 itself — actions and follow-up live
  there. This file only records when the sweep ran and where to resume.
- Not a release log of upstream — only Cantrip-relevant commits land in
  ROADMAP. Use the upstream changelog for general awareness.
- Not pinned to specific Cantrip releases — the audit happens on a time
  cadence, not tied to Cantrip's own version numbers.
