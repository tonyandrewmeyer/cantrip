---
title: "How to generate a charm icon — Cantrip"
description: "Use the Phase 70.5 Painter to generate a Charmhub-style icon.svg for a charm."
h1: "Generate a charm icon"
subtitle: "Painter — LLM-driven charm-icon generation with a session cost cap."
section: howto
breadcrumb_label: "Generate a charm icon"
see_also:
  - label: "Choose an LLM provider"
    href: "howto-provider.html"
  - label: "Search the charm library"
    href: "howto-charm-library.html"
---

{#why}
## Why a Painter?

Every charm on Charmhub ships an `icon.svg` at the project root.
It's what the Charmhub catalogue lists, what the Web UI shows beside
each application in `juju status`, and what people see on the charm's
page.  Authors today either hand-roll one in Inkscape, hire a
designer, or ship the default placeholder — most charms do the third.

The **Painter** (Phase 70.5) is Cantrip's `charm_icon_generate` tool
(plus the `/icon` slash for interactive use).  It routes a structured
prompt to an image-generation provider (Imagen by default), gets back
a square PNG, and writes it into `icon.svg` as an embedded image so
the file is one self-contained artefact ready to commit.

The honest disclaimer up-front: reliable SVG output from image models
is still weak, so the Painter rasterises and embeds rather than
vectorising.  Charmhub accepts the result and so does
`juju show-charm`, but a **designer-polish pass before release** is
recommended — replace `icon.svg` with a true vector once the visual
language is settled.

{#tools}
## What's available

| Surface | Use it for |
|---|---|
| `/icon <description>` | Interactive: paint a fresh icon for the active charm. |
| `charm_icon_generate` agent tool | Programmatic: the agent calls it during a BUILD phase, or you can `/run charm_icon_generate ...`. |
| `generate_icon` (existing, Phase 7) | Deterministic placeholder — coloured circle with the charm's initial.  Shipped before Painter; still the right call when no image-provider API key is configured. |

The Painter and the placeholder coexist intentionally: the
deterministic placeholder is fast, free, and offline-friendly; the
Painter is more interesting but costs money and needs an API key.

{#use-it}
## Use it from the chat

In an active session with a charm path set:

<pre><code><span class="prompt">cantrip&gt;</span> /icon a Postgres database operator</code></pre>

The Painter prefixes a Charmhub style block to your description (square,
flat, simple, legible at 32×32, no embedded text), calls the image
provider, and writes the result.  A typical reply:

```
Generated icon.svg for 'myapp' at /home/me/charms/myapp/icon.svg.
- model: gemini/imagen-3.0-generate-002
- cost: ≈ $0.0400 (session ≈ $0.0400 of $1.00 cap)
- format: PNG embedded in SVG; designer-polish recommended before release.
```

{#cost}
## Cost cap

Iterating on an icon is fun but pricey: at $0.04 per Imagen call, ten
attempts is forty cents.  The Painter enforces a per-session cap via
`state.icon_max_session_cost_usd` (default `$1.00` — about 25
attempts).  When the cap trips, further calls return a tool error
naming the spent amount and the cap; raise the cap by setting
`state.icon_max_session_cost_usd` from a slash command or in code.

There is no per-turn cap (icons aren't easy to spam from one user
message); the session cap alone is enough.

{#overwrite}
## Refusal to overwrite real artwork

The tool **refuses** to overwrite an existing `icon.svg` unless one of:

- The file carries the `cantrip-icon-generated` marker comment we
  embed on every Painter output (so successive `/icon` calls iterate
  freely on a Painter-generated icon);
- The file matches the deterministic placeholder shape from the
  Phase 7 `generate_icon` tool (a coloured `<circle>` at 128, 128); or
- You pass `force=true` (or call `charm_icon_generate force=true`).

Anything else — your own SVG, a designer's work, an existing
Inkscape file — is treated as expensive human output and left alone.

{#provider}
## Switching providers

The defaults (`gemini` / `imagen-3.0-generate-002`) are settable per
session via:

- `state.icon_provider_name` — short name; today only `gemini` is
  supported, but the abstraction in `cantrip.llm.image` accepts
  additional implementations.
- `state.icon_model` — provider-specific model name.

API key resolution mirrors the text Gemini provider: `GEMINI_API_KEY`
or `GOOGLE_API_KEY`.  Without one of those set, the Painter returns a
clean "image provider not configured" error rather than crashing.

{#format}
## What the SVG actually contains

A Painter-generated `icon.svg` is a small XML document wrapping a
base64-encoded PNG:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- cantrip-icon-generated: charm=myapp; raster — designer-polish recommended before release -->
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <image x="0" y="0" width="256" height="256" href="data:image/png;base64,iVBORw0KGgo..." />
</svg>
```

Charmhub accepts this format; so does any SVG-aware viewer.  When you
move on to a true vector icon, drop your replacement into the same
path and the Painter's refusal logic protects it from the next
iteration.

{#deferred}
## Known gaps

The MVP deliberately defers a few things:

- **Reference-image input** (up to three reference PNGs to anchor the
  visual language) — the abstraction supports it but the prompt path
  doesn't yet.
- **True vectorisation via potrace** — embedded PNG is honest about
  what's actually happening; a follow-up can add a `--vectorise` path
  once the dependency cost is acceptable.
- **Auto-invocation at BUILD completion** — the agent will call
  `charm_icon_generate` mid-build today, but there's no
  end-of-build CONFIRM that asks "want to paint an icon now?" yet.
  Tracked as a follow-up under Phase 64 (CONFIRM tasks).
