# `@`-Mention Context Providers

Phase 72.2.  This document covers the input-layer expansion of
`@<name> [args]` mentions into structured context, the protocol third
parties implement, and the conventions for adding a new provider.
The implementation lives in `src/cantrip/agent/context_providers.py`
(parser, registry, protocol) and
`src/cantrip/agent/context_providers_builtin.py` (the eight
unconditionally-shipped providers, plus `@docs` and the three
codeintel providers when their backends are available).

## What gets expanded

A user typing `look at @file src/charm.py and @diff` gets the typed
form replaced *before* the message reaches the LLM:

```
look at <contents of src/charm.py> and
[@diff]
<git diff HEAD output>
[/@diff]
```

The chat surface still shows the user's typed form; the substitution
happens between submission and LLM dispatch.  The TUI and Web input
layers both call
`cantrip.agent.context_providers.expand_mentions()` for this pass,
then post a one-line `Expanded mentions: …` system note when
anything fired so the user can audit what was injected.

## Why input-layer expansion (not a tool call)

Three reasons:

1.  **One fewer round trip.**  The agent sees the substituted text
    immediately and can plan against it.  A `read_file` tool call to
    inline the same content is one extra LLM↔model pass per mention.
2.  **Transcript records both forms.**  Multi-line blocks get a
    `[@file path]…[/@file path]` fence so the typed mention stays
    visible alongside the substituted content — readers see intent
    plus result.
3.  **Providers can wrap any read-only operation**, not just an
    existing typed `Tool`.  `@problems` reuses
    `cantrip.agent.lint_context.gather_project_diagnostics` directly
    without going through a `Tool` envelope.

## The `ContextProvider` protocol

```python
@runtime_checkable
class ContextProvider(Protocol):
    info: ProviderInfo

    async def expand(self, args: str, ctx: ExpansionContext) -> ContextBlock: ...
```

A `ProviderInfo` is the public-facing metadata (name, summary,
arg-style, optional `args_hint`); a `ContextBlock` is the expansion
output (`raw` typed form, `rendered` substituted text, optional
`error` flag for inline failure surfacing).  `ExpansionContext`
carries the runtime hooks a provider may need — currently just
`charm_path` and `repo_root`.

## Argument styles

`ArgStyle` controls how the parser consumes the text after the name.

| Style          | Example                | Consumed                   |
|----------------|------------------------|----------------------------|
| `NONE`         | `@diff`                | nothing                    |
| `TOKEN`        | `@file foo.py`         | one whitespace-delim token |
| `REST_OF_LINE` | `@docs juju secrets`   | until the next `\n`        |

A `TOKEN` provider with no token after the name receives empty `args`
and is expected to surface a friendly error (see `FileProvider`).

## Parser rules

The scanner walks the input once and never expands a mention when:

* the `@` is preceded by a non-space character (an email address
  like `tony@example.com`),
* the prefix is `@@…` (Phase 67.1 reserves `@@` for thread refs),
* the mention sits inside a fenced code block (`` ``` ``…`` ``` ``)
  or an inline code span (`` ` `…`` ` ``) — users routinely paste
  shell snippets containing `@` that aren't mention syntax,
* the name does not match any registered provider (the literal text
  is left in place so a typo reads naturally).

## Token budgets

Each provider declares its own per-call character cap; outputs longer
than the cap are truncated and a `[truncated N chars …]` footer is
appended so dropped content is honestly accounted for rather than
silently elided.  Helpers `chars_for_tokens(n)` and `truncate(...)`
in `cantrip.agent.context_providers` standardise the conversion and
the footer format.

Defaults (in chars; ~4 chars per token):

| Provider     | Cap   | Notes                                   |
|--------------|-------|-----------------------------------------|
| `@file`      | 16000 | one inlined source file                 |
| `@diff`      | 16000 | working-tree changes                    |
| `@tree`      |  8000 | repo file listing                       |
| `@problems`  |  6000 | matches `lint_context.DEFAULT_MAX_CHARS` |
| `@url`       | 12000 | webfetch markdownified body             |
| `@charm`     |  8000 | Charmhub metadata                       |
| `@preset`    |  8000 | known-good bundle shape from `cantrip.agent.presets` |
| `@juju`      |  8000 | read-only `juju` output                 |
| `@terminal`  | 16000 | last visible ``Ctrl-X`` shell-mode block |

## Tab-complete

The TUI mounts a `MentionSuggestions` widget alongside the existing
`SlashCommandSuggestions`.  Both fire from
`on_input_changed`; the mention popup uses
`_trailing_mention_prefix(value, cursor_pos)` to detect the partial
`@<word>` segment under the cursor, so completion works
mid-message — `look at @fi<Tab>` becomes `look at @file `.  Up/Down
move the highlight, Tab accepts, Escape dismisses.  The Web UI does
not yet have a parallel popup.

## Adding a new provider

1.  Implement a frozen dataclass with an `info: ProviderInfo` and an
    async `expand(args, ctx) -> ContextBlock` method.  Reuse
    `truncate(...)` for the budget footer.
2.  Register it in `build_default_registry()` if it ships baseline,
    or via `agent.context_providers.register(provider)` from a Phase
    46 hook / Phase 45 MCP server bootstrap if it's third-party.
3.  Tests: build a `ProviderRegistry`, register the new provider,
    and call `expand_mentions(text, registry, ctx)` to assert the
    expansion shape.  No need to mount a UI — the input layer is
    just an `await expand_mentions(...)` call wrapped around the
    existing message-submit flow.

## Out of scope here

* **`@docs`** ships in Phase 72.1 (indexed charm-ecosystem docs)
  once the provider-roles work in 72.3 lands.
* **`@relation <a>:<b>`** — deferred candidate (Phase 90 side-finding).
  Would expand a relation reference (e.g. `@relation
  prometheus:alertmanager`) into the interface name, provider/requirer
  roles, observed databag keys (from the watcher's cached `juju
  show-unit`), and a one-paragraph description.  The Phase 90 preset
  catalogue (`cantrip.agent.presets`) already gives the agent the
  canonical per-edge prose for the well-known bundles, which covers the
  common case — promote this to a real provider only if the agent is
  observed re-deriving databag shapes for arbitrary relations every
  turn.
* The transcript-side metadata for raw-vs-expanded message records
  is currently approximated by the multi-line fence wrappers.  A
  proper schema-level pair would be a Phase 67.1 transcript polish
  if a use case arises.
