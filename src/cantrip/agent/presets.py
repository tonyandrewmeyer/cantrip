"""Preset bundle catalogue — known-good Juju deployment shapes.

The Juju ecosystem already agrees on the shape of a handful of common
deployments: COS Lite is *always* Prometheus + Loki + Grafana +
Alertmanager + Traefik + Catalogue wired the same way; a 12-Factor app
in production is *always* the app charm plus a database plus an ingress
plus the observability endpoints; the Canonical Identity Platform is
*always* Hydra + Kratos + login-UI + PostgreSQL behind two Traefiks.
This module records those shapes once so two consumers don't each
re-derive them:

* **The agent**, via the ``@preset`` context provider and the
  ``preset-bundles`` skill.  When composing relations or diagnosing a
  deployment it fetches the canonical app list, the relation edges with
  their interface names, and a one-line description per edge — rather
  than rebuilding the shape from web docs every turn.
* **The F8 integration-graph screen**, via :func:`match_preset`.  When
  a live model matches a known preset the screen groups app panels by
  the preset's semantic layer and labels edges with the preset's prose
  instead of falling back to a flat alphabetical layout.

Scope discipline: this is a *lookup table of shapes*, not a deployment
recipe (it prescribes no steps) and not a bundle generator (it emits no
``bundle.yaml``).  The catalogue is deliberately small and curated;
expand it only when a shape is genuinely canonical, not merely common.
"""

from __future__ import annotations

import dataclasses
import typing

if typing.TYPE_CHECKING:
    from jubilant import statustypes


@dataclasses.dataclass(frozen=True, slots=True)
class PresetApp:
    """One application in a preset bundle."""

    name: str
    """Conventional deployed app name (what the bundle deploys it as)."""

    charm: str
    """Charmhub charm name."""

    layer: str
    """Semantic layer for graph grouping, e.g. ``"Data"``, ``"Routing"``."""

    summary: str
    """One-line description of the app's role in the bundle."""

    optional: bool = False
    """True for apps that are situational or live cross-model.

    A 12-Factor app's COS endpoints are usually in a *separate* model;
    Redis is only there when the framework needs a cache. Optional apps
    still get layer grouping in the graph when present, but they don't
    count toward the "is this model that preset?" fraction in
    :func:`match_preset` — otherwise a bare ``app + db + ingress`` model
    would never be recognised as the 12-Factor shape.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class PresetEdge:
    """One relation edge in a preset bundle.

    ``provider`` / ``requirer`` are the *app* names (matching
    :attr:`PresetApp.name`), oriented provides → requires.  The exact
    endpoint names are intentionally omitted — they drift between charm
    revisions, whereas the interface name and the prose are stable and
    are what the agent and the graph screen actually want.
    """

    provider: str
    requirer: str
    interface: str
    description: str
    """One line: what flows across the edge and why it is there."""


@dataclasses.dataclass(frozen=True, slots=True)
class PresetBundle:
    """A known-good deployment shape."""

    name: str
    """Catalogue slug, e.g. ``"cos-lite"``."""

    title: str
    """Human-readable name."""

    summary: str
    """One short paragraph: what the bundle is for."""

    apps: tuple[PresetApp, ...]
    layers: tuple[str, ...]
    """Layer names in display order (top of the topology to bottom)."""

    edges: tuple[PresetEdge, ...]

    def apps_by_layer(self) -> dict[str, list[PresetApp]]:
        """Group :attr:`apps` by layer, preserving :attr:`layers` order.

        Layers with no apps are dropped; any app whose layer is missing
        from :attr:`layers` is appended under its own bucket so the
        catalogue can't silently lose an app to a typo.
        """
        out: dict[str, list[PresetApp]] = {layer: [] for layer in self.layers}
        for app in self.apps:
            out.setdefault(app.layer, []).append(app)
        return {layer: apps for layer, apps in out.items() if apps}

    def app(self, name: str) -> PresetApp | None:
        """Return the :class:`PresetApp` named *name*, or ``None``."""
        for app in self.apps:
            if app.name == name:
                return app
        return None

    def edges_for(self, app_name: str) -> tuple[PresetEdge, ...]:
        """Edges touching *app_name* on either end."""
        return tuple(e for e in self.edges if app_name in (e.provider, e.requirer))


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

# Layer name conventions reused across presets so the graph screen can
# colour them consistently: "Routing" (ingress / mesh), "Telemetry"
# (scrape + log + trace stores), "Alerting", "Visualisation", "Auth",
# "Identity", "Application", "Data", "PKI".

_COS_LITE = PresetBundle(
    name="cos-lite",
    title="COS Lite",
    summary=(
        "Canonical's lightweight observability stack: Prometheus for metrics, "
        "Loki for logs, Alertmanager for routing alerts, Grafana for "
        "dashboards, Catalogue for the landing page, all exposed through a "
        "single Traefik. This is the bundle Cantrip-built charms relate to "
        "for observability — usually cross-model from the workload's model."
    ),
    layers=("Routing", "Telemetry", "Alerting", "Visualisation"),
    apps=(
        PresetApp("traefik", "traefik-k8s", "Routing", "Single ingress for every COS UI and API."),
        PresetApp(
            "prometheus",
            "prometheus-k8s",
            "Telemetry",
            "Scrapes and stores metrics; evaluates alert rules.",
        ),
        PresetApp(
            "loki",
            "loki-k8s",
            "Telemetry",
            "Stores logs pushed by workloads; evaluates log alert rules.",
        ),
        PresetApp(
            "alertmanager",
            "alertmanager-k8s",
            "Alerting",
            "Deduplicates, groups, and routes alerts to receivers.",
        ),
        PresetApp(
            "grafana",
            "grafana-k8s",
            "Visualisation",
            "Dashboards over Prometheus and Loki data sources.",
        ),
        PresetApp(
            "catalogue",
            "catalogue-k8s",
            "Visualisation",
            "Landing page linking to every registered COS UI.",
        ),
    ),
    edges=(
        PresetEdge(
            "traefik",
            "prometheus",
            "ingress",
            "Exposes the Prometheus API through the shared ingress.",
        ),
        PresetEdge(
            "traefik",
            "loki",
            "ingress",
            "Exposes the Loki push/query API through the shared ingress.",
        ),
        PresetEdge(
            "traefik",
            "alertmanager",
            "ingress",
            "Exposes the Alertmanager API and UI through the shared ingress.",
        ),
        PresetEdge(
            "traefik", "grafana", "ingress", "Exposes the Grafana UI through the shared ingress."
        ),
        PresetEdge(
            "traefik",
            "catalogue",
            "ingress",
            "Exposes the Catalogue landing page through the shared ingress.",
        ),
        PresetEdge(
            "alertmanager",
            "prometheus",
            "alertmanager_dispatch",
            "Prometheus forwards fired alerts to Alertmanager.",
        ),
        PresetEdge(
            "alertmanager",
            "loki",
            "alertmanager_dispatch",
            "Loki's ruler forwards fired log alerts to Alertmanager.",
        ),
        PresetEdge(
            "prometheus",
            "grafana",
            "grafana_datasource",
            "Registers Prometheus as a Grafana data source.",
        ),
        PresetEdge(
            "loki", "grafana", "grafana_datasource", "Registers Loki as a Grafana data source."
        ),
        PresetEdge(
            "prometheus",
            "grafana",
            "grafana_dashboard",
            "Ships Prometheus' bundled dashboards into Grafana.",
        ),
        PresetEdge(
            "loki", "grafana", "grafana_dashboard", "Ships Loki's bundled dashboards into Grafana."
        ),
        PresetEdge(
            "alertmanager",
            "grafana",
            "grafana_dashboard",
            "Ships Alertmanager's bundled dashboard into Grafana.",
        ),
        PresetEdge(
            "grafana",
            "catalogue",
            "catalogue",
            "Registers the Grafana UI on the Catalogue landing page.",
        ),
        PresetEdge(
            "prometheus",
            "catalogue",
            "catalogue",
            "Registers the Prometheus UI on the Catalogue landing page.",
        ),
        PresetEdge(
            "alertmanager",
            "catalogue",
            "catalogue",
            "Registers the Alertmanager UI on the Catalogue landing page.",
        ),
        PresetEdge(
            "prometheus",
            "grafana",
            "prometheus_scrape",
            "Self-monitoring: Prometheus scrapes Grafana's own metrics.",
        ),
    ),
)

_TWELVE_FACTOR_COS = PresetBundle(
    name="twelve-factor-cos",
    title="12-Factor app + COS",
    summary=(
        "The production shape of a paas-charm-generated 12-Factor application "
        "(Flask / Django / FastAPI / Go / Spring Boot): the app charm with a "
        "PostgreSQL backing store and a Traefik ingress in its own model, plus "
        "the observability endpoints the paas-charm framework exposes "
        "out of the box — metrics, logs, dashboards, and traces — typically "
        "consumed cross-model from a COS Lite deployment. Add Redis when the "
        "framework needs a cache or Celery broker."
    ),
    layers=("Routing", "Application", "Data", "Telemetry"),
    apps=(
        PresetApp("traefik", "traefik-k8s", "Routing", "Public ingress for the application."),
        PresetApp(
            "app",
            "<paas-charm>",
            "Application",
            "The 12-Factor workload charm built by paas-charm.",
        ),
        PresetApp(
            "postgresql", "postgresql-k8s", "Data", "Primary relational store for the application."
        ),
        PresetApp(
            "redis",
            "redis-k8s",
            "Data",
            "Cache / Celery broker when the framework needs one.",
            optional=True,
        ),
        PresetApp(
            "prometheus",
            "prometheus-k8s",
            "Telemetry",
            "Scrapes the app's /metrics endpoint (usually in the COS model).",
            optional=True,
        ),
        PresetApp(
            "loki",
            "loki-k8s",
            "Telemetry",
            "Receives the app's logs (usually in the COS model).",
            optional=True,
        ),
        PresetApp(
            "grafana",
            "grafana-k8s",
            "Telemetry",
            "Hosts the dashboards the app ships (usually in the COS model).",
            optional=True,
        ),
        PresetApp(
            "tempo",
            "tempo-coordinator-k8s",
            "Telemetry",
            "Receives the app's OpenTelemetry traces (usually in the COS model).",
            optional=True,
        ),
    ),
    edges=(
        PresetEdge(
            "traefik", "app", "ingress", "Routes external traffic to the application units."
        ),
        PresetEdge(
            "postgresql",
            "app",
            "postgresql_client",
            "Provisions a database and injects the connection string into the app.",
        ),
        PresetEdge(
            "redis", "app", "redis", "Provides cache / broker connection details to the app."
        ),
        PresetEdge(
            "app",
            "prometheus",
            "prometheus_scrape",
            "Exposes the app's Prometheus metrics endpoint for scraping.",
        ),
        PresetEdge(
            "app",
            "loki",
            "loki_push_api",
            "Ships the app's logs to Loki via the Pebble log forwarder.",
        ),
        PresetEdge(
            "app",
            "grafana",
            "grafana_dashboard",
            "Publishes the app's bundled dashboards into Grafana.",
        ),
        PresetEdge("app", "tempo", "tracing", "Sends the app's OpenTelemetry traces to Tempo."),
    ),
)

_IDENTITY_PLATFORM = PresetBundle(
    name="identity-platform",
    title="Canonical Identity Platform",
    summary=(
        "The bundle behind the bundle-based-hybrid login default (see the "
        "identity-platform skill and design/IDENTITY_PLATFORM.md): Ory Hydra "
        "as the OAuth2 / OIDC server, Ory Kratos for identity and sessions, "
        "the identity-platform-login-ui as the user-facing flow, a shared "
        "PostgreSQL, separate public and admin Traefik ingresses, and "
        "self-signed-certificates for TLS. A Cantrip-built charm relates to "
        "Hydra over the ``oauth`` interface to become a relying party."
    ),
    layers=("Routing", "Identity", "Data", "PKI"),
    apps=(
        PresetApp(
            "traefik-public",
            "traefik-k8s",
            "Routing",
            "Public ingress for the login UI and Hydra's public endpoint.",
        ),
        PresetApp(
            "traefik-admin",
            "traefik-k8s",
            "Routing",
            "Internal ingress for the Hydra / Kratos admin endpoints.",
        ),
        PresetApp(
            "hydra",
            "hydra",
            "Identity",
            "OAuth2 / OIDC authorization server; issues tokens to relying parties.",
        ),
        PresetApp(
            "kratos",
            "kratos",
            "Identity",
            "Identity store and session manager; backs the login flows.",
        ),
        PresetApp(
            "login-ui",
            "identity-platform-login-ui-operator",
            "Identity",
            "User-facing login / consent / settings UI for Hydra + Kratos.",
        ),
        PresetApp(
            "postgresql", "postgresql-k8s", "Data", "Shared relational store for Hydra and Kratos."
        ),
        PresetApp(
            "self-signed-certificates",
            "self-signed-certificates",
            "PKI",
            "Issues TLS certificates for the ingresses.",
        ),
    ),
    edges=(
        PresetEdge(
            "postgresql",
            "hydra",
            "postgresql_client",
            "Backing database for Hydra's client and token state.",
        ),
        PresetEdge(
            "postgresql",
            "kratos",
            "postgresql_client",
            "Backing database for Kratos' identities and sessions.",
        ),
        PresetEdge(
            "hydra",
            "kratos",
            "hydra_endpoints",
            "Kratos learns Hydra's admin/public URLs to drive the OAuth flow.",
        ),
        PresetEdge(
            "hydra",
            "login-ui",
            "hydra_endpoints",
            "The login UI learns Hydra's URLs to render consent screens.",
        ),
        PresetEdge(
            "kratos",
            "login-ui",
            "kratos_info",
            "The login UI learns Kratos' URLs to render login / settings screens.",
        ),
        PresetEdge(
            "login-ui",
            "kratos",
            "ui_endpoint_info",
            "Kratos learns the login UI's URLs to redirect users to flows.",
        ),
        PresetEdge(
            "login-ui",
            "hydra",
            "ui_endpoint_info",
            "Hydra learns the login UI's URLs to redirect users to consent.",
        ),
        PresetEdge(
            "traefik-public",
            "hydra",
            "ingress",
            "Exposes Hydra's public OAuth2 endpoints externally.",
        ),
        PresetEdge("traefik-public", "login-ui", "ingress", "Exposes the login UI externally."),
        PresetEdge(
            "traefik-admin",
            "hydra",
            "ingress",
            "Exposes Hydra's admin API on the internal ingress.",
        ),
        PresetEdge(
            "traefik-admin",
            "kratos",
            "ingress",
            "Exposes Kratos' admin API on the internal ingress.",
        ),
        PresetEdge(
            "self-signed-certificates",
            "traefik-public",
            "tls_certificates",
            "Issues the public ingress' TLS certificate.",
        ),
        PresetEdge(
            "self-signed-certificates",
            "traefik-admin",
            "tls_certificates",
            "Issues the admin ingress' TLS certificate.",
        ),
    ),
)

_CHARMED_KUBEFLOW = PresetBundle(
    name="charmed-kubeflow",
    title="Charmed Kubeflow (core subset)",
    summary=(
        "The authentication-and-routing core of Charmed Kubeflow — the full "
        "bundle is ~30 charms, but the shape every deployment shares is the "
        "Istio service mesh (pilot + ingress gateway) fronting the Kubeflow "
        "dashboard, with Dex + the OIDC gatekeeper enforcing login at the "
        "mesh edge and the profiles controller backing per-user namespaces. "
        "Treat this as the orientation map, not the deployable bundle."
    ),
    layers=("Ingress", "Auth", "Dashboard"),
    apps=(
        PresetApp(
            "istio-pilot",
            "istio-pilot",
            "Ingress",
            "Istio control plane; configures the mesh and the ingress gateway.",
        ),
        PresetApp(
            "istio-ingressgateway",
            "istio-gateway",
            "Ingress",
            "Mesh edge gateway; all external traffic enters here.",
        ),
        PresetApp(
            "dex-auth",
            "dex-auth",
            "Auth",
            "OIDC identity provider for the cluster (static users or upstream IdP).",
        ),
        PresetApp(
            "oidc-gatekeeper",
            "oidc-gatekeeper",
            "Auth",
            "AuthN filter at the mesh edge; redirects unauthenticated users to Dex.",
        ),
        PresetApp(
            "kubeflow-dashboard",
            "kubeflow-dashboard",
            "Dashboard",
            "The central Kubeflow UI surfaced behind the gateway.",
        ),
        PresetApp(
            "kubeflow-profiles",
            "kubeflow-profiles",
            "Dashboard",
            "Manages per-user profiles and their Kubernetes namespaces.",
        ),
    ),
    edges=(
        PresetEdge(
            "istio-pilot",
            "istio-ingressgateway",
            "istio-pilot",
            "Pilot pushes mesh + gateway configuration to the ingress gateway.",
        ),
        PresetEdge(
            "istio-pilot",
            "kubeflow-dashboard",
            "ingress",
            "Publishes the dashboard as a route on the mesh gateway.",
        ),
        PresetEdge(
            "istio-pilot",
            "oidc-gatekeeper",
            "ingress",
            "Publishes the gatekeeper's callback path on the mesh gateway.",
        ),
        PresetEdge(
            "oidc-gatekeeper",
            "istio-pilot",
            "ingress-auth",
            "Registers the gatekeeper as the mesh's external authorization filter.",
        ),
        PresetEdge(
            "dex-auth",
            "oidc-gatekeeper",
            "oidc-client",
            "Dex issues OIDC tokens that the gatekeeper validates.",
        ),
        PresetEdge(
            "kubeflow-profiles",
            "kubeflow-dashboard",
            "kubeflow-profiles",
            "The dashboard reads profile / namespace data from the profiles controller.",
        ),
    ),
)


CATALOGUE: tuple[PresetBundle, ...] = (
    _COS_LITE,
    _TWELVE_FACTOR_COS,
    _IDENTITY_PLATFORM,
    _CHARMED_KUBEFLOW,
)

_BY_NAME: dict[str, PresetBundle] = {bundle.name: bundle for bundle in CATALOGUE}


def get_preset(name: str) -> PresetBundle | None:
    """Return the preset with slug *name*, or ``None`` if unknown."""
    return _BY_NAME.get(name)


def preset_names() -> tuple[str, ...]:
    """Catalogue slugs in declaration order."""
    return tuple(bundle.name for bundle in CATALOGUE)


# ---------------------------------------------------------------------------
# Live-model matching
# ---------------------------------------------------------------------------

# A live model is "a" preset when at least this many of the preset's apps
# are present (counting optional apps) *and* the matched apps make up at
# least this fraction of the preset's *required* apps.  Both gates
# matter: a 2-app overlap with COS Lite (Prometheus + Grafana, say,
# hanging off some unrelated bundle) should not claim the model is COS
# Lite, and neither should 3 apps out of a 7-required-app preset — but a
# bare ``app + db + ingress`` model *should* still read as 12-Factor even
# though it has none of that preset's (optional) COS apps.
_MIN_MATCHED_APPS = 3
_MIN_MATCH_FRACTION = 0.5


def _live_app_matches(live_name: str, live_charm: str | None, preset_app: PresetApp) -> bool:
    """Return true iff a live app plausibly *is* this preset app.

    Matches on charm name first (robust to renames like ``prometheus`` →
    ``metrics``), then on app-name prefix (``prometheus-k8s`` deployed
    from a bundle that names it ``prometheus``, or vice versa). The
    placeholder charm ``<paas-charm>`` never matches by charm — only the
    conventional app name ``app`` does.
    """
    if live_charm and not preset_app.charm.startswith("<") and live_charm == preset_app.charm:
        return True
    if live_name == preset_app.name:
        return True
    longer, shorter = (
        (live_name, preset_app.name)
        if len(live_name) >= len(preset_app.name)
        else (preset_app.name, live_name)
    )
    return longer.startswith(shorter + "-")


@dataclasses.dataclass(frozen=True, slots=True)
class PresetMatch:
    """The result of matching a live model against the catalogue."""

    bundle: PresetBundle
    matched_apps: int
    """How many of the preset's apps were found (optional ones included)."""

    matched_required: int
    """How many of the preset's *required* apps were found."""

    app_layers: dict[str, str]
    """Maps each *live* app name to the preset layer it matched into."""

    app_to_preset: dict[str, str]
    """Maps each *live* app name to the :attr:`PresetApp.name` it matched."""

    @property
    def required_total(self) -> int:
        """Number of non-optional apps in the preset."""
        return sum(1 for app in self.bundle.apps if not app.optional)

    @property
    def fraction(self) -> float:
        """Fraction of the preset's *required* apps present in the model."""
        total = self.required_total
        return self.matched_required / total if total else 0.0

    def edge_for(self, live_a: str, live_b: str, interface: str) -> PresetEdge | None:
        """Return the preset edge connecting two *live* apps over *interface*, if any.

        Maps the live names back to their preset-app names and looks for
        a catalogue edge with that unordered pair and interface — used
        by the graph screen to label an observed relation with the
        preset's provider/requirer roles and prose.
        """
        pa, pb = self.app_to_preset.get(live_a), self.app_to_preset.get(live_b)
        if pa is None or pb is None:
            return None
        wanted = {pa, pb}
        for edge in self.bundle.edges:
            if edge.interface == interface and {edge.provider, edge.requirer} == wanted:
                return edge
        return None


def match_preset(status: statustypes.Status) -> PresetMatch | None:
    """Return the best-matching preset for *status*, or ``None``.

    "Best" is the preset with the most matched live apps; ties break
    toward the higher required-app fraction, then earlier in the
    catalogue.  Returns ``None`` when no preset clears
    :data:`_MIN_MATCHED_APPS` and :data:`_MIN_MATCH_FRACTION` — an empty
    or unrecognised model falls back to the graph screen's flat layout
    rather than being forced under a layer scheme it doesn't fit.
    """
    live: dict[str, str | None] = {
        name: getattr(app, "charm", None) for name, app in status.apps.items()
    }
    if not live:
        return None

    best: PresetMatch | None = None
    for bundle in CATALOGUE:
        app_layers: dict[str, str] = {}
        app_to_preset: dict[str, str] = {}
        matched_required = 0
        for preset_app in bundle.apps:
            for live_name, live_charm in live.items():
                if live_name in app_layers:
                    continue
                if _live_app_matches(live_name, live_charm, preset_app):
                    app_layers[live_name] = preset_app.layer
                    app_to_preset[live_name] = preset_app.name
                    if not preset_app.optional:
                        matched_required += 1
                    break
        matched = len(app_layers)
        if matched < _MIN_MATCHED_APPS:
            continue
        candidate = PresetMatch(
            bundle=bundle,
            matched_apps=matched,
            matched_required=matched_required,
            app_layers=app_layers,
            app_to_preset=app_to_preset,
        )
        if candidate.fraction < _MIN_MATCH_FRACTION:
            continue
        if best is None or (candidate.matched_apps, candidate.fraction) > (
            best.matched_apps,
            best.fraction,
        ):
            best = candidate
    return best


# ---------------------------------------------------------------------------
# Rendering (shared by the @preset provider and the preset-bundles skill)
# ---------------------------------------------------------------------------


def render_index() -> str:
    """One-line-per-preset index: ``slug — Title: summary``."""
    lines = ["Known bundle shapes (use `@preset <slug>` for the full layout):", ""]
    for bundle in CATALOGUE:
        first_sentence = bundle.summary.split(". ", 1)[0].rstrip(".")
        lines.append(f"- `{bundle.name}` — {bundle.title}: {first_sentence}.")
    return "\n".join(lines)


def render_preset(bundle: PresetBundle) -> str:
    """Full Markdown rendering of one preset: apps by layer, then edges."""
    lines = [f"# {bundle.title} (`{bundle.name}`)", "", bundle.summary, "", "## Applications"]
    for layer, apps in bundle.apps_by_layer().items():
        lines.append("")
        lines.append(f"**{layer}**")
        for app in apps:
            tag_bits = []
            if not app.charm.startswith("<"):
                tag_bits.append(f"`{app.charm}`")
            if app.optional:
                tag_bits.append("optional")
            tag = f" ({', '.join(tag_bits)})" if tag_bits else ""
            lines.append(f"- `{app.name}`{tag} — {app.summary}")
    lines.append("")
    lines.append("## Relations")
    lines.extend(
        f"- `{edge.provider}` → `{edge.requirer}` · `{edge.interface}` — {edge.description}"
        for edge in bundle.edges
    )
    return "\n".join(lines)
