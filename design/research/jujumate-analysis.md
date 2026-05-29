# Lessons from JujuMate for Cantrip

**Source:** [github.com/Abuelodelanada/jujumate](https://github.com/Abuelodelanada/jujumate) —
a K9s-style read-only TUI for monitoring Juju infrastructure. Written by Jose C.
Masson (Canonical). Analysed 2026-03-18.

---

## What JujuMate is

JujuMate is an interactive terminal dashboard for Juju — it monitors clouds,
controllers, models, applications, units, machines, relations, offers, and
secrets in real time. It is **read-only**: it never modifies Juju state. Built on
Textual + python-libjuju with only 3 runtime dependencies.

Key architecture:
- **Polling + snapshot** — `JujuPoller` periodically fetches status from all
  controllers, builds a `PollSnapshot`, posts Textual `Message` objects to the
  widget tree
- **Message-driven UI** — views subscribe to update messages and re-render;
  fully decoupled from data fetching
- **Drill-down navigation** — Cloud → Controller → Model → Status, with
  keyboard-driven selection filtering the next level
- **Entity dataclasses** — ~16 `@dataclass` types normalising python-libjuju's
  raw data (AppInfo, UnitInfo, MachineInfo, RelationInfo, OfferInfo, SecretInfo,
  etc.)
- **YAML-based theming** — 5 built-in themes (ubuntu, dark, monokai,
  solarized-dark, spacemacs) plus user custom themes; centralised palette module
  with semantic colour constants

---

## Lessons

### 1. Relation Databag Inspection

JujuMate can inspect raw app-level and unit-level relation data for any
relation. It reads databags via `ApplicationFacade.UnitsInfo()` and presents
both sides of the relation — what the provider published and what the requirer
sees.

**Relevance to Cantrip:** Relation data mismatches are the single most common
charm integration failure. The agent currently has no way to read databag
contents — it can only see that a relation exists via `juju status`. A
`read_relation_data` tool would let the agent autonomously diagnose "why isn't
my integration working?" by checking whether expected keys are present, whether
the provider has published data, and whether the requirer has consumed it. This
is the highest-impact introspection capability we're missing.

### 2. App Config with Source Tracking

JujuMate's config viewer shows each configuration value alongside its source —
whether it's the schema default, user-set, or model-default. This makes it
immediately clear whether a config change has taken effect.

**Relevance to Cantrip:** When the agent debugs "why isn't my config taking
effect?", it currently has to guess by comparing `charmcraft.yaml` defaults with
`juju config` output. A tool that returns config values with source annotations
would eliminate this guesswork. The `juju config <app> --format yaml` output
already includes source information — we just need to surface it.

### 3. WebSocket Log Streaming

JujuMate connects directly to the Juju controller's WebSocket debug-log
endpoint (`wss://user-{username}:{password}@{endpoint}/model/{uuid}/log`). It
constructs the URL from `controllers.yaml`, builds an SSL context from the
controller's CA certificate, and handles reconnection on `ConnectionClosed`.

**Relevance to Cantrip:** The agent currently relies on SSH-to-Loki for error
logs, which requires COS to be deployed. Direct WebSocket streaming would
provide log access without COS, with lower latency, and with built-in level
filtering. The connection-parameter extraction from Juju's own config files is
the key implementation detail — JujuMate shows exactly how to do it.

### 4. Cross-Model Offer Awareness

JujuMate scans all known controllers to find consumers of each cross-model
offer. The offers browser shows endpoint details, connection status, and which
applications in which models are consuming each offer.

**Relevance to Cantrip:** For multi-model deployments (e.g. a charm connected
to COS via CMR), the agent needs to understand the broader topology. When a
cross-model relation fails, being able to inspect both sides of the offer —
the provider's endpoints and the consumer's status — would significantly
improve autonomous debugging of CMR issues.

### 5. Secrets Inspection

JujuMate lists Juju secrets with owner, granted applications, and rotation
policy. It can optionally decode base64-encoded secret values for display.

**Relevance to Cantrip:** As more charms adopt Juju secrets (per best
practice), the agent needs to verify secrets are correctly created and granted.
A `list_secrets` tool would help diagnose "why can't my charm read this secret?"
issues. The base64 decoding and grant-tracking are the useful details.

### 6. YAML-Based Theming

JujuMate loads themes from YAML files — both built-in (shipped in the package)
and user-provided (`~/.config/jujumate/themes/`). A centralised `palette`
module provides semantic colour constants (SUCCESS, ERROR, WARNING, LINK, MUTED)
populated at startup via PEP 562 `__getattr__`. The theme picker screen lets
users switch themes live.

**Relevance to Cantrip:** The TUI currently has a single hardcoded colour
scheme. Adopting JujuMate's approach — YAML theme definitions, semantic
palette constants, user-overridable themes directory, and a theme picker screen
— would be straightforward since both projects use Textual. The semantic
constant approach (reference `palette.SUCCESS` not `"green"`) keeps the
codebase clean when multiple themes are in play. The PEP 562 module-level
`__getattr__` trick for lazy palette loading is elegant.

### 7. Subordinate Unit Tree Rendering

JujuMate displays subordinate units as tree children of their principal units
using `├─`/`└─` prefixes. This makes the unit hierarchy immediately clear in
the status view.

**Relevance to Cantrip:** The TUI status widget currently shows a flat list of
units. Tree rendering would improve readability for charms with subordinates
(common with observability agents, nrpe, landscape-client, etc.). Small visual
change, meaningful usability improvement.

### 8. Graceful Multi-Controller Failure

When a controller is unreachable during polling, JujuMate increments
`snapshot.failed` and continues with the remaining controllers. The UI still
shows data from healthy controllers rather than failing entirely.

**Relevance to Cantrip:** The watcher should be similarly resilient. If the dev
model's controller is temporarily unreachable (network blip, controller
restart), the agent should degrade gracefully rather than crashing the poll
loop. This is especially important for long-running autonomous sessions.

### 9. `_s()` Coercion for python-libjuju Quirks

python-libjuju returns `bytes | str | None` in many places. JujuMate has a
simple `_s()` helper that normalises these to `str`. Every python-libjuju result
passes through this coercion before being used.

**Relevance to Cantrip:** Cantrip uses Jubilant (which wraps `juju` CLI output)
so this isn't directly needed today. But if any Phase 20 tools use
python-libjuju directly (e.g. WebSocket log streaming, relation databag
inspection), adopting this coercion pattern will prevent type errors from
libjuju's inconsistent return types.

### 10. Inline Table Filtering

Pressing `/` opens a case-insensitive search bar that filters all table rows
and highlights matches. Works across every view (apps, units, machines, etc.).

**Relevance to Cantrip:** The TUI status widget would benefit from the same
pattern when monitoring large deployments. A simple text filter over DataTable
rows is easy to implement in Textual and immediately useful when models have
dozens of units.

### 11. 100% Test Coverage with Safety Fixtures

JujuMate enforces `--cov-fail-under=100` in CI. A `no_juju_connection` fixture
is auto-applied to all tests to prevent accidental real Juju connections. Tests
use Textual's `async with app.run_test() as pilot` pattern for UI testing.

**Relevance to Cantrip:** The safety fixture pattern is immediately adoptable.
Auto-applying a fixture that blocks real Jubilant/Juju connections in unit tests
prevents the "test accidentally hit my live controller" class of bugs. The
`run_test()` pilot pattern for TUI widget tests is also worth expanding in
Cantrip's test suite.

### 12. Minimal Dependency Footprint

JujuMate has exactly 3 runtime dependencies: `juju` (python-libjuju),
`websockets`, and `textual`. Everything else is stdlib.

**Relevance to Cantrip:** A reminder to keep the dependency count honest.
Every new dependency is an ongoing maintenance burden, a potential supply-chain
risk, and a snap-packaging complication. When adding Phase 20 tools, prefer
stdlib + existing dependencies over new packages.

---

## Summary: Priority Matrix

| Priority | Idea | Cantrip Impact |
|----------|------|----------------|
| High | Relation databag inspection tool | Diagnoses the #1 charm failure mode (integration issues) |
| High | App config with source tracking tool | Answers "why isn't my config working?" autonomously |
| Medium | WebSocket log streaming | Log access without COS; lower latency than SSH-to-Loki |
| Medium | YAML-based TUI theming | User-customisable look; semantic palette for clean code |
| Medium | Safety fixtures for Juju in tests | Prevents accidental real connections in unit tests |
| Low | Cross-model offer awareness | Useful for complex multi-model deployments |
| Low | Secrets inspection | Growing importance as charms adopt Juju secrets |
| Low | Subordinate unit tree rendering | Better visual hierarchy in status display |
| Low | Inline table filtering | Useful for large deployments |

---

## Key Code References in JujuMate

| Module | What it does |
|--------|-------------|
| `src/jujumate/client/juju_client.py` | Async python-libjuju wrapper; `_parse_*` functions normalise raw status into dataclasses |
| `src/jujumate/client/watcher.py` | `JujuPoller` — periodic polling, `PollSnapshot` building, Textual message posting |
| `src/jujumate/models/entities.py` | ~16 `@dataclass` types for Juju entities (CloudInfo, AppInfo, UnitInfo, etc.) |
| `src/jujumate/palette.py` | Centralised colour constants via PEP 562 `__getattr__`; populated from active theme |
| `src/jujumate/theme_loader.py` | YAML theme loading (built-in + user), returns Textual `Theme` objects |
| `src/jujumate/screens/main_screen.py` | Tab management, drill-down navigation, keyboard bindings |
| `src/jujumate/screens/relation_data_screen.py` | Relation databag inspector (app-level + unit-level) |
| `src/jujumate/screens/secrets_screen.py` | Secrets browser with base64 decoding |
| `src/jujumate/screens/app_config_screen.py` | App config viewer with source tracking |
| `src/jujumate/screens/offers_screen.py` | Cross-model offers browser with consumer tracking |
| `src/jujumate/screens/log_screen.py` | WebSocket-based live log streaming with level filtering |
| `src/jujumate/screens/theme_screen.py` | Live theme picker |
| `src/jujumate/widgets/status_view.py` | Main status display with subordinate tree rendering |
| `src/jujumate/widgets/navigable_table.py` | Keyboard-navigable DataTable with inline filtering |
| `src/jujumate/settings.py` | App settings dataclass, YAML config loader/saver |
| `src/jujumate/config.py` | Reads Juju config files (controllers.yaml, models.yaml) |
