"""Diátaxis documentation scaffold generation (Canonical starter pack)."""

import dataclasses
import datetime
import json
import pathlib
import re
from typing import Any

import jinja2

from cantrip.agent.tools.base import Tool, ToolResult
from cantrip.agent.tools.publishing._common import (
    _read_charm_metadata,
    generate_architecture_diagram,
)

# Jinja2 templates that back :func:`generate_docs_scaffold`.  Static skeleton
# only — dynamic loops (config options, action lists, integrations) are
# pre-rendered into ``*_block`` strings by the renderer below and substituted
# into the templates as a single placeholder.  Per Phase 85.6 of the roadmap.
_DOCS_TEMPLATE_DIR = pathlib.Path(__file__).parents[3] / "charm" / "docs_templates"
_DOCS_TEMPLATE_ENV: jinja2.Environment | None = None

# (output path relative to charm root, template path relative to docs_templates/).
# ``actions`` pages are appended conditionally below.
_DOCS_TEMPLATE_FILES: tuple[tuple[str, str], ...] = (
    ("docs/index.rst", "docs/index.rst.j2"),
    ("docs/tutorial/getting-started.md", "docs/tutorial/getting-started.md.j2"),
    ("docs/how-to/index.md", "docs/how-to/index.md.j2"),
    ("docs/how-to/deploy.md", "docs/how-to/deploy.md.j2"),
    ("docs/how-to/configure.md", "docs/how-to/configure.md.j2"),
    ("docs/how-to/integrate.md", "docs/how-to/integrate.md.j2"),
    ("docs/reference/index.md", "docs/reference/index.md.j2"),
    ("docs/reference/configuration.md", "docs/reference/configuration.md.j2"),
    ("docs/reference/integrations.md", "docs/reference/integrations.md.j2"),
    ("docs/explanation/index.md", "docs/explanation/index.md.j2"),
    ("docs/explanation/architecture.md", "docs/explanation/architecture.md.j2"),
    ("docs/conf.py", "docs/conf.py.j2"),
    ("docs/requirements.txt", "docs/requirements.txt.j2"),
    ("docs/.custom_wordlist.txt", "docs/custom_wordlist.txt.j2"),
    ("docs/.gitignore", "docs/gitignore.j2"),
    ("docs/Makefile", "docs/Makefile.j2"),
    (".readthedocs.yaml", "readthedocs.yaml.j2"),
)


def _docs_template_env() -> jinja2.Environment:
    """Return the shared docs Jinja env, creating it on first call."""
    global _DOCS_TEMPLATE_ENV  # noqa: PLW0603
    if _DOCS_TEMPLATE_ENV is None:
        _DOCS_TEMPLATE_ENV = jinja2.Environment(
            loader=jinja2.FileSystemLoader(_DOCS_TEMPLATE_DIR),
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _DOCS_TEMPLATE_ENV


# ---------------------------------------------------------------------------
# Bridging Phase 13 root files (TUTORIAL.md / DEMO.md / architecture.md) into
# the Diátaxis tree so the docs/ site reflects what the agent actually did
# rather than the metadata-derived stubs.
# ---------------------------------------------------------------------------

# Map root-file name → docs/ destination path (without ``.md`` so the toctree
# entries match Sphinx's ``dirhtml`` link form).
_BRIDGE_TARGETS: dict[str, str] = {
    "TUTORIAL.md": "tutorial/getting-started",
    "DEMO.md": "how-to/deploy-and-verify",
    "architecture.md": "explanation/architecture",
}

# Markdown link / image regex.  Captures the bracket text and the URL
# separately so the alt/text can be preserved unchanged.
_MARKDOWN_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")

# Absolute-URL prefixes left untouched by the link rewriter.
_ABSOLUTE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://|^//|^mailto:|^tel:")


def _replace_first_h1(content: str, new_heading: str) -> str:
    """Replace the first ATX H1 in *content* with *new_heading*.

    Falls back to prepending the heading when the source has no H1, so the
    bridged page always starts with one.
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        # H1 is exactly one ``#`` followed by a space; ``##`` and deeper are
        # left alone.
        if line.startswith("# ") or line.rstrip() == "#":
            lines[i] = new_heading
            return "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    prefix = new_heading + "\n\n"
    return prefix + content


def _rewrite_root_link(url: str) -> str:
    """Rewrite *url* (originally relative to the charm root) for a docs/<dir>/<page> file.

    - Absolute URLs and anchors are left as-is.
    - Cross-references to other bridged root files become docs/-tree links
      (``../how-to/deploy-and-verify`` etc.) so the rebuilt site still
      resolves them.
    - Other root-relative paths get a ``../../`` prefix to climb out of
      ``docs/<dir>/`` back to the charm root.

    All bridge destinations currently live at depth 2 (``docs/<dir>/<page>``),
    so the climb count is fixed at two.
    """
    if _ABSOLUTE_URL_RE.match(url) or url.startswith("#"):
        return url
    path, anchor = (url.split("#", 1) + [""])[:2]
    anchor_suffix = "#" + anchor if anchor else ""
    if path.startswith("./"):
        path = path[2:]
    if not path:
        return anchor_suffix or url
    # Already escaping out of a subdirectory — leave well alone.
    if path.startswith("../"):
        return url
    if path in _BRIDGE_TARGETS:
        return "../" + _BRIDGE_TARGETS[path] + anchor_suffix
    return "../../" + path + anchor_suffix


def _rewrite_links(content: str) -> str:
    """Apply :func:`_rewrite_root_link` to every Markdown link in *content*."""

    def _sub(match: re.Match[str]) -> str:
        bang, text, url, title = match.group(1), match.group(2), match.group(3), match.group(4)
        new_url = _rewrite_root_link(url)
        return f"{bang}[{text}]({new_url}{title or ''})"

    return _MARKDOWN_LINK_RE.sub(_sub, content)


def bridge_root_file(
    root_filename: str,
    content: str,
    display_name: str,
) -> tuple[str, str]:
    """Convert a charm-root demo file into its docs/-tree equivalent.

    Returns ``(docs_relative_path, rewritten_content)``.  Raises
    :class:`KeyError` for filenames that aren't bridged.
    """
    target = _BRIDGE_TARGETS[root_filename]
    docs_path = "docs/" + target + ".md"
    new_heading = _BRIDGE_HEADINGS[root_filename](display_name)
    rewritten = _replace_first_h1(content, new_heading)
    rewritten = _rewrite_links(rewritten)
    return docs_path, rewritten


# Heading rewrite per bridged file.  Tutorial and how-to pick up the charm's
# display name so the page reads naturally; architecture is just "Architecture"
# because the page title is enough context.
_BRIDGE_HEADINGS: dict[str, Any] = {
    "TUTORIAL.md": lambda display_name: f"# Get started with {display_name}",
    "DEMO.md": lambda display_name: f"# Deploy and verify {display_name}",
    "architecture.md": lambda _display_name: "# Architecture",
}


# Stub left at the charm root after a file has been bridged into ``docs/``.
# Keeps existing in-repo links from 404-ing while making the move discoverable.
_ROOT_STUB_TEMPLATE = (
    "# Moved\n"
    "\n"
    "This content now lives in [`{docs_path}`]({docs_path}).\n"
    "\n"
    "It was bridged into the Diátaxis tree by `generate_docs` so the\n"
    "documentation site builds from a single source.\n"
)


def _root_stub(docs_path: str) -> str:
    return _ROOT_STUB_TEMPLATE.format(docs_path=docs_path)


# ---------------------------------------------------------------------------
# Phase 74.2 — populate tutorial / how-to from acceptance-test artefacts.
# ---------------------------------------------------------------------------

# Phase 13's demo subagent leaves rich captured artefacts in ``demo/``
# (juju-status.txt, actions/<name>.json, …).  Phase 17 leaves a markdown
# summary at ``ACCEPTANCE.md``.  Together they're the "test transcript" the
# roadmap calls for: real commands the agent ran and the output it saw.

# IPv4 octet — 0–255 — used to avoid replacing version strings like 1.2.3.4
# that aren't valid IPv4 addresses (tightened a little vs the trivial
# four-dot pattern).  Each octet is 0–255.
_IPV4_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4_RE = re.compile(rf"\b{_IPV4_OCTET}(?:\.{_IPV4_OCTET}){{3}}\b")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_K8S_FQDN_RE = re.compile(r"\b[\w.-]+\.svc\.cluster\.local\b")
_SHA256_RE = re.compile(r"\bsha256:[0-9a-fA-F]{64}\b")


def sanitise_capture(text: str) -> str:
    """Replace cluster-specific identifiers in *text* with stable placeholders.

    Patterns replaced:

    - IPv4 addresses → ``<unit-ip>``
    - UUIDs (canonical 8-4-4-4-12 hex layout) → ``<model-uuid>``
    - Kubernetes service FQDNs (``*.svc.cluster.local``) → ``<svc-fqdn>``
    - OCI ``sha256:…`` digests → ``<image-sha256>``

    The replacements are intentionally conservative — we'd rather leak a
    rare false-negative than over-redact and produce docs that don't tell
    the reader what the charm actually does.  Versioned strings like
    ``1.2.3.4`` are caught by the IPv4 regex (octets 0–255) since they're
    syntactically valid IPv4 too; in the docs context this is fine.
    """
    text = _UUID_RE.sub("<model-uuid>", text)
    text = _SHA256_RE.sub("<image-sha256>", text)
    text = _K8S_FQDN_RE.sub("<svc-fqdn>", text)
    text = _IPV4_RE.sub("<unit-ip>", text)
    return text


@dataclasses.dataclass(frozen=True)
class AcceptanceArtefacts:
    """Bundle of acceptance-test artefacts read from a charm directory.

    Each field is already sanitised; callers can embed the values directly.
    """

    juju_status: str | None = None
    action_outputs: dict[str, str] = dataclasses.field(default_factory=dict)
    has_acceptance_md: bool = False

    @property
    def is_populated(self) -> bool:
        """True when at least one artefact is present."""
        return bool(self.juju_status) or bool(self.action_outputs) or self.has_acceptance_md


def load_acceptance_artefacts(charm_dir: pathlib.Path) -> AcceptanceArtefacts:
    """Read demo/ + ACCEPTANCE.md artefacts from *charm_dir*.

    Returns an empty :class:`AcceptanceArtefacts` when nothing is present
    (tests haven't run yet) — callers gate behaviour on
    :attr:`AcceptanceArtefacts.is_populated`.
    """
    juju_status: str | None = None
    status_path = charm_dir / "demo" / "juju-status.txt"
    if status_path.is_file():
        juju_status = sanitise_capture(status_path.read_text().rstrip())

    action_outputs: dict[str, str] = {}
    actions_dir = charm_dir / "demo" / "actions"
    if actions_dir.is_dir():
        for action_path in sorted(actions_dir.glob("*.json")):
            try:
                raw = action_path.read_text()
                # Pretty-print so the captured output reads naturally; if the
                # file isn't valid JSON, embed it as-is.
                payload = json.loads(raw)
                rendered = json.dumps(payload, indent=2, sort_keys=True)
            except json.JSONDecodeError:
                rendered = raw.rstrip()
            action_outputs[action_path.stem] = sanitise_capture(rendered)

    has_acceptance_md = (charm_dir / "ACCEPTANCE.md").is_file()

    return AcceptanceArtefacts(
        juju_status=juju_status,
        action_outputs=action_outputs,
        has_acceptance_md=has_acceptance_md,
    )


def _juju_status_excerpt(juju_status: str, *, max_lines: int = 30) -> str:
    """Trim *juju_status* to the first *max_lines* lines for inline embedding."""
    lines = juju_status.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    truncated = "\n".join(lines[:max_lines])
    return truncated + f"\n… ({len(lines) - max_lines} more lines elided)"


_STUB_FALLBACK_NOTICE = (
    "<!-- This page is templated.  Once acceptance tests run "
    "(`acceptance_report`), the agent will rebuild it from the captured "
    "deploy + test output. -->\n\n"
)


def _populate_tutorial_from_artefacts(
    charm_name: str,
    display_name: str,
    metadata: dict[str, Any],
    artefacts: AcceptanceArtefacts,
) -> str:
    """Build a real-output tutorial page from the captured artefacts."""
    requires = metadata.get("requires", {})
    actions = metadata.get("actions", {})

    sections: list[str] = [
        f"# Get started with {display_name}",
        "",
        f"This tutorial walks you through deploying {display_name} the way the agent",
        "did during acceptance testing.  Every command and every output block below",
        "is what the agent actually ran and saw — so the steps are reproducible.",
        "",
        "## Prerequisites",
        "",
        "- A Juju controller bootstrapped and ready",
        "",
        "## Add a model",
        "",
        "```console",
        f"$ juju add-model {charm_name}",
        "```",
        "",
        "## Deploy the charm",
        "",
        "```console",
        f"$ juju deploy {charm_name}",
        "```",
        "",
    ]

    if requires:
        sections.extend(["## Establish integrations", ""])
        for rel_name, rel_data in requires.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            sections.extend(
                [
                    "```console",
                    f"$ juju integrate {charm_name}:{rel_name} <provider>  # interface: {iface}",
                    "```",
                    "",
                ]
            )

    if artefacts.juju_status:
        sections.extend(
            [
                "## Verify the deployment",
                "",
                "```console",
                "$ juju status",
                _juju_status_excerpt(artefacts.juju_status),
                "```",
                "",
            ]
        )

    if actions and artefacts.action_outputs:
        first_action = next(iter(actions))
        if first_action in artefacts.action_outputs:
            sections.extend(
                [
                    f"## Exercise the `{first_action}` action",
                    "",
                    "```console",
                    f"$ juju run {charm_name}/leader {first_action}",
                    artefacts.action_outputs[first_action],
                    "```",
                    "",
                ]
            )

    sections.extend(
        [
            "## Next steps",
            "",
            "- Read the [how-to guides](../how-to/index) for common operations.",
            "- See the [configuration reference](../reference/configuration) "
            "for available options.",
            "",
        ]
    )

    return "\n".join(sections)


def _populate_actions_from_artefacts(
    charm_name: str,
    actions: dict[str, Any],
    artefacts: AcceptanceArtefacts,
) -> str:
    """Emit a per-action how-to with captured JSON output where available."""
    sections: list[str] = ["# Run actions", ""]
    for action_name, action_data in actions.items():
        desc = action_data.get("description", "") if isinstance(action_data, dict) else ""
        sections.append(f"## `{action_name}`")
        sections.append("")
        if desc:
            sections.append(desc)
            sections.append("")
        sections.append("```console")
        sections.append(f"$ juju run {charm_name}/leader {action_name}")
        if action_name in artefacts.action_outputs:
            sections.append(artefacts.action_outputs[action_name])
        sections.append("```")
        sections.append("")
    return "\n".join(sections)


def _populate_deploy_and_verify_from_artefacts(
    charm_name: str,
    display_name: str,
    metadata: dict[str, Any],
    artefacts: AcceptanceArtefacts,
) -> str:
    """Recipe-form deploy-and-verify page (no narrative, real output)."""
    requires = metadata.get("requires", {})
    sections: list[str] = [
        f"# Deploy and verify {display_name}",
        "",
        "Reproduce the deployment exactly as the agent ran it during acceptance",
        "testing.",
        "",
        "```console",
        f"$ juju add-model {charm_name}",
        f"$ juju deploy {charm_name}",
    ]
    for rel_name, rel_data in requires.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        sections.append(f"$ juju integrate {charm_name}:{rel_name} <provider>  # {iface}")
    sections.append("```")
    sections.append("")

    if artefacts.juju_status:
        sections.extend(
            [
                "Wait for the model to settle:",
                "",
                "```console",
                "$ juju status",
                _juju_status_excerpt(artefacts.juju_status),
                "```",
                "",
            ]
        )

    return "\n".join(sections)


def _build_integrations_block(charm_name: str, requires: dict[str, Any]) -> str:
    """Render the tutorial's Establish-integrations section, or '' when empty."""
    relation_lines = [
        f"juju integrate {charm_name} {rel_name}:"
        f"{rel_data.get('interface', '') if isinstance(rel_data, dict) else ''}"
        for rel_name, rel_data in requires.items()
    ]
    if not relation_lines:
        return ""
    return "\n## Establish integrations\n\n" + "".join(
        f"```bash\n{line}\n```\n\n" for line in relation_lines
    )


def _build_config_block(charm_name: str, config: dict[str, Any]) -> str:
    """Render the configure how-to body — sample blocks for the first three options."""
    config_lines = [
        f"```bash\njuju config {charm_name} {opt_name}=<value>\n```\n"
        for opt_name in list(config.keys())[:3]
    ]
    if config_lines:
        return "\n".join(config_lines)
    return f"```bash\njuju config {charm_name} <option>=<value>\n```\n"


def _build_integrate_block(
    charm_name: str, requires: dict[str, Any], provides: dict[str, Any]
) -> str:
    """Render the integrate how-to body, listing requires and provides relations."""
    integrate_lines: list[str] = []
    for rel_name, rel_data in requires.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        integrate_lines.append(
            f"### `{rel_name}` (`{iface}`)\n\n"
            f"```bash\njuju integrate {charm_name}:{rel_name} <provider>\n```\n"
        )
    for rel_name, rel_data in provides.items():
        iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
        integrate_lines.append(
            f"### `{rel_name}` (`{iface}`)\n\n"
            f"```bash\njuju integrate {charm_name}:{rel_name} <requirer>\n```\n"
        )
    if integrate_lines:
        return "\n".join(integrate_lines)
    return "This charm has no integrations defined yet.\n"


def _build_actions_block(charm_name: str, actions: dict[str, Any]) -> str:
    """Render the actions how-to body — one section per action, optional desc.

    Returned without a trailing newline; the template that consumes this
    block (``docs/how-to/actions.md.j2``) ends with ``{{ block }}\\n`` so
    the file lands with a single terminal newline.
    """
    action_lines: list[str] = []
    for action_name, action_data in actions.items():
        desc = action_data.get("description", "") if isinstance(action_data, dict) else ""
        action_lines.append(
            f"## `{action_name}`\n\n"
            + (f"{desc}\n\n" if desc else "")
            + f"```bash\njuju run {charm_name}/leader {action_name}\n```\n"
        )
    return "\n".join(action_lines).removesuffix("\n")


def _build_config_ref_block(config: dict[str, Any]) -> str:
    """Render the configuration reference body, one section per option.

    Returned without a trailing newline; see :func:`_build_actions_block`.
    """
    config_ref_lines: list[str] = []
    for opt_name, opt_data in config.items():
        opt_type = opt_data.get("type", "string")
        opt_desc = opt_data.get("description", "")
        opt_default = opt_data.get("default", "")
        entry = f"## `{opt_name}`\n\n"
        entry += f"- **Type:** `{opt_type}`\n"
        if opt_default not in ("", None):
            entry += f"- **Default:** `{opt_default}`\n"
        if opt_desc:
            entry += f"\n{opt_desc}\n"
        config_ref_lines.append(entry)
    if config_ref_lines:
        return "\n".join(config_ref_lines).removesuffix("\n")
    return "No configuration options are defined."


def _build_integ_ref_block(requires: dict[str, Any], provides: dict[str, Any]) -> str:
    """Render the integrations reference body, grouped by requires / provides.

    Returned without a trailing newline; see :func:`_build_actions_block`.
    """
    integ_ref_lines: list[str] = []
    if requires:
        integ_ref_lines.append("## Requires\n")
        for rel_name, rel_data in requires.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            integ_ref_lines.append(f"### `{rel_name}`\n\n- **Interface:** `{iface}`\n")
    if provides:
        integ_ref_lines.append("## Provides\n")
        for rel_name, rel_data in provides.items():
            iface = rel_data.get("interface", "") if isinstance(rel_data, dict) else ""
            integ_ref_lines.append(f"### `{rel_name}`\n\n- **Interface:** `{iface}`\n")
    if integ_ref_lines:
        return "\n".join(integ_ref_lines).removesuffix("\n")
    return "No integrations are defined."


def _build_actions_ref_block(actions: dict[str, Any]) -> str:
    """Render the actions reference body, with optional parameter tables.

    Returned without a trailing newline; see :func:`_build_actions_block`.
    """
    action_ref_lines: list[str] = []
    for action_name, action_data in actions.items():
        desc = ""
        params_block = ""
        if isinstance(action_data, dict):
            desc = action_data.get("description", "")
            params = action_data.get("params", {})
            if params:
                param_lines = []
                for p_name, p_data in params.items():
                    p_type = p_data.get("type", "string") if isinstance(p_data, dict) else ""
                    p_desc = p_data.get("description", "") if isinstance(p_data, dict) else ""
                    param_lines.append(f"  - `{p_name}` ({p_type}): {p_desc}")
                params_block = "- **Parameters:**\n" + "\n".join(param_lines) + "\n"
        entry = f"## `{action_name}`\n\n"
        if desc:
            entry += f"{desc}\n\n"
        if params_block:
            entry += f"{params_block}\n"
        action_ref_lines.append(entry)
    return "\n".join(action_ref_lines).removesuffix("\n")


def generate_docs_scaffold(
    charm_name: str,
    metadata: dict[str, Any],
    *,
    root_files: dict[str, str] | None = None,
    acceptance: AcceptanceArtefacts | None = None,
) -> dict[str, str]:
    """Generate a complete docs scaffold as a ``{relative_path: content}`` map.

    Follows the Diátaxis structure (tutorial, how-to, reference, explanation)
    and uses the Canonical starter pack conventions (Makefile, conf.py,
    requirements.txt, .readthedocs.yaml).  Content files are MyST Markdown.

    When *root_files* maps a known charm-root file (``TUTORIAL.md`` /
    ``DEMO.md`` / ``architecture.md``) to its current contents, the scaffold
    bridges that content into the matching ``docs/`` page rather than emitting
    the metadata-derived stub (Phase 74.1).

    When *acceptance* is populated (Phase 74.2), real captured commands and
    output from the demo/ tree replace the relevant templated stubs — the
    tutorial, the actions how-to, and the deploy-and-verify recipe.  Bridges
    from *root_files* still take precedence: the agent-authored ``TUTORIAL.md``
    is treated as authoritative over the artefact-derived version.
    """
    display_name = metadata.get("display-name") or metadata.get("name", charm_name)
    description = metadata.get("description", "")
    summary = metadata.get("summary", description.split("\n")[0] if description else "")
    source_url = metadata.get("source", "")

    config = metadata.get("config", {}).get("options", {})
    actions = metadata.get("actions", {})
    requires = metadata.get("requires", {})
    provides = metadata.get("provides", {})

    bridged_files: dict[str, str] = {}
    if root_files:
        for root_name, raw_content in root_files.items():
            if root_name not in _BRIDGE_TARGETS:
                continue
            docs_path, rewritten = bridge_root_file(root_name, raw_content, display_name)
            bridged_files[docs_path] = rewritten

    artefacts_present = bool(acceptance and acceptance.is_populated)

    howto_entries = ["deploy"]
    if "docs/how-to/deploy-and-verify.md" in bridged_files or artefacts_present:
        howto_entries.append("deploy-and-verify")
    howto_entries.extend(["configure", "integrate"])
    if actions:
        howto_entries.append("actions")

    ref_entries = ["configuration", "integrations"]
    if actions:
        ref_entries.append("actions")

    context: dict[str, Any] = {
        "charm_name": charm_name,
        "display_name": display_name,
        "summary": summary,
        "source_url": source_url,
        "year": datetime.date.today().year,
        "integrations_block": _build_integrations_block(charm_name, requires),
        "howto_entries_block": "".join(f"{entry}\n" for entry in howto_entries),
        "config_block": _build_config_block(charm_name, config),
        "integrate_block": _build_integrate_block(charm_name, requires, provides),
        "actions_block": _build_actions_block(charm_name, actions) if actions else "",
        "ref_entries_block": "".join(f"{entry}\n" for entry in ref_entries),
        "config_ref_block": _build_config_ref_block(config),
        "integ_ref_block": _build_integ_ref_block(requires, provides),
        "actions_ref_block": _build_actions_ref_block(actions) if actions else "",
        "description_block": f"{description}\n\n" if description else "",
        "architecture_diagram": generate_architecture_diagram(charm_name, metadata),
    }

    env = _docs_template_env()
    files: dict[str, str] = {
        output_path: env.get_template(template_path).render(**context)
        for output_path, template_path in _DOCS_TEMPLATE_FILES
    }
    if actions:
        files["docs/how-to/actions.md"] = env.get_template("docs/how-to/actions.md.j2").render(
            **context
        )
        files["docs/reference/actions.md"] = env.get_template(
            "docs/reference/actions.md.j2"
        ).render(**context)

    # ── Phase 74.2 — artefact-derived overrides ────────────────────────────
    # Real captured commands and output beat the metadata-derived stubs.
    # Bridged root files (74.1) win over both, so the order is:
    #     templated stubs  <  artefact-derived  <  bridged root files
    if artefacts_present:
        assert acceptance is not None
        files["docs/tutorial/getting-started.md"] = _populate_tutorial_from_artefacts(
            charm_name, display_name, metadata, acceptance
        )
        files["docs/how-to/deploy-and-verify.md"] = _populate_deploy_and_verify_from_artefacts(
            charm_name, display_name, metadata, acceptance
        )
        if actions:
            files["docs/how-to/actions.md"] = _populate_actions_from_artefacts(
                charm_name, actions, acceptance
            )
    else:
        # When acceptance hasn't run, mark each templated page so the reader
        # knows the content is generic until tests run.
        for stub_path in (
            "docs/tutorial/getting-started.md",
            "docs/how-to/deploy.md",
            "docs/how-to/integrate.md",
        ):
            if stub_path in files:
                files[stub_path] = _STUB_FALLBACK_NOTICE + files[stub_path]
        if "docs/how-to/actions.md" in files:
            files["docs/how-to/actions.md"] = (
                _STUB_FALLBACK_NOTICE + files["docs/how-to/actions.md"]
            )

    files.update(bridged_files)

    return files


class GenerateDocsTool(Tool):
    """Generate Diátaxis-structured documentation for a charm."""

    @property
    def name(self) -> str:
        return "generate_docs"

    @property
    def description(self) -> str:
        return (
            "Generate a docs/ directory with Diátaxis-structured documentation "
            "(tutorial, how-to, reference, explanation) using the Canonical "
            "starter pack. Reads charmcraft.yaml to populate configuration "
            "reference, actions, and integrations. Includes Makefile, conf.py, "
            "and .readthedocs.yaml for building with Sphinx."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the charm directory",
                    "default": ".",
                },
                "charm_name": {
                    "type": "string",
                    "description": ("Charm name. If omitted, read from charmcraft.yaml."),
                },
            },
        }

    async def execute(self, path: str = ".", charm_name: str | None = None) -> ToolResult:
        """Generate the docs scaffold in the charm directory."""
        charm_dir = pathlib.Path(path).resolve()
        if not charm_dir.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Directory not found: {path}",
            )

        metadata = _read_charm_metadata(charm_dir)
        if not charm_name:
            charm_name = metadata.get("name", charm_dir.name)

        # Pick up Phase 13 root files (TUTORIAL.md / DEMO.md / architecture.md)
        # so generate_docs_scaffold can bridge them into the docs/ tree.  We
        # only read files we'll actually bridge; the stub left at the root
        # afterwards isn't itself bridged on the next run because it lacks the
        # original page content.
        root_files: dict[str, str] = {}
        for root_name in _BRIDGE_TARGETS:
            root_path = charm_dir / root_name
            if not root_path.is_file():
                continue
            content = root_path.read_text()
            # Skip files that are already the post-bridge stub so re-runs
            # don't double-bridge a "Moved" pointer back into docs/.
            if content.lstrip().startswith("# Moved"):
                continue
            root_files[root_name] = content

        # Phase 74.2 — read demo/ + ACCEPTANCE.md so the scaffold can populate
        # tutorial / actions / deploy-and-verify with real captured output.
        acceptance = load_acceptance_artefacts(charm_dir)

        files = generate_docs_scaffold(
            charm_name, metadata, root_files=root_files, acceptance=acceptance
        )

        written: list[str] = []
        for rel_path, content in files.items():
            full_path = charm_dir / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            written.append(rel_path)

        bridged: list[str] = []
        for root_name in root_files:
            target = _BRIDGE_TARGETS[root_name]
            docs_path = "docs/" + target + ".md"
            (charm_dir / root_name).write_text(_root_stub(docs_path))
            bridged.append(f"{root_name} → {docs_path}")

        summary = (
            f"Generated documentation scaffold for '{charm_name}' "
            f"({len(written)} files):\n"
            + "\n".join(f"  {f}" for f in sorted(written))
            + "\n\nBuild with: cd docs && make html"
        )
        if bridged:
            summary += "\n\nBridged from charm root:\n" + "\n".join(
                f"  {entry}" for entry in bridged
            )
        if acceptance.is_populated:
            populated_pages = ["docs/tutorial/getting-started.md"]
            populated_pages.append("docs/how-to/deploy-and-verify.md")
            if metadata.get("actions"):
                populated_pages.append("docs/how-to/actions.md")
            summary += "\n\nPopulated from acceptance artefacts:\n" + "\n".join(
                f"  {page}" for page in populated_pages
            )

        return ToolResult(
            success=True,
            output=summary,
            data={
                "charm_name": charm_name,
                "file_count": len(written),
                "files": sorted(written),
                "bridged": bridged,
                "acceptance_populated": acceptance.is_populated,
            },
            caption=f"Wrote {len(written)} doc{'s' if len(written) != 1 else ''}",
        )
