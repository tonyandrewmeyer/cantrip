# Docs rebuild — reverse-engineering `docs/docs/` to markdown

**Status:** active (Phase 54).
**Scope:** restore authored-markdown sources for `docs/docs/*.html` so the
Diátaxis site can evolve alongside the code without hand-editing HTML.
This is a reverse-engineering job — no surviving markdown or SSG config
exists in the tree.

## Why not pandoc / MkDocs-Material / markdownify

- **pandoc** is not installed in the development environment and pulls in
  Haskell runtime; heavy for what the docs need.
- **MkDocs-Material** is a heavyweight SSG with its own CSS. The current
  site has hand-crafted CSS (`docs.css`, `../tokens.css`) that matches the
  landing page (`docs/index.html`). Adopting Material would fight the
  existing design and is out of scope per the ROADMAP's note to resist the
  pull toward a heavyweight SSG.
- **One-shot `markdownify`** would produce working markdown for prose but
  can't round-trip inline `<span class="prompt">` / `<span class="comment">`
  spans inside `<pre><code>` blocks, and would duplicate the shared chrome
  (nav / sidebar / footer) into every page's markdown source. That bloats
  every file and breaks the "edit markdown, rebuild HTML" promise.

## Chosen stack

Zero new dependencies — the project already has everything needed:

- **`markdown-it-py`** (4.0.0) — CommonMark parser, pulled in transitively.
- **`mdit_py_plugins.attrs`** — `attrs_block_plugin` gives us
  `{#anchor-id}` on headings, so `## Formats {#formats}` renders
  `<h2 id="formats">`.
- **`Jinja2`** (3.1.6) — page chrome (nav / sidebar / footer / head).
- **`PyYAML`** (6.0.3) — frontmatter.

The build script (`docs/src/_build.py`) is pure-Python and small. A
`make docs` target wraps it. CI diffs the freshly built HTML against the
committed `docs/docs/*.html` to catch drift.

## File layout

```
docs/
├── index.html                (landing page — out of scope for this phase)
├── style.css tokens.css      (shared design tokens)
├── favicon.png logo-*.png
├── docs/                     (build artifacts — stay committed)
│   ├── docs.css
│   ├── index.html
│   ├── tutorial.html
│   ├── howto-*.html
│   ├── reference-*.html
│   └── explanation-*.html
└── src/                      (authored sources — new)
    ├── _build.py             (markdown + frontmatter → HTML via Jinja2)
    ├── _site.yaml            (global: section nav, page order)
    ├── _templates/
    │   └── page.html.j2      (single chrome template, branches on section)
    ├── index.md
    ├── tutorial.md
    ├── howto-*.md
    ├── reference-*.md
    └── explanation-*.md
```

## Frontmatter schema

Every page begins with YAML frontmatter:

```yaml
---
title: "How to export transcripts — Cantrip"
description: "Export Cantrip session transcripts as HTML, Markdown, or JSONL."
h1: "Export transcripts"
subtitle: "Export a session's conversation history and task log for documentation, review, or analysis."
section: howto          # tutorial | howto | reference | explanation | index
breadcrumb_label: "Export transcripts"
see_also:               # optional; omit if the page has no "See also" block
  - label: "CLI reference"
    href: "reference-cli.html"
on_this_page:           # optional; reference & explanation pages use it
  - { anchor: "formats", label: "Formats" }
---
```

Fields:
- `title` → `<title>…</title>` and `<meta name="description">` pair.
- `h1` + `subtitle` → the page heading block under the breadcrumb.
- `section` → picks the sidebar section-nav block and the breadcrumb label
  (`howto` → "How-to guides", `reference` → "Reference", etc.).
- `breadcrumb_label` → the leaf label in the breadcrumb trail.
- `see_also` → optional; renders the "See also" sidebar block.
- `on_this_page` → optional; renders "On this page" anchor list (section
  pages that have long TOCs: reference-cli, reference-tools, most
  explanation pages, tutorial).

The primary section-nav list (e.g. all how-to pages with `current` on the
active one) is derived automatically from `_site.yaml` — authors don't
maintain it by hand.

## Manual-reconciliation rules

The following patterns use **raw HTML inside markdown** rather than
CommonMark:

1. **Callouts** — `<div class="callout">…</div>` and
   `<div class="callout-warn callout">…</div>`. These are small and
   lossless; no CommonMark extension round-trips them byte-identical.

2. **Prompt-styled code blocks** (7 pages) — use raw
   `<pre><code>$ command<span class="comment"># note</span></code></pre>`
   instead of a fenced code block when `<span class="prompt">` /
   `<span class="comment">` / `<span class="dim">` styling is needed.
   Ordinary code (no prompts) uses fenced blocks.

3. **Definition lists** (reference-cli, explanation-race) — write as raw
   `<dl><dt>…</dt><dd>…</dd></dl>`. CommonMark has no dl syntax, and
   PHP-markdown-extra dl syntax isn't supported by markdown-it-py by
   default.

4. **Landing-page cards** (`docs/index.md`) — `<div class="doc-cards">`
   with `<a class="doc-card">` children, raw HTML. One page; not worth a
   custom directive.

Everything else (headings, lists, tables, paragraphs, inline code, links,
emphasis, blockquotes) is plain CommonMark. Anchor IDs on headings use
the `attrs_block` extension: `## Formats {#formats}`.

## Entity handling

The HTML uses a handful of character entities: `&mdash; &amp; &lt; &gt;
&quot; &apos; &ldquo; &rdquo; &rsquo; &hellip; &rarr; &le; &ge; &ne;
&nbsp; &ndash; &times;`.

The markdown sources use the **Unicode characters** directly
(—, “, ”, →, ≤, ≥, ≠, …). The build emits them as UTF-8; a
post-processor then rewrites them to the original HTML-entity form so
the diff against the committed HTML is clean. Entity map lives in
`_build.py`.

## Build behaviour

- `uv run python docs/src/_build.py` — rebuilds every page into
  `docs/docs/`.
- `uv run python docs/src/_build.py --check` — builds to a temporary
  directory and DOM-structurally diffs against the committed HTML.
  Non-zero exit on content drift.
- `uv run python docs/src/_build.py --check --strict` — byte-for-byte
  diff. Only meaningful once the committed HTML has been regenerated
  from markdown (Phase 54.2).
- `make docs` — wraps the build; `make docs-check` — wraps the
  semantic check.

## The diff strategy: semantic DOM, not byte-for-byte

The pilot (`howto-export.html`) confirmed that byte-for-byte round-trip
against the hand-authored HTML is infeasible — the author wrapped
paragraphs at ~70 columns and indented nested tags 6 spaces deep, while
markdown-it-py emits compact flush-left blocks with no inter-block blank
lines. Both render identically in a browser, but a raw textual diff
shows differences on every paragraph.

The build script therefore has two check modes:

1. **Semantic** (default) — parse both HTML documents, flatten to a
   sequence of `(tag, attrs, text)` events with whitespace-normalised
   text and entity-resolved character references (so `&mdash;` and `—`
   compare equal), and compare the sequences. This catches any actual
   content, attribute, or structure change.
2. **Strict** — literal byte-for-byte. Only useful once the committed
   HTML is itself build output (post-54.2), because then drift between
   `make docs` and the committed HTML really is a red flag.

Through 54.2 the semantic check is authoritative. After 54.4 retires
hand-authored HTML, the strict check becomes CI-gated.

## Intentional normalisations

Cases where the rebuilt HTML deliberately differs from the hand-authored
original (and the committed file is overwritten with the rebuild):

- **`howto-hooks.html` footer** — the page had a bespoke footer
  (`<strong>Cantrip</strong> — autonomous charm builder.`) while every
  other page used the shared footer
  (`Cantrip — free & open source`). Normalised to the shared form.
- **`&mdash;` in `<title>` tags** — several pages used literal
  Unicode `—` in the title while the body used `&mdash;`. Normalised
  to `&mdash;` everywhere.
- **Possessive apostrophes** — the hand-authored pages mix `&apos;`
  (ASCII) and `&rsquo;` (curly) for possessives. The markdown source
  uses the original form per-occurrence, but the default in future
  authoring is the curly `’`.

## Authoring patterns

Lessons from converting the how-to section that future authors should
follow:

- **Curly quotes in prose** use Unicode `“ ” ‘ ’` directly.
  `&ldquo;` / `&rdquo;` round-trip through `convert_charrefs=True` to
  the same character.
- **ASCII apostrophes inside prose** (`Fear's`) are preserved as ASCII
  `'`. Write them literally; the build doesn't touch ASCII
  apostrophes. Curly `’` for possessives is also fine, just pick one
  per document.
- **Inline `<code>` containing an entity** (e.g.
  `<code>&nbsp;--&nbsp;</code>`) must be written as raw HTML, not a
  backtick span — markdown-it escapes `&` inside a code span to
  `&amp;` and the entity stops being one.
- **External links** automatically get `target="_blank"
  rel="noopener"` added by the build, so the author writes plain
  `[label](https://…)`.

## Pilot findings (howto-export.html)

- Zero semantic-DOM differences between the rebuilt HTML and the
  committed `docs/docs/howto-export.html` — every tag, attribute, text
  node, and character reference matches after normalisation.
- `mdit_py_plugins.attrs.attrs_block_plugin` attaches `id="…"` when the
  attrs block sits on a line *above* the heading, not after it. All
  heading anchors use this form:
  ```
  {#mid-session}
  ## Export mid-session with `/export`
  ```
- Raw `<pre><code>` blocks in the markdown source survive markdown-it
  untouched (CommonMark's "HTML block" rule) and preserve
  `<span class="prompt">` / `<span class="comment">` styling verbatim.
- Tables emit flush-left with no indentation — not a content change.
- The title originally used Unicode `—` while the body used `&mdash;`.
  The entity rewriter normalises both to `&mdash;`; minor hand-authoring
  inconsistency folded out.
- One quirk of `html.parser`: entity references (`&mdash;` etc.) appear
  as separate text events from surrounding plain text. The DOM flatten
  pass coalesces adjacent text events so the comparison isn't
  position-sensitive to entity placement.

## Hosting model

`docs/docs/*.html` stays committed. The repo is the source of truth
for the published site: `README.md` and `CLAUDE.md` link into pages
via repo-relative paths like `docs/docs/howto-memory.html`, and the
GitHub-rendered version of those links relies on the HTML being
present at that path on `main`. Moving the HTML to CI-only would
silently break every cross-link.

The authored markdown under `docs/src/` is the true source — the
HTML is a build artifact committed for hosting convenience. Drift
is prevented by `make docs-check-strict` in CI, which rebuilds from
markdown into a temp dir and fails if the output differs from the
committed HTML byte-for-byte.

## Phase milestones mapped

- **54.1** — this document + pilot round-trip on one page.
- **54.2** — convert all 19 pages using the patterns above.
- **54.3** — land `make docs`, wire into CI as the `Docs` job.
- **54.4** — resolve the hosting question (keep committed),
  document the authoring loop in `CONTRIBUTING.md`, confirm the
  full-tree strict check is clean.
