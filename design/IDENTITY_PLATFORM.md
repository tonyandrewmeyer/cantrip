# Canonical Identity Platform — Research Findings

> Output of Phase 88.1.  This is a research document, not a design.
> It records the Canonical Identity Platform's surface, the relation
> interfaces a charm relies on for OIDC / OAuth integration, the
> standard deployment topologies, and Cantrip's default-topology
> decision when a user says "add login" without further qualification.

## TL;DR

- **Three charms make up the core of the Canonical Identity
  Platform**: Hydra (OAuth 2.0 / OIDC issuer), Kratos (identity /
  session / login-flow engine), and identity-platform-login-ui (the
  reference web UI Kratos drives for login / registration /
  password recovery).  They ship together as the
  ``canonical-identity-platform`` bundle.
- **Five relation interfaces matter** for charm authors.  ``oauth``
  is the headline — a relying party (RP) charm relates over
  ``oauth`` and Hydra returns the issuer URL, client ID, and
  client secret as relation data.  ``oauth-cli`` covers CLI-style
  device-code flows.  ``oidc-info`` exposes Hydra's discovery
  endpoint to charms that introspect tokens themselves.
  ``hydra-token-introspect`` is the resource-server introspection
  endpoint.  ``kratos-external-idp`` federates external IdPs
  (Google, GitHub) into Kratos.
- **Three topologies are common** (§3): SaaS-style public Hydra
  behind Traefik, internal-only with mTLS, and the bundle-based
  hybrid where login-ui is the user-facing door and Hydra /
  Kratos sit behind it.  The bundle topology is what ``juju
  deploy canonical-identity-platform`` brings up.
- **Default for Cantrip: bundle-based hybrid.**  When a user says
  "add login" without qualification, Cantrip generates a charm
  with an ``oauth`` relation, suggests
  ``juju deploy canonical-identity-platform``, and integrates the
  charm against the bundle's Hydra app.  Rationale: it's the
  Canonical-blessed default, fastest to bring up in dev, and
  mirrors the existing observability story (deploy COS bundle,
  integrate).
- The skill expansion that lands this knowledge is sub-phase
  88.2 — pre-existing in the roadmap; this research note unblocks
  it by deciding the topology and the relation-interface
  shortlist.

## 1. The components

### 1.1 Hydra

[Ory Hydra](https://www.ory.sh/hydra/) is a stateless OAuth 2.0 /
OpenID Connect provider.  Charmed at
[`charmhub.io/hydra`](https://charmhub.io/hydra) (k8s).  Hydra
issues access / refresh / ID tokens; it does not handle login UI
(that's Kratos's job).  A relying party charm wires up via the
``oauth`` relation and receives client credentials Hydra
generates per-relation.

### 1.2 Kratos

[Ory Kratos](https://www.ory.sh/kratos/) is an identity-management
engine: user database, login flows, registration, password
recovery, MFA.  Charmed at
[`charmhub.io/kratos`](https://charmhub.io/kratos) (k8s).  Kratos
plus Hydra is the standard pair — Hydra issues the OIDC tokens,
Kratos owns the user accounts and login flows.

### 1.3 identity-platform-login-ui

The reference web UI Kratos drives.  Charmed at
[`charmhub.io/identity-platform-login-ui-operator`](https://charmhub.io/identity-platform-login-ui-operator)
(k8s).  Renders the login / registration / consent / recovery
pages a user actually sees during the OIDC dance.  Customisable
via Kratos config; in most deployments the default is fine.

### 1.4 The bundle

[`canonical-identity-platform`](https://charmhub.io/canonical-identity-platform)
deploys Hydra + Kratos + login-ui + the supporting integrations
(Traefik for ingress, a database backend, etc.) as a unit.
Mirrors the COS bundle pattern.

## 2. Relation interfaces

The interfaces the agent needs to know about, ranked by how
often a charm author will reach for each.

| Interface | Direction | Purpose | Charm-lib (PyPI candidate) |
|---|---|---|---|
| ``oauth`` | RP requires, Hydra provides | OAuth 2.0 / OIDC client registration; Hydra returns issuer URL + client ID + client secret per relation | ``charms.hydra.v0.oauth`` (still ``charmcraft fetch-libs``; not yet on PyPI per ``design/UPSTREAM_AUDIT.md``) |
| ``oauth-cli`` | CLI client requires, Hydra provides | Device-code flow for CLI tools | ``charms.hydra.v0.oauth_cli`` |
| ``oidc-info`` | Charm requires, Hydra provides | Hydra's OIDC discovery URL (``/.well-known/openid-configuration``) and JWKs | ``charms.hydra.v0.oidc_info`` |
| ``hydra-token-introspect`` | Resource server requires, Hydra provides | Token-introspection endpoint for opaque-token validation | ``charms.hydra.v0.token_introspect`` |
| ``kratos-external-idp`` | External-IdP charm provides, Kratos requires | Federate Google / GitHub / generic OIDC into Kratos | ``charms.kratos.v0.kratos_external_idp`` (referenced in ``charmcraft/SKILL.md``) |

The ``oauth`` interface is the one Cantrip's twelve-factor skill
already mentions in passing; the rest are absent.  All five live
in the per-charm libs ecosystem (``charmcraft fetch-libs`` route)
rather than on PyPI today.

For 12-factor charms, the relation data lands on the workload as
environment variables thanks to the ``paas-charm`` base — the
same pattern as the existing OIDC section in
``twelve-factor/SKILL.md``.  For custom and infrastructure
charms, the charm author wires the relation handler manually.

## 3. Deployment topologies

Three shapes that come up in real deployments.

### 3.1 SaaS-style public Hydra

```
[Internet user] ─► Traefik ─► Hydra (public OIDC issuer)
                              ▲
                              │ oauth relation
                              │
                          [my-app charm]
```

- Hydra exposed on a public TLS endpoint via Traefik.
- RP charms relate to Hydra over ``oauth`` and use the issuer URL
  Hydra returns.
- Suitable for production deployments where the OIDC provider is
  shared across many apps.
- Requires TLS (cert-manager + Traefik) which Cantrip already
  understands.

### 3.2 Internal-only with mTLS

```
[Workload pod] ─mTLS─► Hydra (internal-only OIDC issuer)
       ▲
       │ oauth relation (over mTLS)
       │
   [my-app charm]
```

- All identity components on a private network.
- mTLS for charm-to-Hydra traffic.
- Higher security but more setup (cert distribution, mTLS profile
  on Traefik, charm-side mTLS handler).
- Appropriate for regulated environments; rare for standard charm
  development.

### 3.3 Bundle-based hybrid

```
[Internet user] ─► Traefik ─► identity-platform-login-ui
                                    │
                                    │ (drives)
                                    ▼
                              Kratos ◄── kratos-external-idp ── [Google/GitHub IdP charm]
                                    │
                                    │ (uses)
                                    ▼
                                  Hydra ──oauth──► [my-app charm]
```

- ``juju deploy canonical-identity-platform`` brings this up as
  one unit.
- login-ui is the user-facing door; Kratos owns user accounts and
  login flows; Hydra is the OIDC issuer the RP charms talk to.
- Most ergonomic for development and most charms in production.
- Matches the COS-bundle pattern: deploy the bundle, integrate
  against the apps inside.

## 4. Default topology — Cantrip's pick

**Bundle-based hybrid.**

When the user says "add login" without further qualification,
Cantrip:

1. Generates the charm with an ``oauth`` relation in
   ``charmcraft.yaml`` (interface ``oauth``, requires Hydra).
2. Adds the appropriate charm-lib import in ``src/charm.py``
   (``charms.hydra.v0.oauth``) and a relation-handler stub.
3. Suggests the bundle deploy:
   ```bash
   juju deploy canonical-identity-platform
   juju integrate my-app:oauth canonical-identity-platform.hydra:oauth
   ```
4. For 12-factor charms, the relation data flows through to the
   workload via the ``paas-charm`` base's env-var injection —
   no extra wiring needed on the workload side.

Reasons the bundle wins as the default:

- **Canonical-blessed.**  ``canonical-identity-platform`` is the
  topic page on Charmhub and the Canonical Identity team's
  recommended starting point.  Picking any other default
  contradicts that.
- **Single-command bring-up.**  ``juju deploy canonical-identity-
  platform`` is one command; the alternatives need three or four
  charms deployed in the right order with the right relations.
- **Mirrors the COS bundle pattern.**  Cantrip already prescribes
  ``juju deploy cos-lite`` for observability; the identity story
  parallels that.
- **Customisation path is open.**  A user who needs SaaS-style
  public Hydra (3.1) or internal-only mTLS (3.2) can replace the
  bundle's Hydra with their own and the ``oauth`` relation works
  unchanged.  The default is a starting point, not a constraint.

The two alternatives are documented as escape hatches:

- ``--topology saas`` (or equivalent prompt phrasing): generate
  for the SaaS shape — same charm code, Cantrip skips the bundle
  suggestion and points at the user's existing Hydra deployment.
- ``--topology internal-mtls``: same charm code, Cantrip adds an
  mTLS profile to the relation handler and prompts the user to
  wire cert-manager.

In practice users won't reach for these flags — they'll say
"deploy the canonical-identity-platform bundle" or "use my
existing Hydra at https://...".  The flags exist so the agent
can disambiguate when needed.

## 5. What Phase 88.2 needs from this note

Phase 88.2 (the skill ``identity-platform`` expansion that's
already scoped in the roadmap) lands the operational knowledge.
This note unblocks 88.2 by deciding:

- The default topology (3.3, bundle-based hybrid).
- The five interfaces worth covering in the skill (``oauth`` is
  primary, ``oauth-cli`` / ``oidc-info`` /
  ``hydra-token-introspect`` are situational, ``kratos-external-idp``
  is for IdP-charm authors).
- The charm-lib route — ``charmcraft fetch-libs`` for now (none
  on PyPI per ``UPSTREAM_AUDIT.md``); add to the LIB001
  fetch-libs allowlist in the charm prompts.
- The 12-factor vs custom vs infrastructure split:
  - 12-factor: ``oauth`` relation + paas-charm env-var injection.
    Skill body is short.
  - Custom: ``oauth`` relation handler + token-validation library
    pulled in.  Skill body covers the manual wiring.
  - Infrastructure: ``oauth-cli`` for service-to-service (or
    ``hydra-token-introspect`` for resource-server validation).

## 6. Phase 88.3 — agent-side affordances

Phase 88.3 decided whether typed ``identity_platform_*`` tools are
worth building.  Verdict: **no new tool.**

- The existing ``juju_read_relation_data`` covers the common debug
  case (inspect what Hydra wrote into the relation);
  ``juju_status`` covers deployment health.  The skill prose
  shipped in 88.2 is enough for charm generation.
- A typed tool would only be justified if a concrete debug case
  surfaces where the agent wants to inspect Hydra's registered
  clients programmatically (``hydra clients list``) and the
  pattern repeats often enough to amortise the tool work.

This is the same posture Phase 86 took for kubectl: ship the
skill knowledge today, defer the typed tool against a concrete
trigger.

What 88.3 *did* land:

- **Acceptance harness wiring.**  The ``oauth``, ``oauth-cli``,
  ``oidc-info``, ``hydra-token-introspect``, and
  ``kratos-external-idp`` interfaces are now in
  ``_INTERFACE_PARTNERS`` (``src/cantrip/agent/tools/acceptance.py``)
  with ``hydra`` / ``kratos`` as smoke partners.  ``RelationSmokeTool``
  (Phase 17.2) automatically deploys the appropriate partner and
  exercises the relation when it sees an identity-platform
  endpoint on a generated charm — no per-charm wiring needed.
- **Acceptance runbook.**  §9 below records the manual end-to-end
  verification for a charm asked for "OIDC login backed by
  Canonical Identity Platform".  Full bundle deploy isn't a
  unit-test surface, so the procedure is a documented runbook the
  user (or an integration harness) can follow on real K8s.

## 7. Revisit triggers

The verdicts in §4 / §5 / §6 stand until evidence appears that
the world changed.  Specific things that would re-open this
note:

1. **A canonical interface change.**  The ``oauth`` relation
   schema gains fields (e.g. PKCE state, audiences) that the
   default skill body doesn't cover.  Re-read §2 and update.
2. **Charm-lib PyPI publication.**  The ``charms.hydra.v0.*``
   libs land on PyPI under the ``charmlibs-*`` namespace.  When
   that happens, the LIB001 mapping (``UPSTREAM_AUDIT.md``)
   gets updated and the skill drops the ``charmcraft fetch-
   libs`` instruction in favour of the PyPI install.
3. **Bundle topology shift.**  The
   ``canonical-identity-platform`` bundle's default deployment
   shape changes (e.g. login-ui becomes optional, Kratos
   replaces Hydra as the OIDC issuer, etc.).  Re-read §3 and
   §4.
4. **A real charm-author pain point.**  A user reports the
   default doesn't fit their case (most likely: production
   deployment with an existing public Hydra).  Either tighten
   the prompt-phrasing detection or document the
   ``--topology saas`` escape hatch more prominently.
5. **Repeated programmatic-introspection ask.**  The agent (or
   the user, via the agent) ends up shelling out to
   ``hydra clients list`` / ``hydra clients get`` more than a
   handful of times in real sessions, or the relation databag
   isn't enough to debug a misconfigured client.  Either of
   those means the §6 "no new tool" verdict needs revisiting —
   build a typed ``identity_platform_*`` tool family at that
   point.

## 8. What this phase is *not*

- **Not the implementation of the identity-platform skill.**
  That's Phase 88.2; this note unblocks it but does not pre-empt
  it.
- **Not a custom IAM story.**  LDAP, SAML, ad-hoc OAuth — out of
  scope.  Canonical Identity Platform charms only.
- **Not a security audit.**  Token storage, session-fixation
  resistance, CSRF on the login flow — those are Phase 16 /
  OWASP territory and are charm-author concerns, not Cantrip's.
- **Not a bundle authoring story.**  Cantrip generates *charms*
  that integrate against the identity platform; it doesn't
  generate identity-platform bundles.
- **Not Vault integration.**  Hydra + Kratos can use Vault for
  secret storage; charm-side Vault integration is its own surface
  (``charms.vault_kv.*``) covered separately.

## 9. Acceptance runbook

Phase 88.3's exit criterion is "a charm asked for 'OIDC login
backed by Canonical Identity Platform' deploys with Hydra
correctly related and the demo app's login flow works
end-to-end on the Phase 17 harness."  Two layers verify this:

**Layer 1 — automated (every CI run).**

The Phase 17 ``RelationSmokeTool`` (``relation_smoke_test``)
reads the generated charm's ``charmcraft.yaml``, sees the
``oauth`` requires endpoint, looks it up in
``_INTERFACE_PARTNERS``, deploys ``hydra`` as the smoke
partner, and integrates.  ``_verify_relation_data`` then
asserts the relation databag carries non-trivial keys (issuer
URL, client ID, client-secret URI).  This is a relation-level
smoke; it doesn't drive a browser.

**Layer 2 — manual end-to-end on real K8s** (run when changing
the skill body, the partner map, or the bundle topology):

```bash
# 0.  Substrate.
sudo snap install k8s --classic
sudo k8s bootstrap
juju add-k8s --client k8s
juju bootstrap k8s identity-acceptance

# 1.  Identity platform.
juju add-model identity
juju deploy canonical-identity-platform

# 2.  Demo charm (use the twelve-factor or custom-charm worked
#     example from src/cantrip/skills/identity-platform/SKILL.md).
juju add-model demo
juju deploy ./demo-app_amd64.charm \
  --resource oci-image=localhost:32000/demo-app:latest

# 3.  Cross-model integration.
juju offer identity.hydra:oauth
juju consume admin/identity.hydra demo.hydra
juju integrate demo:oauth demo.hydra

# 4.  Wait for steady state.
juju status -m demo --watch 5s
juju status -m identity --watch 5s

# 5.  Drive the login flow.
#     - Browse to the demo app's external hostname.
#     - Click "Sign in".
#     - Confirm the redirect lands on identity-platform-login-ui.
#     - Register a test user, complete the flow, confirm the
#       redirect back to the demo app, and confirm the session
#       cookie / JWT is set.
#
# The browser-driven step is what Layer 1 cannot automate;
# Layer 1 only proves the relation wiring is correct.
```

PASS criteria:

- ``juju status`` shows ``demo`` and the bundle's apps in
  ``active/idle``.
- ``juju show-unit demo/0`` exposes a populated
  ``oauth`` relation databag with ``issuer-url``,
  ``client-id``, and a Juju secret URI for the client secret.
- The browser flow reaches the demo app post-login with a
  valid session.

FAIL recovery: on a relation-data shape mismatch, re-check the
``charms.hydra.v0.oauth`` library version against
``charm-libs:`` in ``charmcraft.yaml`` — the bundle and the
fetched lib must agree on the ``v0`` schema.  A schema bump in
the upstream lib is **trigger §7.1** ("a canonical interface
change") on this note; update §2 and the skill before
re-running the runbook.
