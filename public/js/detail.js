import { state } from "./state.js";
import { $, detailEl, escapeHtml, md, fmtTime, shortModel, tilde, toast, api, base, messageUrl } from "./util.js";
import { renderSessionList } from "./list.js";
import { loadSessions } from "./data.js";
import { showViewer } from "./nav.js";

// ---------------------------------------------------------------------------
// session detail
// ---------------------------------------------------------------------------
export async function selectSession(id) {
  state.selectedId = id;
  state.selectAnchor = id; // the opened row is the "latest selected" (shift-click anchor)
  renderSessionList();
  detailEl.innerHTML = '<div class="empty"><div class="big">⏳</div><div>Loading…</div></div>';
  try {
    state.detail = await api(`${base()}/sessions/${encodeURIComponent(id)}`);
    renderDetail();
  } catch (err) {
    detailEl.innerHTML = `<div class="empty"><div class="big">⚠️</div><div>${escapeHtml(err.message)}</div></div>`;
  }
}

// <option> list for the project dropdown: every known project, plus the
// session's current directory if it has no project row yet
function projectOptions(current) {
  const known = state.projects.map((p) => p.worktree);
  const list = known.includes(current)
    ? state.projects
    : [{ worktree: current }, ...state.projects];
  return list.map((p) =>
    `<option value="${escapeHtml(p.worktree)}"${p.worktree === current ? " selected" : ""}>${escapeHtml(tilde(p.worktree))}</option>`
  ).join("");
}

export function renderDetail() {
  const s = state.detail;
  if (!s) return;
  const model = shortModel(s.model);
  const tokens =
    (s.tokens_input || 0) + (s.tokens_output || 0) + (s.tokens_reasoning || 0) +
    (s.tokens_cache_read || 0) + (s.tokens_cache_write || 0);

  detailEl.innerHTML = `
    <div class="detail-inner">
      <div class="sess-head">
        <h1 id="sess-title">${escapeHtml(s.title || s.slug || s.id)}</h1>
        <div class="sess-meta">
          <span><span class="k">id </span><span class="v mono copyable" id="sess-id" title="click to copy">${s.id}</span></span>
          ${state.source === "opencode"
            ? `<span><span class="k">proj </span><span class="proj-combo"><select id="sess-project" title="move this conversation to another project">${projectOptions(s.directory)}</select><button class="combo-more" id="sess-pick" title="choose a project folder…">…</button></span></span>`
            : `<span><span class="k">proj </span><span class="v mono">${escapeHtml(tilde(s.directory))}</span></span>`}
          ${s.agent ? `<span><span class="k">agent </span><span class="v">${escapeHtml(s.agent)}</span></span>` : ""}
          ${model ? `<span><span class="k">model </span><span class="v">${escapeHtml(model)}</span></span>` : ""}
          <span><span class="k">created </span><span class="v">${fmtTime(s.time_created)}</span></span>
          <span><span class="k">updated </span><span class="v">${fmtTime(s.time_updated)}</span></span>
          ${tokens ? `<span><span class="k">tokens </span><span class="v">${tokens.toLocaleString()}</span></span>` : ""}
          ${s.cost ? `<span><span class="k">cost </span><span class="v">$${Number(s.cost).toFixed(4)}</span></span>` : ""}
          ${s.time_archived ? `<span class="badge archived">archived</span>` : ""}
        </div>
        <div class="sess-actions">
          <button class="btn small" id="btn-edit-title">Rename<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>
          <button class="btn small" id="btn-archive">${s.time_archived ? "Unarchive" : "Archive"}</button>
          <button class="btn small" id="btn-export">Export JSON</button>
          <button class="btn small" id="btn-move" title="Copy this conversation to the other source">${state.source === "opencode" ? "Move to Cursor" : "Move to opencode"}</button>
          <button class="btn small danger" id="btn-delete">Delete<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
        </div>
      </div>
      <div id="msg-list"></div>
    </div>`;

  $("#sess-id").addEventListener("click", () => {
    navigator.clipboard.writeText(s.id).then(() => toast("session id copied"));
  });
  $("#btn-edit-title").addEventListener("click", editSessionTitle);
  $("#btn-archive").addEventListener("click", toggleArchive);
  $("#btn-export").addEventListener("click", exportSession);
  $("#btn-move").addEventListener("click", () => openMoveModal(s.id, s.directory));
  $("#btn-delete").addEventListener("click", deleteSession);
  // … button (fused to the select's trailing edge): opens the native folder
  // picker. A button click is a valid user gesture in Safari.
  const pickBtn = $("#sess-pick");
  if (pickBtn) pickBtn.addEventListener("click", () => pickProjectDirectory(s.id, s.directory, pickBtn));
  const projSel = $("#sess-project");
  if (projSel) projSel.addEventListener("change", (e) => moveSessionTo(s.id, e.target.value));
  renderMessages();
}

// Show/hide the spinner inside the "…" button (the trailing-edge combo button)
function setPickBusy(busy) {
  const btn = $("#sess-pick");
  if (!btn) return;
  btn.disabled = busy;
  btn.innerHTML = busy ? '<span class="spinner"></span>' : "…";
}

// Re-home a session to a new directory (shared by the dropdown + path picker)
export async function moveSessionTo(sessionId, directory) {
  setPickBusy(true);
  try {
    await api(`${base()}/sessions/${sessionId}`, { method: "PATCH", body: { directory } });
    toast("project updated");
    state.detail = await api(`${base()}/sessions/${sessionId}`);
    renderDetail(); // rebuilds the meta row (fresh … button)
    loadSessions();
  } catch (err) { toast(err.message, "error"); setPickBusy(false); }
}

// Move a transcript to the other source (opencode <-> Cursor). Asks for the
// target project folder + whether to delete the original, then converts and
// jumps to the new conversation in the other source.
export async function openMoveModal(sessionId, currentDir) {
  const target = state.source === "opencode" ? "cursor" : "opencode";
  const targetLabel = target === "cursor" ? "Cursor" : "opencode";

  // Existing projects in the target source — the move lands in one of these.
  // Fetch by target (not the current view), so cursor -> opencode lists
  // opencode's projects even while the Cursor view is active.
  let options = [];
  try {
    const projs = target === "cursor"
      ? await api("/api/cursor/projects")
      : await api("/api/projects");
    options = projs.map((p) => p.worktree);
  } catch (e) { /* best-effort */ }
  // Default to the source's own path (preserve it); add it if not already listed.
  if (currentDir && !options.includes(currentDir)) options.unshift(currentDir);

  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <h2>Move to ${targetLabel}</h2>
      <p class="modal-sub">Copies this conversation into an existing ${targetLabel} project as a new conversation. Tool output and model info may not carry over.</p>
      <div class="field">
        <label>Target project</label>
        ${options.length
          ? `<select id="mv-dir">
               ${options.map((d) => `<option value="${escapeHtml(d)}"${d === currentDir ? " selected" : ""}>${escapeHtml(tilde(d))}</option>`).join("")}
             </select>`
          : `<input id="mv-dir" value="${escapeHtml(currentDir || "")}" disabled>
             <p class="modal-sub">No ${targetLabel} projects found yet.</p>`}
      </div>
      <div class="field">
        <label class="check"><input type="checkbox" id="mv-delete"> Delete the original</label>
      </div>
      <div class="modal-actions">
        <button class="btn" id="mv-cancel">Cancel</button>
        <button class="btn primary" id="mv-go">Move</button>
      </div>
    </div>`;
  document.body.appendChild(backdrop);

  const close = () => backdrop.remove();
  backdrop.querySelector("#mv-cancel").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  backdrop.querySelector("#mv-go").addEventListener("click", async () => {
    const directory = backdrop.querySelector("#mv-dir").value.trim();
    const del = backdrop.querySelector("#mv-delete").checked;
    if (!directory) return toast("target folder is required", "error");
    const btn = backdrop.querySelector("#mv-go");
    btn.disabled = true; btn.textContent = "Moving…";
    try {
      const url = target === "cursor"
        ? `${base()}/sessions/${encodeURIComponent(sessionId)}/move-to-cursor`
        : `${base()}/sessions/${encodeURIComponent(sessionId)}/move-to-opencode`;
      const res = await api(url, { method: "POST", body: { directory, delete_original: del } });
      close();
      toast(`moved to ${targetLabel}`);
      await showViewer(target);   // switches source + reloads the list
      selectSession(res.id);      // opens the new conversation
    } catch (err) { toast(err.message, "error"); btn.disabled = false; btn.textContent = "Move"; }
  });
}

// Open a native directory picker that works in Chrome, Safari and Firefox.
// The picker exposes files with relative paths; we derive the folder name + a
// child-name fingerprint and let the local backend resolve the full path.
function pickProjectDirectory(sessionId, currentDir, selectEl) {
  // Only a <select> needs resetting (a button trigger has no value to restore)
  const reset = () => { if (selectEl.isConnected && selectEl.tagName === "SELECT") selectEl.value = currentDir; };

  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.title = "Move"; // best-effort native dialog title
  input.setAttribute("webkitdirectory", "");
  input.setAttribute("directory", "");
  // Off-screen (not display:none) — Safari won't open the dialog for a
  // display:none file input triggered outside a direct click gesture.
  input.style.cssText = "position:fixed; top:0; left:0; width:1px; height:1px; opacity:0; pointer-events:none;";
  document.body.appendChild(input);

  const cleanup = (ok) => { input.remove(); if (!ok) reset(); };

  input.addEventListener("change", async () => {
    const files = Array.from(input.files || []);
    if (!files.length) return cleanup(false);
    // Spin immediately — resolving a brand-new dir scans the home tree, which
    // is the slow part (it runs before moveSessionTo would otherwise spin).
    setPickBusy(true);
    const rel = files[0].webkitRelativePath || files[0].name;
    const name = rel.split("/")[0];
    const children = new Set();
    for (const f of files) {
      const s = (f.webkitRelativePath || "").split("/");
      if (s.length > 1) children.add(s[1]);
      if (children.size >= 50) break;
    }
    try {
      const res = await api(`${base()}/resolve-dir`, { method: "POST", body: { name, children: [...children] } });
      if (!res.path) throw new Error("could not resolve path");
      cleanup(true);
      await moveSessionTo(sessionId, res.path);
    } catch (err) {
      toast(err.message, "error");
      cleanup(false);
      setPickBusy(false);
    }
  });
  input.addEventListener("cancel", () => cleanup(false));
  input.click();
}

export function renderMessages() {
  const s = state.detail;
  const el = $("#msg-list");
  if (!s.messages.length) {
    el.innerHTML = '<div class="sysline"><span class="pill">no messages yet</span></div>';
    return;
  }
  el.innerHTML = s.messages.map((m) => renderMessage(m)).join("");
  el.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => editMessage(b.dataset.edit))
  );
  el.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", () => deleteMessage(b.dataset.del))
  );
}

function renderMessage(m) {
  const d = m.data || {};
  const time = fmtTime(m.time_created);

  if (m.type === "user") {
    return `
      <div class="msg user" id="msg-${m.id}">
        <div class="avatar user">You</div>
        <div class="msg-body">
          <div class="msg-head">
            <span class="name">You</span>
            <span class="time">${time}</span>
            <span class="actions">
              <button class="btn small icon-btn" data-edit="${m.id}" title="Edit message"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>
              <button class="btn small icon-btn danger" data-del="${m.id}" title="Delete message"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
            </span>
          </div>
          <div class="msg-content">${md(d.text || "")}</div>
        </div>
      </div>`;
  }

  if (m.type === "assistant") {
    const model = d.model ? `${d.model.id}${d.model.variant ? "#" + d.model.variant : ""}` : "assistant";
    const parts = (d.content || []).map((c) => {
      if (c.type === "reasoning") {
        return `<details class="thinking"><summary>thinking</summary><div class="inner">${md(c.text || "")}</div></details>`;
      }
      if (c.type === "text") {
        return `<div class="msg-content" style="margin-top:6px">${md(c.text || "")}</div>`;
      }
      if (c.type === "tool") {
        const status = c.state?.status || (c.executed ? "completed" : "pending");
        const input = c.state?.input;
        const inputStr = input ? (typeof input === "string" ? input : JSON.stringify(input, null, 2)) : "";
        const output = (c.state?.content || []).map((x) => x.text || "").join("\n");
        return `
          <details class="tool">
            <summary><span class="tool-name">${escapeHtml(c.name || "tool")}</span>
              <span class="tool-status ${status}">${status}</span></summary>
            <div class="inner">
              ${inputStr ? `<div style="margin-bottom:6px;color:var(--muted)">input</div><pre>${escapeHtml(inputStr)}</pre>` : ""}
              ${output ? `<div style="margin:6px 0 4px;color:var(--muted)">output</div><pre>${escapeHtml(output)}</pre>` : ""}
            </div>
          </details>`;
      }
      return "";
    }).join("");
    return `
      <div class="msg assistant" id="msg-${m.id}">
        <div class="avatar assistant">AI</div>
        <div class="msg-body">
          <div class="msg-head">
            <span class="name">${escapeHtml(model)}</span>
            <span class="time">${time}</span>
            <span class="actions">
              <button class="btn small icon-btn" data-edit="${m.id}" title="Edit message"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>
              <button class="btn small icon-btn danger" data-del="${m.id}" title="Delete message"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
            </span>
          </div>
          ${parts || '<div class="msg-content"><em>(no content)</em></div>'}
        </div>
      </div>`;
  }

  // system / synthetic / idle / switches / compaction
  let label = "";
  if (m.type === "system") label = d.text ? d.text.split("\n")[0].slice(0, 120) : "system";
  else if (m.type === "synthetic") label = d.text || "synthetic";
  else if (m.type === "idle") label = `idle · ${d.outcome || ""}`;
  else if (m.type === "agent-switched") label = `agent: ${d.previous || "?"} → ${d.agent || "?"}`;
  else if (m.type === "model-switched") {
    const a = d.previous ? d.previous.id : "?";
    const b = d.model ? d.model.id : "?";
    label = `model: ${a} → ${b}`;
  } else if (m.type === "compaction") {
    return `
      <details class="compaction" style="max-width:900px;margin:10px auto">
        <summary>compaction · ${d.reason || ""} · ${d.status || ""}</summary>
        <div class="inner"><pre>${escapeHtml(d.summary || "")}</pre></div>
      </details>`;
  } else label = m.type;

  return `<div class="sysline"><span class="pill">${escapeHtml(label)}</span></div>`;
}

// ---------------------------------------------------------------------------
// mutations
// ---------------------------------------------------------------------------
export async function editSessionTitle() {
  const s = state.detail;
  const h1 = $("#sess-title");
  const input = document.createElement("input");
  input.className = "title-input";
  input.value = s.title || "";
  h1.replaceWith(input);
  input.focus();
  input.select();
  const done = async (save) => {
    if (save && input.value.trim()) {
      try {
        await api(`${base()}/sessions/${s.id}`, { method: "PATCH", body: { title: input.value.trim() } });
        toast("title updated");
      } catch (err) { toast(err.message, "error"); }
    }
    renderDetail();
    loadSessions();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") done(true);
    if (e.key === "Escape") done(false);
  });
  input.addEventListener("blur", () => done(true));
}

export async function toggleArchive() {
  const s = state.detail;
  try {
    await api(`${base()}/sessions/${s.id}`, { method: "PATCH", body: { archived: !s.time_archived } });
    toast(s.time_archived ? "unarchived" : "archived");
    state.detail = await api(`${base()}/sessions/${s.id}`);
    renderDetail();
    loadSessions();
  } catch (err) { toast(err.message, "error"); }
}

export async function deleteSession() {
  const s = state.detail;
  const isCursor = state.source === "cursor";
  const msg = isCursor
    ? `Delete "${s.title || s.id}"?\n\nThis purges the conversation from EVERY Cursor store:\n\n• transcript (.jsonl)\n• store.db (encrypted reasoning)\n• search index\n• cloud-sync copy\n• UI state\n• telemetry\n\nThis cannot be undone.`
    : `Delete session "${s.title || s.id}"?\n\nThis removes the session and all its messages from the opencode database. This cannot be undone.`;
  if (!confirm(msg)) return;
  try {
    const res = await api(`${base()}/sessions/${s.id}`, { method: "DELETE" });
    const stores = (res.stores || []).join(", ");
    toast(stores ? `deleted: ${stores}` : "session deleted");
    state.detail = null;
    state.selectedId = null;
    detailEl.innerHTML = '<div class="empty"><div class="big">💬</div><div>Select a conversation to view it</div></div>';
    await loadSessions();
  } catch (err) { toast(err.message, "error"); }
}

export function exportSession() {
  const s = state.detail;
  const blob = new Blob([JSON.stringify(s, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(s.title || s.id).replace(/[^\w\- ]/g, "").trim() || s.id}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function editMessage(id) {
  const m = state.detail.messages.find((x) => x.id === id);
  if (!m) return;
  let initial = "";
  if (m.type === "assistant") {
    const t = (m.data.content || []).find((c) => c.type === "text");
    initial = t ? t.text : "";
  } else {
    initial = m.data.text || "";
  }
  const box = document.createElement("div");
  box.innerHTML = `
    <textarea class="edit-box">${escapeHtml(initial)}</textarea>
    <div class="edit-actions">
      <button class="btn small primary btn-save">Save</button>
      <button class="btn small btn-cancel">Cancel</button>
    </div>`;
  const target = document.getElementById(`msg-${id}`);
  const body = target.querySelector(".msg-body");
  const content = body.querySelector(".msg-content") || body;
  content.replaceWith(box);
  const ta = box.querySelector("textarea");
  ta.focus();
  const finish = async (save) => {
    if (save) {
      try {
        await api(messageUrl(id), { method: "PATCH", body: { text: ta.value } });
        toast("message updated");
      } catch (err) { toast(err.message, "error"); }
    }
    state.detail = await api(`${base()}/sessions/${state.detail.id}`);
    renderDetail();
  };
  box.querySelector(".btn-save").addEventListener("click", () => finish(true));
  box.querySelector(".btn-cancel").addEventListener("click", () => finish(false));
}

export async function deleteMessage(id) {
  if (!confirm("Delete this message? This cannot be undone.")) return;
  try {
    await api(messageUrl(id), { method: "DELETE" });
    toast("message deleted");
    state.detail = await api(`${base()}/sessions/${state.detail.id}`);
    renderDetail();
    loadSessions();
  } catch (err) { toast(err.message, "error"); }
}
