---
name: twelve-factor
description: Build 12-factor PaaS charms with paas-charm — fit, rock, charm, build, push, deploy, verify.
---

# 12-Factor PaaS Charm Workflow

This skill covers the complete workflow for building a Juju charm from a 12-factor web application using the **paas-charm** base.  Inspect first — generate nothing until the fit verdict is clear.  The structure here is adapted from canonical/skills PR #4 (Apache-2.0); the per-framework rules and the handoff-payload shape come from upstream.

## Phases at a Glance

1. **Fit Assessment** — confirm framework, web-service scope, deployment context, relation optionality, experimental gating, target environment.  Produce a handoff payload.  Stop early if the project does not fit.
2. **Rock Generation** — `rockcraft init` with the framework profile, validate the rock contract, stay inside the extension boundary.
3. **Charm Generation** — `charmcraft init` with the framework profile, mirror env contracts, never re-declare extension-embedded relations, keep `src/charm.py` stock.
4. **Build, Push, Deploy, Verify** — pack the rock, push to the registry, pack the charm, deploy with the OCI resource, watch `juju status`.

The rock and charm phases can run independently once the fit verdict is in.

## Framework-to-Profile Mapping

The "experimental" status differs between charmcraft and rockcraft.  Cantrip's ``rockcraft_init`` and ``rockcraft_pack`` tools set ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`` unconditionally — every rockcraft framework extension is still experimental upstream as of April 2026, even for the long-stable Flask and Django profiles.

| Framework   | Charmcraft Profile         | Rockcraft Profile          | Charmcraft Experimental? | Rockcraft Experimental? |
|-------------|----------------------------|----------------------------|--------------------------|-------------------------|
| Flask       | `flask-framework`          | `flask-framework`          | No                       | Yes                     |
| Django      | `django-framework`         | `django-framework`         | No                       | Yes                     |
| FastAPI     | `fastapi-framework`        | `fastapi-framework`        | Yes                      | Yes                     |
| Go          | `go-framework`             | `go-framework`             | Yes                      | Yes                     |
| Express     | `express-framework`        | `express-framework`        | Yes                      | Yes                     |
| Spring Boot | `spring-boot-framework`    | `spring-boot-framework`    | Yes                      | Yes                     |

To use a charmcraft-experimental extension you also need ``CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`` for ``charmcraft init`` and ``charmcraft pack`` — Cantrip's ``charmcraft_init`` sets this for the relevant profiles.

---

## Phase 1: Fit Assessment

### Fit Workflow

1. Inspect the repository before asking questions.
2. Run ``analyse_framework`` to get a framework verdict with signals, candidates, and a web-app-fit guess.  If multiple candidates score similarly, surface the alternatives to the user before committing.
3. If the repo clearly separates backend and frontend in a monorepo, stop treating the repo root as the packaging target.  Confirm which backend subdirectory should be the 12-factor scope.
4. Confirm the detected framework with the user.
5. Confirm the application is meant to run as a web service on a Kubernetes-backed Juju model.
6. If the repo separates frontend and backend into different subdirectories, default to applying the 12-factor workflow to the backend subdirectory only.  Do not bundle both into one image without explicit user confirmation.
7. If the repo has a frontend or static-asset build step, ask the user explicitly whether that build belongs inside the rock or remains a separate deployment concern.  Do not infer ``frontend_build`` on your own.
8. Ask the **mandatory questions** below for any answer the conversation has not already established.
9. Confirm whether the app needs database migrations and whether they should be framework-managed or use a root ``migrate.sh``.
10. Confirm whether the app needs extra ``-worker`` or ``-scheduler`` services alongside the main web service, and capture the intended commands.
11. If any relation will be declared in the charm beyond those already embedded in the charmcraft extension (ingress, grafana-dashboard, metrics-endpoint, logging are extension-provided with fixed optionality), ask which of those additional relations should be optional in charm metadata.  Do not infer requiredness from repo inspection or app behaviour alone.
12. If the framework is FastAPI, Go, Express, or Spring Boot, ask whether the user accepts the experimental extension path and edge-channel tooling.
13. Once the user has answered, run ``preflight_targets`` to verify the chosen Kubernetes context, Juju controller, registry, and required local tools.
14. Produce a fit verdict (the handoff payload below) or explicit stop reasons if the project does not fit.

### Mandatory Questions

Ask these unless the answer is already explicit and reliable in the conversation.

**Fit and intent:**

- Which framework should I target?
- Is this application meant to run as a web service?
- Is the target Juju model Kubernetes-backed?
- If the repo is a monorepo, which subdirectory is the backend application root?
- If the framework is FastAPI / Go / Express / Spring Boot: do you accept the current experimental-extension path, including edge-channel ``rockcraft`` and ``charmcraft``?

**Deployment contract:**

- Should the charm remain local, or do you want a Charmhub-first workflow?
- Which Juju controller should I use?
- Which model should I use or create?

**Rock and registry:**

- Which OCI registry should hold the rock?
- Can the target cluster pull from that registry?
- Do registry credentials need to be configured?

**Cluster selection:**

- Which Kubernetes context or cluster should I target?
- Should I inspect the available contexts before you choose?

**Runtime behaviour:**

- Which port should the application listen on?
- Which settings should become charm config options?
- Which of those settings are secrets?
- Does the app have a frontend build step (webpack, Vite, Angular, Vue, ``collectstatic``, …)?
- Should that frontend build stay separate, or do you want it embedded into the backend image for this project?
- Does the app require a database?  If yes, which one?
- Are database migrations needed?  If yes, framework-managed or via a root ``migrate.sh``?
- Does the app need extra ``-worker`` or ``-scheduler`` services?  If yes, what commands?
- Do you need ingress, observability, proxying, S3, SMTP, Redis, RabbitMQ, OIDC, SAML, OpenFGA, or tracing now?  (Note: ingress, grafana-dashboard, metrics-endpoint, and logging are already embedded in the charmcraft extension with fixed optionality — do not ask about those.)
- For each additional relation declared in the charm beyond the extension-embedded set: should it be ``optional: true`` or ``optional: false`` in charm metadata?
- If ingress is needed: what external hostname should the app be reachable at?

**Layout adaptation:**

- The framework extension expects the app under ``<expected-path>/``.  If the repo does not match, is a small trial-copy layout adaptation acceptable?

### Stop-Early Conditions

Stop and explain why if any of these are true:

- the framework is outside the supported set (Flask, Django, FastAPI, Go, Express, Spring Boot);
- the project is not a web application;
- the app cannot reasonably read runtime configuration from env vars;
- the deployment target is not Kubernetes-backed Juju;
- the repo separates frontend and backend and the requested scope is to force both into one image anyway;
- the repo has a frontend / static-build question and the user has not confirmed whether it should be embedded or kept separate;
- a relation should be declared in the charm but the user has not confirmed its optionality;
- the project only works after leaving the extension boundary.

### Handoff Payload

Once the fit checks pass, record the following structure (in conversation, in a comment, or in a scratch file) so the rock and charm phases do not have to re-derive the answers.  Adapted from the upstream's handoff contract.

```yaml
framework: <flask | django | fastapi | go | express | spring-boot>
repo_path: <absolute path>
k8s_context: <string>
juju_controller: <string>
juju_model: <string or null>
registry: <string>
charm_publication: local | charmhub
deployment_mode: provider-first | hybrid-local-artifact
relations:
  - name: <relation name>
    optional: true | false
config_options_needed:
  - <option name>
frontend_build: none | embedded-in-backend-image | separate-deployment
migrations:
  mode: none | framework-managed | migrate-sh
  tool: <string or null>
background_services:
  workers:
    - <service name or command>
  schedulers:
    - <service name or command>
experimental_extensions_accepted: true | false
minimal_change_policy: true
ingress:
  needed: true | false
  external_hostname: <string or null>
```

---

## Phase 2: Rock Generation

Stay inside the extension.  If the repo only works after replacing the extension, stop.

### Rock Workflow

1. Reuse the fit verdict.
2. Run ``check_rock_contract`` with the chosen framework before generating anything.  It returns blocking issues, advisory warnings, and the supported ``base:`` list.  Resolve every blocking issue before continuing.
3. If the framework is FastAPI / Go / Express / Spring Boot, verify the user accepted the experimental path and that ``rockcraft`` is on an edge channel (``preflight_targets`` reports the snap channel).
4. If the repo separates frontend and backend, confirm the backend subdirectory is the target scope before running ``rockcraft init``.
5. If the app needs database migrations, prefer a root ``migrate.sh`` for Flask / FastAPI / Express / Go when the repo does not already provide a supported migration entrypoint.  For Django, ``paas-charm`` uses ``manage.py migrate`` whenever ``manage.py`` exists, so a new ``migrate.sh`` will not replace that path.  For Spring Boot, prefer framework-managed migrations (Flyway / Liquibase) unless the repo already exposes a compatible wrapper.
6. If the app needs background services, add ``rockcraft.yaml`` services whose names end in ``-worker`` or ``-scheduler``.  ``-worker`` services run on every unit; ``-scheduler`` services run on exactly one unit — name deliberately.
7. Run ``rockcraft_init`` with the exact framework profile.  Always use the tool — never copy from templates, previously generated files, or example rocks.
8. Inspect the generated ``rockcraft.yaml``.
9. If you add or override Pebble services, inspect the effective expanded service command, user, and working directory before packing.
10. If the service runs as a non-root user (``_daemon_``), verify any path the app may write to at startup is writable by that user, or relocate that mutable state.
11. If the application binary is a multi-command CLI, make the Pebble service command invoke the actual long-running subcommand (``server``, ``worker``, …) rather than the bare top-level binary.
12. Build with ``rockcraft_pack``.  Never use ``--destructive-mode``.
13. If ``rockcraft pack`` fails on ``base: bare``, first try a supported Ubuntu base from the contract table below before deeper dependency surgery.

### Allowed Edits

- name, summary, description, version, platforms;
- ``build-packages`` / ``stage-packages`` the app actually needs;
- staged files the extension does not already include;
- tuning extension-owned parts;
- a root ``migrate.sh`` when the app needs migrations and the repo does not already expose a supported entrypoint;
- ``-worker`` / ``-scheduler`` services with repo-backed or user-confirmed commands;
- a small repo-backed startup wrapper or entrypoint shim when the app needs a minimal bridge from fixed ``paas-charm`` env names to its existing runtime contract;
- ownership / mode adjustments for runtime-mutated files inside extension-owned parts;
- frontend / static-asset preparation when the user explicitly confirmed the embedded path;
- moving to a supported Ubuntu base when ``base: bare`` fails.

### Disallowed Edits

- rewriting the rock from ``rockcraft expand-extensions`` output;
- creating a bespoke manual rock as a silent fallback;
- generating ``rockcraft.yaml`` by copying from templates;
- defaulting to bundling separated frontend/backend into one image;
- widening the staged file set unless the extension contract requires it;
- upgrading app dependencies before trying an older supported ``build-base`` for Python frameworks;
- inventing ``-worker`` / ``-scheduler`` commands without repo evidence or a user-confirmed handoff;
- duplicate migration paths when the framework already manages migrations;
- moving static-asset / frontend build work into the charm when it can be done at rock build time;
- ``rockcraft pack --destructive-mode``.

### Per-Framework Rock Contracts

| Framework | Runtime | Bases | Required Evidence |
|-----------|---------|-------|-------------------|
| Flask | Gunicorn | ``bare``, ``ubuntu@22.04``, ``ubuntu@24.04`` | ``requirements.txt`` or ``pyproject.toml`` with ``flask``; discoverable WSGI entrypoint |
| Django | Gunicorn | ``bare``, ``ubuntu@22.04``, ``ubuntu@24.04`` | root ``requirements.txt``; runtime app under ``<repo>/<project-name>/``; supported ``wsgi.py`` with ``application`` |
| FastAPI | Uvicorn | ``bare``, ``ubuntu@24.04`` | root ``requirements.txt`` with ``fastapi`` or ``starlette``; discoverable ASGI ``app`` object |
| Express | ``npm start`` | ``bare``, ``ubuntu@24.04`` | ``app/package.json`` with ``name`` and ``scripts.start`` |
| Go | compiled binary | ``bare``, ``ubuntu@24.04`` | root ``go.mod``; service command defaults to the rock name; extra assets via ``go-framework/assets`` |
| Spring Boot | fat jar | ``bare``, ``ubuntu@24.04`` | exactly one active build system (``pom.xml`` XOR ``build.gradle``); ``mvnw`` XOR ``gradlew``; wrapper scripts executable |

### Framework-Specific Rock Notes

**Flask** — realistic apps may need extra staged runtime files (``config.py``, ``migrations/``, ``migrate.sh``).  ``-r requirements/*.txt`` includes are handled by the dep parser in ``check_rock_contract``.

**Django** — realistic repos often need a trial-copy layout adaptation to match the extension's directory expectations.  If Python deps compile native code, add only the missing ``build-packages`` to ``django-framework/dependencies``.  If ``pyproject.toml`` plus ``charm/`` causes ``pip install .`` to fail, treat it as a build-tooling interaction and make the smallest explicit workaround.  ``collectstatic`` belongs in the rock build, not the charm.

**FastAPI** — on ``base: bare``, Python comes from ``build-base``; ``ubuntu@22.04`` gives Python 3.10, ``ubuntu@24.04`` gives Python 3.12.

**Express** — root-level Express repos are valid fit candidates but the rock contract requires a move into ``app/``.  On ``base: bare`` the extension already stages Node and npm.  Be careful with code that forces TLS just because a database URL is set.

**Go** — if you override ``services.go.command``, the extension stops auto-adding the default binary organize rule; when the main package directory name differs from the rock name, add an explicit ``go-framework/install-app.organize`` mapping rather than manualising the rock.  Multi-command CLIs need an explicit subcommand in the Pebble service command.

**Spring Boot** — wrapper scripts (``mvnw``, ``gradlew``) must be executable before build.  Dual-build-system repos need explicit user confirmation of which build path to keep.  ``application.properties`` / ``application.yml`` is the natural place to bridge env-driven runtime config.

---

## Phase 3: Charm Generation

Always build the charm in ``charm/``.  Treat ``paas-charm`` as part of the contract.

### Charm Workflow

1. Reuse the fit verdict.
2. Create or use a dedicated ``charm/`` subdirectory.  Do not generate the charm at project root.
3. If the framework is FastAPI / Go / Express / Spring Boot, verify the user accepted the experimental path and that ``charmcraft`` is on an edge channel with ``CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true``.
4. Run ``charmcraft_init`` with the exact framework profile inside ``charm/``.  Always use the tool — never copy from templates, previously generated files, or example charms.
5. Inspect the generated ``charmcraft.yaml``, ``requirements.txt``, and ``src/charm.py``.
6. Run ``inspect_env_keys`` with the framework to inventory application env expectations before adding config options or workload-side env bridges.  The tool returns the framework's expected env contract (built-in vars, user-config prefix, relation env families) alongside the detected keys so you can spot keys the workload reads that ``paas-charm`` will not deliver.
7. If the repo already has a ``rockcraft.yaml``, inspect ``services.*.environment`` for the main app service and any worker / scheduler services.  Assume those rock-defined env vars will not survive automatically once ``paas-charm`` renders the workload Pebble layer; mirror the required keys.
8. Add only user-confirmed relations and config options.  Do not add or re-declare extension-embedded relations.
9. For each declared relation, set ``optional`` from the fit handoff or the user's explicit answer.  If that choice is missing, stop and ask — never default.
10. For Express, verify whether the generated charm injects ``app-port`` while current ``paas-charm`` aliases still expect ``port``.  If so, add a non-conflicting ``port`` config option rather than rewriting charm logic.
11. Treat generated ``paas-charm`` env output as the baseline contract.  When ``rockcraft.yaml`` defines service env, prefer non-conflicting charm config defaults for deploy-time values, or a tiny workload-side defaulting bridge for static app-facing defaults, before editing charm Python.
12. For OAuth / OIDC, prefer deploy-time config such as ``<endpoint>-redirect-path`` over charm subclassing or relation-hook overrides.
13. If live Juju or Pebble logs show service exit loops, CLI usage output, or ``permission denied`` on workload paths, treat that as a rock / runtime issue first.  Inspect the rock service command, runtime user, and writable paths before considering charm Python changes.
14. If ``src/charm.py`` changes still seem necessary after exhausting workload-side adaptations, stop and ask before modifying it.
15. Build with ``charmcraft_pack``.  Never use ``--destructive-mode``.

### Extension-Embedded Relations

The charmcraft framework extensions already declare these relations in the generated ``charmcraft.yaml`` with fixed optionality.  **Do not re-declare them.**  Do not ask the user whether they should be optional — the extension owns that decision.

| Relation | Interface | Optionality |
|----------|-----------|-------------|
| ingress | ``ingress`` | required |
| grafana-dashboard | ``grafana_dashboard`` | optional |
| metrics-endpoint | ``prometheus_scrape`` | optional |
| logging | ``loki_push_api`` | optional |

### `paas-charm` Runtime Contract

Generated 12-factor charms subclass ``paas-charm`` framework classes.  ``paas-charm`` owns:

- readiness gating;
- ingress publication;
- secret handling and rotation;
- migration execution;
- relation-driven env generation;
- supported relation env injection into the workload;
- Pebble layer overlay;
- observability wiring.

**Migration precedence** (current ``paas-charm`` checks in this order, last match wins):

1. ``manage.py``
2. ``migrate.py``
3. ``migrate.sh``
4. ``migrate``

Because Django repos normally have ``manage.py``, adding a repo ``migrate.sh`` will *not* replace the default migration path — ``paas-charm`` will still prefer ``manage.py migrate``.

**Rock-defined service env**: env set under ``services.*.environment`` in ``rockcraft.yaml`` should not be assumed to survive unchanged once the app runs under the charm.  ``paas-charm`` owns the final Pebble layer; mirror required keys into the charm-managed contract.

### Per-Framework Charm Contracts

**Flask** — Charmcraft extension is stable.  Built-in config surface includes Gunicorn options plus Flask-specific settings; built-in env shape is mostly ``FLASK_*``.

**Django** — Charmcraft extension is stable.  Built-in config surface includes Gunicorn options, ``django-debug``, ``django-secret-key``, ``django-allowed-hosts``.  Built-in action surface includes ``create-superuser``.  Built-in env shape is mostly ``DJANGO_*``.  Prefer the built-in config for ``django-secret-key`` and ``django-allowed-hosts`` over inventing parallel charm options.  ``manage.py migrate`` is always preferred — do not rely on a repo ``migrate.sh`` to force static asset work.  ``collectstatic`` belongs in the rock build.

**FastAPI** — experimental.  Built-in config surface includes ``webserver-workers``, ``webserver-port``, ``webserver-log-level``, ``metrics-*``, ``app-secret-key``.  Built-in env shape is mostly unprefixed framework variables plus ``APP_*`` for user config.

**Express** — experimental.  Built-in config surface includes ``app-port``, ``metrics-*``, ``app-secret-key``.  Known mismatch: current ``paas-charm`` Express aliases may expect ``port`` while the charm injects ``app-port``.  Adding a non-conflicting ``port`` config option is the preferred bridge.

**Go** — experimental.  Built-in config surface includes ``app-port``, ``metrics-*``, ``app-secret-key``.  Built-in env shape is ``APP_*``.  Relation-provided database URLs often need a small workload-side alias to the repo's existing config key.

**Spring Boot** — experimental.  Built-in config surface includes ``app-port``, ``app-profiles``, ``metrics-*``, ``app-secret-key``.  Default metrics path is ``/actuator/prometheus``.  Relation env is heavily translated into Spring property names: ``spring.datasource.url``, ``spring.data.redis.url``, ``spring.security.oauth2.*``, ``management.endpoints.web.*``.

### Pebble Failure Triage

- Service exit loops with CLI usage output → rock service-command problem first.  Inspect the effective Pebble command before editing charm Python.
- ``permission denied`` on workload paths (``/app``, …) → rock filesystem-layout or runtime-user problem first.  Inspect writable paths before charm changes.

---

## Phase 4: Build, Push, Deploy, Verify

The scaffolded ``requirements.txt`` for any PaaS profile contains both ``ops`` and ``paas-charm`` — these are mandatory.  ``src/charm.py`` imports ``paas_charm.<framework>``, so removing ``paas-charm`` makes the charm crash at install time with ``ModuleNotFoundError: No module named 'paas_charm'``.

If you bring the application's own ``requirements.txt`` into the charm directory, **merge** — never overwrite.  The charm's ``requirements.txt`` must end up with both the app's runtime deps (e.g. ``flask``) AND ``ops`` + ``paas-charm``.  A ``cp requirements.txt <charm-dir>/`` is a bug.

### 1. Pack the Rock

```bash
rockcraft pack
```

Use ``rockcraft_pack``.  As of rockcraft 1.18, the Flask, Django, and FastAPI extensions default to a **bare** base — the resulting rock contains only the application and its runtime dependencies, no Ubuntu shell or apt.  Smaller image, faster pulls, smaller attack surface.  Override with an explicit ``base:`` only when the workload genuinely needs system packages.

### 2. Push to a Container Registry

```bash
skopeo copy --insecure-policy --dest-tls-verify=false \
  oci-archive:my-app_0.1_amd64.rock \
  docker://localhost:32000/my-app:latest
```

Use ``skopeo_registry_push``.  The default registry is ``localhost:32000`` — but **call ``local_registry_status`` first** to confirm a local registry is reachable.  The canonical ``k8s`` snap (the preferred substrate) does **not** ship a registry, so the typical first-run on a fresh ``k8s`` dev box looks like:

1. ``local_registry_status`` → reports "no registry, k8s snap detected"
2. ``setup_local_registry`` → deploys a registry charm into the dev model and prints the sudo block for containerd trust
3. Apply the sudo block once (operator action)
4. ``skopeo_registry_push`` to the URL ``setup_local_registry`` returned

Only fall back to MicroK8s (``microk8s enable registry``) if the user has explicitly asked for that substrate.  Avoid public registries (ghcr.io, Docker Hub) unless the image is already there or the user has pointed you at one — ``registry_mirror`` handles the rate-limit case where copying a public image into the local registry once saves repeated round-trips.

### 3. Pack the Charm

```bash
charmcraft pack
```

Use ``charmcraft_pack``.  Produces a ``.charm`` file ready for deployment.

### 4. Deploy with Resources

```bash
juju deploy ./my-app_amd64.charm \
  --resource oci-image=localhost:32000/my-app:latest
```

Use ``juju_deploy`` with ``resources={"oci-image": "localhost:32000/my-app:latest"}``.  For charms that access cloud APIs (e.g. ingress), also pass ``trust=True``.

### 5. Verify

```bash
juju status --watch 5s
```

Use ``juju_status``.  The application should reach ``active/idle`` within a couple of minutes.  If it stays in ``waiting`` or ``blocked``, check the status message and logs.

---

## Database Integration (PostgreSQL)

Most 12-factor apps need a database.  The paas-charm profiles support PostgreSQL via a standard ``requires`` relation.  Add to ``charmcraft.yaml`` (set ``optional`` from the user's explicit answer in the fit phase):

```yaml
requires:
  postgresql:
    interface: postgresql_client
    optional: false
```

Deploy and relate:

```bash
juju deploy postgresql-k8s --trust
juju integrate my-app:postgresql postgresql-k8s:database
```

The framework automatically exposes database connection details as environment variables (``POSTGRESQL_DB_CONNECT_STRING``, etc.).

## HTTP Proxy

Charmcraft 4.2+ ships an ``http-proxy`` integration for 12-factor charms that automatically wires charm config (or a related proxy charm) into the workload's ``http_proxy`` / ``https_proxy`` / ``no_proxy`` environment variables.  Add to ``charmcraft.yaml``:

```yaml
requires:
  http-proxy:
    interface: http_proxy
    optional: true
```

Useful in restricted environments where the workload needs to reach external HTTP services through a corporate proxy.

## OpenID Connect / SSO

For 12-factor charms that need authentication, the OIDC integration adds an ``oidc`` relation that exposes the OpenID Connect provider's issuer URL, client ID, and client secret to the workload as environment variables.  Add to ``charmcraft.yaml``:

```yaml
requires:
  oidc:
    interface: oauth
    optional: true
    limit: 1
```

Deploy alongside an OIDC provider charm (Hydra, Keycloak, …) and integrate; the paas-charm base populates the env vars on the workload's behalf.

For Canonical Identity Platform integration (Hydra + Kratos + login-ui as a bundle), load the ``identity-platform`` skill — it covers the bundle-based default topology, the four other relation interfaces (``oauth-cli``, ``oidc-info``, ``hydra-token-introspect``, ``kratos-external-idp``), and the worked example for a 12-factor charm.

## Observability

The ``charmcraft_init`` tool automatically adds the ``tracing`` relation to ``charmcraft.yaml`` for all profiles (including PaaS framework profiles).  Once COS is deployed, wire up tracing:

```bash
juju integrate my-app:tracing cos.tempo:tracing
```

For standard (non-PaaS) charms, ``charmcraft_init`` also injects ``ops-tracing`` into ``requirements.txt`` and ``src/charm.py`` — no manual setup needed.  For full observability (metrics, logs, dashboards), load the ``observability`` skill.

## Config Options and Environment Variables

12-factor apps are configured through environment variables.  The paas-charm base auto-converts charm config options to environment variables with a framework-specific prefix.

| Framework | User-Config Prefix |
|-----------|--------------------|
| Flask | ``FLASK_`` |
| Django | ``DJANGO_`` |
| FastAPI | ``APP_`` |
| Go | ``APP_`` |
| Express | ``APP_`` |
| Spring Boot | ``APP_`` (also ``spring.*`` properties) |

Example — adding a config option:

```yaml
# charmcraft.yaml
config:
  options:
    log-level:
      type: string
      default: "info"
      description: Application log level
```

For Flask this becomes ``FLASK_LOG_LEVEL`` on the workload.  Use ``inspect_env_keys`` to surface the env vars the application actually reads, then map them through charm config.

## Version Bumps

When updating the application:

1. Bump ``version`` in ``rockcraft.yaml``.
2. Run ``rockcraft pack`` → new ``.rock``.
3. Push new image with an updated tag (e.g. ``0.2``).
4. Run ``charmcraft pack`` if charm metadata changed.
5. ``juju refresh my-app --path=./my-app.charm --resource oci-image=localhost:32000/my-app:0.2``.

## Common Pitfalls

1. **Forgetting the experimental flag** — Go, Express, FastAPI, and Spring Boot profiles fail without ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`` (and ``CHARMCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`` for the matching charmcraft path).  ``preflight_targets`` reports both gates.
2. **Re-declaring extension-embedded relations** — ingress, grafana-dashboard, metrics-endpoint, and logging are already declared with fixed optionality; do not re-declare them in ``charmcraft.yaml``.
3. **Inferring relation optionality** — every additional relation's ``optional`` field must come from the fit handoff or an explicit user answer.  Defaulting to ``optional: false`` because "it feels required" is wrong.
4. **Missing ``resources`` section in ``charmcraft.yaml``** — the charm cannot pull the OCI image without a declared ``oci-image`` resource.
5. **Not pushing the rock before deploying** — ``juju deploy`` pulls the image from the registry; if it is not there, the unit will enter ``error`` state.
6. **Registry TLS errors** — the local registry at ``localhost:32000`` does not use TLS.  Always pass ``--dest-tls-verify=false`` to skopeo.
7. **Stale images** — after a ``rockcraft pack`` + push, the K8s node may cache the old image.  Use a unique tag (not just ``latest``) or delete the pod to force a re-pull.
8. **Wrong profile** — using the ``kubernetes`` profile instead of a framework profile gives a bare ops charm without the paas-charm base.  Always match the profile to the detected framework.
9. **Adding ``migrate.sh`` for Django** — ``paas-charm`` always prefers ``manage.py migrate`` when ``manage.py`` exists.  A new ``migrate.sh`` will not replace that path.
10. **Spring Boot dual build systems** — the rock contract rejects repos that expose both ``pom.xml`` and ``build.gradle`` (or ``build.gradle.kts``).  ``check_rock_contract`` flags this before ``rockcraft pack``.
11. **Editing ``src/charm.py`` to fix workload issues** — Pebble service-command failures, ``permission denied`` on ``/app``, missing env vars are rock / runtime issues first.  Fix the rock before touching charm Python.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| ``rockcraft init`` fails with "unknown extension" | Experimental flag not set | Set ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`` |
| ``check_rock_contract`` reports issues | Framework contract violated | Resolve every issue before ``rockcraft pack`` |
| Unit stuck in ``waiting`` | Image not in registry | Push the rock with ``skopeo_registry_push`` |
| Unit in ``error`` | Workload crash | Check ``juju debug-log`` for container errors |
| ``blocked: missing relation`` | Database or ingress not related | Run ``juju_relate`` to add the integration |
| Config change has no effect | Wrong env var prefix | Check the framework prefix table above |
| Pebble exit loop with CLI usage | Wrong service command | Fix ``rockcraft.yaml`` ``services.*.command``, repack, repush |
| ``permission denied`` on ``/app`` | Non-root runtime user, unwritable path | Fix ownership in the rock, repack |
| Spring Boot rock build refused | Both Maven and Gradle present | Pick one in the trial copy; ``check_rock_contract`` reports this |
