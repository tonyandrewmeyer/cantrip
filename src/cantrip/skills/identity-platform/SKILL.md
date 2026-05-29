---
name: identity-platform
description: Wire charms to the Canonical Identity Platform (Hydra / Kratos / login-ui) for OIDC, OAuth, and federated login.
---

# Canonical Identity Platform Integration

Use this skill when a charm needs login, OIDC tokens, OAuth clients, or service-to-service authentication backed by the Canonical Identity Platform — Hydra (OAuth 2.0 / OIDC issuer), Kratos (identity / sessions), and identity-platform-login-ui (the reference login UI).  The bundle and the underlying charms live on Charmhub; the per-charm libraries that wire the relations live on Charmhub too (``charmcraft fetch-libs`` route — none on PyPI yet).

The defaults here mirror the COS pattern Cantrip already prescribes for observability: tell the user to ``juju deploy canonical-identity-platform`` and integrate against the apps inside.  The skill body covers when to deviate.

## When to Use This Skill

Reach for this skill when the request involves any of:

- "Add login" / "add SSO" / "add OIDC" to a generated charm.
- A web app that needs to register users, manage sessions, or accept third-party identity (Google, GitHub).
- A CLI or daemon that needs OAuth 2.0 device-code or service-to-service credentials.
- A resource server that needs to validate opaque access tokens via Hydra introspection.
- An identity provider charm that wants to federate into Kratos.

Do **not** use this skill for:

- Custom IAM (LDAP, SAML, ad-hoc OAuth flows) — out of scope.
- Generic auth library wiring inside the workload (PKCE handling, JWT verification) — that's application code, not charm wiring.
- Vault-backed secrets storage — that's the ``charms.vault_kv.*`` surface, separate from the identity platform.

## Default Topology — Bundle-Based Hybrid

When the user says "add login" without further qualification, generate against the bundle:

```bash
juju deploy canonical-identity-platform
juju integrate my-app:oauth canonical-identity-platform.hydra:oauth
```

`juju deploy canonical-identity-platform` brings up Hydra + Kratos + identity-platform-login-ui + Traefik + a database backend as a single unit.  login-ui is the user-facing door, Kratos owns user accounts and login flows, and Hydra is the OIDC issuer the relying-party (RP) charm talks to over the ``oauth`` relation.

This mirrors the COS-bundle pattern (``juju deploy cos-lite`` → integrate).  Pick another topology only when the user is explicit:

| Topology | Trigger | What changes |
|----------|---------|--------------|
| **Bundle-based hybrid** *(default)* | "add login", "OIDC", "SSO" | Suggest `juju deploy canonical-identity-platform`; relate `oauth`. |
| **SaaS-style public Hydra** | "use my existing Hydra at `<URL>`", production deployment | Same charm code; skip the bundle suggestion; point at the user's Hydra app. |
| **Internal-only with mTLS** | regulated / classified environments | Same charm code; add an mTLS profile to the relation handler; wire cert-manager. |

The customisation path is open in all three: the ``oauth`` relation works the same regardless of where Hydra lives.

## Relation Interfaces — Pick the One That Fits

Five interfaces matter for charm authors.  Pick the *single* interface that matches the charm's role; do not declare more than one unless the charm genuinely plays multiple roles.

| Interface | Direction | When to use it | Charm library |
|-----------|-----------|----------------|---------------|
| `oauth` | RP requires, Hydra provides | Web app registers as an OAuth/OIDC client; receives issuer URL + client ID + client secret per relation. **The headline interface.** | `charms.hydra.v0.oauth` |
| `oauth-cli` | CLI requires, Hydra provides | CLI tool or daemon needs the OAuth 2.0 device-code flow. | `charms.hydra.v0.oauth_cli` |
| `oidc-info` | Charm requires, Hydra provides | Charm wants Hydra's discovery URL (`/.well-known/openid-configuration`) and JWKs to validate ID tokens itself. | `charms.hydra.v0.oidc_info` |
| `hydra-token-introspect` | Resource server requires, Hydra provides | Resource-server validates opaque access tokens via Hydra's introspection endpoint. | `charms.hydra.v0.token_introspect` |
| `kratos-external-idp` | External-IdP charm provides, Kratos requires | Charm federates Google / GitHub / generic OIDC into Kratos. | `charms.kratos.v0.kratos_external_idp` |

Decision shortcut:

- *"My web app needs login."* → `oauth`, no questions asked.
- *"My CLI needs to talk to a service that wants a token."* → `oauth-cli`.
- *"My charm validates JWTs itself."* → `oidc-info`.
- *"My charm validates opaque tokens by asking Hydra."* → `hydra-token-introspect`.
- *"I'm building a Google / GitHub / corporate-IdP charm."* → `kratos-external-idp`.

## Charm Libraries — Fetch-Libs Route

The five libraries above are **not on PyPI** today (per `design/research/UPSTREAM_AUDIT.md`, audit cutoff 2026-04-22).  Fetch them via charmcraft.  In `charmcraft.yaml`:

```yaml
charm-libs:
  - lib: hydra.oauth
    version: "0"
  # add only the ones the charm actually imports
```

Then run `charmcraft fetch-libs` once.  The libraries land under `lib/charms/hydra/v0/oauth.py` (etc.) and import as `from charms.hydra.v0.oauth import OAuthRequirer`.

**Revisit:** When the libs land on PyPI under the `charmlibs-*` namespace, the LIB001 mapping (`design/research/UPSTREAM_AUDIT.md`) will be updated and this skill should switch to `uv add charmlibs-hydra-oauth` (or whatever the published name is).  Until then, the fetch-libs instruction is correct.

## Secret-Relation Wiring for Client Credentials

Hydra writes the OAuth client secret into the `oauth` relation **as a Juju secret**, not as a plain databag value.  The library handles the secret-fetch dance for you, but the charm needs to declare access:

- **No `provides`-side secret declaration is needed.**  Hydra owns the secret; the relation databag carries the secret URI; the requirer charm fetches the secret on demand.
- The charm process must run with permission to read secrets — the default `oci-image` runtime user has this on the Pebble side; on machine charms the Juju agent has it.
- For 12-factor charms, the `paas-charm` base injects the resolved client secret into the workload as `OAUTH_CLIENT_SECRET` (or the framework's prefixed equivalent).  No charm Python is needed; the secret is materialised in the env.
- For custom charms, call `OAuthRequirer.get_provider_info()` inside the relation-changed handler — the library transparently calls `Secret.get_content()` against the secret URI in the databag.

Do not log the client secret, do not echo it into status messages, and do not place it in a config option — that defeats the secret-relation contract.

## Worked Examples

### Example 1 — 12-factor App with Hydra Requirer (`oauth`)

A Flask app needs OIDC login.  The user accepts the bundle default.

**`charmcraft.yaml`** (in the `charm/` subdirectory; the framework profile is already in place):

```yaml
charm-libs:
  - lib: hydra.oauth
    version: "0"

requires:
  oidc:
    interface: oauth
    optional: true   # optionality must come from the fit handoff
    limit: 1
```

The `paas-charm` base auto-injects relation env into the workload — no `src/charm.py` changes needed.  On the workload side, the Flask app reads:

| Env var | Source | Purpose |
|---------|--------|---------|
| `FLASK_OIDC_ISSUER_URL` | `oauth` databag | Hydra's issuer URL |
| `FLASK_OIDC_CLIENT_ID` | `oauth` databag | Per-relation client ID |
| `FLASK_OIDC_CLIENT_SECRET` | resolved Juju secret | Per-relation client secret |

Framework prefix follows the `paas-charm` table in the `twelve-factor` skill (Flask: `FLASK_`, Django: `DJANGO_`, Express/FastAPI/Go/Spring Boot: `APP_`).

Deploy and integrate:

```bash
juju deploy canonical-identity-platform
juju deploy ./my-app_amd64.charm --resource oci-image=localhost:32000/my-app:latest
juju integrate my-app:oidc canonical-identity-platform.hydra:oauth
```

Verify with `juju_status` — once Hydra registers the client, the workload restarts with the new env and the login flow works end-to-end against the bundle's login-ui.

### Example 2 — Custom Charm with Kratos-Backed Sessions

A custom ops-framework K8s charm that runs a non-PaaS web service and needs Kratos to own user accounts + login flows, with Hydra issuing tokens to the workload.

**`charmcraft.yaml`**:

```yaml
charm-libs:
  - lib: hydra.oauth
    version: "0"

requires:
  oauth:
    interface: oauth
    optional: false
    limit: 1
```

**`src/charm.py`**:

```python
import ops
import ops_tracing
from charms.hydra.v0.oauth import OAuthRequirer, ClientConfig


class MyAppCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        self._tracing = ops_tracing.Tracing(self, "tracing")
        self._oauth = OAuthRequirer(
            self,
            client_config=ClientConfig(
                redirect_uri=f"https://{self.config['external-hostname']}/callback",
                scope="openid profile email",
                grant_types=["authorization_code", "refresh_token"],
            ),
            relation_name="oauth",
        )
        framework.observe(self._oauth.on.oauth_info_changed, self._on_oauth_info_changed)
        framework.observe(framework.on.config_changed, self._reconcile)

    def _on_oauth_info_changed(self, event: ops.EventBase) -> None:
        self._reconcile(event)

    def _reconcile(self, _event: ops.EventBase) -> None:
        info = self._oauth.get_provider_info()
        if info is None:
            self.unit.status = ops.WaitingStatus("waiting for hydra")
            return
        # ``info.client_secret`` is already resolved from the Juju secret.
        self._push_pebble_layer(info)
        self.unit.status = ops.ActiveStatus()
```

The login *UI* is owned by the bundle's identity-platform-login-ui — the workload does not render its own login page in this topology.  After authentication, login-ui hands the user back to the workload with an authorisation code; the workload exchanges it for tokens via Hydra.

If the workload also needs to verify ID tokens locally (rather than calling introspection on every request), add the `oidc-info` relation alongside `oauth` and use `OIDCInfoRequirer` to fetch JWKs.

### Example 3 — Infrastructure Charm with Service-to-Service `oauth-cli`

An infrastructure charm (a backup daemon, a CLI-driven controller, a scheduled job runner) needs to authenticate to a downstream service that requires an OAuth 2.0 access token.  No human is in the loop, so the device-code flow is wrong; what fits is `oauth-cli` issuing client-credentials tokens to the service.

**`charmcraft.yaml`**:

```yaml
charm-libs:
  - lib: hydra.oauth_cli
    version: "0"

requires:
  oauth-cli:
    interface: oauth-cli
    optional: false
    limit: 1
```

**`src/charm.py`** (sketch):

```python
from charms.hydra.v0.oauth_cli import OAuthCliRequirer


class BackupDaemonCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        self._oauth_cli = OAuthCliRequirer(self, relation_name="oauth-cli")
        framework.observe(self._oauth_cli.on.token_available, self._on_token_available)

    def _on_token_available(self, event: ops.EventBase) -> None:
        # Library has resolved the access token from the Juju secret on the
        # databag.  Pass it to the workload via Pebble env or a mounted file.
        token = self._oauth_cli.get_access_token()
        self._push_pebble_env({"DOWNSTREAM_API_TOKEN": token})
```

The downstream service it calls must, in turn, validate the token — typically by relating to the same Hydra over `hydra-token-introspect` (a resource-server pattern), or by trusting Hydra's JWKs over `oidc-info`.

## Topology Escape Hatches

The bundle is the default; the two alternatives are reachable via the prompt-driven escape hatches called out in `design/IDENTITY_PLATFORM.md` §4:

- **SaaS-style public Hydra** — the user already runs Hydra (in another model, in a separate Juju cloud, or as a hosted service).  Skip `juju deploy canonical-identity-platform`; relate against the user's Hydra app or its offer:
  ```bash
  juju integrate my-app:oauth their-hydra-offer
  ```
  The charm code is unchanged.
- **Internal-only with mTLS** — regulated environments where Hydra must not be reachable from outside the cluster.  Add an mTLS profile to the relation handler (cert-manager + Traefik mTLS), and document the cert-distribution flow.  This path involves more wiring than the bundle but no library API change.

In practice users will ask in prose — "use my existing Hydra at auth.example.com" — rather than reaching for a flag.  Detect the prompt and skip the bundle suggestion accordingly.

## Common Pitfalls

1. **Re-declaring `oauth` when the framework profile already provides it.**  The `twelve-factor` skill's OIDC section already documents adding an `oidc` relation against `interface: oauth`; do not also declare a separate `oauth` relation in the same charm.  Pick one name; both work.
2. **Treating the client secret as a plain string.**  It arrives as a Juju secret URI on the relation databag; only the resolved value is the actual secret.  Always go through the library API or the `paas-charm` env injection — never read the databag directly.
3. **Logging client credentials.**  Charm logs are accessible to anyone with `juju debug-log`; secrets in logs are leaked secrets.  Status messages are the same.
4. **Choosing `oauth-cli` for a human-driven web app.**  `oauth-cli` is the device-code / client-credentials path; for browser-based login flows the right interface is `oauth`.
5. **Mixing topology layers.**  Do not deploy `hydra` directly *and* `canonical-identity-platform` in the same model — pick one.  The bundle owns its own Hydra; a second copy will fight for the same relations.
6. **Assuming PyPI availability.**  `charms.hydra.v0.*` and `charms.kratos.v0.*` are not on PyPI as of April 2026 — use `charmcraft fetch-libs`.  Re-check `design/research/UPSTREAM_AUDIT.md` if a future change is suspected.
7. **Forgetting the bundle's database.**  `canonical-identity-platform` deploys its own backing database for Kratos; do not relate Kratos to the user's PostgreSQL unless explicitly asked.

## Cross-References

- `twelve-factor` skill — the OIDC section there covers the simplest case (Flask/Django/FastAPI app + `oauth` relation + paas-charm env injection); load both skills together when working on a 12-factor charm with login.
- `custom-charm` skill — for non-PaaS apps, pair this skill with `custom-charm` for the broader workflow; the OAuth wiring in Example 2 above is the identity-specific delta.
- `infrastructure-charm` skill — for service-to-service auth in a Path C charm, pair with this skill's Example 3.
- `observability` skill — auth flows produce useful spans and metrics; instrument them with ops-tracing once the relation is wired.
- `design/IDENTITY_PLATFORM.md` — the research note that grounds the choices here, including the trade-off table for the three topologies and the revisit triggers.

## When *Not* To Use This Skill

- Custom IAM (LDAP, SAML, ad-hoc OAuth) — out of scope; the Canonical-stack scope only.
- Bundle authoring — Cantrip generates *charms* that integrate against the identity platform; bundle authoring is a separate concern.
- Token verification *inside the workload* (JWT signature check, audience validation) — that's application code, not charm wiring.  This skill stops at "charm has the credentials"; what the workload does with them is a workload concern.
- Generic security review — load `security-review` for that.
