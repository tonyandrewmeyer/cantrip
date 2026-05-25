"""Ubuntu Inference Snap LLM provider.

Uses the OpenAI-compatible API exposed by Canonical's inference snaps
(https://documentation.ubuntu.com/inference-snaps/).  Each snap serves
a local model at ``http://localhost:<port>/v1`` and supports chat
completions, streaming, and tool calling — no API key required.

The HTTP and wire-format plumbing lives in ``_openai_compat``; this
module only adds the snap-specific discovery bits (``snap status`` /
``/models`` probing, vision allowlist).
"""

import dataclasses
import logging
import os
import subprocess
from collections.abc import AsyncIterator
from typing import Any

import httpx

from cantrip.llm._openai_compat import OpenAICompatBase
from cantrip.llm.base import Chunk, Message, ProviderError, Tool
from cantrip.llm.mistral_format import parse_mistral_tool_call_content, rewrite_for_mistral

log = logging.getLogger(__name__)

# Known inference snaps and their default ports.
_SNAP_DEFAULTS: dict[str, int] = {
    "gemma3": 8328,
    "deepseek-r1": 8324,
    "qwen-vl": 8326,
    "nemotron-3-nano": 8330,
    "qwen3-coder": 8332,
    "gemma4": 8336,
}

# Small local models have limited context windows.  The training context
# may be larger, but practical limits with quantised weights are lower.
_DEFAULT_CONTEXT_WINDOW = 8_192

# Below this usable per-slot context, the agent flips into short-session
# mode (aggressive compaction + ledger-and-drop + per-turn ephemeral
# conversation).  gemma4 (~10 K per slot) lands below it; qwen3-coder
# (~32 K per slot) stays above.  See ``LLMProvider.short_session_mode``.
_SHORT_SESSION_MAX_CONTEXT_TOKENS = 16_000

# Known vision-capable inference snaps.  ``qwen-vl`` is explicitly
# vision-language; Gemma 3 (4B and larger) accepts images through the
# snap's OpenAI-compatible endpoint; gemma4 (Gemma 3n E4B) advertises
# ``multimodal`` and accepts image inputs.  The ``/models`` capability
# probe extends this at runtime when a server advertises a vision flag.
_VISION_SNAP_NAMES: frozenset[str] = frozenset({"qwen-vl", "gemma3", "gemma4"})

# Inference snaps known to support OpenAI-style tool calling once
# llama.cpp is launched with ``--jinja``.  llama.cpp's ``/v1/models``
# reports ``capabilities: ["completion"]`` (the model task type, not a
# tool-support flag), so the negative-inference branch in
# ``_apply_model_metadata`` would otherwise wrongly disable tools for
# every llama.cpp-backed snap.  Add a snap here once you've confirmed
# tool-call round-tripping works against it.
_TOOL_CAPABLE_SNAP_NAMES: frozenset[str] = frozenset(
    {
        "qwen3-coder",
        "gemma4",
        "qwen3-8b",
        "qwen3-14b",
        "deepseek-coder-v2-lite",
        "mistral-nemo-12b",
        "granite-4.1-8b",
        "granite-4.1-3b",
    }
)


# Operator-visible env var to override snap-family detection (Phase 109.4).
# Accepted values: "openai" (default) or "mistral".  An unrecognised value
# logs a warning and falls back to auto-detection from the snap name.
_MESSAGE_FORMAT_ENV = "CANTRIP_MESSAGE_FORMAT"

# Snap-name prefixes that indicate Mistral's Tekken chat-template format.
# The Tekken template rejects separate "tool" role messages and requires tool
# calls and results folded into adjacent assistant/user turns with the
# [TOOL_CALLS]/[TOOL_RESULTS] markers.  Snap names matching these prefixes
# receive the Mistral rewriter automatically; operators can override via
# CANTRIP_MESSAGE_FORMAT for non-standard names.
_MISTRAL_NAME_PREFIXES: tuple[str, ...] = ("mistral-nemo", "magistral-")


def _detect_message_format(snap_name: str) -> str:
    """Derive the message-format convention for *snap_name* from its name.

    Returns ``"mistral"`` for snap names that belong to the Mistral model
    family (whose Tekken chat template requires tool calls and results folded
    into assistant turns), and ``"openai"`` for everything else.
    """
    for prefix in _MISTRAL_NAME_PREFIXES:
        if snap_name.startswith(prefix):
            return "mistral"
    return "openai"


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


def _resolve_read_timeout(explicit: float | None) -> float:
    """Resolve the snap HTTP read timeout from caller / env / default.

    Phase 102.1: precedence order is *explicit argument* → env var
    ``CANTRIP_SNAP_READ_TIMEOUT`` → :attr:`InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS`.
    A non-numeric or non-positive env value logs a warning and falls
    back to the default rather than crashing provider construction —
    a typo in a long-lived shell rc shouldn't take cantrip down.
    """
    if explicit is not None and explicit > 0:
        return float(explicit)
    raw = os.environ.get("CANTRIP_SNAP_READ_TIMEOUT")
    if raw:
        try:
            value = float(raw)
        except ValueError:
            log.warning(
                "Ignoring CANTRIP_SNAP_READ_TIMEOUT=%r — expected a positive number",
                raw,
            )
        else:
            if value > 0:
                return value
            log.warning(
                "Ignoring CANTRIP_SNAP_READ_TIMEOUT=%r — must be > 0",
                raw,
            )
    return InferenceSnapProvider.DEFAULT_READ_TIMEOUT_SECONDS


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

    @property
    def short_session_mode(self) -> bool:
        """True when the detected per-slot context is too tight for rich history.

        Reads the runtime ``context_window_tokens`` (after the
        ``/slots`` / ``/props`` probe in :meth:`_probe_slot_context`),
        so a snap launched with a generous ``--ctx-size`` and few
        ``--parallel`` slots stays out of short-session mode while a
        128 KiB-on-paper model whose slots are only 10 K wide flips in.
        """
        return self._context_window < _SHORT_SESSION_MAX_CONTEXT_TOKENS

    @property
    def conversation_temperature(self) -> float:
        """Clamp the conversation temperature low for reliable tool calls.

        At 0.7 the qwen3-coder snap (and the gemma family) intermittently
        breaks out of the OpenAI tool-call envelope and emits raw
        ``<function=...>`` chat-template scaffolding inside ``content``,
        which the conversation loop then mistakes for a final reply and
        exits.  0.2 keeps tool-call formatting deterministic without
        making the model parrot its own past replies.
        """
        return 0.2

    def _build_request_body(self, messages: list[Message], *args, **kwargs):  # type: ignore[override]
        """Apply outbound message rewriting then suppress Qwen3 chain-of-thought.

        Phase 109.1: ``rewrite_messages`` fires here — once per call, before
        the request body is assembled — so the wire format matches what the
        snap's chat template expects.  For most snaps (OpenAI / Qwen format)
        this is the identity.  For Mistral-family snaps the rewriter folds
        ``tool``-role messages into the preceding assistant turn.

        The ``enable_thinking=false`` kwarg suppresses the ``<think>``
        reasoning block on Qwen3-family models (see original comment below);
        templates that don't recognise the kwarg ignore it safely.
        """
        messages = self.rewrite_messages(messages)
        body = super()._build_request_body(messages, *args, **kwargs)
        body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        return body

    @staticmethod
    def _resolve_message_format(snap_name: str) -> str:
        """Resolve the outbound message-format for *snap_name*.

        Precedence: ``CANTRIP_MESSAGE_FORMAT`` env var → snap-name family
        detection.  Accepted env values are ``"openai"`` (explicit identity)
        and ``"mistral"``; unrecognised values log a warning and fall back to
        name-based detection.
        """
        raw = os.environ.get(_MESSAGE_FORMAT_ENV, "").strip().lower()
        if raw == "mistral":
            return "mistral"
        if raw == "openai":
            # Explicit override: always use the identity rewriter regardless of
            # what the snap name would normally suggest.
            return "openai"
        if raw == "":
            return _detect_message_format(snap_name)
        log.warning(
            "Ignoring %s=%r — unrecognised value; use 'openai' or 'mistral'",
            _MESSAGE_FORMAT_ENV,
            raw,
        )
        return _detect_message_format(snap_name)

    def rewrite_messages(self, messages: list[Message]) -> list[Message]:
        """Rewrite messages for the snap's expected wire format.

        Delegates to :func:`~cantrip.llm.mistral_format.rewrite_for_mistral`
        for Mistral-family snaps; returns the input list unchanged for
        everything else.
        """
        if self._message_format == "mistral":
            return rewrite_for_mistral(messages)
        return messages

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ):
        """Complete a turn, applying the Mistral inbound parser when needed.

        Phase 109.2: after the upstream response arrives, the Mistral-format
        inbound parser fires as a client-side fallback.  When llama.cpp's
        ``--jinja`` correctly converts the model's ``[TOOL_CALLS]`` output
        into OpenAI-shaped ``tool_calls``, the response already has
        ``tool_calls`` populated and the parser is a no-op.  When ``--jinja``
        fails and the markers land in ``content`` instead, the parser extracts
        the tool calls and sets ``content`` to the remainder.
        """
        response = await super().complete(
            messages,
            tools,
            temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            response_schema=response_schema,
        )
        if self._message_format == "mistral" and not response.tool_calls:
            tool_calls, content = parse_mistral_tool_call_content(response.content)
            if tool_calls:
                return dataclasses.replace(response, tool_calls=tool_calls, content=content)
        return response

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[Chunk]:
        """Stream a turn, applying the Mistral inbound parser on the final chunk.

        Phase 109.2: for non-Mistral snaps, chunks are yielded as they arrive
        (no change from the base behaviour).  For Mistral snaps, content
        chunks are buffered so the full content can be inspected for inline
        ``[TOOL_CALLS]`` markers.  When ``--jinja`` handles tool calls
        correctly the final chunk already carries ``tool_calls`` (OpenAI
        format) and the buffer is re-yielded as a single content chunk before
        the final.  When ``--jinja`` fails and the markers are in ``content``,
        the parser extracts the tool calls, suppresses the buffered content
        (which was the raw marker text), and yields a single final chunk with
        the parsed calls.
        """
        if self._message_format != "mistral":
            async for chunk in super().stream(
                messages,
                tools,
                temperature,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                response_schema=response_schema,
            ):
                yield chunk
            return

        # Mistral path: buffer content to detect inline tool-call markers.
        accumulated: list[str] = []
        last_final: Chunk | None = None

        async for chunk in super().stream(
            messages,
            tools,
            temperature,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            response_schema=response_schema,
        ):
            if chunk.is_final:
                last_final = chunk
            elif chunk.content:
                accumulated.append(chunk.content)

        if last_final is None:
            return

        full_content = "".join(accumulated)

        if not last_final.tool_calls:
            tool_calls, remainder = parse_mistral_tool_call_content(full_content)
            if tool_calls:
                # --jinja failed; the markers were in content.  Yield the
                # parsed calls on the final chunk and suppress the raw marker
                # text so the caller never sees the literal [TOOL_CALLS] tags.
                yield Chunk(
                    tool_calls=tool_calls,
                    is_final=True,
                    usage=last_final.usage,
                    metadata=last_final.metadata,
                )
                return
            # Regular text response — re-yield buffered content then the final.
            if full_content:
                yield Chunk(content=full_content)
        else:
            # --jinja handled it; re-yield any buffered content before the final.
            if full_content:
                yield Chunk(content=full_content)

        yield last_final

    #: Default httpx read timeout (seconds) for snap chat completions.
    #: 20 min is enough headroom for any plausible single-turn
    #: generation on the slowest local snap (qwen3-coder routinely
    #: takes 8–15 minutes for a big ``edit_file`` rewrite once the
    #: conversation is several KB long).  Operators on faster GPUs can
    #: shrink this via :data:`READ_TIMEOUT_ENV` or ``--snap-read-timeout``.
    DEFAULT_READ_TIMEOUT_SECONDS: float = 1200.0

    #: Environment variable read by :meth:`__init__` when ``read_timeout``
    #: isn't passed explicitly.  Lets operators override the default
    #: timeout without going through CLI flags (handy for the TUI and
    #: Web entry points which read env directly).
    READ_TIMEOUT_ENV: str = "CANTRIP_SNAP_READ_TIMEOUT"

    def __init__(
        self,
        snap_name: str = "gemma3",
        model: str | None = None,
        base_url: str | None = None,
        read_timeout: float | None = None,
    ):
        """Initialise the inference snap provider.

        Args:
            snap_name: Name of the inference snap (e.g. "gemma3").
            model: Model identifier to pass in API requests.  Auto-detected
                from the snap's ``/models`` endpoint if not given.
            base_url: Override the API base URL (e.g.
                ``http://localhost:8328/v1``).  Discovered automatically
                if not given.
            read_timeout: HTTP read timeout for chat completions, in
                seconds.  When ``None``, falls back to
                ``CANTRIP_SNAP_READ_TIMEOUT`` and finally
                :attr:`DEFAULT_READ_TIMEOUT_SECONDS`.  Phase 102.1: a
                slow GPU on a big rewrite can take longer than the
                previous 1200 s constant; the knob lets fast hardware
                shrink it back.

        Raises:
            ProviderError: If the snap's server is not reachable.
        """
        self.snap_name = snap_name
        self.base_url = (base_url or discover_snap_endpoint(snap_name)).rstrip("/")
        self.read_timeout = _resolve_read_timeout(read_timeout)
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.read_timeout)
        self._context_window = _DEFAULT_CONTEXT_WINDOW
        self._supports_tools = True
        # Seed from the static allowlist; ``_apply_model_metadata`` may
        # upgrade this to True if the server advertises a vision
        # capability at runtime.
        self._supports_vision = snap_name in _VISION_SNAP_NAMES
        # Phase 109.4: resolve the outbound message format from the env var
        # first, falling back to snap-name-based family detection.
        self._message_format = self._resolve_message_format(snap_name)

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
                with httpx.Client(base_url=self._root_url(), timeout=10.0) as root:
                    self._probe_slot_context(root)
        except httpx.ConnectError as e:
            raise ProviderError(
                f"Cannot connect to inference snap '{self.snap_name}' at "
                f"{self.base_url}. Is the snap running?\n"
                f"  Try: sudo snap start {self.snap_name}\n"
                f"  Check: {self.snap_name} status"
            ) from e
        except (httpx.HTTPError, ValueError):
            # ``ValueError`` covers ``json.JSONDecodeError`` — a snap that
            # 200s with non-JSON shouldn't crash provider construction.
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
                with httpx.Client(base_url=self._root_url(), timeout=10.0) as root:
                    self._probe_slot_context(root)
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
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            # ``ValueError`` covers ``json.JSONDecodeError``.  Any of the
            # listed failure modes degrade to the snap-name fallback,
            # which is the conservative thing for an opaque local server.
            pass
        return self.snap_name

    def _root_url(self) -> str:
        """Strip the ``/v1`` OpenAI-compat prefix to address the snap root.

        ``/slots`` and ``/props`` are mounted one level above the
        OpenAI surface; both 404 under ``/v1``.
        """
        return self.base_url.removesuffix("/v1")

    def _probe_slot_context(self, root_client: httpx.Client) -> None:
        """Tighten the context window when the runtime KV cache is smaller than the model.

        ``/v1/models`` advertises the model's *trained* context
        (``n_ctx_train``), but llama.cpp servers split their KV cache
        across ``--parallel`` slots, and an admin can also start the
        server with ``--ctx-size`` smaller than the trained context.
        Either case caps every individual request at the per-slot
        ``n_ctx``.  Trusting only ``/v1/models`` is what made gemma4
        appear to have a 128 KiB window even though each slot was
        actually 4 KiB, and Cantrip never compacted because the
        threshold was 80% of 128 KiB.

        ``root_client`` must be anchored at the server root, *not*
        ``/v1`` — both ``/slots`` and ``/props`` live one level above
        the OpenAI-compat surface, and a ``/v1/slots`` request 404s.

        Two probes, in order of preference:

        * ``/slots`` — llama.cpp's per-slot status feed.  When present
          it reports the true per-slot ``n_ctx``; take the minimum
          across slots.
        * ``/props`` — fallback when ``/slots`` 404s (some snap builds
          gate it behind ``--slots``); reports
          ``default_generation_settings.n_ctx``, which is the per-slot
          context in current llama.cpp builds.

        vLLM/OVMS 404 both — those backends keep the value already set
        by ``_apply_model_metadata``.
        """
        runtime_ctx = self._read_runtime_ctx(root_client)
        if runtime_ctx is None:
            return
        if runtime_ctx < self._context_window:
            log.info(
                "Snap '%s' reports runtime n_ctx=%d (was %d from /models); "
                "downgrading effective context window — restart the snap with a "
                "larger --ctx-size or fewer --parallel slots to widen it.",
                self.snap_name,
                runtime_ctx,
                self._context_window,
            )
            self._context_window = runtime_ctx

    @staticmethod
    def _read_runtime_ctx(root: httpx.Client) -> int | None:
        """Probe ``/slots`` then ``/props`` for the runtime per-slot context.

        Returns the smallest positive ``n_ctx`` we can find, or ``None``
        when neither endpoint answers.  Kept narrow so the call sites
        don't need to know which endpoint won.
        """
        try:
            resp = root.get("/slots")
            resp.raise_for_status()
            slots = resp.json()
        except (httpx.HTTPError, ValueError):
            slots = None
        if isinstance(slots, list) and slots:
            slot_ctxs = [
                slot["n_ctx"]
                for slot in slots
                if isinstance(slot, dict)
                and isinstance(slot.get("n_ctx"), int)
                and slot["n_ctx"] > 0
            ]
            if slot_ctxs:
                return min(slot_ctxs)

        # Fall back to /props.  Some snap builds disable /slots but
        # still surface the runtime context here.
        try:
            resp = root.get("/props")
            resp.raise_for_status()
            props = resp.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(props, dict):
            return None
        gen = props.get("default_generation_settings")
        if isinstance(gen, dict):
            ctx = gen.get("n_ctx")
            if isinstance(ctx, int) and ctx > 0:
                return ctx
        return None

    def _apply_model_metadata(self, models_response: dict) -> None:
        """Extract context window size and capabilities from /models data."""
        models = models_response.get("data", [])
        if not models:
            return
        entry = models[0]
        # llama.cpp nests model parameters under ``data[0].meta``;
        # vLLM/OVMS put them at the top level of ``data[0]``.  Read both
        # so the same snap layer covers both backends.
        nested = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}

        # Context window: try n_ctx_train (llama.cpp), context_length
        # (vLLM/OVMS), or max_model_len as fallbacks.  Check the nested
        # llama.cpp shape before the flat one — llama.cpp servers report
        # the trained context only under ``meta``.
        for source in (nested, entry):
            for key in ("n_ctx_train", "context_length", "max_model_len"):
                ctx = source.get(key)
                if isinstance(ctx, int) and ctx > 0:
                    self._context_window = ctx
                    log.debug("Detected context window: %d tokens (%s)", ctx, key)
                    break
            else:
                continue
            break

        # Capabilities can live in three places: ``data[0].capabilities``
        # (most backends), ``data[0].meta.capabilities`` (rare), and the
        # parallel top-level ``models`` array some llama.cpp builds emit
        # alongside ``data`` (gemma4 reports ``["completion","multimodal"]``
        # there).  Merge them so the checks below see one combined list.
        capabilities: list[str] = []
        for source in (entry, nested):
            caps = source.get("capabilities")
            if isinstance(caps, list):
                capabilities.extend(caps)
        parallel = models_response.get("models")
        if isinstance(parallel, list) and parallel:
            head = parallel[0]
            if isinstance(head, dict):
                caps = head.get("capabilities")
                if isinstance(caps, list):
                    capabilities.extend(caps)

        # Tool support: some backends (e.g. OVMS) don't support function
        # calling.  Check for an explicit capability flag if present.
        # llama.cpp-backed snaps report ``capabilities: ["completion"]``
        # (the task type), so allowlisted snaps skip the negative
        # inference — tool-calling is enabled there by ``--jinja``, not
        # by this metadata.
        if (
            capabilities
            and "tool_use" not in capabilities
            and "tools" not in capabilities
            and self.snap_name not in _TOOL_CAPABLE_SNAP_NAMES
        ):
            self._supports_tools = False
            log.info(
                "Model %s does not advertise tool support; "
                "tool calls will be omitted from requests.",
                entry.get("id", self.snap_name),
            )

        # Vision support: a runtime-advertised capability upgrades the
        # seed from the static allowlist.  Never downgrade — a snap in
        # the allowlist stays vision-capable even if the server omits
        # the flag (not every backend populates ``capabilities`` fully).
        # ``multimodal`` is llama.cpp's umbrella term for image-capable
        # models (gemma4 reports it in lieu of ``vision``).
        if any(c in capabilities for c in ("vision", "image", "multimodal")):
            self._supports_vision = True

    # count_tokens inherited from LLMProvider (character-based heuristic).
