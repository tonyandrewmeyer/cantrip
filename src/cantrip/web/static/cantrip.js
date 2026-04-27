/* Cantrip Web UI — WebSocket client, Markdown rendering, and DOM updates. */

const cantrip = (() => {
  "use strict";

  let ws = null;
  let reconnectDelay = 1000;
  let port = 8471;
  let statusPollTimer = null;
  let historyLoaded = false;

  // Spellcasting-themed labels for the "thinking" indicator.  Kept in
  // lockstep with ``cantrip.ui.flavour.think_pool()`` on the Python
  // side; a unit test (``tests/unit/test_ui_flavour.py``) diffs the
  // two lists so drift fails the build rather than silently
  // desynchronising the TUI and Web UIs.
  const FLAVOUR_POOL = [
    "Incanting",
    "Invoking",
    "Conjuring",
    "Weaving the pattern",
    "Chanting softly",
    "Channelling",
    "Enchanting",
    "Murmuring to the circle",
    "Consulting the oracle",
    "Thumbing the grimoire",
    "Tracing sigils",
    "Drawing the pentagram",
    "Stirring the cauldron",
    "Threading the runes",
    "Whispering to the familiar",
    "Parting the veil",
    "Pondering the arcane",
    "Unrolling the scroll",
    "Checking the almanac",
    "Rifling through the spellbook",
    "Shuffling the tarot",
    "Lighting the candles",
    "Polishing the crystal",
    "Tuning the lute",
    "Counting the motes",
    "Casting bones on the table",
  ];

  function pickFlavourLabel() {
    const idx = Math.floor(Math.random() * FLAVOUR_POOL.length);
    return FLAVOUR_POOL[idx];
  }

  // ── DOM references ──────────────────────────────────────────────
  const chatMessages = () => document.getElementById("chat-messages");
  const chatInput = () => document.getElementById("chat-input");
  const chatForm = () => document.getElementById("chat-form");
  const taskList = () => document.getElementById("task-list");
  const thinkingEl = () => document.getElementById("thinking-indicator");
  const statusDot = () => document.getElementById("connection-status");
  const jujuApps = () => document.getElementById("juju-apps");
  const helpOverlay = () => document.getElementById("help-overlay");
  const logsOverlay = () => document.getElementById("logs-overlay");
  const logsOutput = () => document.getElementById("logs-output");
  const graphOverlay = () => document.getElementById("graph-overlay");
  const graphView = () => document.getElementById("graph-view");

  // ── WebSocket connection ────────────────────────────────────────

  function connect(wsPort) {
    port = wsPort || port;
    _openSocket();

    // Wire up the chat form.
    chatForm().addEventListener("submit", (e) => {
      e.preventDefault();
      const input = chatInput();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      _autoResizeChatInput();
      // Echo the user's message immediately — the server doesn't
      // broadcast it back, so without the echo the chat sits silent
      // until the assistant reply arrives.  Slash commands do come
      // back via ``_broadcast_chat``; those cases naturally appear
      // in addition to this eager echo.
      _echoUserMessage(text);
      _send("chat_input", { content: text });
    });

    function _echoUserMessage(text) {
      // Use the server-side renderer's output shape (pre-rendered
      // HTML + ISO timestamp) so the echoed row matches a real
      // server-sent message visually.
      const ts = new Date().toISOString();
      // Simple client-side render: since the user just typed it,
      // the content is trusted text — escape-and-paragraph it so
      // it lines up with server-rendered output.
      const html = `<p>${_esc(text).replace(/\n/g, "<br>")}</p>`;
      appendMessage("user", text, html, ts);
    }

    // Multiline input: Enter submits, Shift+Enter inserts a newline.
    // Without this every Enter keypress would just drop a newline in
    // the textarea — fine for long-form text, lousy for fast chat.
    const input = chatInput();
    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          chatForm().requestSubmit();
        }
      });
      // Auto-grow the textarea to fit its content, capped so it can't
      // eat the entire panel.
      input.addEventListener("input", _autoResizeChatInput);
    }

    // Keyboard shortcuts.
    document.addEventListener("keydown", _handleKeyDown);

    // Click on overlay backdrop closes the overlay via the dialog helpers
    // so focus restoration and inert both clear correctly.
    for (const key of Object.keys(_OVERLAYS)) {
      const overlay = document.getElementById(_OVERLAYS[key].overlayId);
      if (!overlay) continue;
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) _closeOverlay(key);
      });
    }

    // Poll Juju status every 15 seconds.
    _fetchJujuStatus();
    statusPollTimer = setInterval(_fetchJujuStatus, 15000);

    // Show the scroll-to-bottom button only when the user has
    // scrolled up; hide it again once they're near the latest row.
    const scroller = chatMessages();
    if (scroller) {
      scroller.addEventListener("scroll", _updateScrollBottomButton);
      _updateScrollBottomButton();
    }
  }

  function _openSocket() {
    const url = `ws://${location.hostname || "127.0.0.1"}:${port}/ws`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      reconnectDelay = 1000;
      _setStatus("connected");
      _fetchState();
      if (!historyLoaded) {
        historyLoaded = true;
        _fetchMessages();
        _fetchSessionPreview();
        _fetchUpdateStatus();
      }
    };

    ws.onclose = () => {
      _setStatus("reconnecting");
      setTimeout(_openSocket, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    };

    ws.onerror = () => { _setStatus("disconnected"); };

    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      _dispatch(msg);
    };
  }

  function _send(type, data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type, data }));
    }
  }

  function _setStatus(state) {
    const dot = statusDot();
    if (!dot) return;
    dot.className = "status-dot " + state;
    const label = state.charAt(0).toUpperCase() + state.slice(1);
    dot.title = label;
    dot.setAttribute("aria-label", label);
  }

  // ── Message dispatcher ──────────────────────────────────────────

  function _dispatch(msg) {
    switch (msg.type) {
      case "chat_message":
        appendMessage(
          msg.data.role, msg.data.content, msg.data.html, msg.data.timestamp,
          msg.data.reasoning,
        );
        break;
      case "task_updated":
        updateTask(msg.data);
        break;
      case "tasks_full":
        replaceAllTasks(msg.data);
        break;
      case "thinking":
        setThinking(msg.data.active);
        break;
      case "memory_written":
        appendMessage(
          "system",
          `Wrote ${msg.data.kind} memory: ${msg.data.title} (${msg.data.scope})`,
          "",
          new Date().toISOString(),
        );
        break;
      case "memory_recalled":
        appendMessage(
          "system",
          `Recalled memory: ${msg.data.title} (${msg.data.scope})`,
          "",
          new Date().toISOString(),
        );
        break;
      case "update_available":
        _renderUpdateBanner(msg.data && msg.data.info);
        break;
      case "preflight_started":
        _preflightStarted(msg.data && msg.data.checks);
        break;
      case "preflight_updated":
        _preflightUpdated(msg.data);
        break;
      case "preflight_complete":
        _preflightComplete();
        break;
      case "preflight_failed":
        _preflightFailed(msg.data && msg.data.error);
        break;
      case "status_bar_changed":
        _handleStatusBarChanged(msg.data || {});
        break;
      case "tool_invoked":
        // Phase 75: render a compact tool block so the user can see
        // what the agent just did between "Let me check the file:"
        // and the agent's next narrative message.  Phase 82: when a
        // matching pending block is on screen, the helper updates it
        // in place rather than appending a new line.
        appendToolBlock(msg.data || {});
        break;
      case "tool_invoked_pending":
        // Phase 82: render the "running now" block immediately so
        // slow tools (charmcraft_pack, juju_wait, web_fetch) don't
        // leave the chat staring at silence between the agent's last
        // line and the tool's eventual completion.
        appendPendingToolBlock(msg.data || {});
        break;
      case "cache_metrics_updated":
        // Phase 78.2: keep the header cache indicator in sync with
        // the TUI modelbar's ``cache: X% hit`` readout.
        _updateCacheMetrics(msg.data || {});
        break;
    }
  }

  function _updateCacheMetrics(data) {
    const el = document.getElementById("cache-indicator");
    if (!el) return;
    const total = data.cache_total_tokens || 0;
    if (total <= 0) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    const pct = Math.round(data.hit_pct || 0);
    el.hidden = false;
    el.textContent = `cache: ${pct}% hit`;
    el.title =
      `${data.cache_read_tokens.toLocaleString()} read / ` +
      `${data.cache_creation_tokens.toLocaleString()} created`;
    el.setAttribute("aria-label", `Prompt cache ${pct}% hit`);
  }

  // Status-bar activity updates come from the agent's event bus via
  // ``_publish_activity``.  ``task_label`` carries strings like
  // ``⟳ running: charmcraft_pack`` between tool calls, letting the
  // thinking indicator show what the agent is actually doing rather
  // than a generic "Incanting...".  Empty ``task_label`` means the
  // activity has ended — revert to the flavour pool on the next
  // ``thinking`` event.
  function _handleStatusBarChanged(data) {
    if (data.task_label === undefined) return;
    _setThinkingLabel(data.task_label);
    const footer = document.getElementById("status-label");
    if (footer) footer.textContent = data.task_label || "";
  }

  function _setThinkingLabel(label) {
    const el = thinkingEl();
    if (!el || el.hidden) return;
    const labelEl = document.getElementById("thinking-label");
    if (!labelEl) return;
    labelEl.textContent = label ? ` ${label}` : ` ${pickFlavourLabel()}…`;
  }

  // ── Preflight panel (Phase 31.13) ───────────────────────────────
  //
  // Mirrors the TUI's ``#task-checklist`` preflight group: five
  // fixed rows (Concierge, Environment, Juju CLI, Controller, COS)
  // that animate from ○ pending → ⟳ running → ✓ passed / ✗ failed
  // / ◌ skipped.  Panel stays visible until every row has settled;
  // we hide it after a short grace period so the user has time to
  // read the final state.

  const _PREFLIGHT_LABELS = {
    concierge: "Concierge",
    prepare: "Environment",
    juju: "Juju CLI",
    controller: "Controller",
    cos: "COS",
    snap_install: "Snap install",
    bootstrap: "Bootstrap",
  };
  let _preflightHideTimer = null;

  function _preflightStarted(checks) {
    const panel = document.getElementById("preflight-panel");
    const list = document.getElementById("preflight-list");
    if (!panel || !list) return;
    if (_preflightHideTimer) { clearTimeout(_preflightHideTimer); _preflightHideTimer = null; }
    list.innerHTML = "";
    const names = Array.isArray(checks) && checks.length
      ? checks
      : ["concierge", "prepare", "juju", "controller", "cos"];
    for (const name of names) {
      const li = document.createElement("li");
      li.className = "preflight-row preflight-pending";
      li.dataset.check = name;
      li.innerHTML =
        `<span class="preflight-icon" aria-hidden="true"></span>` +
        `<span class="preflight-label">${_esc(_PREFLIGHT_LABELS[name] || name)}</span>` +
        `<span class="preflight-msg"></span>`;
      list.appendChild(li);
    }
    panel.hidden = false;
  }

  function _preflightUpdated(data) {
    const list = document.getElementById("preflight-list");
    if (!list || !data) return;
    let row = list.querySelector(`[data-check="${CSS.escape(data.check_name)}"]`);
    if (!row) {
      // Check wasn't in the pre-rendered list (e.g. snap_install on a
      // warm_up path) — append it live so the UI still reflects reality.
      row = document.createElement("li");
      row.className = "preflight-row preflight-pending";
      row.dataset.check = data.check_name;
      row.innerHTML =
        `<span class="preflight-icon" aria-hidden="true"></span>` +
        `<span class="preflight-label">${_esc(data.label || data.check_name)}</span>` +
        `<span class="preflight-msg"></span>`;
      list.appendChild(row);
    }
    row.className = `preflight-row preflight-${data.status}`;
    const msg = row.querySelector(".preflight-msg");
    if (msg) msg.textContent = data.message || "";
  }

  function _preflightComplete() {
    // Fade out after a grace period so users can see the final state.
    if (_preflightHideTimer) clearTimeout(_preflightHideTimer);
    _preflightHideTimer = setTimeout(() => {
      const panel = document.getElementById("preflight-panel");
      if (panel) panel.hidden = true;
    }, 4000);
  }

  function _preflightFailed(error) {
    const list = document.getElementById("preflight-list");
    if (!list) return;
    const row = document.createElement("li");
    row.className = "preflight-row preflight-failed";
    row.innerHTML =
      `<span class="preflight-icon" aria-hidden="true"></span>` +
      `<span class="preflight-label">Preflight</span>` +
      `<span class="preflight-msg">${_esc(error || "failed")}</span>`;
    list.appendChild(row);
  }

  // ── Chat rendering ──────────────────────────────────────────────
  //
  // Markdown is rendered server-side by ``cantrip.web.markdown`` — the
  // server sends both ``content`` (the raw text, useful for
  // accessibility tooling) and ``html`` (the rendered HTML).  We
  // ``innerHTML`` the HTML directly; the server disables raw HTML in
  // its renderer so ``<script>`` etc. arrive as escaped text.  When
  // the HTML field is missing (older server, system-generated local
  // messages) we fall back to ``textContent`` to stay XSS-safe.

  function appendMessage(role, content, html, timestamp, reasoning) {
    const container = chatMessages();
    if (!container) return;
    // First real message hides the welcome placeholder.
    const empty = document.getElementById("chat-empty");
    if (empty) empty.remove();

    const div = document.createElement("div");
    div.className = `msg msg-${role}`;

    const header = document.createElement("div");
    header.className = "msg-header";

    const roleLabel = document.createElement("span");
    roleLabel.className = "msg-role";
    roleLabel.textContent = role;
    header.appendChild(roleLabel);

    if (timestamp) {
      const time = document.createElement("time");
      time.className = "msg-time";
      time.dateTime = timestamp;
      time.textContent = _formatTimestamp(timestamp);
      time.title = new Date(timestamp).toLocaleString();
      header.appendChild(time);
    }

    div.appendChild(header);

    // Reasoning (Claude extended thinking, Kimi K2 reasoning_content)
    // renders as a collapsible block above the answer so the user can
    // tell when a turn spent budget on thinking.
    if (reasoning) {
      const details = document.createElement("details");
      details.className = "msg-reasoning";
      const summary = document.createElement("summary");
      summary.textContent = "💭 thinking";
      details.appendChild(summary);
      const body = document.createElement("div");
      body.className = "msg-reasoning-body";
      body.textContent = reasoning;
      details.appendChild(body);
      div.appendChild(details);
    }

    const body = document.createElement("div");
    body.className = "msg-body";
    if (html) {
      body.innerHTML = html;
    } else {
      body.textContent = content;
    }
    div.appendChild(body);

    // Only auto-scroll if the user is already near the bottom;
    // otherwise leave them where they are (the scroll-to-bottom
    // button will appear so they know there's new content below).
    const wasAtBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight
        < _SCROLL_BOTTOM_THRESHOLD;
    container.appendChild(div);
    if (wasAtBottom) container.scrollTop = container.scrollHeight;
    _updateScrollBottomButton();
  }

  // Phase 75: render a tool-invocation block in the chat stream.
  // Mirrors the TUI ``ToolBlockWidget``: compact single line, accent
  // border on success, error border on failure, caption prefixed
  // with a glyph.  Duration shown only when it crosses the
  // attention threshold (500 ms) so fast calls don't clutter the
  // chat.
  const _TOOL_BLOCK_DURATION_THRESHOLD_MS = 500;

  // Phase 82: tool-call-id → pending DOM div, so a later TOOL_INVOKED
  // event with the same id replaces the spinner caption in place
  // rather than appending a duplicate line.
  const _pendingToolBlocks = new Map();

  function _renderToolBlockBody(div, data) {
    const success = Boolean(data.success);
    const glyph = success ? "🔧" : "✗";
    const caption = data.caption || data.tool_name || "(tool)";

    div.className = "msg msg-tool";
    if (!success) div.classList.add("msg-tool-failed");

    const body = document.createElement("div");
    body.className = "msg-body";

    const text = document.createElement("span");
    text.textContent = `${glyph} ${caption}`;
    body.appendChild(text);

    const duration = Number(data.duration_ms);
    if (Number.isFinite(duration) && duration >= _TOOL_BLOCK_DURATION_THRESHOLD_MS) {
      const suffix = document.createElement("span");
      suffix.className = "msg-time";
      suffix.textContent = ` (${duration} ms)`;
      body.appendChild(suffix);
    }

    // Replace existing children — used when updating a pending block.
    div.replaceChildren(body);
  }

  function appendToolBlock(data) {
    const container = chatMessages();
    if (!container) return;
    const empty = document.getElementById("chat-empty");
    if (empty) empty.remove();

    const tcid = data.tool_call_id;
    // Phase 82: when a pending block exists for this id, update it
    // in place instead of appending a fresh line.
    if (tcid && _pendingToolBlocks.has(tcid)) {
      const div = _pendingToolBlocks.get(tcid);
      _pendingToolBlocks.delete(tcid);
      _renderToolBlockBody(div, data);
      _updateScrollBottomButton();
      return;
    }

    const div = document.createElement("div");
    _renderToolBlockBody(div, data);

    const wasAtBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight
        < _SCROLL_BOTTOM_THRESHOLD;
    container.appendChild(div);
    if (wasAtBottom) container.scrollTop = container.scrollHeight;
    _updateScrollBottomButton();
  }

  // Phase 82: render the pre-call "running now" block.  Tagged with
  // a ``msg-tool-pending`` class so CSS can dim it / show a
  // spinner glyph; the matching TOOL_INVOKED event swaps the body
  // out via ``appendToolBlock`` above.
  function appendPendingToolBlock(data) {
    const container = chatMessages();
    if (!container) return;
    const tcid = data.tool_call_id;
    if (!tcid || _pendingToolBlocks.has(tcid)) return;
    const empty = document.getElementById("chat-empty");
    if (empty) empty.remove();

    const caption = data.caption || data.tool_name || "(running)";

    const div = document.createElement("div");
    div.className = "msg msg-tool msg-tool-pending";

    const body = document.createElement("div");
    body.className = "msg-body";

    const text = document.createElement("span");
    text.textContent = `⟳ ${caption}`;
    body.appendChild(text);

    div.appendChild(body);

    const wasAtBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight
        < _SCROLL_BOTTOM_THRESHOLD;
    container.appendChild(div);
    _pendingToolBlocks.set(tcid, div);
    if (wasAtBottom) container.scrollTop = container.scrollHeight;
    _updateScrollBottomButton();
  }

  // Phase 82: convert any orphan pending blocks (e.g. cancelled mid-
  // tool, server crash) into failed tool blocks so the chat never
  // leaves a dangling spinner.  Called when the thinking indicator
  // turns off — the turn has ended and any unresolved pending event
  // can no longer expect a matching final.
  function scrubPendingToolBlocks() {
    if (_pendingToolBlocks.size === 0) return;
    for (const [tcid, div] of _pendingToolBlocks) {
      _renderToolBlockBody(div, {
        success: false,
        caption: "cancelled",
        tool_call_id: tcid,
      });
    }
    _pendingToolBlocks.clear();
  }

  // Format an ISO timestamp as HH:MM in the browser's locale.  Falls
  // back to the raw string when Date parsing fails so a malformed
  // stamp doesn't break the chat layout.
  function _formatTimestamp(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function setThinking(active) {
    const el = thinkingEl();
    if (!el) return;
    if (active) {
      // Write into the dedicated label span so the cancel button
      // and animated dots aren't disturbed.  A fresh flavour is
      // picked each time the indicator switches on, matching the
      // TUI's per-phase re-roll cadence.
      const label = document.getElementById("thinking-label");
      if (label) label.textContent = ` ${pickFlavourLabel()}…`;
    } else {
      // Phase 82: turn ended — any pending tool block that never got
      // its matching TOOL_INVOKED becomes a failed "cancelled" block
      // so the chat never leaves a dangling spinner.
      scrubPendingToolBlocks();
    }
    el.hidden = !active;
  }

  // ── Task rendering ──────────────────────────────────────────────

  function updateTask(data) {
    const list = taskList();
    if (!list) return;

    const empty = list.querySelector(".task-empty");
    if (empty) empty.remove();

    let el = document.getElementById(`task-${data.id}`);
    const wt = data.worktree_path || "";
    if (el) {
      el.className = `task task-${data.status}`;
      el.querySelector(".task-title").textContent = data.title;
      el.querySelector(".task-badge").textContent = data.category;
      const wtEl = el.querySelector(".task-worktree");
      if (wt) {
        if (wtEl) {
          wtEl.textContent = `worktree: ${wt}`;
        } else {
          const span = document.createElement("span");
          span.className = "task-worktree";
          span.textContent = `worktree: ${wt}`;
          el.appendChild(span);
        }
      } else if (wtEl) {
        wtEl.remove();
      }
    } else {
      el = document.createElement("div");
      el.id = `task-${data.id}`;
      el.className = `task task-${data.status}`;
      el.dataset.category = data.category;
      el.innerHTML =
        '<span class="task-icon"></span>' +
        `<span class="task-title">${_esc(data.title)}</span>` +
        `<span class="task-badge">${_esc(data.category)}</span>` +
        (wt ? `<span class="task-worktree">worktree: ${_esc(wt)}</span>` : "");
      list.appendChild(el);
    }
  }

  function replaceAllTasks(tasks) {
    const list = taskList();
    if (!list) return;
    list.innerHTML = "";
    if (!tasks || tasks.length === 0) {
      list.innerHTML = '<div class="task-empty">No tasks yet.</div>';
      return;
    }
    tasks.forEach(updateTask);
  }

  // ── Juju status rendering ──────────────────────────────────────

  async function _fetchJujuStatus() {
    try {
      const resp = await fetch("/api/juju-status");
      if (!resp.ok) return;
      const data = await resp.json();
      _renderJujuStatus(data);
    } catch { /* ignore */ }
  }

  function _renderJujuStatus(data) {
    const container = jujuApps();
    if (!container) return;

    const apps = data.apps || {};
    const appNames = Object.keys(apps);

    if (appNames.length === 0) {
      container.innerHTML = '<div class="juju-empty">No model connected.</div>';
      return;
    }

    container.innerHTML = "";
    for (const name of appNames.sort()) {
      const app = apps[name];
      const div = document.createElement("div");
      div.className = `juju-app status-${app.status}`;

      const unitCount = Object.keys(app.units || {}).length;
      const statusIcon = { active: "●", waiting: "○", blocked: "◌", error: "✗" }[app.status] || "○";

      // Full message goes into ``title`` so hover shows the whole
      // thing; CSS truncates the visible line with an ellipsis so
      // one chatty status message doesn't blow up the card layout.
      const fullMessage = app.message ? `${app.status}: ${app.message}` : app.status;
      div.innerHTML =
        `<div class="juju-app-name">${_esc(name)}</div>` +
        `<div class="juju-app-status" title="${_esc(fullMessage)}">${statusIcon} ${_esc(app.status)}` +
        (app.message ? `: <span class="juju-app-msg">${_esc(app.message)}</span>` : "") + `</div>` +
        `<div class="juju-app-units">${unitCount} unit${unitCount !== 1 ? "s" : ""}</div>`;

      container.appendChild(div);
    }
  }

  // ── Overlays (dialogs with focus management) ────────────────────

  // Each overlay pairs with its trigger button and an optional onOpen hook.
  const _OVERLAYS = {
    help:  { overlayId: "help-overlay",  triggerId: "btn-help",  onOpen: null },
    logs:  { overlayId: "logs-overlay",  triggerId: "btn-logs",  onOpen: () => _fetchLogs() },
    graph: { overlayId: "graph-overlay", triggerId: "btn-graph", onOpen: () => _fetchGraph() },
  };
  const _savedFocus = {};

  function _isOverlayOpen(key) {
    const el = document.getElementById(_OVERLAYS[key].overlayId);
    return !!(el && !el.classList.contains("hidden"));
  }

  function _openOverlay(key) {
    const cfg = _OVERLAYS[key];
    const overlay = document.getElementById(cfg.overlayId);
    const trigger = document.getElementById(cfg.triggerId);
    if (!overlay || _isOverlayOpen(key)) return;

    _savedFocus[cfg.overlayId] = document.activeElement;
    overlay.classList.remove("hidden");
    if (trigger) trigger.setAttribute("aria-expanded", "true");

    for (const el of document.querySelectorAll("body > header, body > main, body > footer")) {
      el.inert = true;
    }

    const heading = overlay.querySelector("h2");
    if (heading) heading.focus();

    if (cfg.onOpen) cfg.onOpen();
  }

  function _closeOverlay(key) {
    const cfg = _OVERLAYS[key];
    const overlay = document.getElementById(cfg.overlayId);
    const trigger = document.getElementById(cfg.triggerId);
    if (!overlay || !_isOverlayOpen(key)) return;

    overlay.classList.add("hidden");
    if (trigger) trigger.setAttribute("aria-expanded", "false");

    for (const el of document.querySelectorAll("body > header, body > main, body > footer")) {
      el.inert = false;
    }

    const saved = _savedFocus[cfg.overlayId];
    if (saved && typeof saved.focus === "function" && document.contains(saved)) {
      saved.focus();
    } else if (trigger) {
      trigger.focus();
    }
    delete _savedFocus[cfg.overlayId];
  }

  function _toggleOverlay(key) {
    if (_isOverlayOpen(key)) _closeOverlay(key);
    else _openOverlay(key);
  }

  function _currentOpenOverlayKey() {
    return Object.keys(_OVERLAYS).find(_isOverlayOpen) || null;
  }

  // Trap Tab/Shift-Tab inside the open overlay.
  function _handleOverlayTab(e) {
    if (e.key !== "Tab") return;
    const key = _currentOpenOverlayKey();
    if (!key) return;

    const overlay = document.getElementById(_OVERLAYS[key].overlayId);
    const focusable = Array.from(overlay.querySelectorAll(
      'a[href], button:not([disabled]), textarea, input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((el) => el.offsetParent !== null);

    if (focusable.length === 0) {
      e.preventDefault();
      const heading = overlay.querySelector("h2[tabindex='-1']");
      if (heading) heading.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    const insideOverlay = overlay.contains(active);

    if (e.shiftKey) {
      if (!insideOverlay || active === first || active === overlay.querySelector("h2")) {
        e.preventDefault();
        last.focus();
      }
    } else if (!insideOverlay || active === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function toggleHelp()  { _toggleOverlay("help"); }
  function toggleLogs()  { _toggleOverlay("logs"); }
  function toggleGraph() { _toggleOverlay("graph"); }

  // Manual Juju status refresh — exposed so the panel button can call it.
  function refreshJujuStatus() { _fetchJujuStatus(); }

  // Cancel the in-flight agent turn.  Fires a WS message the server
  // translates into ``asyncio.Task.cancel()`` on ``process_message``.
  // The server answers with a ``thinking: {active: false}`` broadcast
  // and a ``Cancelled.`` system message, so no UI state changes here.
  function cancelTurn() { _send("cancel_request", {}); }

  // Textarea auto-resize — grows with content up to ``max-height``
  // set in CSS, then scrolls internally.  Reset to one row when the
  // content is empty so the input doesn't keep the multiline height
  // forever after submitting.
  function _autoResizeChatInput() {
    const input = chatInput();
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  }

  // Manual scroll-to-bottom — bypasses the "near bottom" heuristic
  // and always jumps to the latest row.
  function scrollChatToBottom() {
    const scroller = chatMessages();
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }

  // Threshold (in pixels) below which we consider the user "at the
  // bottom" — within one screenful, so the button stays out of the
  // way when they're actively reading recent messages.
  const _SCROLL_BOTTOM_THRESHOLD = 120;

  function _updateScrollBottomButton() {
    const scroller = chatMessages();
    const btn = document.getElementById("btn-scroll-bottom");
    if (!scroller || !btn) return;
    const gap = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    btn.hidden = gap < _SCROLL_BOTTOM_THRESHOLD;
  }

  async function _fetchLogs() {
    const output = logsOutput();
    if (!output) return;
    output.textContent = "Loading Juju debug-log…";
    try {
      const resp = await fetch("/api/logs?lines=200&level=INFO");
      if (!resp.ok) {
        output.textContent =
          `Could not load logs (HTTP ${resp.status}). Is a dev model attached?`;
        return;
      }
      const data = await resp.json();
      if (data.error) {
        output.textContent = data.error;
        return;
      }
      output.textContent =
        (data.lines || []).join("\n") || "No log entries at this level.";
    } catch (e) {
      output.textContent = `Could not reach the server: ${e.message || e}.`;
    }
  }

  // ── Graph overlay ────────────────────────────────────────────────

  async function _fetchGraph() {
    const view = graphView();
    if (!view) return;
    view.innerHTML = '<div class="juju-empty">Loading model status\u2026</div>';
    try {
      const resp = await fetch("/api/juju-status");
      if (!resp.ok) {
        view.innerHTML =
          `<div class="juju-empty">Could not load status (HTTP ${resp.status}).</div>`;
        return;
      }
      const data = await resp.json();
      _renderGraph(view, data);
    } catch (e) {
      view.innerHTML =
        `<div class="juju-empty">Could not reach the server: ${_esc(e.message || String(e))}.</div>`;
    }
  }

  function _renderGraph(container, data) {
    const apps = data.apps || {};
    const relations = data.relations || [];
    const appNames = Object.keys(apps);

    if (appNames.length === 0) {
      container.innerHTML = '<div class="juju-empty">No applications deployed.</div>';
      return;
    }

    container.innerHTML = "";

    // App cards.
    for (const name of appNames.sort()) {
      const app = apps[name];
      const div = document.createElement("div");
      const status = app.status || "unknown";
      div.className = `graph-app status-${status}`;

      const units = app.units || {};
      const unitCount = Object.keys(units).length;
      const statusIcon = { active: "\u25cf", waiting: "\u25cb", blocked: "\u25cc", error: "\u2717" }[status] || "\u25cb";

      let html =
        `<div class="graph-app-name">${_esc(name)}</div>` +
        `<div class="graph-app-status">${statusIcon} ${_esc(status)}` +
        (app.message ? `: ${_esc(app.message.substring(0, 40))}` : "") + `</div>` +
        `<div class="graph-app-units">${unitCount} unit${unitCount !== 1 ? "s" : ""}</div>`;

      // Unit breakdown.
      for (const [uName, uInfo] of Object.entries(units)) {
        const uStatus = uInfo.status || "unknown";
        const uIcon = { active: "\u25cf", waiting: "\u25cb", blocked: "\u25cc", error: "\u2717" }[uStatus] || "\u25cb";
        const short = uName.split("/").pop();
        html += `<div class="graph-app-unit">${uIcon} /${_esc(short)} ${_esc(uStatus)}</div>`;
      }

      div.innerHTML = html;
      container.appendChild(div);
    }

    // Relations section.
    if (relations.length > 0) {
      const relDiv = document.createElement("div");
      relDiv.className = "graph-relations";
      let relHtml = "<h3>Relations</h3>";
      for (const rel of relations) {
        relHtml +=
          `<div class="graph-relation">` +
          `<span class="rel-app">${_esc(rel.provider || "")}</span>` +
          ` \u2500\u2500 ` +
          `<span class="rel-iface">[${_esc(rel.interface || "")}]</span>` +
          ` \u2500\u2500\u25b8 ` +
          `<span class="rel-app">${_esc(rel.requirer || "")}</span>` +
          `</div>`;
      }
      relDiv.innerHTML = relHtml;
      container.appendChild(relDiv);
    }
  }

  // ── Keyboard shortcuts ──────────────────────────────────────────
  //
  // Activation keys are gated behind Alt so they don't collide with
  // normal typing — WCAG 2.1.4 Character Key Shortcuts.  Escape and
  // the overlay Tab-trap run unconditionally.

  function _handleKeyDown(e) {
    if (e.key === "Escape") {
      const openKey = _currentOpenOverlayKey();
      if (openKey) {
        e.preventDefault();
        _closeOverlay(openKey);
        return;
      }
      const thinking = thinkingEl();
      if (thinking && !thinking.hidden) {
        e.preventDefault();
        cancelTurn();
      }
      return;
    }

    _handleOverlayTab(e);

    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (!e.altKey || e.ctrlKey || e.metaKey) return;

    const key = e.key.toLowerCase();
    if (key === "h" || key === "?") {
      e.preventDefault();
      toggleHelp();
    } else if (key === "l") {
      e.preventDefault();
      toggleLogs();
    } else if (key === "g") {
      e.preventDefault();
      toggleGraph();
    } else if (key === "r") {
      e.preventDefault();
      if (_isOverlayOpen("graph")) {
        _fetchGraph();
      } else {
        _fetchJujuStatus();
      }
    }
  }

  // ── State sync ──────────────────────────────────────────────────

  async function _fetchState() {
    try {
      const resp = await fetch("/api/state");
      if (!resp.ok) return;
      const state = await resp.json();
      if (state.tasks) replaceAllTasks(state.tasks);
    } catch { /* ignore */ }
  }

  async function _fetchMessages() {
    const container = chatMessages();
    if (!container) return;
    try {
      const resp = await fetch("/api/messages");
      if (!resp.ok) return;
      const data = await resp.json();
      const messages = data.messages || [];
      if (messages.length === 0) return;  // keep the welcome placeholder
      container.innerHTML = "";
      for (const m of messages) {
        appendMessage(m.role, m.content, m.html, m.timestamp, m.reasoning);
      }
    } catch { /* ignore */ }
  }

  // ── Session resume prompt (Phase 31.3) ──────────────────────────

  async function _fetchSessionPreview() {
    try {
      const resp = await fetch("/api/session/preview");
      if (!resp.ok) return;
      const preview = await resp.json();
      if (!preview.exists || preview.decided) return;
      _showResumeBanner(preview);
    } catch { /* ignore */ }
  }

  function _showResumeBanner(preview) {
    const banner = document.getElementById("resume-banner");
    if (!banner) return;
    const summary = document.getElementById("resume-banner-summary");
    if (summary) summary.textContent = preview.summary || "Prior session on disk.";
    banner.hidden = false;

    const resumeBtn = document.getElementById("resume-btn-resume");
    const freshBtn = document.getElementById("resume-btn-fresh");
    const transcriptBtn = document.getElementById("resume-btn-transcript");
    if (resumeBtn) resumeBtn.onclick = () => _decideSession("resume");
    if (freshBtn) freshBtn.onclick = () => _decideSession("fresh");
    if (transcriptBtn) transcriptBtn.onclick = () => _toggleResumeTranscript();
  }

  async function _decideSession(choice) {
    try {
      const resp = await fetch("/api/session/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice }),
      });
      if (!resp.ok) return;
      const banner = document.getElementById("resume-banner");
      if (banner) banner.hidden = true;
      // Reload the messages list so the summary (resume) or empty state
      // (fresh) reflects the new world.  The server also broadcasts a
      // chat_message so WS-connected clients pick it up.
      await _fetchMessages();
    } catch { /* ignore */ }
  }

  // ── Self-update banner (Phase 63.4) ──────────────────────────────

  const UPDATE_DISMISS_KEY = "cantrip.update.dismissed";

  async function _fetchUpdateStatus() {
    try {
      const resp = await fetch("/api/update-status");
      if (!resp.ok) return;
      const data = await resp.json();
      _renderUpdateBanner(data.info);
    } catch { /* ignore */ }
  }

  function _renderUpdateBanner(info) {
    const banner = document.getElementById("update-banner");
    if (!banner) return;
    if (!info) {
      banner.hidden = true;
      return;
    }
    // Dismissal is keyed on the version so shipping a newer release
    // re-surfaces the banner without the user having to clear storage.
    const dismissed = _getDismissedUpdateVersion();
    if (dismissed && dismissed === info.latest) {
      banner.hidden = true;
      return;
    }

    const body = document.getElementById("update-banner-body");
    const link = document.getElementById("update-banner-link");
    const dismiss = document.getElementById("update-banner-dismiss");
    if (body) body.innerHTML = _updateBannerHtml(info);
    if (link && info.pypi_url) link.href = info.pypi_url;
    if (dismiss) {
      dismiss.onclick = () => {
        try {
          localStorage.setItem(UPDATE_DISMISS_KEY, info.latest);
        } catch { /* storage disabled; dismissal is per-session */ }
        banner.hidden = true;
      };
    }
    banner.hidden = false;
  }

  function _updateBannerHtml(info) {
    const current = _esc(info.current || "");
    const latest = _esc(info.latest || "");
    let headline;
    if (info.installed_yanked) {
      headline = `Cantrip ${current} has been yanked — upgrading to ${latest} is recommended.`;
    } else {
      headline = `A newer Cantrip is available: ${latest} (you have ${current}).`;
    }
    const command = info.upgrade_command
      ? ` Run <code>${_esc(info.upgrade_command)}</code> to upgrade.`
      : " Upgrade via your usual installer.";
    return `<strong>${headline}</strong>${command}`;
  }

  function _getDismissedUpdateVersion() {
    try {
      return localStorage.getItem(UPDATE_DISMISS_KEY);
    } catch {
      return null;
    }
  }

  async function _toggleResumeTranscript() {
    const panel = document.getElementById("resume-transcript");
    const btn = document.getElementById("resume-btn-transcript");
    if (!panel || !btn) return;
    if (!panel.hidden) {
      panel.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      return;
    }
    try {
      const resp = await fetch("/api/session/transcript?limit=20");
      if (!resp.ok) return;
      const data = await resp.json();
      const messages = data.messages || [];
      if (messages.length === 0) {
        panel.textContent = "(no messages persisted)";
      } else {
        panel.textContent = messages
          .map((m) => {
            let content = (m.content || "").replace(/\n/g, " ");
            if (content.length > 200) content = content.slice(0, 197) + "...";
            return `${(m.role || "").toUpperCase()}: ${content}`;
          })
          .join("\n");
      }
      panel.hidden = false;
      btn.setAttribute("aria-expanded", "true");
    } catch { /* ignore */ }
  }

  // ── Utilities ───────────────────────────────────────────────────

  function _esc(text) {
    const el = document.createElement("span");
    el.textContent = text;
    return el.innerHTML;
  }

  // ── Public API ──────────────────────────────────────────────────

  return {
    connect, appendMessage, updateTask, replaceAllTasks, setThinking,
    toggleHelp, toggleLogs, toggleGraph, refreshJujuStatus, cancelTurn,
    scrollChatToBottom,
  };
})();
