import { state } from "./state.js";
import { $, detailEl, escapeHtml, relTime, shortModel, tilde, toast, api, base, selectPromptHtml } from "./util.js";
import { loadSessions } from "./data.js";
import { selectSession } from "./detail.js";

// ---------------------------------------------------------------------------
// session list
// ---------------------------------------------------------------------------
export function projectKey(s) {
  return s.project_worktree || s.directory || "(unknown)";
}

// Group sessions by project, ordered by most recent activity per project.
// Archived sessions are pulled into their own "Archived" group (pinned last).
// Returns an array of [groupKey, [session, ...]] pairs.
export function groupedSessions() {
  const groups = new Map();
  for (const s of state.sessions) {
    const k = s.time_archived ? "__archived__" : projectKey(s);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(s);
  }
  const latest = (items) => Math.max(0, ...items.map((s) => s.time_updated || 0));
  const entries = [...groups.entries()];
  entries.sort((a, b) => {
    if (a[0] === "__archived__") return 1;
    if (b[0] === "__archived__") return -1;
    return latest(b[1]) - latest(a[1]);
  });
  return entries;
}

export function renderSessionList() {
  const el = $("#session-list");
  $("#f-count").textContent = `${state.sessions.length} sessions`;
  if (state.sessions.length === 0) {
    el.innerHTML = '<div class="empty" style="height:auto;padding:40px 10px">No sessions found</div>';
    updateSelectionUI();
    return;
  }
  const groups = groupedSessions();
  el.innerHTML = groups.map(([key, items]) => {
    const collapsed = state.collapsedProjects.has(key);
    const name = key === "__archived__" ? "Archived" : tilde(key);
    return `
      <div class="proj-group" data-proj="${escapeHtml(key)}">
        <div class="proj-head" data-proj="${escapeHtml(key)}">
          <span class="proj-toggle">${collapsed ? "▸" : "▾"}</span>
          <span class="proj-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
          <span class="badge">${items.length}</span>
        </div>
        <div class="proj-items" style="display:${collapsed ? "none" : "block"}">
          ${items.map(sessionItemHtml).join("")}
        </div>
      </div>`;
  }).join("");
  el.querySelectorAll(".session-item").forEach((node) =>
    node.addEventListener("click", (e) => {
      if (e.shiftKey) {
        e.preventDefault();
        rangeSelect(node.dataset.id);
      } else {
        clickItem(node.dataset.id);
      }
    })
  );
  el.querySelectorAll(".proj-head").forEach((node) =>
    node.addEventListener("click", () => toggleProject(node.dataset.proj))
  );
  updateSelectionUI();
}

function sessionItemHtml(s) {
  const title = s.title || s.slug || s.id;
  const model = shortModel(s.model);
  const cls = [
    "session-item",
    s.id === state.selectAnchor ? "active" : "",
    state.selected.has(s.id) ? "selected" : "",
  ].filter(Boolean).join(" ");
  return `
    <div class="${cls}" data-id="${s.id}">
      <div class="si-text">
        <div class="title">${escapeHtml(title)}</div>
        <div class="meta">
          <span>${relTime(s.time_updated)}</span>
          <span>·</span>
          <span>${s.message_count} msg</span>
          ${s.agent ? `<span class="badge agent">${escapeHtml(s.agent)}</span>` : ""}
          ${model ? `<span class="badge model">${escapeHtml(model)}</span>` : ""}
          ${s.content_state === "orphaned" ? `<span class="badge orphan" data-tip="Header only — content is cloud-only or evicted by Cursor">no local content</span>` : ""}
          ${s.time_archived ? `<span class="badge archived">archived</span>` : ""}
        </div>
      </div>
    </div>`;
}

export function toggleProject(key) {
  if (state.collapsedProjects.has(key)) state.collapsedProjects.delete(key);
  else state.collapsedProjects.add(key);
  let group = null;
  document.querySelectorAll(".proj-group").forEach((g) => { if (g.dataset.proj === key) group = g; });
  if (!group) return renderSessionList();
  const collapsed = state.collapsedProjects.has(key);
  group.querySelector(".proj-items").style.display = collapsed ? "none" : "block";
  group.querySelector(".proj-toggle").textContent = collapsed ? "▸" : "▾";
}

export function toggleSelect(id, on) {
  if (on) state.selected.add(id);
  else state.selected.delete(id);
  updateSelectionUI();
}

// Plain click: select only this row (clears the rest) and open it.
export function clickItem(id) {
  state.selected.clear();
  state.selected.add(id);
  selectSession(id);
}

// Shift-click: select the inclusive span between the anchor row and this row,
// replacing the previous selection; this row becomes the new anchor (the
// "latest selected" item) and is opened.
export function rangeSelect(id) {
  const ids = groupedSessions().map((g) => g[1]).flat().map((s) => s.id);
  const a = ids.indexOf(state.selectAnchor);
  const b = ids.indexOf(id);
  if (a === -1) {
    clickItem(id); // no anchor yet: behave like a plain click
    return;
  }
  const [lo, hi] = a < b ? [a, b] : [b, a];
  state.selected.clear();
  for (let i = lo; i <= hi; i++) state.selected.add(ids[i]);
  selectSession(id);
}

// Click on empty space (not on a row): clear the selection.
export function clearSelection() {
  if (state.selected.size === 0 && !state.selectAnchor) return;
  state.selected.clear();
  state.selectAnchor = null;
  updateSelectionUI();
}

export function updateSelectionUI() {
  const n = state.selected.size;
  $("#f-selcount").textContent = `${n} selected`;
  const bar = $("#bulk-bar");
  bar.style.display = n > 0 ? "flex" : "none";
  const all = $("#f-selectall");
  all.checked = state.sessions.length > 0 && state.sessions.every((s) => state.selected.has(s.id));
  all.indeterminate = n > 0 && !all.checked;
  // sync row highlights without a full re-render (keeps scroll position)
  document.querySelectorAll("#session-list .session-item").forEach((el) => {
    el.classList.toggle("selected", state.selected.has(el.dataset.id));
    el.classList.toggle("active", el.dataset.id === state.selectAnchor);
  });
}

export async function bulkAction(action) {
  const ids = [...state.selected];
  if (ids.length === 0) return;
  const verb = action === "delete" ? "deleted" : action === "archive" ? "archived" : "unarchived";
  if (action === "delete" && !confirm(`Delete ${ids.length} session(s) and all their messages? This cannot be undone.`)) return;
  try {
    const res = await api(`${base()}/sessions/bulk`, { method: "POST", body: { action, ids } });
    toast(`${res.affected} session(s) ${verb}`);
    if (state.selectedId && state.selected.has(state.selectedId)) {
      state.detail = null;
      state.selectedId = null;
      detailEl.innerHTML = selectPromptHtml();
    }
    state.selected.clear();
    state.selectAnchor = null;
    await loadSessions();
  } catch (err) { toast(err.message, "error"); }
}
