import { state } from "./state.js";
import { $, api, base, tilde, escapeHtml, sessionsUrl, listLoadingHtml } from "./util.js";
import { renderSessionList } from "./list.js";
import { updateHitNav } from "./detail.js";

// ---------------------------------------------------------------------------
// loading
// ---------------------------------------------------------------------------
export async function loadProjects() {
  state.projects = await api(base() + "/projects");
  renderFilterMenu();
}

// Build the project filter menu (All projects + each project); the active one gets a checkmark
export function renderFilterMenu() {
  const menu = $("#f-menu");
  if (!menu) return;
  const items = [
    { id: "", label: "All projects" },
    ...state.projects.map((p) => ({ id: p.id, label: `${tilde(p.worktree)} (${p.session_count})` })),
  ];
  const projHtml = items.map((it) => {
    const active = it.id === state.projectFilter;
    return `<div class="filter-item" data-kind="project" data-id="${escapeHtml(it.id)}">
      <span class="check">${active ? "✓" : ""}</span>
      <span class="label">${escapeHtml(it.label)}</span>
    </div>`;
  }).join("");
  const archHtml = `<div class="filter-sep"></div>
    <div class="filter-item" data-kind="archived">
      <span class="check">${state.showArchived ? "✓" : ""}</span>
      <span class="label">Show archived</span>
    </div>`;
  menu.innerHTML = projHtml + archHtml;
  menu.querySelectorAll(".filter-item").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.dataset.kind === "archived") {
        state.showArchived = !state.showArchived;
      } else {
        state.projectFilter = el.dataset.id;
      }
      closeFilterMenu();
      renderFilterMenu();
      loadSessions();
    });
  });
}
export function closeFilterMenu() {
  const menu = $("#f-menu");
  if (menu) menu.classList.remove("open");
}

export async function loadModels() {
  if (state.source === "cursor") { state.models = []; return; }
  try {
    state.models = await api(base() + "/models");
  } catch {
    state.models = []; // source without a /models endpoint (e.g. claude)
  }
}

export async function loadSessions() {
  const q = $("#f-search").value.trim();
  const project = state.projectFilter;
  const archived = state.showArchived;
  // slow sources (e.g. cursor) leave the list blank while fetching — show a
  // spinner whenever the list is empty so it's clear a load is in progress
  const listEl = $("#session-list");
  const showSpinner = listEl && !listEl.firstElementChild;
  if (showSpinner) listEl.innerHTML = listLoadingHtml();
  let sessions;
  try {
    sessions = await api(sessionsUrl({ q, project, archived }));
  } catch (err) {
    // don't leave a spinner behind on failure (it may have been set by showViewer)
    if (listEl.querySelector(".list-loading")) listEl.innerHTML = "";
    throw err;
  }
  state.sessions = sessions;
  // drop selections (and the range anchor) that are no longer in the visible list
  const visible = new Set(state.sessions.map((s) => s.id));
  for (const id of [...state.selected]) if (!visible.has(id)) state.selected.delete(id);
  if (state.selectAnchor && !visible.has(state.selectAnchor)) state.selectAnchor = null;
  renderSessionList();
  updateHitNav(); // the open detail's hit stepper tracks the (re)loaded hits
}

export async function refreshAll() {
  await Promise.all([loadProjects(), loadModels(), loadSessions()]);
}
