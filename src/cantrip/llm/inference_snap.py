"""Ubuntu Inference Snap LLM provider.

Uses the OpenAI-compatible API exposed by Canonical's inference snaps
(https://documentation.ubuntu.com/inference-snaps/).  Each snap serves
a local model at ``http://localhost:<port>/v1`` and supports chat
completions, streaming, and tool calling — no API key required.
"""

import contextlib
import json
import logging
import subprocess
from collections.abc import AsyncIterator
from typing import Any

import httpx

from cantrip.llm.base import (
    Chunk,
    LLMProvider,
    Message,
    ProviderError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    Response,
    Role,
    Tool,
    ToolCall,
)

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


class InferenceSnapProvider(LLMProvider):
    """LLM provider backed by a local Ubuntu inference snap."""

    @property
    def name(self) -> str:
        """Short identifier for this provider."""
        return "inference-snap"

    @property
    def context_window_tokens(self) -> int:
        """Maximum context window size in tokens for the current model."""
        return self._context_window

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

    # -- Message conversion (to OpenAI chat format) -----------------------

    @staticmethod
    def _convert_messages(messages: list[Message]) -> tuple[str | None, list[dict]]:
        """Convert messages to OpenAI chat API format.

        Returns a (system_prompt, messages) tuple.  The system prompt is
        extracted from the first SYSTEM message and passed as a separate
        system message at the start.

        Consecutive user or assistant messages are merged into a single
        message because some local model backends (e.g. Mediapipe in the
        gemma3 snap) reject conversations with consecutive same-role
        messages.
        """
        system_prompt: str | None = None
        result: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                system_prompt = msg.content
                continue

            if msg.role == Role.USER:
                # Merge with previous user message if consecutive.
                if result and result[-1]["role"] == "user":
                    if msg.content:
                        result[-1]["content"] += "\n\n" + msg.content
                else:
                    result.append({"role": "user", "content": msg.content})

            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant"}
                if msg.tool_calls:
                    entry["content"] = msg.content or None
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                else:
                    # Merge with previous assistant message if consecutive
                    # and neither has tool calls.
                    if (
                        result
                        and result[-1]["role"] == "assistant"
                        and "tool_calls" not in result[-1]
                    ):
                        if msg.content:
                            result[-1]["content"] += "\n\n" + msg.content
                        continue
                    entry["content"] = msg.content
                result.append(entry)

            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    result.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "content": tr.content,
                        }
                    )

        return system_prompt, result

    @staticmethod
    def _convert_tools(tools: list[Tool] | None) -> list[dict] | None:
        """Convert tools to OpenAI function-calling format."""
        if not tools:
            return None

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    # -- API calls --------------------------------------------------------

    def _build_request_body(
        self,
        messages: list[Message],
        tools: list[Tool] | None,
        temperature: float,
        *,
        stream: bool = False,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Build the JSON request body for a chat completion."""
        system_prompt, api_messages = self._convert_messages(messages)
        if system_prompt:
            api_messages.insert(0, {"role": "system", "content": system_prompt})

        body: dict[str, Any] = {
            "model": self.model_name,
            "messages": api_messages,
            "temperature": temperature,
            "stream": stream,
        }

        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        # Only include tools if the backend supports function calling.
        if self._supports_tools:
            api_tools = self._convert_tools(tools)
            if api_tools:
                body["tools"] = api_tools

        return body

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list[dict]) -> list[ToolCall]:
        """Parse tool calls from an OpenAI-format response."""
        tool_calls = []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            arguments = func.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=arguments,
                )
            )
        return tool_calls

    async def complete(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Response:
        """Generate a completion via the snap's OpenAI-compatible API."""
        body = self._build_request_body(messages, tools, temperature, max_tokens=max_tokens)

        try:
            resp = await self.client.post("/chat/completions", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise ProviderRateLimitError("Inference snap rate limit reached.") from e
            if e.response.status_code >= 500:
                raise ProviderOverloadedError(
                    f"Inference snap server error ({e.response.status_code})."
                ) from e
            # Include the response body for debugging 4xx errors.
            detail = ""
            with contextlib.suppress(AttributeError, UnicodeDecodeError, ValueError):
                detail = e.response.text[:500]
            raise ProviderError(
                f"Inference snap error ({e.response.status_code}): {detail or e}"
            ) from e
        except httpx.HTTPError as e:
            raise ProviderError(
                f"Failed to connect to inference snap at {self.base_url}: {e}"
            ) from e

        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"Inference snap returned non-JSON response: {resp.text[:200]}"
            ) from exc
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = self._parse_tool_calls(raw_tool_calls)

        usage = data.get("usage", {})

        return Response(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Chunk]:
        """Stream a completion via SSE."""
        body = self._build_request_body(
            messages,
            tools,
            temperature,
            stream=True,
            max_tokens=max_tokens,
        )

        tool_calls_acc: dict[int, dict[str, str]] = {}

        try:
            async with self.client.stream("POST", "/chat/completions", json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :]
                    if payload.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})

                    # Accumulate streamed tool calls.
                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.get("id", ""),
                                "name": "",
                                "arguments": "",
                            }
                        func = tc_delta.get("function", {})
                        if "name" in func:
                            tool_calls_acc[idx]["name"] = func["name"]
                        if "arguments" in func:
                            tool_calls_acc[idx]["arguments"] += func["arguments"]

                    # Yield text content as it arrives.
                    text = delta.get("content")
                    if text:
                        yield Chunk(content=text)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise ProviderRateLimitError("Inference snap rate limit reached.") from e
            if e.response.status_code >= 500:
                raise ProviderOverloadedError(
                    f"Inference snap server error ({e.response.status_code})."
                ) from e
            raise ProviderError(f"Inference snap error: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError(
                f"Failed to connect to inference snap at {self.base_url}: {e}"
            ) from e

        # Emit final chunk with accumulated tool calls.
        final_tool_calls = []
        for idx in sorted(tool_calls_acc):
            acc = tool_calls_acc[idx]
            try:
                arguments = json.loads(acc["arguments"])
            except json.JSONDecodeError:
                arguments = {}
            final_tool_calls.append(ToolCall(id=acc["id"], name=acc["name"], arguments=arguments))

        yield Chunk(tool_calls=final_tool_calls, is_final=True)

    # count_tokens inherited from LLMProvider (character-based heuristic).
