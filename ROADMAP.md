# Cantrip Implementation Roadmap

## Phase 0: Foundation

**Goal:** Basic infrastructure that everything else builds on.

### 0.1 Project Skeleton
- [ ] Set up uv project structure
- [ ] Configure pyproject.toml with dependencies
- [ ] Set up GitHub Actions CI (lint, type check, test)
- [ ] Create basic CLI entry point

### 0.2 LLM Abstraction
- [ ] Define LLM provider interface
- [ ] Implement Gemini provider
- [ ] Basic conversation loop (no TUI yet, just CLI)
- [ ] API key configuration

### 0.3 Juju Integration
- [ ] Jubilant wrapper for common operations
- [ ] Status parsing (JSON format)
- [ ] Model management basics

### 0.4 Skills Infrastructure
- [ ] Skills loader (lazy-load from agentskills.io format)
- [ ] Skills index (lightweight list of available skills + descriptions)
- [ ] Core charm skills:
  - [ ] `scenario-tests` - Writing unit tests with ops.testing
  - [ ] `jubilant-tests` - Writing integration tests with Jubilant
  - [ ] `relation-data-design` - Relation data bag patterns
  - [ ] `observability` - COS integration, ops-tracing
  - [ ] `ingress` - Traefik ingress configuration
  - [ ] `adding-actions` - Implementing charm actions
  - [ ] `adding-config` - Config options with validation
- [ ] System prompt includes skill index (names + one-line descriptions)
- [ ] Full skill content loaded only when agent needs it

**Exit criteria:** Can have a conversation with Gemini that calls Jubilant to show juju status.

---

## Phase 1: Minimum Viable Cantrip

**Goal:** "Build a charm for my Flask app" → active/running in 2 minutes.

### 1.0 Housekeeping
- [x] Migrate from `google-generativeai` to `google-genai` (the old package is deprecated and emits a FutureWarning)

### 1.1 Environment Setup
- [ ] Concierge integration
- [ ] Auto-setup LXD or Canonical K8s based on charm type
- [ ] COS-lite deployment to separate model
- [ ] Cross-model relation setup

### 1.2 12-Factor Path (Path A)
- [ ] **Fetch and summarise 12-factor tutorials** (prerequisite)
  - Rockcraft tutorials: Flask, Django, FastAPI, Go, Express, Spring Boot
    (https://documentation.ubuntu.com/rockcraft/stable/tutorial/)
  - Charmcraft tutorials: same 6 frameworks
    (https://documentation.ubuntu.com/charmcraft/stable/tutorial/)
  - Extract common workflow pattern into knowledge file for agent
- [ ] Framework detection (Flask, Django, Go, etc.)
  - Run `charmcraft list-extensions` to get current supported list
- [ ] paas-charm base integration
- [ ] rockcraft.yaml generation
- [ ] Rock building
- [ ] Deploy and verify active/running

### 1.3 Basic TUI
- [ ] Textual app shell
- [ ] Split view: status + chat
- [ ] Juju status display (from JSON)
- [ ] Basic chat input/output
- [ ] Status refresh

### 1.4 Conversational Iteration
- [ ] Add config options via conversation
- [ ] Add actions via conversation
- [ ] Re-deploy after changes

**Exit criteria:** User can say "build a charm for my Flask app", point at a repo, and have it running with basic COS integration.

---

## Phase 2: Development Experience

**Goal:** Fast iteration loop, observability-driven debugging.

### 2.1 Fast Dev Cycle
- [ ] juju ssh code injection for quick updates
- [ ] Automatic hook triggering
- [ ] Smart switching between fast/full paths
- [ ] Pack validation before "done"

### 2.2 Observability Integration
- [ ] ops-tracing integration in generated charms
- [ ] Tempo query for trace analysis
- [ ] Loki query for log analysis
- [ ] Agent uses traces to debug issues

### 2.3 Testing
- [ ] Scenario test generation
- [ ] Jubilant integration test generation
- [ ] Background test runner
- [ ] Test results in TUI

### 2.4 Persistence
- [ ] .cantrip/ folder structure
- [ ] Session save/restore
- [ ] Context summarisation for long sessions
- [ ] Decision tracking

**Exit criteria:** Agent can debug a failing charm by looking at traces, fix the issue, and run tests.

---

## Phase 3: Expand Charm Paths

**Goal:** Support custom apps and infrastructure, not just 12-factor.

### 3.1 Path B: Custom Applications
- [ ] Full charm scaffolding (not paas-charm base)
- [ ] Workload analysis
- [ ] Config/action inference
- [ ] Machine and K8s support

### 3.2 Path C: Infrastructure
- [ ] Charmhub search for existing charms
- [ ] Fork/extend existing charm workflow
- [ ] Operational pattern templates (primary/replica, etc.)
- [ ] Research mode for unknown software

### 3.3 OCI Image Handling
- [ ] Registry search (Docker Hub, GHCR, etc.)
- [ ] Image evaluation
- [ ] Rockcraft for building when needed

**Exit criteria:** Can charm a custom Python app and MariaDB with appropriate operational patterns.

---

## Phase 4: Polish & Ecosystem

**Goal:** Full integration showcase, multiple LLMs, publication.

### 4.1 Integration Expansion
- [ ] Full COS integration (all components)
- [ ] Sloth, Parca, Pyroscope
- [ ] Identity integration
- [ ] Litmus chaos testing

### 4.2 TUI Enhancements
- [ ] Visual model/app/integration graph
- [ ] Multiple model views
- [ ] Log viewer
- [ ] Trace viewer (or Grafana links)

### 4.3 Multi-LLM Support
- [ ] Claude provider
- [ ] Provider switching
- [ ] Model selection per task (cost optimisation)

### 4.4 Charmhub Publishing (Stage 2)
- [ ] charmcraft upload integration
- [ ] Release management
- [ ] README generation

**Exit criteria:** Showcase-ready demo of the full Canonical ecosystem.

---

## Phase 5: Advanced Features

**Goal:** Power user features, multi-agent maturity.

### 5.1 Background Agents
- [ ] Test runner agent
- [ ] Research agent
- [ ] Trace analysis agent
- [ ] Parallel execution

### 5.2 Advanced Workflows
- [ ] Charm pairs (app + database)
- [ ] Migration assistance
- [ ] Upgrade testing

### 5.3 Collaboration
- [ ] Export charm guidance for other tools
- [ ] Integration with existing charm repos

---

## Dependencies & Blockers

| Item | Blocked By | Notes |
|------|------------|-------|
| 12-factor path | Tutorial summarisation | Fetch & summarise 12 tutorials from rockcraft/charmcraft docs |
| Observability | COS deployment working | Need COS-lite reliable |
| Testing | Scenario/Jubilant docs | Need links |
| Libraries | PyPI migration list | Which libs are on PyPI |

---

## Milestones

| Milestone | Target | Definition |
|-----------|--------|------------|
| M0: Talking | Phase 0 done | CLI chat with Gemini + juju status |
| M1: First Charm | Phase 1 done | Flask app → running charm in 2 min |
| M2: Dev Loop | Phase 2 done | Fast iteration with trace debugging |
| M3: All Paths | Phase 3 done | 12-factor, custom, infra all working |
| M4: Showcase | Phase 4 done | Demo-ready for ecosystem showcase |
