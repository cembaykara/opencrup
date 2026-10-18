import { state } from "./state.js";

export const $ = (sel) => document.querySelector(sel);
export const detailEl = $("#detail");

// ---------------------------------------------------------------------------
// utils
// ---------------------------------------------------------------------------
export function escapeHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function md(text) {
  const codes = [];
  let s = escapeHtml(text);
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    codes.push(`<pre><code>${code.replace(/\n$/, "")}</code></pre>`);
    return `\u0000${codes.length - 1}\u0000`;
  });
  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/\n/g, "<br>");
  s = s.replace(/\u0000(\d+)\u0000/g, (m, i) => codes[Number(i)]);
  return s;
}

export function relTime(ts) {
  if (!ts) return "";
  const d = Date.now() - ts;
  const min = Math.floor(d / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
}

export function fmtTime(ts) {
  return ts ? new Date(ts).toLocaleString() : "";
}

export function shortModel(modelStr) {
  if (!modelStr) return null;
  try {
    const m = JSON.parse(modelStr);
    return m.variant ? `${m.id}#${m.variant}` : m.id;
  } catch { return modelStr; }
}

export function tilde(p) {
  const home = window.__home;
  if (p && home && p.startsWith(home)) return "~" + p.slice(home.length);
  return p || "";
}

// Feather-style inline icons (stroke, currentColor) for empty/loading states
const ICON_CHAT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
const ICON_WARN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;

export function emptyHtml(big, text) {
  return `<div class="empty"><div class="big">${big}</div><div>${text}</div></div>`;
}
export const selectPromptHtml = () => emptyHtml(ICON_CHAT, "Select a conversation to view it");
export const loadingHtml = () => emptyHtml('<span class="spinner"></span>', "Loading…");
export const errorHtml = (msg) => emptyHtml(ICON_WARN, escapeHtml(msg));

export function toast(msg, type = "ok") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `show ${type}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.className = ""), 2500);
}

export async function api(path, opts = {}) {
  // Claude supports multiple accounts; thread the active one through as ?account=
  if (state.source === "claude" && state.account && state.account !== "default") {
    path += (path.includes("?") ? "&" : "?") + "account=" + encodeURIComponent(state.account);
  }
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// source-aware API base + path builders
const API_BASE = { opencode: "/api", cursor: "/api/cursor", claude: "/api/claude" };
export function base() { return API_BASE[state.source] || "/api"; }
export function sessionsUrl(params) {
  const p = new URLSearchParams();
  if (params.q) p.set("q", params.q);
  if (params.project) p.set(state.source === "opencode" ? "project_id" : "project", params.project);
  if (params.archived) p.set("archived", "1");
  return `${base()}/sessions?${p}`;
}
export function messageUrl(mid) {
  if (state.source === "cursor" || state.source === "claude")
    return `${base()}/sessions/${encodeURIComponent(state.detail.id)}/messages/${encodeURIComponent(mid)}`;
  return `${base()}/messages/${encodeURIComponent(mid)}`;
}
