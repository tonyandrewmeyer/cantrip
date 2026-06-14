"""Shared helpers and constants for the observability tools.

Holds the patchable ``_juju_available`` and ``_find_cos_unit`` entry points
plus output truncation and the SSH-based URL/binary fetch helpers that the
log/query and rendering tools build on.
"""

import base64

import jubilant

from cantrip.agent.tools.juju_subprocess import juju_available as _juju_available  # noqa: F401

# Cap tool output to avoid overwhelming LLM context.
_MAX_OUTPUT_CHARS = 10000

# Timeout for urllib requests executed inside SSH sessions.
_HTTP_TIMEOUT_SECONDS = 10


def _find_cos_unit(cos_model: str, app_hint: str) -> tuple[jubilant.Juju, str]:
    """Find a COS unit whose app name contains *app_hint*.

    Returns a ``(juju, unit_name)`` tuple.  Raises ``ValueError`` with
    the list of available app names if no match is found.
    """
    juju = jubilant.Juju(model=cos_model)
    status = juju.status()

    for app_name, app in status.apps.items():
        if app_hint in app_name:
            # Pick the first unit available.
            for unit_name in app.units:
                return juju, unit_name

    available = ", ".join(sorted(status.apps.keys())) or "(none)"
    raise ValueError(
        f"No app containing '{app_hint}' found in model '{cos_model}'. Available apps: {available}"
    )


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """Truncate *text* to *limit* characters, appending a notice if trimmed."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... (truncated — {len(text)} chars total)"


def _ssh_fetch_url(juju: jubilant.Juju, unit_name: str, url: str, timeout: int) -> str:
    """Fetch a URL from inside a Juju unit via SSH, safely.

    The Python script is base64-encoded before being passed through the
    shell, preventing injection regardless of what characters appear in
    the URL.
    """
    # Percent-encode single quotes so the URL is safe inside a Python string literal.
    safe_url = url.replace("'", "%27")
    script = (
        "import urllib.request, sys; "
        f"resp = urllib.request.urlopen('{safe_url}', timeout={timeout}); "
        "sys.stdout.write(resp.read().decode())"
    )
    encoded = base64.b64encode(script.encode()).decode()
    return juju.ssh(
        unit_name,
        f"python3 -c \"import base64,sys;exec(base64.b64decode('{encoded}'))\"",
    )


def _ssh_fetch_binary(
    juju: jubilant.Juju,
    unit_name: str,
    url: str,
    timeout: int,
    auth_header: str | None = None,
) -> bytes:
    """Fetch a URL from inside a Juju unit and return the raw bytes.

    Mirrors :func:`_ssh_fetch_url` but base64-encodes the response
    inside the unit before printing to stdout, so we can reliably
    transport binary payloads (PNGs in particular) across the SSH
    channel — ``juju ssh`` returns a ``str`` and would otherwise
    mangle non-UTF-8 bytes.
    """
    safe_url = url.replace("'", "%27")
    header_line = ""
    if auth_header is not None:
        safe_header = auth_header.replace("'", "%27")
        header_line = f"req.add_header('Authorization', '{safe_header}'); "
    script = (
        "import urllib.request, sys, base64; "
        f"req = urllib.request.Request('{safe_url}'); "
        f"{header_line}"
        f"resp = urllib.request.urlopen(req, timeout={timeout}); "
        "sys.stdout.write(base64.b64encode(resp.read()).decode('ascii'))"
    )
    encoded = base64.b64encode(script.encode()).decode()
    raw = juju.ssh(
        unit_name,
        f"python3 -c \"import base64,sys;exec(base64.b64decode('{encoded}'))\"",
    )
    # ``juju ssh`` occasionally appends trailing whitespace; strip it
    # before b64-decoding.
    return base64.b64decode(raw.strip())
