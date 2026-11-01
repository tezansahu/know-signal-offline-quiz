// Know Signal host / projector screen.
const app = $("#app");
const nextBtn = $("#next");
let state = { phase: "init" };
let lastKey = "";
let info = null;
let tickTimer = null;
let knownPlayers = new Set();
let selectedQuiz = localStorage.getItem("quiz-selected") || null;

const ICONS = {
  sound: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/></svg>`,
  muted: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M17 9l5 6M22 9l-5 6"/></svg>`,
  sun: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`,
  moon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>`,
};

const noun = (s, n) => (s.teams ? (n === 1 ? "team" : "teams") : (n === 1 ? "player" : "players"));
const secs = (ms) => `${(ms / 1000).toFixed(2)}s`;

$("#brand").innerHTML = logo();
liveStream(() => "/api/host/events", onState, (ok) => $("#conn").classList.toggle("off", !ok));

function onState(s) {
  s.receivedAt = performance.now();
  const key = `${s.phase}:${s.qi}`;
  const prev = state;
  state = s;
  if (key !== lastKey) {
    lastKey = key;
    render(s, prev);
  } else {
    update(s);
  }
  setChrome(s);
  setNext(s);
}

function render(s, prev) {
  clearInterval(tickTimer);
  if (s.phase !== "question") Sound.stopMusic();
  $("#hints").classList.toggle("hidden", s.phase === "final");
  const screens = { none: renderSetup, lobby: renderLobby, question: renderQuestion,
                    reveal: renderReveal, leaderboard: renderLeaderboard, final: renderFinal };
  (screens[s.phase] || renderSetup)(s, prev);
}

function update(s) {
  if (s.phase === "lobby") updateLobby(s);
  if (s.phase === "question") {
    const a = $("#answered");
    if (a && a.textContent !== String(s.answered)) {
      a.textContent = s.answered;
      a.animate([{ transform: "scale(1.35)" }, { transform: "scale(1)" }], { duration: 250, easing: "ease-out" });
    }
  }
}

function setChrome(s) {
  const inSession = s.phase && !["none", "init"].includes(s.phase);
  $("#crumb").textContent = inSession ? s.title : "";
  $("#roomchip").innerHTML = inSession
    ? `<span class="dot"></span><span class="num">${s.playerCount}</span> ${s.teams ? "teams" : "in the room"}` : "";
}

function setNext(s) {
  const labels = {
    lobby: "Start the show",
    question: "Skip timer",
    reveal: s.afterReveal === "final" ? "Reveal the winners" : s.afterReveal === "question" ? "Next question" : "Standings",
    leaderboard: "Next question",
  };
  const label = labels[s.phase];
  nextBtn.classList.toggle("hidden", !label);
  if (label) nextBtn.innerHTML = `${label} <kbd>Space</kbd>`;
  nextBtn.disabled = s.phase === "lobby" && s.playerCount === 0;
}

async function next() {
  if (nextBtn.classList.contains("hidden") || nextBtn.disabled) return;
  Sound.unlock();
  nextBtn.disabled = true;
  try { await api("/api/host/next", {}); } catch (e) { toast(e.message); }
  setNext(state);
}

function paintIcons() {
  $("#mute").innerHTML = Sound.muted ? ICONS.muted : ICONS.sound;
  $("#theme").innerHTML = Theme.get() === "night" ? ICONS.sun : ICONS.moon;
}
nextBtn.onclick = next;
$("#mute").onclick = () => { Sound.toggleMute(); paintIcons(); };
$("#theme").onclick = () => { Theme.toggle(); paintIcons(); };
$("#fs").onclick = toggleFullscreen;
paintIcons();
function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
}
document.addEventListener("keydown", (e) => {
  if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
  const k = e.key.toLowerCase();
  if (e.key === " " || e.key === "Enter" || e.key === "ArrowRight") { e.preventDefault(); next(); }
  else if (k === "m") $("#mute").click();
  else if (k === "f") toggleFullscreen();
  else if (k === "t") $("#theme").click();
});

async function loadInfo() {
  info = await api("/api/info");
  return info;
}

function playerUrl() {
  const ip = localStorage.getItem("quiz-ip");
  const host = info.ips.includes(ip) ? ip : info.ips[0];
  if (!host) return null;
  return `http://${host}${info.port === 80 ? "" : ":" + info.port}/`;
}

function qrSvg(text) {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 6, margin: 1, scalable: true });
}

const wifiEsc = (s) => s.replace(/([\\;,:"])/g, "\\$1");

// Ask Windows for the hotspot's state/name/password; remembers the name/password when found.
async function detectHotspot() {
  try {
    const hs = await api("/api/hotspot");
    if (!hs.ok || !hs.ssid) return hs.ok ? null : hs;
    await api("/api/config", { ssid: hs.ssid, password: hs.password || "" });
    if (info) info.config = { ssid: hs.ssid, password: hs.password || "" };
    return hs;
  } catch { return null; }
}

function renderHotspotState(hs) {
  const pill = $("#hsstate"), btn = $("#hsbtn"), hint = $("#wifihint");
  if (!pill) return;
  const on = hs && hs.state === "on";
  pill.className = `hspill ${on ? "on" : hs && hs.state === "unavailable" ? "bad" : ""}`;
  pill.innerHTML = on ? `<span class="dot"></span> On · ${hs.clients ?? 0} connected`
    : hs && hs.state === "unavailable" ? "Unavailable" : "Off";
  btn.textContent = on ? "Stop hotspot" : "Start hotspot";
  btn.classList.toggle("ghost", on);
  btn.dataset.on = on ? "1" : "";
  hint.innerHTML = !hs ? "Checking this laptop's hotspot…"
    : hs.reason ? `<span class="warn" style="display:block">${esc(hs.reason)}</span>`
    : on ? `Phones join <b>${esc(hs.ssid)}</b>. The lobby shows it as a "Join Wi‑Fi" QR.${hs.sharing === "offline" ? " Running fully offline." : ""}`
    : `Set a name and password, then start it. No internet needed.`;
}

// ---------------- setup ----------------
async function renderSetup() {
  knownPlayers = new Set();
  app.innerHTML = `<div class="screen"><div class="setup">
    <section class="hero">
      <div class="eyebrow">${esc(BRAND.tagline)}</div>
      <h1 class="display">Pick a quiz.</h1>
      <p class="sub">Everyone plays on this laptop's own Wi‑Fi. No internet, no sign‑ups, no player caps.</p>
      <div class="quiz-list" id="quizzes"><p class="hint">Loading…</p></div>
      <div class="herobtns"><a class="btn ghost small" href="/edit">＋ Create or edit quizzes</a>
        <button class="btn ghost small hidden" id="results">Open results folder</button>
        <button class="btn ghost small hidden" id="quit">Quit Know Signal</button></div>
    </section>
    <aside class="card panel">
      <div class="hshead"><h3>Wi‑Fi hotspot</h3><span class="hspill" id="hsstate">…</span></div>
      <div class="row2">
        <div class="field"><label>Wi‑Fi name</label><input class="input" id="ssid" placeholder="e.g. QuizTime"></div>
        <div class="field"><label>Password</label><input class="input" id="pw" placeholder="8+ characters"></div>
      </div>
      <button class="btn" id="hsbtn">Start hotspot</button>
      <p class="hint" id="wifihint">Checking this laptop's hotspot…</p>
      <div class="sep"></div>
      <h3>Show settings</h3>
      <label class="switch"><input type="checkbox" id="suspense"><i></i>
        <span><b>Suspense finish</b><br><span class="hint">Standings go dark for the last two questions. The winner is revealed on the podium.</span></span></label>
      <label class="switch"><input type="checkbox" id="teams"><i></i>
        <span><b>Teams mode</b><br><span class="hint">One phone per group, for rooms bigger than the hotspot.</span></span></label>
      <div class="field"><label>Players open</label><select class="input" id="ip"></select></div>
      <p class="hint" id="iphint"></p>
      <button class="btn" id="open" disabled>Open the room →</button>
    </aside>
  </div></div>`;
  $("#teams").checked = localStorage.getItem("quiz-teams") === "1";
  $("#teams").onchange = (e) => localStorage.setItem("quiz-teams", e.target.checked ? "1" : "0");
  $("#suspense").checked = localStorage.getItem("quiz-suspense") !== "0";
  $("#suspense").onchange = (e) => localStorage.setItem("quiz-suspense", e.target.checked ? "1" : "0");

  const [quizzes] = await Promise.all([api("/api/quizzes"), loadInfo()]);
  $("#ssid").value = info.config.ssid || "";
  $("#pw").value = info.config.password || "";
  const saveCfg = () => api("/api/config", { ssid: $("#ssid").value.trim(), password: $("#pw").value });
  $("#ssid").onchange = saveCfg;
  $("#pw").onchange = saveCfg;
  if (info.app) {
    $("#results").classList.remove("hidden");
    $("#quit").classList.remove("hidden");
    $("#results").onclick = () => api("/api/host/open-results", {});
    $("#quit").onclick = async () => {
      if (!confirm("Quit Know Signal? Phones will disconnect.")) return;
      await api("/api/host/quit", {}).catch(() => {});
      document.body.innerHTML = `<div style="display:grid;place-items:center;height:100vh;text-align:center"><div>${logo()}<p class="hint">Know Signal has stopped. You can close this window.</p></div></div>`;
      window.close();
    };
  }

  detectHotspot().then((hs) => {
    if (hs && hs.ssid) { $("#ssid").value = hs.ssid; $("#pw").value = hs.password || ""; }
    renderHotspotState(hs || { state: "off" });
  });
  const refreshIps = async () => { await loadInfo(); fillIps(); };
  $("#hsbtn").onclick = async () => {
    const btn = $("#hsbtn");
    const stopping = btn.dataset.on === "1";
    if (!stopping && $("#pw").value.length < 8) { toast("The Wi‑Fi password needs at least 8 characters."); $("#pw").focus(); return; }
    btn.disabled = true;
    btn.textContent = stopping ? "Stopping…" : "Starting…";
    const hs = await api("/api/hotspot", stopping ? { action: "stop" }
      : { action: "start", ssid: $("#ssid").value.trim(), password: $("#pw").value }).catch((e) => ({ reason: e.message, state: "off" }));
    btn.disabled = false;
    renderHotspotState(hs);
    if (hs.ok && hs.state === "on") {
      info.config = { ssid: hs.ssid, password: hs.password || "" };
      setTimeout(refreshIps, 2500);
      setTimeout(refreshIps, 6000);
    }
  };

  const ipSel = $("#ip");
  const fillIps = () => {
    if (!$("#ip")) return;
    const cur = localStorage.getItem("quiz-ip");
    const hotspotIp = info.ips.find((ip) => ip.startsWith("192.168.137."));
    ipSel.innerHTML = info.ips.map((ip) => `<option ${(hotspotIp ? ip === hotspotIp : ip === cur) ? "selected" : ""}>${ip}</option>`).join("")
      || `<option value="">No network yet</option>`;
    $("#iphint").innerHTML = info.ips.length === 0 ? "Start the hotspot above. Its address appears here."
      : hotspotIp ? "192.168.137.1 is this laptop's own hotspot."
      : "On a shared Wi‑Fi or LAN instead? Pick its address.";
  };
  fillIps();
  ipSel.onchange = () => localStorage.setItem("quiz-ip", ipSel.value);

  const list = $("#quizzes");
  if (!quizzes.length) {
    list.innerHTML = `<p class="hint">No quizzes yet. Create your first one to get started.</p>`;
  } else {
    if (!quizzes.some((q) => q.id === selectedQuiz)) selectedQuiz = quizzes[0].id;
    list.innerHTML = quizzes.map((q) => `<button class="quiz-card ${q.id === selectedQuiz ? "sel" : ""}" data-id="${q.id}">
      <span class="tick">✓</span><b>${esc(q.title)}</b>
      <span class="meta"><span>${q.count} question${q.count === 1 ? "" : "s"}</span>${mark()}</span></button>`).join("");
    list.onclick = (e) => {
      const card = e.target.closest(".quiz-card");
      if (!card) return;
      selectedQuiz = card.dataset.id;
      localStorage.setItem("quiz-selected", selectedQuiz);
      list.querySelectorAll(".quiz-card").forEach((c) => c.classList.toggle("sel", c === card));
    };
    list.ondblclick = () => $("#open").click();
    $("#open").disabled = false;
  }
  $("#open").onclick = async () => {
    Sound.unlock();
    if (ipSel.value) localStorage.setItem("quiz-ip", ipSel.value);
    await saveCfg();
    try { await api("/api/host/start", { quizId: selectedQuiz, teams: $("#teams").checked, suspense: $("#suspense").checked }); }
    catch (e) { toast(e.message); }
  };
}

// ---------------- lobby ----------------
const ROOM_LEVELS = [[0, "Searching for signal…"], [1, "Weak signal"], [5, "Getting stronger"], [15, "Strong signal"], [30, "Full signal"]];

async function renderLobby(s) {
  if (!info) await loadInfo();
  const url = playerUrl();
  const cfg = info.config;
  const wifiQr = cfg.password
    ? `WIFI:T:WPA;S:${wifiEsc(cfg.ssid)};P:${wifiEsc(cfg.password)};;`
    : `WIFI:T:nopass;S:${wifiEsc(cfg.ssid || "")};;`;
  const wifi = cfg.ssid
    ? `<div class="qr">${qrSvg(wifiQr)}</div><div class="cap">Network <b>${esc(cfg.ssid)}</b> · Password <b>${esc(cfg.password || "none")}</b></div>`
    : `<div class="qr missing">Wi‑Fi QR unavailable.<br>Start the hotspot, or add its name and password on the setup screen.</div>`;
  const open = url
    ? `<div class="qr">${qrSvg(url)}</div><div class="cap">Opens the quiz in any browser. No app needed.</div>`
    : `<div class="qr missing">No network found.<br>Start the hotspot, then press F5.</div>`;
  app.innerHTML = `<div class="screen"><div class="lobby">
      <section class="card joinpanel">
        <div class="qrs">
          <div class="step"><div class="lab"><span class="n">1</span>Join the Wi‑Fi</div>${wifi}</div>
          <div class="step"><div class="lab"><span class="n">2</span>Open the quiz</div>${open}</div>
        </div>
        ${url ? `<div class="typeurl"><span class="eyebrow">QR not scanning? Type</span><span class="display">${esc(url.replace("http://", "").replace(/\/$/, ""))}</span></div>` : ""}
        <p class="hint">Phone says <b>"No internet"</b>? Tap <b>Stay connected</b>. Page won't load? Switch off mobile data.</p>
      </section>
      <section class="room">
        <div class="eyebrow">Now showing</div>
        <h1 class="display">${esc(s.title)}</h1>
        <div class="meter"><div class="bars" id="bars"><i></i><i></i><i></i><i></i></div>
          <span class="display count num" id="count">0</span>
          <span class="lbl"><b id="level"></b><span class="hint">${s.teams ? "teams" : "players"} in the room</span></span></div>
        <div class="chips" id="chips"></div>
      </section></div></div>`;
  $("#chips").onclick = async (e) => {
    const chip = e.target.closest(".chip");
    if (chip && confirm(`Remove "${chip.textContent}" from the quiz?`)) {
      await api("/api/host/kick", { token: chip.dataset.token });
    }
  };
  updateLobby(s, true);
  if (!cfg.ssid) {
    detectHotspot().then((hs) => { if (hs && hs.ssid && state.phase === "lobby") renderLobby(state); });
  }
}

function updateLobby(s, initial = false) {
  const chips = $("#chips");
  if (!chips) return;
  const n = s.playerCount;
  $("#count").textContent = n;
  const lvl = ROOM_LEVELS.filter(([min]) => n >= min).length - 1;
  $("#level").textContent = ROOM_LEVELS[lvl][1];
  $("#bars").querySelectorAll("i").forEach((b, i) => {
    const on = i < lvl;
    if (on && !b.classList.contains("on") && !initial) { b.classList.add("bump"); setTimeout(() => b.classList.remove("bump"), 400); }
    b.classList.toggle("on", on);
  });
  const tokens = new Set(s.players.map((p) => p.token));
  chips.querySelectorAll(".chip").forEach((c) => { if (!tokens.has(c.dataset.token)) c.remove(); });
  let added = false;
  for (const p of s.players) {
    if (!chips.querySelector(`[data-token="${p.token}"]`)) {
      const c = document.createElement("span");
      c.className = `chip opt-${[...p.token].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 4}`;
      c.dataset.token = p.token;
      c.title = "Click to remove";
      c.textContent = p.name;
      chips.prepend(c);
      if (!knownPlayers.has(p.token)) added = true;
      knownPlayers.add(p.token);
    }
  }
  if (added && !initial) Sound.pop();
}

// ---------------- question ----------------
function pips(s) {
  return `<span class="pips">${Array.from({ length: s.total }, (_, i) =>
    `<i class="${i < s.qi ? "done" : i === s.qi ? "cur" : ""}"></i>`).join("")}</span>`;
}

function renderQuestion(s) {
  const q = s.question;
  app.innerHTML = `<div class="screen ready" id="qs">
    <div class="qtop"><span class="eyebrow" id="qlabel">Question ${s.qi + 1} of ${s.total}</span>${pips(s)}
      <span class="locked"><b id="answered" class="num">${s.answered}</b> / ${s.playerCount} locked in</span></div>
    <div class="timerbar" id="tbar"><div></div></div>
    <div class="qbody">
      <h1 class="qtext rise">${esc(q.text)}</h1>
      <div class="display clock num" id="clock"><span>3</span></div>
    </div>
    <div class="options">${q.options.map((o, i) =>
      `<div class="opt opt-${i}" style="animation-delay:${i * 0.07}s">${badge()}<span>${esc(o)}</span></div>`).join("")}</div>
  </div>`;
  const readyEnd = s.receivedAt + s.readyMs;
  const deadline = s.receivedAt + s.remainingMs;
  const total = q.time * 1000;
  const scr = $("#qs"), clock = $("#clock"), bar = $("#tbar div");
  let shown = false, lastSec = null, lastReady = null;
  $("#qlabel").classList.add("readylab");
  const step = () => {
    const now = performance.now();
    if (now < readyEnd) {
      const r = Math.ceil((readyEnd - now) / 1000);
      if (r !== lastReady) { clock.innerHTML = `<span>${r}</span>`; lastReady = r; if (lastReady !== null) Sound.tick(); }
      bar.style.transform = `scaleX(${1 - (readyEnd - now) / 3000})`;
      return;
    }
    if (!shown) {
      shown = true;
      scr.classList.remove("ready");
      $("#qlabel").classList.remove("readylab");
      Sound.startMusic();
    }
    const left = Math.max(0, deadline - now);
    const sec = Math.ceil(left / 1000);
    bar.style.transform = `scaleX(${left / total})`;
    $("#tbar").classList.toggle("low", sec <= 5);
    clock.classList.toggle("low", sec <= 5 && sec > 0);
    if (sec !== lastSec) {
      clock.textContent = sec;
      if (sec <= 5 && sec > 0 && lastSec !== null) Sound.tick(sec === 1);
      if (sec === 0 && lastSec !== null) { Sound.stopMusic(); Sound.timeUp(); }
      lastSec = sec;
    }
  };
  step();
  tickTimer = setInterval(step, 50);
}

// ---------------- reveal ----------------
function renderReveal(s) {
  const q = s.question;
  const dist = s.distribution;
  const max = Math.max(1, ...dist);
  const right = dist[q.correct] || 0;
  const pct = s.answered ? Math.round((right / s.answered) * 100) : 0;
  Sound.reveal();
  app.innerHTML = `<div class="screen">
    <div class="qtop"><span class="eyebrow">Question ${s.qi + 1} of ${s.total}</span>${pips(s)}
      <span class="locked"><b class="num">${s.answered}</b> / ${s.playerCount} answered</span></div>
    <h2 class="qsmall">${esc(q.text)}</h2>
    <div class="chart" style="grid-template-columns:repeat(${q.options.length},1fr)">
      ${q.options.map((o, i) => `<div class="col opt-${i} ${i === q.correct ? "correct" : "dim"}">
        <div class="n display num">${dist[i]}</div><div class="bar" data-h="${dist[i] / max}"></div>
        <div class="lab">${badge()}<span>${esc(o)}</span>${i === q.correct ? '<span class="ck">✓</span>' : ""}</div></div>`).join("")}
    </div>
    <div class="callouts">
      ${s.answered ? `<span class="pill" style="animation-delay:.9s">${pct}% got it right</span>` : `<span class="pill">Nobody answered. Tough crowd!</span>`}
      ${s.fastest ? `<span class="pill pop" style="animation-delay:1.2s">⚡ Fastest · ${esc(s.fastest.name)} <span class="num">${secs(s.fastest.ms)}</span></span>` : ""}
    </div></div>`;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const chart = app.querySelector(".chart");
    const room = chart.clientHeight - 9 * parseFloat(getComputedStyle(document.body).fontSize);
    app.querySelectorAll(".bar").forEach((b) => { b.style.height = `${Math.max(6, room * b.dataset.h)}px`; });
  }));
}

// ---------------- leaderboard ----------------
// Beat 1: standings before this question. Beat 2: this round's points count up.
// Beat 3: rows swap into the new order.
function renderLeaderboard(s) {
  const rows = s.leaderboard;
  for (const r of rows) {
    r.gained = r.gained || 0;
    if (typeof r.prevScore !== "number") r.prevScore = r.score - r.gained;
  }
  const SLOTS = 10;
  app.innerHTML = `<div class="screen"><div class="lbhead"><h2 class="display">Standings</h2>
    <span class="eyebrow">after question ${s.qi + 1} of ${s.total}</span></div>
    <div class="lb" id="lb">${rows.length ? "" : `<p class="empty">No ${s.teams ? "teams" : "players"} yet</p>`}</div></div>`;
  if (!rows.length) return;
  const lb = $("#lb");
  const before = [...rows].sort((a, b) =>
    (a.prevRank ?? 1e9) - (b.prevRank ?? 1e9) || b.prevScore - a.prevScore);
  const els = new Map();
  for (const r of rows) {
    const el = document.createElement("div");
    el.className = "lb-row";
    const moved = (r.prevRank ?? r.rank) - r.rank;
    el.innerHTML = `<span class="r">${r.prevRank ?? "–"}</span>
      <span class="nm"><span class="nmt">${esc(r.name)}</span>${r.fastest ? `<span class="fast">⚡ fastest</span>` : ""}</span>
      ${r.gained ? `<span class="gain num">+${r.gained}</span>` : ""}
      <span class="delta ${moved > 0 ? "up" : moved < 0 ? "down" : ""}">${moved > 0 ? `▲${moved}` : moved < 0 ? `▼${-moved}` : ""}</span>
      <span class="sc num">${r.prevScore}</span>`;
    lb.appendChild(el);
    els.set(r, el);
  }
  const natural = lb.firstElementChild.offsetHeight + 12;
  const visible = Math.min(SLOTS, rows.length);
  const avail = innerHeight - lb.getBoundingClientRect().top - 6 * parseFloat(getComputedStyle(document.body).fontSize);
  const H = Math.max(34, Math.min(natural, avail / visible));
  if (H < natural) lb.querySelectorAll(".lb-row").forEach((el) => { el.style.height = `${H - 10}px`; el.style.fontSize = `${Math.max(0.8, (H - 10) / (natural - 12)) * 1.15}em`; });
  lb.style.height = `${visible * H}px`;
  const place = (el, slot, animate) => {
    el.style.transition = animate ? "" : "none";
    el.style.transform = `translateY(${Math.min(slot, SLOTS) * H}px)`;
    el.style.opacity = slot < SLOTS ? "1" : "0";
  };
  before.forEach((r, i) => place(els.get(r), i, false));
  lb.getBoundingClientRect();

  setTimeout(() => {
    if (!lb.isConnected) return;
    for (const r of rows) {
      const el = els.get(r);
      el.classList.add("counting");
      if (r.gained) countUp(el.querySelector(".sc"), r.prevScore, r.score, 1300);
    }
    if (rows.some((r) => r.gained)) Sound.pop();
  }, 900);

  setTimeout(() => {
    if (!lb.isConnected) return;
    Sound.whoosh();
    rows.forEach((r) => {
      const el = els.get(r);
      place(el, r.rank - 1, true);
      el.querySelector(".r").textContent = r.rank;
      el.classList.toggle("top1", r.rank === 1);
      el.classList.add("moved");
    });
  }, 2700);
}

function countUp(el, from, to, ms) {
  const t0 = performance.now();
  const step = () => {
    const k = Math.min(1, (performance.now() - t0) / ms);
    el.textContent = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---------------- final ----------------
function renderFinal(s) {
  const rows = s.leaderboard || [];
  const pod = (r, cls) => r ? `<div class="pod ${cls}">${cls === "p1" ? '<div class="crown">👑</div>' : ""}
      <div class="who">${esc(r.name)}</div><div class="pts num">${r.score} pts</div>
      <div class="block display">${r.rank}</div></div>` : `<div class="pod ${cls}" style="visibility:hidden"><div class="block"></div></div>`;
  app.innerHTML = `<div class="screen final">
    <div class="eyebrow">${esc(s.title)} · final results</div>
    <h1 class="display">${rows.length ? "And the winner is…" : "That's a wrap!"}</h1>
    <div class="podium">${pod(rows[1], "p2")}${pod(rows[0], "p1")}${pod(rows[2], "p3")}</div>
    <div class="rest">${rows.filter((r) => r.rank > 3).slice(0, 7).map((r) => `<span>${r.rank}. <b>${esc(r.name)}</b> <span class="num">${r.score}</span></span>`).join("")}</div>
    <div class="exports">
      <a class="btn ghost small" href="/api/host/leaderboard.csv">⬇ Standings CSV</a>
      <a class="btn ghost small" href="/api/host/answers.csv">⬇ All answers CSV</a>
      <button class="btn ghost small" id="close">Close the room</button>
    </div></div>`;
  $("#hints").classList.add("hidden");
  $("#close").onclick = async () => {
    if (confirm("Close this room? Results are already saved in the results folder.")) {
      $("#hints").classList.remove("hidden");
      await api("/api/host/close", {});
    }
  };
  if (!rows.length) return;
  Sound.drumroll(2.8);
  const show = (cls, delay, cb) => setTimeout(() => { const p = app.querySelector(`.${cls}`); if (p) p.classList.add("show"); cb && cb(); }, delay);
  show("p3", 700);
  show("p2", 1700);
  show("p1", 3000, () => { Sound.fanfare(); confetti(); });
}

function confetti() {
  const cv = $("#confetti"), cx = cv.getContext("2d");
  cv.width = innerWidth; cv.height = innerHeight;
  const colors = ["#ff4757", "#2f7bff", "#ff7a1a", "#12c2b0", "#3d5afe", "#ff2e88", "#ffffff"];
  const burst = (x) => Array.from({ length: 140 }, () => ({
    x, y: innerHeight * 0.55,
    vx: (Math.random() - 0.5) * 16, vy: -Math.random() * 20 - 8,
    r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.3,
    w: 6 + Math.random() * 8, h: 8 + Math.random() * 12, c: colors[(Math.random() * colors.length) | 0],
  }));
  const parts = [...burst(innerWidth * 0.3), ...burst(innerWidth * 0.5), ...burst(innerWidth * 0.7)];
  const t0 = performance.now();
  const frame = () => {
    cx.clearRect(0, 0, cv.width, cv.height);
    for (const p of parts) {
      p.vy += 0.38; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      cx.save(); cx.translate(p.x, p.y); cx.rotate(p.r); cx.fillStyle = p.c;
      cx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h * Math.abs(Math.cos(p.r * 2))); cx.restore();
    }
    if (performance.now() - t0 < 6500) requestAnimationFrame(frame);
    else cx.clearRect(0, 0, cv.width, cv.height);
  };
  frame();
}
