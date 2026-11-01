// Know Signal participant phone screen.
const app = $("#app");
let token = localStorage.getItem("quiz-token");
let state = null;
let lastKey = "";
let timer = null;
let stream = null;

const buzz = (p) => navigator.vibrate && navigator.vibrate(p);
const secs = (ms) => `${(ms / 1000).toFixed(1)}s`;

function start() {
  if (stream) stream.close();
  stream = liveStream(() => `/api/events?token=${encodeURIComponent(token || "")}`, onState, (ok) => {
    $("#offline").classList.toggle("hidden", ok);
  });
}

function onState(s) {
  s.receivedAt = performance.now();
  state = s;
  if (s.phase === "kicked" || s.phase === "none" || !token) {
    if (token && s.phase === "kicked") {
      localStorage.removeItem("quiz-token");
      token = null;
    }
    const k = `join:${s.phase}`;
    if (lastKey !== k) showJoin(undefined, k);
    return;
  }
  const key = `${s.phase}:${s.qi}:${s.me.choice ?? ""}`;
  if (key === lastKey) return;
  lastKey = key;
  clearInterval(timer);
  ({ lobby: showLobby, question: showQuestion, reveal: showResult,
     leaderboard: showResult, final: showFinal })[s.phase](s);
}

async function showJoin(msg, key = "join:none") {
  lastKey = key;
  clearInterval(timer);
  let status = { open: false };
  try { status = await api("/api/status"); } catch {}
  if (lastKey !== key) return;
  const label = status.teams ? "Team name" : "Your nickname";
  app.innerHTML = `<div class="screen"><div class="center join-hero">
    ${logo(!status.open)}
    <p class="tag">${esc(BRAND.tagline)}</p>
    ${status.open ? `<h1 class="display" style="font-size:1.9em;margin-top:18px">${esc(status.title)}</h1>
      <form id="join"><input class="input" id="name" maxlength="20" autocomplete="off" autocapitalize="words" placeholder="${label}" required>
      <button class="btn">Join the room →</button></form>
      <p class="fine">No app. No sign-up. Just play.</p>`
      : `<p class="muted" style="margin-top:22px">The room isn't open yet.<br>Hang tight, it'll start here automatically.</p>`}
    ${msg ? `<p class="err">${esc(msg)}</p>` : ""}
  </div></div>`;
  if (!status.open) {
    setTimeout(() => { if (lastKey === key && !token) showJoin(undefined, key); }, 3000);
    return;
  }
  const name = $("#name");
  name.value = localStorage.getItem("quiz-name") || "";
  $("#join").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("#join button");
    btn.disabled = true;
    try {
      const r = await api("/api/join", { name: name.value });
      token = r.token;
      localStorage.setItem("quiz-token", token);
      localStorage.setItem("quiz-name", r.name);
      buzz(30);
      lastKey = "";
      start();
    } catch (err) {
      btn.disabled = false;
      toast(err.message);
    }
  };
}

function header(s) {
  return `<div class="top"><span class="me">${mark()}<span>${esc(s.me.name)}</span></span>
    <span class="pts num">${s.qi >= 0 ? `Q${s.qi + 1}/${s.total} · ` : ""}${s.me.score} pts</span></div>`;
}

function showLobby(s) {
  app.innerHTML = `<div class="screen">${header(s)}<div class="center">
    <div class="bigbars">${mark(true)}</div>
    <h1 class="display you">You're in.</h1>
    <span class="nametag">${s.teams ? "Team " : ""}${esc(s.me.name)}</span>
    <p class="muted">Eyes on the big screen.<br>Questions will pop up right here.</p>
  </div></div>`;
}

function showQuestion(s) {
  const q = s.question;
  const locked = s.me.choice !== null && s.me.choice !== undefined;
  const readyEnd = s.receivedAt + s.readyMs;
  const deadline = s.receivedAt + s.remainingMs;
  const total = q.time * 1000;
  app.innerHTML = `<div class="screen">${header(s)}<div id="body" style="flex:1;display:flex;flex-direction:column"></div></div>`;
  const body = $("#body");
  let mode = null, lastReady = null;
  const showReady = () => {
    body.innerHTML = `<div class="center"><span class="eyebrow qlabel">Question ${s.qi + 1} of ${s.total}</span>
      <div class="display readynum num" id="rd"></div><p class="q" style="margin:0">${esc(q.text)}</p></div>`;
  };
  const showChoices = () => {
    body.innerHTML = `<p class="q">${esc(q.text)}</p><div class="tbar" id="tbar"><div></div></div>
      <div class="choices ${locked ? "locked" : ""}" id="choices">${q.options.map((o, i) =>
        `<button class="choice opt-${i} ${s.me.choice === i ? "picked" : ""}" data-i="${i}" style="animation-delay:${i * 0.05}s">${badge()}<span>${esc(o)}</span></button>`).join("")}</div>
      ${locked ? `<p class="lockmsg">Locked in. Fingers crossed 🤞</p>` : ""}`;
    $("#choices").onclick = (e) => {
      const b = e.target.closest(".choice");
      if (b) answer(s, Number(b.dataset.i), b);
    };
  };
  const step = () => {
    const now = performance.now();
    if (now < readyEnd) {
      if (mode !== "ready") { mode = "ready"; showReady(); }
      const r = Math.ceil((readyEnd - now) / 1000);
      if (r !== lastReady) { $("#rd").innerHTML = `<span>${r}</span>`; lastReady = r; }
      return;
    }
    if (mode !== "go") { mode = "go"; showChoices(); }
    const left = Math.max(0, deadline - now);
    const bar = $("#tbar");
    if (bar) {
      bar.firstElementChild.style.transform = `scaleX(${left / total})`;
      bar.classList.toggle("low", left < 5000);
    }
    if (left <= 0) clearInterval(timer);
  };
  step();
  timer = setInterval(step, 100);
}

async function answer(s, i, btn) {
  const box = $("#choices");
  if (box.classList.contains("locked")) return;
  box.classList.add("locked");
  btn.classList.add("picked");
  buzz(35);
  try {
    await api("/api/answer", { token, qi: s.qi, choice: i });
    box.insertAdjacentHTML("afterend", `<p class="lockmsg">Locked in. Fingers crossed 🤞</p>`);
  } catch (e) {
    if (e.status === 410) { localStorage.removeItem("quiz-token"); token = null; return showJoin(e.message, "join:expired"); }
    toast(e.message);
    if (!/already|time|not accepting/i.test(e.message)) { box.classList.remove("locked"); btn.classList.remove("picked"); }
  }
}

const CHEERS = ["Nailed it!", "Correct!", "Big brain!", "On fire!", "Too easy!"];
const OOPS = ["Not quite", "So close", "Nope!", "Plot twist"];

function showResult(s) {
  const l = s.me.last || { answered: false, correct: false, points: 0 };
  const cls = !l.answered ? "none" : l.correct ? "good" : "bad";
  const pick = (arr) => arr[(s.qi + s.me.name.length) % arr.length];
  const title = !l.answered ? "Time's up" : l.correct ? pick(CHEERS) : pick(OOPS);
  if (s.phase === "reveal") buzz(l.correct ? [40, 60, 40] : 220);
  const rank = s.me.rank
    ? `<div><b class="num">#${s.me.rank}</b><span>of ${s.me.of}</span></div>`
    : `<div><b>🤫</b><span>Rank is a secret</span></div>`;
  app.innerHTML = `<div class="screen">${header(s)}<div class="center">
    <div class="result ${cls}"><div class="display big">${title}</div>
      ${l.correct ? `<div class="pts num">+${l.points}</div><div class="sub">Answered in ${secs(l.ms)}</div>`
        : `<div class="sub">Answer: <b>${esc(l.correctText)}</b></div>`}
      ${l.fastest ? `<span class="flash">⚡ Fastest in the room</span>` : ""}</div>
    <div class="stat">${rank}<div><b class="num">${s.me.score}</b><span>total points</span></div></div>
    <p class="muted">${s.phase === "leaderboard" ? "Standings are up on the big screen" : "Eyes on the big screen"}</p>
  </div></div>`;
}

function showFinal(s) {
  const r = s.me.rank;
  const medal = r === 1 ? "🏆" : r === 2 ? "🥈" : r === 3 ? "🥉" : "🎉";
  const line = r === 1 ? "Champion of the room!" : r <= 3 ? "On the podium!" : r <= 10 ? "Top ten. Respect." : "Thanks for playing!";
  app.innerHTML = `<div class="screen">${header(s)}<div class="center">
    <div class="medal">${medal}</div>
    <h1 class="display" style="font-size:2.2em">${line}</h1>
    <div class="stat"><div><b class="num">#${r}</b><span>of ${s.me.of}</span></div><div><b class="num">${s.me.score}</b><span>final points</span></div></div>
    <p class="fine" style="margin-top:20px">${mark()}&nbsp; Powered by Know Signal. ${esc(BRAND.tagline)}</p>
  </div></div>`;
  if (r <= 3) buzz([60, 40, 60, 40, 140]);
}

start();
