# Questions to Clarify

## Naming
1. ~~What's your reaction to "Snake Charmer"?~~
   **DECIDED: Cantrip** - A small, simple spell. Fits "quick charm in 2 minutes".

## Target Users & Use Cases

**CLARIFIED:** Three distinct paths identified:
- **Path A: 12-Factor PaaS** - Flask, Django, Go, etc. Use existing paas-charm system (details TBD)
- **Path B: Custom App** - Doesn't fit 12-factor, needs full scaffolding
- **Path C: Infrastructure** - MariaDB, Redis, etc. - complex operational patterns

2. ~~Who is the primary user?~~
   **DECIDED:**
   - MVP: 12-factor developers (Path A)
   - Rapid follow-on: Custom apps (B) and infrastructure (C) - not deferred to Stage 2

3. ~~What's a typical "charm for X" request?~~ → Answered above

## Charm Complexity

4. ~~What should the initial "2 minute" charm include?~~
   **ANSWERED:** Packed, deployed, active status, workload running. That's it. Everything else is iteration.

5. ~~For K8s charms, do we assume an OCI image exists, or should finding/building one be part of the flow?~~
   **ANSWERED:** Prefer existing OCI images. Search registries first. If not found or broken/needs changes → build a rock.

### New Questions - Three Paths

6a. ~~**Path A (12-Factor): What frameworks are currently supported?**~~
    **ANSWERED:** Run `charmcraft list-extensions` to get current list.
    - **Stable (ubuntu@22.04):** Django, Flask
    - **Experimental (ubuntu@24.04):** ExpressJS, FastAPI, Go, Spring Boot
    - Agent should run this command to stay current rather than hardcoding the list

6b. ~~**Path A: What's the paas-charm workflow?**~~
    **ANSWERED:** Documented in official tutorials:
    - Rockcraft: https://documentation.ubuntu.com/rockcraft/stable/tutorial/
    - Charmcraft: https://documentation.ubuntu.com/charmcraft/stable/tutorial/
    - **Follow-up task:** Fetch and summarise all 12 tutorials (6 frameworks × 2) into agent knowledge (added to ROADMAP.md Phase 1.2)

6c. ~~**Path B (Custom): What's the threshold between "custom" and "should be 12-factor"?**~~
    **DECIDED:** Strict matching only.
    - Only use 12-factor path if framework is explicitly supported (`charmcraft list-extensions`)
    - Must have standard structure for that framework
    - Otherwise, go custom (Path B)
    - No forcing unsupported frameworks into 12-factor extensions

6d. ~~**Path C (Infrastructure): Should the agent check Charmhub first?**~~
    **DECIDED:** Yes, check first and suggest existing.
    - Agent searches Charmhub before building infrastructure charms
    - "There's already a `mariadb-k8s` charm maintained by Canonical. Want to use that instead?"
    - Only build new if user has specific reasons
    - Rationale: Infrastructure charms have battle-tested operational logic; reinventing is wasteful

6e. ~~**Path C: How much infra knowledge should be baked in vs. researched?**~~
    **DECIDED:** Hybrid approach.
    - Bake in high-level patterns (databases need replication/backups, caches need clustering, etc.)
    - Research specifics for each software (how does PostgreSQL streaming replication work?)
    - Also study existing Charmhub charms when available (per 6d) before building alternatives

## Integrations
6. ~~Which integrations should be "automatic" or strongly suggested?~~
   **DECIDED:**
   - Observability (COS): Always
   - Database: Almost always, support multiple if workload does (mysql + postgresql)
   - Ingress (Traefik): K8s, almost always
   - Also consider: Sloth, Parca, Pyroscope, Identity, Litmus
   - Philosophy: Show off the Canonical ecosystem

7. ~~For integration discovery, should the agent:~~
   **DECIDED:** Query Charmhub via API/charmcraft, stay current automatically.

## Observability

8. ~~Which specific observability stack?~~
   **ANSWERED:**
   - Minimum: ops-tracing for charm (helps agent debug too), ideally workload tracing
   - Full: COS/COS-lite (Tempo, Loki, Prometheus, Grafana, Alertmanager, catalogue-k8s)
   - Agent installs COS in local env and uses it during development

9. ~~How should the agent use tracing data for debugging?~~
   **ANSWERED:**
   - Query Tempo/Loki directly (primary)
   - Fallback to debug-log via jubilant
   - Link to Grafana for visualisation, don't replicate in TUI
   - Agent uses traces internally - user focuses on describing functionality

## Testing
10. ~~What testing frameworks/approaches for charms?~~
    **DECIDED:**
    - Unit tests: Scenario (ops.testing Context, State) - NOT Harness
    - Integration tests: Jubilant - NOT pytest-operator/python-libjuju
    - `charmcraft init` scaffolds test structure

## LLM Architecture
11. ~~Single agent or multi-agent?~~
    **DECIDED: Hybrid** - Main agent handles conversation + code, spawns background agents for tests, research, trace queries.

12. ~~For multi-provider support, priority order after Gemini?~~
    **DECIDED:** Gemini first (Canonical preference), Claude second (best performance), others TBD.

## Environment
13. ~~Concierge setup - what's the default environment?~~
    **DECIDED:**
    - Machine charms: LXD
    - K8s charms: Canonical K8s (`k8s` preset in concierge) - NOT MicroK8s
    - Agent recommends based on workload, user confirms

14. ~~Should the agent manage multiple models/environments simultaneously?~~
    **DECIDED:** Yes, Cantrip manages both dev model and COS model. User doesn't do setup.

## Persistence & Projects
15. ~~How should charm projects be persisted?~~
    **DECIDED:** Auto-persistence within charm folder (`.cantrip/` directory with session data).

16. ~~Should the agent track "charm sessions" that can be continued later?~~
    **DECIDED:** Yes, with context management (summarise old turns, keep recent verbatim, track decisions separately).

## Charm Libraries
17. ~~Should the agent know about and fetch charm libraries?~~
    **DECIDED:**
    - Yes, auto-fetch common interface libs
    - Prefer PyPI versions where available (list to be provided)
    - Use charmcraft.yaml + `charmcraft fetch-libs` for Charmhub libs

## Scope Boundaries
18. ~~What's explicitly OUT of scope for v1?~~
    **DECIDED:**
    - Bundles: OUT (deprecated)
    - Charmhub publishing: Stage 2
    - Cross-model relations: IN (especially for COS)
    - pytest-operator/python-libjuju: OUT (use Jubilant)
    - Harness: OUT (use Scenario)

## Your Expertise
19. ~~You mentioned providing guidance for writing charms well - in what form?~~
    **DECIDED:**
    - Starting point: https://github.com/tonyandrewmeyer/charming-with-claude
    - Additional docs/links to be provided during development
    - User is on Canonical Charm Tech team, responsible for docs + tools

20. ~~Are there existing charm templates or patterns you'd want baked in?~~
    **PARTIALLY ANSWERED:** `charmcraft init` provides scaffolding. Additional patterns via knowledge sources above.

## Knowledge Architecture

21. ~~How should domain knowledge be structured in the agent?~~
    **DECIDED:** Use [Agent Skills](https://agentskills.io/home) pattern.
    - Lightweight skills index always loaded (name + brief description)
    - Full skill document loaded on demand when needed
    - Keeps context window lean
    - Skills are shareable with other agent systems (interoperability)
    - Example skills: `scenario-tests`, `jubilant-tests`, `relation-data-design`, `observability`, `ingress`, `adding-actions`, `spread-tests`, `rockcraft`
