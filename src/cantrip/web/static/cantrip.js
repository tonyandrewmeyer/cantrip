/* Cantrip Web UI — WebSocket client and DOM updates. */

const cantrip = (() => {
  "use strict";

  let ws = null;
  let reconnectDelay = 1000;
  let port = 8471;

  // ── DOM references ──────────────────────────────────────────────
  const chatMessages = () => document.getElementById("chat-messages");
  const chatInput = () => document.getElementById("chat-input");
  const chatForm = () => document.getElementById("chat-form");
  const taskList = () => document.getElementById("task-list");
  const thinkingEl = () => document.getElementById("thinking-indicator");
  const statusDot = () => document.getElementById("connection-status");

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
  }

  function _openSocket() {
    const url = `ws://${location.hostname || "127.0.0.1"}:${port}/ws`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      reconnectDelay = 1000;
      _setStatus("connected");
      // Sync full state on reconnect.
      _fetchState();
    };

    ws.onclose = () => {
      _setStatus("reconnecting");
      setTimeout(_openSocket, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    };

    ws.onerror = () => {
      _setStatus("disconnected");
    };

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
    body.textContent = content;
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

    // Remove the "no tasks" placeholder.
    const empty = list.querySelector(".task-empty");
    if (empty) empty.remove();

    let el = document.getElementById(`task-${data.id}`);
    if (el) {
      // Update existing task.
      el.className = `task task-${data.status}`;
      el.querySelector(".task-title").textContent = data.title;
      el.querySelector(".task-badge").textContent = data.category;
    } else {
      // Create new task element.
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

  // ── State sync ──────────────────────────────────────────────────

  async function _fetchState() {
    try {
      const resp = await fetch(`/api/state`);
      if (!resp.ok) return;
      const state = await resp.json();
      if (state.tasks) replaceAllTasks(state.tasks);
    } catch { /* ignore fetch errors during reconnect */ }
  }

  // ── Utilities ───────────────────────────────────────────────────

  function _esc(text) {
    const el = document.createElement("span");
    el.textContent = text;
    return el.innerHTML;
  }

  // ── Public API ──────────────────────────────────────────────────

  return { connect, appendMessage, updateTask, replaceAllTasks, setThinking };
})();
