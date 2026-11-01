// Shared helpers for host, player and editor pages.
const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LETTERS = "ABCD";

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, ms = 2600) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

// EventSource that reconnects (including after a phone wakes from sleep).
function liveStream(urlFn, onState, onStatus) {
  let es = null;
  const open = () => {
    if (es) es.close();
    es = new EventSource(urlFn());
    es.addEventListener("state", (e) => onState(JSON.parse(e.data)));
    es.onopen = () => onStatus && onStatus(true);
    es.onerror = () => {
      onStatus && onStatus(false);
      if (es.readyState === EventSource.CLOSED) setTimeout(open, 1500);
    };
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && (!es || es.readyState === EventSource.CLOSED)) open();
  });
  open();
  return { reopen: open, close: () => es && es.close() };
}

function shape(i) { return `<span class="shape"></span>`; }
function badge() { return `<span class="badge"><span class="shape"></span></span>`; }

const BRAND = { name: "Know Signal", tagline: "Out of range. Never out of answers." };
function logo(live = false, word = true) {
  return `<span class="logo ${live ? "live" : ""}"><span class="mark"><i></i><i></i><i></i><i></i></span>${word ? `<span class="word"><b>know</b>signal</span>` : ""}</span>`;
}
const mark = (live = false) => logo(live, false);

// Theme: "night" (default) or "day" (for washed-out projectors in bright rooms).
const Theme = {
  get() { return localStorage.getItem("ks-theme") || "night"; },
  apply(t = Theme.get()) { document.documentElement.dataset.theme = t; },
  toggle() { const t = Theme.get() === "night" ? "day" : "night"; localStorage.setItem("ks-theme", t); Theme.apply(t); return t; },
};
Theme.apply();
