import { state } from "./state.js";
import { $, detailEl, api, toast } from "./util.js";
import { refreshAll } from "./data.js";

// ---------------------------------------------------------------------------
// navigation: home <-> viewer
// ---------------------------------------------------------------------------
export function resetViewerState() {
  state.selected.clear();
  state.selectAnchor = null;
  state.selectedId = null;
  state.detail = null;
  state.projectFilter = "";
  state.showArchived = false;
}

export function showHome() {
  state.source = null;
  resetViewerState();
  $("#viewer").classList.add("hidden");
  $("#home").classList.remove("hidden");
}

export async function showViewer(source) {
  state.source = source;
  resetViewerState();
  $("#home").classList.add("hidden");
  $("#viewer").classList.remove("hidden");
  $("#app-logo").innerHTML = 'Open<span>Crup</span>';
  $("#f-search").value = "";
  detailEl.innerHTML = '<div class="empty"><div class="big">💬</div><div>Select a conversation to view it</div></div>';
  try {
    if (source === "cursor") {
      const env = await api("/api/cursor/env");
      window.__home = env.home;
      $("#db-sub").textContent = `${env.count} conversations · ${env.dir.replace(/^\/Users\/[^/]+/, "~")}`;
    } else {
      const env = await api("/api/env");
      window.__home = env.home;
      $("#db-sub").textContent = `opencode v${env.version} · ${env.db.replace(/^\/Users\/[^/]+/, "~")}`;
    }
  } catch {}
  await refreshAll().catch((err) => toast(err.message, "error"));
}

// home source cards: rendered from /api/sources (only found sources + an "add" card)
const SOURCE_META = {
  opencode: {
    name: "opencode", desc: "opencode sessions",
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="4" width="19" height="16" rx="3"/><path d="M7 9.5l3.5 2.5L7 14.5"/><line x1="12.5" y1="14.5" x2="16" y2="14.5"/></svg>',
  },
  cursor: {
    name: "cursor", desc: "Cursor agent chats",
    icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 3l14 7-6 1.5L9.5 19z"/></svg>',
  },
};

function sourceCardHtml(source, info) {
  const m = SOURCE_META[source];
  const noun = source === "opencode" ? "sessions" : "conversations";
  return `<div class="source-card" data-source="${source}">
    <div class="icon">${m.icon}</div>
    <div class="name">${m.name}</div>
    <div class="desc">${m.desc}</div>
    <div class="count">${info.count} ${noun}</div>
  </div>`;
}

function addCardHtml() {
  return `<div class="source-card add" id="card-add">
    <div class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
    <div class="name">add</div>
    <div class="desc">point to Cursor data</div>
    <div class="count"></div>
  </div>`;
}

export async function renderHome() {
  const el = $("#home-cards");
  let sources = {};
  try { sources = await api("/api/sources"); } catch {}
  const cards = [];
  if (sources.opencode && sources.opencode.found) cards.push(sourceCardHtml("opencode", sources.opencode));
  if (sources.cursor && sources.cursor.found) cards.push(sourceCardHtml("cursor", sources.cursor));
  cards.push(addCardHtml()); // always present; max 3 cards total
  el.innerHTML = cards.join("");
  el.querySelectorAll(".source-card[data-source]").forEach((c) =>
    c.addEventListener("click", () => showViewer(c.dataset.source)));
  const add = el.querySelector("#card-add");
  if (add) add.addEventListener("click", addSource);
}

// "+" card: pick a folder, resolve its full path, save it as the Cursor source
export function addSource() {
  const input = document.createElement("input");
  input.type = "file"; input.multiple = true;
  input.setAttribute("webkitdirectory", ""); input.setAttribute("directory", "");
  input.style.cssText = "position:fixed; top:0; left:0; width:1px; height:1px; opacity:0; pointer-events:none;";
  document.body.appendChild(input);
  input.addEventListener("change", async () => {
    const files = Array.from(input.files || []);
    input.remove();
    if (!files.length) return;
    const rel = files[0].webkitRelativePath || files[0].name;
    const name = rel.split("/")[0];
    const children = new Set();
    for (const f of files) {
      const s = (f.webkitRelativePath || "").split("/");
      if (s.length > 1) children.add(s[1]);
      if (children.size >= 50) break;
    }
    try {
      const res = await api("/api/resolve-dir", { method: "POST", body: { name, children: [...children] } });
      if (!res.path) throw new Error("could not resolve path");
      await api("/api/sources/cursor", { method: "POST", body: { path: res.path } });
      toast("Cursor added");
      renderHome();
    } catch (err) { toast(err.message, "error"); }
  });
  input.addEventListener("cancel", () => input.remove());
  input.click();
}
