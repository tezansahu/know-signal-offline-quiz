// Quiz editor (host laptop only).
$("#elogo").innerHTML = logo();
const main = $("#main");
let quiz = null;
let dirty = false;
const TIMES = [10, 15, 20, 30, 45, 60, 90];

const blankQuestion = () => ({ text: "", options: ["", "", "", ""], correct: 0, time: 20 });

async function loadList(selectId) {
  const list = await api("/api/quizzes");
  $("#list").innerHTML = list.map((q) => `<button class="qitem ${quiz && q.id === quiz.id ? "sel" : ""}" data-id="${q.id}">
    ${esc(q.title)}<small>${q.count} question${q.count === 1 ? "" : "s"}</small></button>`).join("")
    || `<p class="hint" style="color:var(--muted)">No quizzes yet.</p>`;
  if (selectId) open(selectId);
}

$("#list").onclick = (e) => {
  const b = e.target.closest(".qitem");
  if (b && confirmDiscard()) open(b.dataset.id);
};

function confirmDiscard() {
  return !dirty || confirm("You have unsaved changes. Discard them?");
}

async function open(id) {
  quiz = await api(`/api/quizzes/${id}`);
  dirty = false;
  render();
  document.querySelectorAll(".qitem").forEach((b) => b.classList.toggle("sel", b.dataset.id === id));
}

$("#new").onclick = () => {
  if (!confirmDiscard()) return;
  quiz = { id: null, title: "Untitled quiz", questions: [blankQuestion()] };
  dirty = true;
  render();
  $("#title").select();
};

$("#import").onchange = async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f || !confirmDiscard()) return;
  try {
    const data = JSON.parse(await f.text());
    data.id = null;
    quiz = data;
    dirty = true;
    render();
    toast("Imported. Review the quiz, then press Save.");
  } catch {
    toast("That file isn't valid quiz JSON");
  }
};

function setDirty() {
  dirty = true;
  $("#dirty").textContent = "Unsaved changes";
}

function render() {
  main.innerHTML = `
    <div class="titlebar"><input class="input" id="title" value="${esc(quiz.title)}" placeholder="Quiz title"></div>
    <div id="qs"></div>
    <button class="btn ghost" id="addq">+ Add question</button>
    <div class="savebar">
      <button class="btn" id="save">Save</button>
      <span id="dirty">${dirty ? "Unsaved changes" : "All changes saved"}</span>
      <span class="sp"></span>
      <button class="btn ghost small" id="export">Export JSON</button>
      ${quiz.id ? `<button class="btn danger small" id="del">Delete quiz</button>` : ""}
    </div>`;
  $("#title").oninput = (e) => { quiz.title = e.target.value; setDirty(); };
  $("#addq").onclick = () => {
    quiz.questions.push(blankQuestion());
    setDirty();
    renderQuestions();
    const all = document.querySelectorAll(".qcard textarea");
    all[all.length - 1].focus();
  };
  $("#save").onclick = save;
  $("#export").onclick = exportJson;
  if ($("#del")) $("#del").onclick = del;
  renderQuestions();
}

function renderQuestions() {
  const qs = $("#qs");
  qs.innerHTML = quiz.questions.map((q, qi) => `
    <div class="card qcard" data-qi="${qi}">
      <div class="qcard-head">Question ${qi + 1}<span class="sp"></span>
        <button data-act="up" title="Move up" ${qi === 0 ? "disabled" : ""}>↑</button>
        <button data-act="down" title="Move down" ${qi === quiz.questions.length - 1 ? "disabled" : ""}>↓</button>
        <button data-act="dup" title="Duplicate">⧉</button>
        <button data-act="del" title="Delete">🗑</button></div>
      <textarea class="input" data-f="text" placeholder="Type the question…">${esc(q.text)}</textarea>
      <div class="opts">${q.options.map((o, oi) => `
        <div class="optrow opt-${oi} ${q.correct === oi ? "correct" : ""}">
          <b>${LETTERS[oi]}</b><input type="text" data-f="opt" data-oi="${oi}" value="${esc(o)}" placeholder="Option ${LETTERS[oi]}">
          <label><input type="radio" name="c${qi}" data-f="correct" data-oi="${oi}" ${q.correct === oi ? "checked" : ""}>correct</label>
          ${q.options.length > 2 ? `<button class="x" data-act="rmopt" data-oi="${oi}" title="Remove option">✕</button>` : ""}
        </div>`).join("")}</div>
      <div class="qfoot">
        ${q.options.length < 4 ? `<button class="btn ghost small" data-act="addopt">+ Option</button>` : ""}
        <span class="sp" style="flex:1"></span>
        <label style="color:var(--muted)">Timer</label>
        <select class="input" data-f="time">${TIMES.map((t) => `<option value="${t}" ${q.time === t ? "selected" : ""}>${t} s</option>`).join("")}</select>
      </div>
    </div>`).join("") || `<div class="empty">No questions yet.</div>`;
}

$("#main").addEventListener("input", (e) => {
  const card = e.target.closest(".qcard");
  if (!card) return;
  const q = quiz.questions[+card.dataset.qi];
  const f = e.target.dataset.f;
  if (f === "text") q.text = e.target.value;
  else if (f === "opt") q.options[+e.target.dataset.oi] = e.target.value;
  else if (f === "time") q.time = +e.target.value;
  else if (f === "correct") {
    q.correct = +e.target.dataset.oi;
    card.querySelectorAll(".optrow").forEach((r, i) => r.classList.toggle("correct", i === q.correct));
  } else return;
  setDirty();
});

$("#main").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  const card = e.target.closest(".qcard");
  if (!b || !card) return;
  const qi = +card.dataset.qi;
  const qs = quiz.questions;
  const q = qs[qi];
  switch (b.dataset.act) {
    case "up": [qs[qi - 1], qs[qi]] = [qs[qi], qs[qi - 1]]; break;
    case "down": [qs[qi + 1], qs[qi]] = [qs[qi], qs[qi + 1]]; break;
    case "dup": qs.splice(qi + 1, 0, JSON.parse(JSON.stringify(q))); break;
    case "del":
      if ((q.text || q.options.some(Boolean)) && !confirm(`Delete question ${qi + 1}?`)) return;
      qs.splice(qi, 1); break;
    case "addopt": q.options.push(""); break;
    case "rmopt": {
      const oi = +b.dataset.oi;
      q.options.splice(oi, 1);
      if (q.correct === oi) q.correct = 0;
      else if (q.correct > oi) q.correct--;
      break;
    }
    default: return;
  }
  setDirty();
  renderQuestions();
});

async function save() {
  try {
    const r = await api("/api/quizzes", quiz);
    quiz.id = r.id;
    dirty = false;
    toast("Saved ✔");
    render();
    loadList();
  } catch (e) {
    toast(e.message, 4000);
  }
}

function exportJson() {
  const blob = new Blob([JSON.stringify(quiz, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(quiz.title || "quiz").replace(/[^\w-]+/g, "-")}.json`;
  a.click();
}

async function del() {
  if (!confirm(`Delete "${quiz.title}" permanently?`)) return;
  await api("/api/quizzes/delete", { id: quiz.id });
  quiz = null;
  dirty = false;
  main.innerHTML = `<div class="empty">Quiz deleted.</div>`;
  loadList();
}

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && quiz) { e.preventDefault(); save(); }
});
window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

const wanted = new URLSearchParams(location.search).get("id");
loadList(wanted);
