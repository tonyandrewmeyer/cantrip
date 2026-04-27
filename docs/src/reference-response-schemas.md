---
title: "Response schemas reference — Cantrip"
description: "Built-in JSON schemas for structured LLM output, plus the validation pipeline."
h1: "Response schemas"
subtitle: "Cantrip ships JSON schemas for the recurring structured-output shapes its callers consume. Pass one to `complete_structured()` (or directly to `provider.complete(response_schema=…)`) when you want a parseable reply rather than free text."
section: reference
breadcrumb_label: "Response schemas"
on_this_page:
  - { anchor: "when-to-use", label: "When to use a schema" }
  - { anchor: "builtin", label: "Built-in schemas" }
  - { anchor: "providers", label: "Provider matrix" }
  - { anchor: "usage", label: "Calling complete_structured" }
  - { anchor: "validation", label: "Validation and retry" }
---

<h2 id="when-to-use">When to use a schema</h2>

<p>
  Pass a <code>response_schema</code> when the caller will parse the
  reply rather than show it to the user.  Recipes consume planner
  briefings.  The oracle returns a structured second opinion that
  downstream code feeds back into decision points.  Acceptance
  reports populate test matrices.  Free-form prose stays untyped
  — schemas are for data, not conversation.
</p>

<p>
  Schemas are <em>plain dicts</em> matching JSON Schema draft
  2020-12 — the same surface every supported provider already
  accepts.  No Pydantic, no attrs, no DSL.  Pass a built-in or
  hand-roll your own.
</p>

<h2 id="builtin">Built-in schemas</h2>

<p>
  Importable from <code>cantrip.llm.schemas</code>.  Resolve by name
  through <code>BUILTIN_SCHEMAS</code> for caller paths driven by
  config (recipes, settings).
</p>

<dl>
  <dt><code>PLANNER_BRIEFING</code></dt>
  <dd>
    Output of a planner LLM call: a list of work-queue tasks each
    with a <code>title</code>, a <code>category</code> (one of
    <code>research</code> / <code>build</code> / <code>deploy</code>
    / <code>test</code> / <code>debug</code> / <code>infra</code>
    / <code>confirm</code> — mirrors
    <code>cantrip.agent.queue.TaskCategory</code>), an optional
    description and dependency list.
  </dd>

  <dt><code>ORACLE_ANSWER</code></dt>
  <dd>
    Shape of an oracle reply when the caller wants more
    than free-form prose: <code>answer</code> (required), optional
    <code>confidence</code> in <code>[0, 1]</code>, and lists of
    <code>caveats</code> and <code>references</code>.
  </dd>

  <dt><code>CHECK_RESULT</code></dt>
  <dd>
    Output of a prompt-based "Check" — the LLM evaluates
    a named rule against the active charm and returns
    <code>status: pass | fail</code>, a <code>message</code>, and
    optionally <code>severity</code>, <code>evidence</code>, and a
    <code>suggested_fix</code>.
  </dd>

  <dt><code>ACCEPTANCE_REPORT</code></dt>
  <dd>
    Acceptance-test report — what the agent produces after
    exercising a deployed charm.  <code>app</code> and
    <code>overall_status</code> (<code>pass | fail | partial</code>)
    are required; <code>coverage</code> records which areas were
    exercised; <code>findings</code> is a list of issues to surface.
  </dd>
</dl>

<h2 id="providers">Provider matrix</h2>

<p>
  Native enforcement is an <em>optimisation</em> — Cantrip-side
  validation runs regardless, so providers without native support
  still satisfy the contract via the corrective-retry path.
</p>

<table>
  <thead>
    <tr>
      <th>Provider</th>
      <th>Native enforcement</th>
      <th>Wire mechanism</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Gemini</td>
      <td>Yes</td>
      <td><code>response_mime_type=application/json</code> + <code>response_schema</code></td>
    </tr>
    <tr>
      <td>OpenAI-compatible (vLLM, Fireworks, OpenRouter, inference-snap)</td>
      <td>Yes (where the backend supports it)</td>
      <td><code>response_format: {type: json_schema, json_schema: {...}}</code></td>
    </tr>
    <tr>
      <td>Anthropic Claude</td>
      <td>No</td>
      <td>Argument accepted but ignored; relies on Cantrip-side validation.</td>
    </tr>
  </tbody>
</table>

<p>
  The <code>provider.supports_response_schema</code> property
  distinguishes the two so callers that <em>require</em> native
  enforcement can short-circuit early.
</p>

<h2 id="usage">Calling <code>complete_structured</code></h2>

<p>
  The high-level entry point lives at
  <code>cantrip.llm.structured.complete_structured</code>.  It calls
  the provider with the schema, parses the reply, validates it, and
  returns a dict — or raises <code>StructuredOutputError</code> on
  unrecoverable failure.
</p>

<pre><code class="language-python">from cantrip.llm.schemas import ORACLE_ANSWER
from cantrip.llm.structured import complete_structured

answer = await complete_structured(
    provider,
    messages=[
        Message(role=Role.SYSTEM, content="You are an architecture oracle."),
        Message(role=Role.USER, content="Should this charm use Pebble or systemd?"),
    ],
    schema=ORACLE_ANSWER,
)
print(answer["answer"])           # always a string
print(answer.get("confidence"))   # optional, in [0, 1] if present
</code></pre>

<p>
  For the lower-level path, pass <code>response_schema=…</code>
  directly to <code>provider.complete()</code> and validate
  manually with
  <code>cantrip.llm.structured.validate_against_schema</code>.
  Use this when you need provider-specific kwargs (custom
  <code>thinking_budget</code>, tool choices) the helper doesn't
  expose.
</p>

<h2 id="validation">Validation and retry</h2>

<p>
  Validation strips wrapping <code>```json</code> code fences,
  parses the result with <code>json.loads</code>, and runs
  <code>jsonschema.validate</code> against the schema.  Failures
  raise <code>StructuredOutputError</code> carrying the raw text,
  the schema, and the underlying parser or validator error.
</p>

<p>
  <code>complete_structured</code> retries once by default
  (<code>retries=1</code>).  On failure it appends the malformed
  reply as an assistant turn and a corrective USER turn that quotes
  the schema and the validation error, asking the model to emit
  valid JSON.  Set <code>retries=0</code> for one-shot calls (CI),
  or higher when burning extra tokens to coax a recalcitrant model
  is acceptable.
</p>

<p>
  When all retries are exhausted, the <em>last</em> error is raised
  so the caller can surface the most recent malformed output to the
  user — earlier attempts are discarded.
</p>
