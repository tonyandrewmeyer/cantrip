/* Cantrip Web UI — WebSocket client, Markdown rendering, and DOM updates. */

const cantrip = (() => {
  "use strict";

  let ws = null;
  let reconnectDelay = 1000;
  let port = 8471;
  let statusPollTimer = null;

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
    dot.title = state.charAt(0).toUpperCase() + state.slice(1);
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
    }
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
    el.classList.toggle("hidden", !active);
  }

  // ── Task rendering ──────────────────────────────────────────────

  function updateTask(data) {
    const list = taskList();
    if (!list) return;

    const empty = list.querySelector(".task-empty");
    if (empty) empty.remove();

    let el = document.getElementById(`task-${data.id}`);
    if (el) {
      el.className = `task task-${data.status}`;
      el.querySelector(".task-title").textContent = data.title;
      el.querySelector(".task-badge").textContent = data.category;
    } else {
      el = document.createElement("div");
      el.id = `task-${data.id}`;
      el.className = `task task-${data.status}`;
      el.dataset.category = data.category;
      el.innerHTML =
        '<span class="task-icon"></span>' +
        `<span class="task-title">${_esc(data.title)}</span>` +
        `<span class="task-badge">${_esc(data.category)}</span>`;
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

  // ── Overlays ────────────────────────────────────────────────────

  function toggleHelp() {
    const el = helpOverlay();
    if (el) el.classList.toggle("hidden");
  }

  function toggleLogs() {
    const el = logsOverlay();
    if (!el) return;
    const wasHidden = el.classList.contains("hidden");
    el.classList.toggle("hidden");
    if (wasHidden) _fetchLogs();
  }

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

  // ── Keyboard shortcuts ──────────────────────────────────────────

  function _handleKeyDown(e) {
    // Don't intercept when typing in the input.
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
      e.preventDefault();
      toggleHelp();
    } else if (e.key === "l" || e.key === "L") {
      e.preventDefault();
      toggleLogs();
    } else if (e.key === "Escape") {
      const help = helpOverlay();
      const logs = logsOverlay();
      if (help && !help.classList.contains("hidden")) help.classList.add("hidden");
      else if (logs && !logs.classList.contains("hidden")) logs.classList.add("hidden");
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

  // ── Utilities ───────────────────────────────────────────────────

  function _esc(text) {
    const el = document.createElement("span");
    el.textContent = text;
    return el.innerHTML;
  }

  // ── Public API ──────────────────────────────────────────────────

  return {
    connect, appendMessage, updateTask, replaceAllTasks, setThinking,
    toggleHelp, toggleLogs,
  };
})();
