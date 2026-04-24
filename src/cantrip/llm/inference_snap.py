"""Ubuntu Inference Snap LLM provider.

Uses the OpenAI-compatible API exposed by Canonical's inference snaps
(https://documentation.ubuntu.com/inference-snaps/).  Each snap serves
a local model at ``http://localhost:<port>/v1`` and supports chat
completions, streaming, and tool calling — no API key required.

The HTTP and wire-format plumbing lives in ``_openai_compat``; this
module only adds the snap-specific discovery bits (``snap status`` /
``/models`` probing, vision allowlist).
"""

import logging
import subprocess

import httpx

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import ProviderError

log = logging.getLogger(__name__)

# Known inference snaps and their default ports.
_SNAP_DEFAULTS: dict[str, int] = {
    "gemma3": 8328,
    "deepseek-r1": 8324,
    "qwen-vl": 8326,
    "nemotron-3-nano": 8330,
}

# Small local models have limited context windows.  The training context
# may be larger, but practical limits with quantised weights are lower.
_DEFAULT_CONTEXT_WINDOW = 8_192

# Known vision-capable inference snaps.  ``qwen-vl`` is explicitly
# vision-language; Gemma 3 (4B and larger) accepts images through the
# snap's OpenAI-compatible endpoint.  The ``/models`` capability probe
# extends this at runtime when a server advertises a vision flag.
_VISION_SNAP_NAMES: frozenset[str] = frozenset({"qwen-vl", "gemma3"})


def discover_snap_endpoint(snap_name: str) -> str:
    """Discover the OpenAI API endpoint for an inference snap.

    Runs ``<snap_name> status`` and parses the ``openai:`` endpoint line.
    Falls back to constructing a URL from the default port if the snap
    command is unavailable.
    """
    try:
        result = subprocess.run(
            [snap_name, "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "openai:" in line:
                return line.split("openai:", 1)[1].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Fallback: use the known default port.
    port = _SNAP_DEFAULTS.get(snap_name, 8328)
    return f"http://localhost:{port}/v1"


def list_available_snaps() -> list[str]:
    """Return the names of installed inference snaps."""
    try:
        result = subprocess.run(
            ["snap", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        installed = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if not parts:
                continue
            if parts[0] in _SNAP_DEFAULTS:
                installed.append(parts[0])
        return installed
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


class InferenceSnapProvider(OpenAICompatBase):
    """LLM provider backed by a local Ubuntu inference snap."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "inference-snap"

    @property
    def _error_label(self) -> str:
        """Include the snap name in error messages for operator clarity."""
        return f"inference snap '{self.snap_name}'"

    @property
    def max_tools(self) -> int | None:
        """Local models have limited context; restrict tools to a core set."""
        return 12

    def __init__(
        self,
        snap_name: str = "gemma3",
        model: str | None = None,
        base_url: str | None = None,
    ):
        """Initialise the inference snap provider.

        Args:
            snap_name: Name of the inference snap (e.g. "gemma3").
            model: Model identifier to pass in API requests.  Auto-detected
                from the snap's ``/models`` endpoint if not given.
            base_url: Override the API base URL (e.g.
                ``http://localhost:8328/v1``).  Discovered automatically
                if not given.

        Raises:
            ProviderError: If the snap's server is not reachable.
        """
        self.snap_name = snap_name
        self.base_url = (base_url or discover_snap_endpoint(snap_name)).rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=300.0)
        self._context_window = _DEFAULT_CONTEXT_WINDOW
        self._supports_tools = True
        # Seed from the static allowlist; ``_apply_model_metadata`` may
        # upgrade this to True if the server advertises a vision
        # capability at runtime.
        self._supports_vision = snap_name in _VISION_SNAP_NAMES

        # Always auto-detect the model from the /models endpoint.  The snap
        # name (e.g. "gemma3") is NOT a valid model ID — the actual served
        # model has a different name.  Only skip detection if the caller
        # provides a model that differs from the snap name.
        if model and model != snap_name:
            self.model_name = model
            self._probe_server()
        else:
            self.model_name = self._detect_model()

    def _probe_server(self) -> None:
        """Check that the snap server is reachable and probe capabilities.

        Queries ``/models`` to detect the context window size and whether the
        server supports tool calling.  Raises ``ProviderError`` with an
        actionable message if the server is not running.
        """
        try:
            with httpx.Client(base_url=self.base_url, timeout=10.0) as client:
                resp = client.get("/models")
                resp.raise_for_status()
                data = resp.json()
                self._apply_model_metadata(data)
        except httpx.ConnectError as e:
            raise ProviderError(
                f"Cannot connect to inference snap '{self.snap_name}' at "
                f"{self.base_url}. Is the snap running?\n"
                f"  Try: sudo snap start {self.snap_name}\n"
                f"  Check: {self.snap_name} status"
            ) from e
        except httpx.HTTPError:
            log.debug("Failed to probe snap server at %s", self.base_url)

    def _detect_model(self) -> str:
        """Query the snap's /models endpoint to find the served model.

        Also probes context window size and tool support as a side effect.
        Raises ``ProviderError`` if the server is unreachable.
        """
        try:
            with httpx.Client(base_url=self.base_url, timeout=10.0) as client:
                resp = client.get("/models")
                resp.raise_for_status()
                data = resp.json()
                self._apply_model_metadata(data)
                models = data.get("data", [])
                if models:
                    return models[0]["id"]
        except httpx.ConnectError as e:
            raise ProviderError(
                f"Cannot connect to inference snap '{self.snap_name}' at "
                f"{self.base_url}. Is the snap running?\n"
                f"  Try: sudo snap start {self.snap_name}\n"
                f"  Check: {self.snap_name} status"
            ) from e
        except (httpx.HTTPError, KeyError, IndexError):
            pass
        return self.snap_name

    def _apply_model_metadata(self, models_response: dict) -> None:
        """Extract context window size and capabilities from /models data."""
        models = models_response.get("data", [])
        if not models:
            return
        meta = models[0]

        # Context window: try n_ctx_train (llama.cpp), context_length
        # (vLLM/OVMS), or max_model_len as fallbacks.
        for key in ("n_ctx_train", "context_length", "max_model_len"):
            ctx = meta.get(key)
            if isinstance(ctx, int) and ctx > 0:
                self._context_window = ctx
                log.debug("Detected context window: %d tokens (%s)", ctx, key)
                break

        # Tool support: some backends (e.g. OVMS) don't support function
        # calling.  Check for an explicit capability flag if present.
        capabilities = meta.get("capabilities", [])
        if capabilities and "tool_use" not in capabilities and "tools" not in capabilities:
            self._supports_tools = False
            log.info(
                "Model %s does not advertise tool support; "
                "tool calls will be omitted from requests.",
                meta.get("id", self.snap_name),
            )

        # Vision support: a runtime-advertised capability upgrades the
        # seed from the static allowlist.  Never downgrade — a snap in
        # the allowlist stays vision-capable even if the server omits
        # the flag (not every backend populates ``capabilities`` fully).
        if capabilities and ("vision" in capabilities or "image" in capabilities):
            self._supports_vision = True

    # count_tokens inherited from LLMProvider (character-based heuristic).
