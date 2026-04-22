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
| `canonical/jubilant` | 2026-04-21 | `e9923ec` (HEAD on `main`); release was `2c389a6` / v1.8.0 (2026-04-13) | Reviewed every commit since the previous Cantrip pin. Actionable findings: ``run_action`` was renamed to ``run`` and the legacy ``apps=…, status=…`` ``wait()`` form replaced by predicate callables (``jubilant.all_active`` etc.) — Cantrip's ``generate_integration_tests``/``generate_load_test`` outputs were calling APIs that no longer exist. Jubilant 1.8.0 ships a breaking change to ``offer()`` (now respects ``self.model``) but Cantrip doesn't call ``.offer()`` from Python — only the skills mention it. New helpers (``add_cloud``, ``update_cloud``, ``model_constraints``, ``destroy_model(release_storage=, no_wait=, timeout=)``, ``bootstrap(metadata_source=)``) are not currently surfaced by Cantrip. ``pytest-operator`` migration guide moved out of Jubilant docs (``a501972``) — already covered by the §37.1 ops-docs work. |
| `canonical/concierge` | 2026-04-21 | `aeda3bc` (HEAD on `main`); latest release v1.4.5 | Reviewed the v1.0.0→main window. Cantrip's preflight is transparent to the most impactful fixes (``0ddf24c`` — only wipe ``/run/containerd`` when bootstrapping k8s; ``86b1b21`` — treat non-active snaps as installed; ``6307920`` — merge provider credentials) so they apply automatically once the user's Concierge snap is current. Three features worth surfacing in the ``concierge`` skill rather than Cantrip code: ``bebf251`` (``--dry-run`` on ``prepare``/``restore``), ``d844183`` (provider-level ``image-registry`` block with ``$VAR`` interpolation for docker.io mirrors), and ``4d6726c`` (``extra-bootstrap-args`` on the juju section).  No Cantrip preflight changes needed — ``_WARMUP_CONFIG`` and the ``--preset`` path still compose correctly.  **NB:** the upstream repo moved from ``jnsgruk/concierge`` to ``canonical/concierge``; always clone the canonical one. |
| `canonical/operator` (Pebble + ops.testing) | 2026-04-21 | Post-§37.1 re-scan across ``ops/pebble.py`` + ``testing/``; cutoff matches the main ``canonical/operator`` row above | Very little churn in ``ops/pebble.py`` itself (``0ce8a0f`` trims ``ExecError.__str__``, ``379d013`` fixes empty ``_checks_action`` — both transparent). The live-impact changes are in ``ops.testing`` (Scenario): ``61e606e`` enables plain ``breakpoint()`` inside a ``testing.Context.run`` (no more rebound ``sys.breakpointhook`` — fastest possible debug loop once you have a snapshot); ``55c41eb`` autoloads ``charmcraft`` extension metadata so 12-factor PaaS charms don't need manual meta reconstruction in tests; ``706b667`` lets ``State.get_relation`` accept a relation object (type-narrowed to peer/regular/subordinate). ``5e752be`` in ``ops`` proper now logs total deferred-event count per hook — a backlog signal worth spotting during Workload-bucket triage. ``scenario-tests`` and ``iterate-fix`` skills updated accordingly. |
| `canonical/charmcraft` | 2026-04-22 | `fae9862` (HEAD on `main`); latest release v4.2.1 | Actionable findings: **all six framework extensions are not uniformly stable** — Flask and Django returned `is_experimental() = False` in `charmcraft/extensions/app.py`, but FastAPI, Go, ExpressJS, and Spring Boot are still experimental. Cantrip's `CharmcraftInitTool` was running `charmcraft init` without the experimental flag, which would have failed downstream at `charmcraft pack` for four out of six profiles; fixed by gating on a `_CHARMCRAFT_EXPERIMENTAL_PROFILES` frozenset. The `simple` profile is gone (`fc17daa`, replaced by `kubernetes` — Cantrip already used `kubernetes`). New 12-factor integrations: HTTP proxy (`2d6022a`) and OpenID Connect (`2b6a9cf`); Spring Boot got app profiles (`7a9a3b4`). K8s/machine scaffolding now includes a `src/workload.py` alongside `src/charm.py` (`040cce3`) — skill guidance updated. Ubuntu 25.10 is stable, 26.04 devel (`562b748`, `24ef777`); docs default to 26.04 (`6839f16`) but K8s/machine profiles still scaffold 24.04 (`f05c915`). pytest-jubilant adoption in templates (`77c4d69`) already aligned via §37.1. |
| `canonical/rockcraft` | 2026-04-22 | `e03ed9f` (HEAD on `main`); latest release v1.18.0 | **All rockcraft framework extensions (Flask, Django, FastAPI, Go, ExpressJS, Spring Boot) are still flagged experimental upstream** — even the long-stable Flask and Django ones return `is_experimental() = True`. Cantrip's `RockcraftInitTool` previously gated the env var on a subset (`go-framework`, `express-framework`, `fastapi-framework`), so Flask / Django / Spring Boot users would have hit "Extension is experimental" errors. Fix: set `ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true` unconditionally (matching `RockcraftPackTool`). Notable feature changes: Flask / Django / FastAPI extensions default to a bare base (`3fba20c`, Feb 2026) — smaller rocks, no shell or apt; `entrypoint-command` added (`0f919f9`); uv and poetry plugins disabled on 25.10+ until usrmerge-ready (`5e1e347`) — affects bleeding-edge bases but not the 24.04 default; Bazel plugin added (`5f91cc8`); 26.04 devel base (`0c9f355`). `twelve-factor` skill updated with accurate experimental flags and the bare-base note. |
| `canonical/charmlibs` + PyPI ecosystem (data-platform-libs, observability-libs, traefik-k8s, grafana-agent, loki-k8s, prometheus-k8s, catalogue-k8s, charmlibs-* namespace, dpcharmlibs, cosl) | 2026-04-22 | PyPI simple index + `canonical/charmlibs` HEAD | The headline finding: **Cantrip's previous LIB001 PyPI map was almost entirely wrong** — it named packages like `loki-k8s-lib`, `traefik-k8s-lib`, `data-platform-libs`, `grafana-k8s-lib` that **do not exist on PyPI**, so LIB001 was telling users to install ghosts. The real picture: (a) the `charmlibs-*` monorepo publishes `charmlibs-pathops`, `-apt`, `-snap`, `-passwd`, `-sysctl`, `-systemd`, `-nginx-k8s` plus the `charmlibs-interfaces-*` set (`-tls-certificates`, `-certificate-transfer`, `-otlp`, `-mcp`, `-sloth`, `-k8s-backup-target`, `-gateway-metadata`) — imports become `from charmlibs import …` or `from charmlibs.interfaces import …`; (b) `cosl` ships COS utilities on PyPI; (c) the big observability libs (`charms.loki_k8s`, `charms.grafana_k8s`, `charms.prometheus_k8s`, `charms.traefik_k8s`, `charms.tempo_*`, `charms.catalogue_k8s`, `charms.observability_libs`), `charms.data_platform_libs`, and `charms.sdcore_nms_k8s` are **still not on PyPI** — `charmcraft fetch-libs` remains the only route. `dpcharmlibs` is a reserved namespace (not installable yet). Both Python and Rust charmlint rules rewritten to match; `operator_libs_linux` now splits by submodule (each → its own `charmlibs-*` package). Skills (`charmcraft`, `observability`, `ingress`) updated. System prompt's Libraries bullet rewritten. |

## Re-running the operator audit

```bash
# 1. Shallow clone (or pull a fresh copy) of canonical/operator.
git clone --depth=200 --filter=blob:none \
  https://github.com/canonical/operator.git /tmp/operator-audit
cd /tmp/operator-audit

# 2. List docs commits since the cutoff. Replace <CUTOFF> with the hash from
#    the table above. Iterate the limit if 200 isn't deep enough.
git log --oneline --grep='^docs' -i <CUTOFF>..HEAD

# 3. Also look at Pebble client + ops.testing commits; those are outside the
#    docs filter but land in the same repo.
git log --oneline <CUTOFF>..HEAD -- ops/pebble.py testing/

# 4. For anything that looks actionable, inspect the diff.
git show <hash> --stat
git show <hash> -- docs/

# 5. Append findings to ROADMAP §37.1 (or a sibling subsection) with the
#    source commit hash, then update the table above to the newest commit
#    you reviewed.
```

## Re-running the Concierge / Jubilant audit

Same shape — shallow clone, diff since cutoff, triage.  The Concierge
repo lives at ``canonical/concierge``; Jubilant at
``canonical/jubilant``.  Neither has a ``docs:``-prefix convention, so
walk the full commit list and rely on the conventional-commits
``feat:``/``fix!:`` prefixes to pick out actionable items.

## What this log is *not*

- Not a substitute for ROADMAP §37 itself — actions and follow-up live
  there. This file only records when the sweep ran and where to resume.
- Not a release log of upstream — only Cantrip-relevant commits land in
  ROADMAP. Use the upstream changelog for general awareness.
- Not pinned to specific Cantrip releases — the audit happens on a time
  cadence, not tied to Cantrip's own version numbers.
