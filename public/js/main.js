import { state } from "./state.js";
import { $, api, toast } from "./util.js";
import { loadSessions, renderFilterMenu, closeFilterMenu, refreshAll } from "./data.js";
import { renderSessionList, bulkAction, clearSelection } from "./list.js";
import { showHome, renderHome, showViewer } from "./nav.js";
import { selectSession } from "./detail.js";

// ---------------------------------------------------------------------------
// init
// ---------------------------------------------------------------------------
let searchTimer;
$("#f-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadSessions, 250);
});
// Filter icon: reveal/hide the project menu below it
$("#f-filter").addEventListener("click", (e) => {
  e.stopPropagation();
  const menu = $("#f-menu");
  if (!menu) return;
  renderFilterMenu(); // refresh checkmarks before showing
  menu.classList.toggle("open");
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".filter-wrap")) closeFilterMenu();
});
$("#f-selectall").addEventListener("change", (e) => {
  if (e.target.checked) state.sessions.forEach((s) => state.selected.add(s.id));
  else state.selected.clear();
  renderSessionList();
});
$("#bulk-archive").addEventListener("click", () => bulkAction("archive"));
$("#bulk-unarchive").addEventListener("click", () => bulkAction("unarchive"));
$("#bulk-delete").addEventListener("click", () => bulkAction("delete"));
$("#btn-refresh").addEventListener("click", () => refreshAll().then(() => toast("refreshed")));

$("#btn-home").addEventListener("click", showHome);
// While Shift is held: disable text selection app-wide (shift-click safe)
window.addEventListener("keydown", (e) => {
  if (e.key === "Shift") document.body.classList.add("shift-held");
});
window.addEventListener("keyup", (e) => {
  if (e.key === "Shift") document.body.classList.remove("shift-held");
});
window.addEventListener("blur", () => document.body.classList.remove("shift-held"));
// Safety net: if Shift is already held at mousedown (keydown may not have fired),
// make sure selection is disabled for that drag
window.addEventListener("mousedown", (e) => {
  if (e.shiftKey) document.body.classList.add("shift-held");
});
// Click outside a row (detail pane, empty list space) clears the selection;
// the filter/bulk controls are excluded so they keep acting on the selection
$("main").addEventListener("click", (e) => {
  if (e.target.closest(".session-item")) return;
  if (e.target.closest(".filters, .bulk-bar, .proj-head")) return;
  clearSelection();
});

(async () => {
  try {
    const env = await api("/api/env");
    window.__home = env.home;
  } catch {}
  renderHome();
  // deep link: ?source=opencode&session=<id> (shareable / screenshot-able views)
  const params = new URLSearchParams(location.search);
  const src = params.get("source");
  if (src && ["opencode", "cursor", "claude"].includes(src)) {
    await showViewer(src, params.get("account"));
    const sid = params.get("session");
    if (sid) selectSession(sid);
  }
})();
