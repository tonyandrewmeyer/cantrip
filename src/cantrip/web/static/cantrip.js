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
      appendMessage("user", text);
      _send("chat_input", { content: text });
    });

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
        appendMessage(msg.data.role, msg.data.content);
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
        );
        break;
      case "memory_recalled":
        appendMessage(
          "system",
          `Recalled memory: ${msg.data.title} (${msg.data.scope})`,
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
    }
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

  // ── Markdown rendering ──────────────────────────────────────────

  function _renderMarkdown(text) {
    if (!text) return "";
    let html = _esc(text);

    // Code blocks (``` ... ```).
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre><code>${code}</code></pre>`;
    });

    // Inline code.
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Bold.
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

    // Italic.
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

    // Headings (### before ## before #).
    html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");

    // Unordered lists.
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`);

    // Ordered lists.
    html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");

    // Paragraphs: wrap remaining text blocks.
    html = html.replace(/\n\n/g, "</p><p>");
    if (!html.startsWith("<")) html = "<p>" + html;
    if (!html.endsWith(">")) html += "</p>";

    // Clean up empty paragraphs.
    html = html.replace(/<p>\s*<\/p>/g, "");

    return html;
  }

  // ── Chat rendering ──────────────────────────────────────────────

  function appendMessage(role, content) {
    const container = chatMessages();
    if (!container) return;

    const div = document.createElement("div");
    div.className = `msg msg-${role}`;

    const roleLabel = document.createElement("div");
    roleLabel.className = "msg-role";
    roleLabel.textContent = role;
    div.appendChild(roleLabel);

    const body = document.createElement("div");
    if (role === "assistant") {
      body.innerHTML = _renderMarkdown(content);
    } else {
      body.textContent = content;
    }
    div.appendChild(body);

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function setThinking(active) {
    const el = thinkingEl();
    if (!el) return;
    if (active) {
      // Preserve the animated dots span; only the trailing text
      // changes.  A fresh label is picked each time the indicator
      // switches on, matching the TUI's per-phase re-roll cadence.
      const dots = el.querySelector(".dots");
      el.textContent = "";
      if (dots) el.appendChild(dots);
      el.appendChild(document.createTextNode(` ${pickFlavourLabel()}…`));
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

      div.innerHTML =
        `<div class="juju-app-name">${_esc(name)}</div>` +
        `<div class="juju-app-status">${statusIcon} ${_esc(app.status)}` +
        (app.message ? `: ${_esc(app.message.substring(0, 40))}` : "") + `</div>` +
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

  async function _fetchLogs() {
    const output = logsOutput();
    if (!output) return;
    output.textContent = "Loading...";
    try {
      const resp = await fetch("/api/logs?lines=200&level=INFO");
      if (!resp.ok) { output.textContent = "Failed to fetch logs."; return; }
      const data = await resp.json();
      output.textContent = (data.lines || []).join("\n") || "No log entries.";
    } catch { output.textContent = "Error fetching logs."; }
  }

  // ── Graph overlay ────────────────────────────────────────────────

  async function _fetchGraph() {
    const view = graphView();
    if (!view) return;
    view.innerHTML = '<div class="juju-empty">Loading\u2026</div>';
    try {
      const resp = await fetch("/api/juju-status");
      if (!resp.ok) { view.innerHTML = '<div class="juju-empty">Failed to fetch status.</div>'; return; }
      const data = await resp.json();
      _renderGraph(view, data);
    } catch { view.innerHTML = '<div class="juju-empty">Error fetching status.</div>'; }
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
      container.innerHTML = "";
      for (const m of messages) appendMessage(m.role, m.content);
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
  };
})();
