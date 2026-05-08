---
title: "How to add Canonical Identity Platform login to a charm — Cantrip"
description: "Wire OIDC, OAuth, or federated login into a generated charm via Hydra, Kratos, and identity-platform-login-ui — using the bundled identity-platform skill."
h1: "Add Canonical Identity Platform login"
subtitle: "Reach for the bundled identity-platform skill when a charm needs OIDC tokens, OAuth clients, or federated login backed by Hydra, Kratos, and login-ui."
section: howto
breadcrumb_label: "Add identity-platform login"
on_this_page:
  - { anchor: "when", label: "When to use this skill" }
  - { anchor: "trigger", label: "Trigger it from a prompt" }
  - { anchor: "topology", label: "Default topology" }
  - { anchor: "interface", label: "Pick the right relation" }
  - { anchor: "libraries", label: "Charm libraries" }
  - { anchor: "verify", label: "Verify the wiring" }
see_also:
  - label: "Add a custom skill"
    href: "howto-skills.html"
  - label: "Search the charm library"
    href: "howto-charm-library.html"
  - label: "The three charm paths"
    href: "explanation-charm-paths.html"
---

{#when}
## When to use this skill

Cantrip ships a bundled `identity-platform` skill that teaches the
agent how to wire charms to the **Canonical Identity Platform** —
Hydra (the OAuth 2.0 / OIDC issuer), Kratos (identity and sessions),
and identity-platform-login-ui (the reference login UI). The skill
loads automatically when the agent recognises an identity request;
you do not need to install or configure anything.

Reach for it when the charm needs any of:

- "Add login" / "add SSO" / "add OIDC" to a generated charm.
- A web app that registers users, manages sessions, or accepts
  third-party identity (Google, GitHub, corporate IdP).
- A CLI or daemon that needs the OAuth 2.0 device-code flow or
  service-to-service credentials.
- A resource server that validates opaque access tokens via
  Hydra's introspection endpoint.
- An external-IdP charm that federates Google / GitHub / a generic
  OIDC issuer into Kratos.

Do **not** reach for it for custom IAM (LDAP, SAML, ad-hoc OAuth),
in-workload auth library wiring (PKCE, JWT verification — that is
application code), or Vault-backed secrets (use the
`charms.vault_kv.*` interface instead).

{#trigger}
## Trigger it from a prompt

The skill activates on prose, not a slash command. Describe what the
charm needs in natural language and the agent will pick the skill up
on its next planning step:

<pre><code><span class="prompt">cantrip&gt;</span> add OIDC login to this Flask charm against the
Canonical Identity Platform bundle</code></pre>

You can also load it explicitly when steering a stuck plan:

<pre><code><span class="prompt">cantrip&gt;</span> /skill identity-platform</code></pre>

`/skill` lists the bundled skills if you want to confirm the name.
See [Add a custom skill](howto-skills.html) for the discovery order
and how to override a bundled skill from your own directory.

{#topology}
## Default topology — bundle-based hybrid

When the request is "add login" without further qualification, the
skill generates against the published bundle:

<pre><code><span class="prompt">$</span> juju deploy canonical-identity-platform
<span class="prompt">$</span> juju integrate my-app:oauth canonical-identity-platform.hydra:oauth</code></pre>

`canonical-identity-platform` brings up Hydra + Kratos +
identity-platform-login-ui + Traefik + a database backend as a
single unit. The relying-party charm only talks to Hydra over the
`oauth` relation; login-ui is the user-facing door; Kratos owns user
accounts and login flows. This mirrors the COS-bundle pattern
(`juju deploy cos-lite` → integrate).

The skill keeps two other topologies in reserve when the user is
explicit:

| Topology | Trigger phrase | What changes |
| --- | --- | --- |
| **Bundle-based hybrid** *(default)* | "add login", "OIDC", "SSO" | Suggests `juju deploy canonical-identity-platform` and integrates `oauth`. |
| **SaaS-style public Hydra** | "use my existing Hydra at &lt;URL&gt;", production reuse | Same charm code; skips the bundle suggestion; points at the user's Hydra app. |
| **Internal-only with mTLS** | regulated or classified environments | Same charm code; adds an mTLS profile to the relation handler; wires cert-manager. |

The charm code is portable across all three — only the deployment
shape changes.

{#interface}
## Pick the right relation

The skill chooses one of five interfaces based on the charm's role.
Charms generally play exactly one role; declare a second only when
the charm genuinely needs both.

| Interface | Direction | When | Library |
| --- | --- | --- | --- |
| `oauth` | RP requires, Hydra provides | Web app registers as an OAuth/OIDC client; receives issuer URL + client ID + client secret per relation. **The headline interface.** | `charms.hydra.v0.oauth` |
| `oauth-cli` | CLI requires, Hydra provides | CLI tool or daemon needs the OAuth 2.0 device-code flow. | `charms.hydra.v0.oauth_cli` |
| `oidc-info` | Charm requires, Hydra provides | Charm wants Hydra's discovery URL and JWKs to validate ID tokens itself. | `charms.hydra.v0.oidc_info` |
| `hydra-token-introspect` | Resource server requires, Hydra provides | Resource server validates opaque access tokens via Hydra's introspection endpoint. | `charms.hydra.v0.token_introspect` |
| `kratos-external-idp` | Provider, Kratos requires | Charm federates Google / GitHub / generic OIDC into Kratos. | `charms.kratos.v0.kratos_external_idp` |

A quick decision shortcut:

- *"My web app needs login."* → `oauth`.
- *"My CLI needs to talk to a service that wants a token."* → `oauth-cli`.
- *"My charm validates JWTs itself."* → `oidc-info`.
- *"My charm validates opaque tokens by asking Hydra."* → `hydra-token-introspect`.
- *"I'm building a Google / GitHub / corporate-IdP charm."* → `kratos-external-idp`.

{#libraries}
## Charm libraries — fetch-libs route

These five libraries are not yet on PyPI. Cantrip declares them in
`charmcraft.yaml` and runs `charmcraft fetch-libs` at scaffold time:

```yaml
charm-libs:
  - lib: hydra.oauth
    version: "0"
  # add only the interfaces the charm actually imports
```

Once fetched, the libraries land under
`lib/charms/hydra/v0/oauth.py` (etc.) and import as
`from charms.hydra.v0.oauth import OAuthRequirer`. When the libs
land on PyPI under the `charmlibs-*` namespace the skill will switch
to `uv add charmlibs-hydra-oauth`; the agent tracks the upstream
audit so this is a one-line change when the time comes.

For 12-factor charms (Path A — Flask, Django, FastAPI, Express,
Spring Boot, Go), the `paas-charm` base injects the resolved
relation values into the workload as environment variables — no
charm Python is needed:

| Env var | Source | Purpose |
| --- | --- | --- |
| `FLASK_OIDC_ISSUER_URL` | `oauth` databag | Hydra's issuer URL |
| `FLASK_OIDC_CLIENT_ID` | `oauth` databag | Per-relation client ID |
| `FLASK_OIDC_CLIENT_SECRET` | resolved Juju secret | Per-relation client secret |

The framework prefix follows the `paas-charm` table — `FLASK_`,
`DJANGO_`, or `APP_` for the rest. Hydra writes the client secret
as a Juju secret (not a plain databag value); the library handles
the secret-fetch dance, so the charm only needs to declare the
relation.

For custom (Path B) charms, call `OAuthRequirer.get_provider_info()`
inside the relation-changed handler — the library transparently
resolves the secret URI in the databag.

{#verify}
## Verify the wiring

Once the agent finishes, drive the usual verification loop. The most
useful checks are:

<pre><code><span class="prompt">cantrip&gt;</span> @juju status
<span class="prompt">cantrip&gt;</span> @juju show-relation oauth</code></pre>

`@juju show-relation` is the fastest way to confirm Hydra has
written the issuer URL, client ID, and secret URI into the relation
databag — see [Use @-mention context](howto-mentions.html) for the
full provider catalogue. If the workload still cannot reach Hydra,
check `juju_debug_log` for relation-changed errors and confirm the
charm runs with permission to read Juju secrets.

<div class="callout">
  <p>
    Never log the client secret, never echo it into status messages,
    and never place it in a config option &mdash; that defeats the
    secret-relation contract. Cantrip's generator follows this rule;
    audit before merging if you hand-edit the relation handler.
  </p>
</div>
