# Questions to Clarify

## Naming
1. ~~What's your reaction to "Snake Charmer"?~~
   **DECIDED: Cantrip** - A small, simple spell. Fits "quick charm in 2 minutes".

## Target Users & Use Cases

**CLARIFIED:** Three distinct paths identified:
- **Path A: 12-Factor PaaS** - Flask, Django, Go, etc. Use existing paas-charm system (details TBD)
- **Path B: Custom App** - Doesn't fit 12-factor, needs full scaffolding
- **Path C: Infrastructure** - MariaDB, Redis, etc. - complex operational patterns

2. **Who is the primary user?**
   - Developers charming their own applications? (Paths A & B)
   - Ops folks charming existing open-source software? (Path C)
   - Both?

3. ~~What's a typical "charm for X" request?~~ → Answered above

## Charm Complexity

4. ~~What should the initial "2 minute" charm include?~~
   **ANSWERED:** Packed, deployed, active status, workload running. That's it. Everything else is iteration.

5. ~~For K8s charms, do we assume an OCI image exists, or should finding/building one be part of the flow?~~
   **ANSWERED:** Prefer existing OCI images. Search registries first. If not found or broken/needs changes → build a rock.

### New Questions - Three Paths

6a. **Path A (12-Factor): What frameworks are currently supported?**
    - Flask, Django, Go - what else?
    - Is FastAPI supported?
    - How does the agent detect which framework?

6b. **Path A: What's the paas-charm workflow?**
    - User provides code repo → agent generates rockcraft.yaml → builds rock → deploys?
    - Are there specific files the agent needs to look for/generate?

6c. **Path B (Custom): What's the threshold between "custom" and "should be 12-factor"?**
    - e.g., A Python app that's not Flask/Django - try to fit 12-factor or go custom?

6d. **Path C (Infrastructure): Should the agent check Charmhub first?**
    - "Charm MariaDB" → "There's already a mariadb charm, want to use that instead?"
    - Or assume user wants a new/different charm?

6e. **Path C: How much infra knowledge should be baked in vs. researched?**
    - Common patterns (primary/replica, clustering) as templates?
    - Or agent researches each time?

## Integrations
6. **Which integrations should be "automatic" or strongly suggested?**
   - Observability (Grafana, Prometheus, Loki)?
   - Ingress for K8s?
   - Database relations?
   - What's the "default stack" you'd want?

7. **For integration discovery, should the agent:**
   - Query Charmhub for compatible charms?
   - Have a curated list of common integration patterns?
   - Both?

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
10. **What testing frameworks/approaches for charms?**
    - pytest-operator?
    - Scenario testing?
    - Integration tests with real Juju?
    - All of the above?

## LLM Architecture
11. ~~Single agent or multi-agent?~~
    **DECIDED: Hybrid** - Main agent handles conversation + code, spawns background agents for tests, research, trace queries.

12. ~~For multi-provider support, priority order after Gemini?~~
    **DECIDED:** Gemini first (Canonical preference), Claude second (best performance), others TBD.

## Environment
13. **Concierge setup - what's the default environment?**
    - LXD for machine charms?
    - MicroK8s for K8s charms?
    - User chooses?
    - Detect from charm type?

    **PARTIALLY ANSWERED:** Agent analyses workload, makes recommendation, asks user to confirm.

14. **Should the agent manage multiple models/environments simultaneously?**

## Persistence & Projects
15. **How should charm projects be persisted?**
    - Git repo per charm?
    - Working directory structure?
    - Project files that can be resumed?

16. **Should the agent track "charm sessions" that can be continued later?**

## Charm Libraries
17. **Should the agent know about and fetch charm libraries?**
    - ops library (core)
    - Common interface libs (database, ingress, etc.)
    - Custom libs from Charmhub?

## Scope Boundaries
18. **What's explicitly OUT of scope for v1?**
    - Bundle creation?
    - Charm publishing to Charmhub?
    - Cross-model relations?
    - Production deployment advice?

## Your Expertise
19. **You mentioned providing guidance for writing charms well - in what form?**
    - A document I can feed to the agent?
    - Interactive guidance during planning?
    - Both?

20. **Are there existing charm templates or patterns you'd want baked in?**
