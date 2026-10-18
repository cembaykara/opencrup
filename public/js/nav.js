import { state } from "./state.js";
import { $, detailEl, api, toast, selectPromptHtml, saveView, clearView } from "./util.js";
import { refreshAll } from "./data.js";

// ---------------------------------------------------------------------------
// navigation: home <-> viewer
// ---------------------------------------------------------------------------
export function resetViewerState() {
  state.account = "default";
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
  clearView(); // going back: don't restore this view on refresh
  $("#viewer").classList.add("hidden");
  $("#home").classList.remove("hidden");
}

export async function showViewer(source, account) {
  state.source = source;
  resetViewerState();
  state.account = (source === "claude" && account) ? account : "default";
  saveView({ source, account: state.account });
  $("#home").classList.add("hidden");
  $("#viewer").classList.remove("hidden");
  $("#app-logo").innerHTML = 'Open<span>Crup</span>';
  $("#f-search").value = "";
  detailEl.innerHTML = selectPromptHtml();
  try {
    if (source === "cursor") {
      const env = await api("/api/cursor/env");
      window.__home = env.home;
      $("#db-sub").textContent = `${env.count} conversations · ${env.dir.replace(/^\/Users\/[^/]+/, "~")}`;
    } else if (source === "claude") {
      const env = await api("/api/claude/env");
      window.__home = env.home;
      $("#db-sub").textContent = `${env.count} sessions · ${env.dir.replace(/^\/Users\/[^/]+/, "~")}`;
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
  claude: {
    name: "claude", desc: "Claude Code sessions",
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17l6-11 4 7 2-3 4 7z"/><line x1="4" y1="20" x2="20" y2="20"/></svg>',
  },
};

function sourceCardHtml(source, info) {
  const m = SOURCE_META[source];
  const noun = source === "cursor" ? "conversations" : "sessions";
  return `<div class="source-card" data-source="${source}">
    <div class="icon">${m.icon}</div>
    <div class="name">${m.name}</div>
    <div class="desc">${m.desc}</div>
    <div class="count">${info.count} ${noun}</div>
  </div>`;
}

function claudeAccountCardHtml(acc) {
  const m = SOURCE_META.claude;
  return `<div class="source-card" data-source="claude" data-account="${acc.id}">
    <div class="icon">${m.icon}</div>
    <div class="name">${acc.label}</div>
    <div class="desc">${m.desc}</div>
    <div class="count">${acc.count} sessions</div>
  </div>`;
}

function addCardHtml() {
  return `<div class="source-card add" id="card-add">
    <div class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></div>
    <div class="name">add</div>
    <div class="desc">point to an app's data</div>
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
  // claude: one card per account (default + any the user added)
  const claudeAccounts = (sources.claude_accounts && sources.claude_accounts.length)
    ? sources.claude_accounts
    : (sources.claude && sources.claude.found
        ? [{ id: "default", label: "Claude Code", path: sources.claude.path, found: true, count: sources.claude.count }]
        : []);
  for (const acc of claudeAccounts) {
    if (acc.found) cards.push(claudeAccountCardHtml(acc));
  }
  cards.push(addCardHtml()); // always present
  el.innerHTML = cards.join("");
  el.querySelectorAll(".source-card[data-source]").forEach((c) =>
    c.addEventListener("click", () => showViewer(c.dataset.source, c.dataset.account)));
  const add = el.querySelector("#card-add");
  if (add) add.addEventListener("click", addSource);
}

// "+" card: pick a folder, resolve its full path, save it as the Cursor source
export function addSource() {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal">
      <h2>Add a source</h2>
      <p class="modal-sub">Pick an app and where its projects live. We scan the path to confirm it's real — if we can't figure it out, the app stays out.</p>
      <div class="field">
        <label>App</label>
        <select id="add-app">
          <option value="opencode">opencode</option>
          <option value="cursor">Cursor</option>
          <option value="claude">Claude Code</option>
        </select>
      </div>
      <div class="field">
        <label>Projects path</label>
        <div class="path-row">
          <input id="add-path" placeholder="choose a folder, or paste a path">
          <button class="btn small" id="add-pick">Choose…</button>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn" id="add-cancel">Cancel</button>
        <button class="btn primary" id="add-go">Add</button>
      </div>
    </div>`;
  document.body.appendChild(backdrop);

  const close = () => backdrop.remove();
  backdrop.querySelector("#add-cancel").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });

  // folder picker (hidden input, triggered by "Choose…")
  backdrop.querySelector("#add-pick").addEventListener("click", () => {
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
        backdrop.querySelector("#add-path").value = res.path;
      } catch (err) { toast(err.message, "error"); }
    });
    input.addEventListener("cancel", () => input.remove());
    input.click();
  });

  backdrop.querySelector("#add-go").addEventListener("click", async () => {
    const app = backdrop.querySelector("#add-app").value;
    const picked = backdrop.querySelector("#add-path").value.trim();
    if (!picked) return toast("choose a folder first", "error");
    const btn = backdrop.querySelector("#add-go");
    btn.disabled = true; btn.textContent = "Adding…";
    try {
      // if the scan already found this app elsewhere, ask which location to use
      let path = picked;
      try {
        const sources = await api("/api/sources");
        const found = sources[app];
        const norm = (p) => String(p).replace(app === "opencode" ? /opencode\.db$/ : /\/$/, "").replace(/\/$/, "");
        if (found && found.found && norm(found.path) !== norm(picked)) {
          const usePicked = confirm(
            `The scan already found ${app} at:\n${found.path}\n\nYou picked:\n${picked}\n\nUse your pick?`);
          path = usePicked ? picked : found.path;
        }
      } catch {}
      await api("/api/sources/add", { method: "POST", body: { app, path } });
      close();
      toast(`${app} added`);
      renderHome();
    } catch (err) { toast(err.message, "error"); btn.disabled = false; btn.textContent = "Add"; }
  });
}
