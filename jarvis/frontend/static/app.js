/* ==========================================================================
   JARVIS frontend.
   Thin renderer over a Python API: it fetches state + server-computed
   dashboards/schedules and POSTs mutations back. Every mutation returns the
   full new state, so the UI re-renders from one authoritative source and
   never drifts.
   ========================================================================== */

let STATE = null;       // full editable state (/api/state)
let CATALOG = [];       // the six selectable peptides
let GREETING = null;    // cached so a todo-toggle doesn't reroll the greeting
let CURRENT = "home";

let ciAnswers = {};       // current check-in answers being collected
let checkinHandled = false; // shown/dismissed once this session → don't auto-pop again

const ENGINES = ["none", "floor", "skill", "venture", "personal"];
const ENGINE_LABEL = { none: "—", floor: "Floor", skill: "Skill", venture: "Venture", personal: "Personal" };

const SECTIONS = [
  { key: "layer1", idx: "L1", name: "Destinations", meta: "rarely change · the why" },
  { key: "layer3", idx: "L3", name: "Annual Recal", meta: "once a year · deviation = input" },
  { key: "layer2", idx: "L2", name: "This Quarter", meta: "90 days · the what-now" },
  { key: "current", idx: "▶", name: "Current Enhancements", meta: "the live checklist" },
];

/* ---- tiny utils ---------------------------------------------------------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function esc(s) { return (s ?? "").toString().replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function todayISO() { return new Date().toISOString().slice(0, 10); }

function fmtVal(v, unit) {
  if (v === null || v === undefined) return "—";
  if (unit === "CAD") return "$" + Number(v).toLocaleString("en-CA", { maximumFractionDigits: 0 });
  if (unit === "%") return (+v).toFixed(1) + "%";
  if (unit === "lb") return (+v).toFixed(1) + " lb";
  return (+v).toLocaleString();
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-CA", { month: "short", day: "numeric" });
}
function relDay(n) {
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n < 0) return Math.abs(n) + "d ago";
  return "in " + n + "d";
}

/* ---- toast --------------------------------------------------------------- */
let toastT;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isErr ? " err" : "");
  clearTimeout(toastT);
  toastT = setTimeout(() => { t.className = ""; }, 2800);
}

/* ---- sound (WebAudio, no assets) ----------------------------------------- */
let actx;
function tick(up = true) {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === "suspended") actx.resume();
    const o = actx.createOscillator(), g = actx.createGain();
    o.connect(g); g.connect(actx.destination);
    o.type = "triangle";
    const t0 = actx.currentTime;
    o.frequency.setValueAtTime(up ? 520 : 360, t0);
    o.frequency.exponentialRampToValueAtTime(up ? 880 : 280, t0 + 0.09);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(0.14, t0 + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
    o.start(t0); o.stop(t0 + 0.17);
  } catch (e) { /* sound is a nicety, never block on it */ }
}

/* ---- API ----------------------------------------------------------------- */
async function api(path, method = "GET", body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch (e) { /* noop */ }
    throw new Error(detail || ("HTTP " + res.status));
  }
  return res.status === 204 ? null : res.json();
}

/** Run a mutation; on success swap in the returned state and re-render. */
async function mutate(path, method, body, okMsg) {
  try {
    const newState = await api(path, method, body);
    if (newState && newState.profile) STATE = newState;
    if (okMsg) toast(okMsg);
    renderTab(CURRENT);
    return newState;
  } catch (e) {
    toast(e.message, true);
    throw e;
  }
}

/* ---- status + clock ------------------------------------------------------ */
function setStatus(ok, text) {
  $("#status-dot").className = "dot" + (ok ? "" : " bad");
  $("#status-text").textContent = text;
}
function startClock() {
  const upd = () => {
    const now = new Date();
    $("#clock").textContent = now.toLocaleDateString("en-CA", { weekday: "short", month: "short", day: "numeric" })
      + " · " + now.toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit" });
  };
  upd(); setInterval(upd, 30000);
}

/* ---- SVG line chart ------------------------------------------------------ */
function lineChart(series, { height = 130, color = "var(--amber)", target = null, unit = "", forecast = [] } = {}) {
  if (!series.length) return '<div class="empty">no readings yet — add one below</div>';
  const W = 640, H = height, pL = 6, pR = 6, pT = 14, pB = 20;
  const X = d => new Date(d).getTime();
  const xs = series.map(p => X(p.date)).concat(forecast.map(f => X(f.date)));
  const ys = series.map(p => p.value);
  const fys = forecast.flatMap(f => [f.lower, f.upper]);
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys, ...fys), maxY = Math.max(...ys, ...fys);
  if (target !== null) { minY = Math.min(minY, target); maxY = Math.max(maxY, target); }
  const yPad = (maxY - minY) * 0.14 || 1;
  minY -= yPad; maxY += yPad;
  const spanX = (maxX - minX) || 1, spanY = (maxY - minY) || 1;
  const px = t => pL + (t - minX) / spanX * (W - pL - pR);
  const py = v => pT + (1 - (v - minY) / spanY) * (H - pT - pB);

  const pts = series.map(p => [px(X(p.date)), py(p.value)]);
  const linePath = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const areaPath = linePath + ` L${pts[pts.length - 1][0].toFixed(1)} ${py(minY).toFixed(1)} L${pts[0][0].toFixed(1)} ${py(minY).toFixed(1)} Z`;
  const last = pts[pts.length - 1];

  // projected continuation: faint band + dashed predicted line
  let fcSvg = "";
  if (forecast.length > 1) {
    const up = forecast.map(f => [px(X(f.date)), py(f.upper)]);
    const lo = forecast.map(f => [px(X(f.date)), py(f.lower)]);
    const band = "M" + up.map(p => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L")
      + " L" + lo.reverse().map(p => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L") + " Z";
    const pred = forecast.map((f, i) => (i ? "L" : "M") + px(X(f.date)).toFixed(1) + " " + py(f.predicted).toFixed(1)).join(" ");
    fcSvg = `<path d="${band}" fill="${color}" opacity="0.10"/>
      <path d="${pred}" fill="none" stroke="${color}" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.85"/>`;
  }

  let targetLine = "";
  if (target !== null) {
    const ty = py(target).toFixed(1);
    targetLine = `<line x1="${pL}" y1="${ty}" x2="${W - pR}" y2="${ty}" stroke="var(--ink-faint)" stroke-width="1" stroke-dasharray="4 4" opacity="0.7"/>
      <text x="${W - pR}" y="${(+ty - 4)}" text-anchor="end" font-size="10" fill="var(--ink-faint)">target ${fmtVal(target, unit)}</text>`;
  }
  const rightDate = forecast.length ? forecast[forecast.length - 1].date : series[series.length - 1].date;
  const gid = "g" + Math.random().toString(36).slice(2, 7);
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
    <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    ${targetLine}
    ${fcSvg}
    <path d="${areaPath}" fill="url(#${gid})"/>
    <path d="${linePath}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3.5" fill="${color}"/>
    <text x="${pts[0][0]}" y="${H - 6}" font-size="10" fill="var(--ink-faint)">${fmtDate(series[0].date)}</text>
    <text x="${W - pR}" y="${H - 6}" text-anchor="end" font-size="10" fill="var(--ink-faint)">${fmtDate(rightDate)}</text>
  </svg>`;
}
function sparkline(series, color = "var(--amber)") {
  if (!series || series.length < 2) return "";
  return `<div class="spark">${lineChart(series, { height: 38, color }).replace(/<text[^>]*>.*?<\/text>/g, "")}</div>`;
}

/* ---- metric stats (client-side, for Health/Money tabs) ------------------- */
function metricStats(m) {
  const rs = [...m.readings].sort((a, b) => a.date < b.date ? -1 : 1);
  const latest = rs[rs.length - 1] || null, prev = rs[rs.length - 2] || null, first = rs[0] || null;
  let delta = null, good = null;
  if (latest && prev) {
    delta = +(latest.value - prev.value).toFixed(2);
    good = delta === 0 ? null : (m.direction === "down" ? delta < 0 : delta > 0);
  }
  let pct = null;
  if (latest && m.target != null) {
    if (m.direction === "down" && first) {
      const span = first.value - m.target;
      if (span > 0) pct = Math.max(0, Math.min(1, (first.value - latest.value) / span)) * 100;
    } else if (m.direction === "up" && m.target > 0) {
      pct = Math.min(1, latest.value / m.target) * 100;
    }
  }
  return { rs, latest, prev, first, delta, good, pct };
}
function trendChip(delta, good, unit) {
  if (delta === null) return `<span class="trend flat">— no trend yet</span>`;
  if (delta === 0) return `<span class="trend flat">no change</span>`;
  const arrow = delta > 0 ? "▲" : "▼";
  const cls = good === null ? "flat" : (good ? "good" : "bad");
  return `<span class="trend ${cls}">${arrow} ${fmtVal(Math.abs(delta), unit)}</span>`;
}

/* ========================================================================== */
/*  TABS                                                                       */
/* ========================================================================== */
function switchTab(name) {
  CURRENT = name;
  $$(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(s => s.classList.toggle("active", s.id === "tab-" + name));
  renderTab(name);
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function renderTab(name) {
  if (name === "home") return renderHome();
  if (name === "peptides") return renderPeptides();
  if (name === "health") return renderHealth();
  if (name === "workouts") return renderWorkouts();
  if (name === "money") return renderMoney();
  if (name === "rods") return renderRods();
  if (name === "garage") return renderGarage();
  if (name === "claude") return renderClaude();
}

/* ========================================================================== */
/*  HOME                                                                       */
/* ========================================================================== */
function gaugeRing(pct, color = "var(--amber)") {
  const r = 26, c = 2 * Math.PI * r, off = c * (1 - (pct || 0) / 100);
  return `<svg viewBox="0 0 64 64" class="gauge">
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="var(--line)" stroke-width="6"/>
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 32 32)"/>
    <text x="32" y="37" text-anchor="middle" font-size="19" fill="var(--ink)" style="font-family:var(--cond);font-weight:700">${pct == null ? "—" : pct}</text>
  </svg>`;
}

function flagsRow(fl) {
  if (!fl || !fl.length) return "";
  return `<div class="flags">${fl.map(f =>
    `<div class="flag ${f.level}"><span class="fi">${f.icon}</span>${esc(f.text)}</div>`).join("")}</div>`;
}

function streakStrip(st, setup) {
  if (!st) return "";
  const gauge = (setup && setup.available)
    ? `<div class="chip-stat gauge-stat link" data-action="goto" data-tab="garage">
         ${gaugeRing(setup.today, "var(--amber)")}
         <div><b>setup score</b><span>today · ${setup.avg7} avg (7d)</span></div></div>`
    : "";
  return `<div class="strip">
    <div class="chip-stat"><span class="cs-ico">🔥</span><div><b>${st.checkin_streak}d</b><span>check-in streak</span></div></div>
    <div class="chip-stat"><span class="cs-ico">🥩</span><div><b>${st.protein_streak}d</b><span>protein streak</span></div></div>
    <div class="chip-stat"><span class="cs-ico">🏋</span><div><b>${st.training_week}/${st.training_target}</b><span>sessions this wk</span></div></div>
    ${gauge}
  </div>`;
}

function raceReport(r) {
  if (!r) return "";
  const tile = (label, value, sub = "") =>
    `<div class="rr-tile"><span class="rr-l">${label}</span><span class="rr-v">${value}${sub}</span></div>`;
  const dd = (v, goodNeg) => v == null ? "" :
    `<span class="rr-d ${v === 0 ? "flat" : (goodNeg ? (v < 0 ? "good" : "bad") : (v > 0 ? "good" : "bad"))}">${v > 0 ? "+" : ""}${v}</span>`;
  const wc = r.weight_change != null ? `${r.weight_change > 0 ? "+" : ""}${r.weight_change} ${r.weight_unit}` : "—";
  return `<div class="panel report">
    <div class="panel-head"><h3>📋 Race Report</h3><span class="hint">week of ${fmtDate(r.week_of)}</span></div>
    <div class="rr-verdict">${esc(r.verdict)}</div>
    <div class="rr-grid">
      ${tile("Weight Δ", wc)}
      ${tile("Sessions", r.sessions, ` <span class="rr-sub">vs ${r.sessions_prev}</span>`)}
      ${tile("Volume", r.tonnage.toLocaleString() + " " + r.tonnage_unit, ` <span class="rr-sub">vs ${r.tonnage_prev.toLocaleString()}</span>`)}
      ${tile("Deep work", (r.deep_work_avg ?? "—") + "h/d ", dd(r.deep_work_delta, false))}
      ${tile("Degging", (r.degging_avg ?? "—") + "h/d ", dd(r.degging_delta, true))}
      ${tile("Adherence", r.checkin_days + "/7", ` <span class="rr-sub">${r.protein_days}/7 protein</span>`)}
      ${tile("PRs", r.prs.length)}
      ${tile("Quarter", r.current_done + "/" + r.current_total)}
    </div>
  </div>`;
}

async function renderHome() {
  const el = $("#tab-home");
  let dash;
  try { dash = await api("/api/dashboard"); }
  catch (e) { el.innerHTML = `<div class="err">Dashboard unavailable: ${esc(e.message)}</div>`; return; }
  if (!GREETING) GREETING = dash.greeting;

  const k = dash.kpis;
  const nw = k.networth, wt = k.weight, bf = k.bodyfat, mo = k.money_online;

  // peptide upcoming rows
  const doses = dash.peptides_upcoming;
  const doseRows = doses.length ? doses.map(d => `
    <div class="dose-row ${d.is_today ? "today" : ""}">
      <span class="d-date">${fmtDate(d.date)}</span>
      <span class="d-name">${esc(d.label)}${d.dosage ? " · " + esc(d.dosage) : ""}</span>
      ${d.is_today ? '<span class="badge-today">today</span>' : `<span class="d-when">${relDay(d.days_until)}</span>`}
    </div>`).join("") : '<div class="empty">no upcoming doses — add a protocol</div>';

  // todos
  const todoRows = dash.todos.length ? dash.todos.map(t => `
    <div class="check ${t.done ? "done" : ""}" data-action="toggle-todo" data-id="${t.id}">
      <div class="box"></div>
      <span class="c-text">${esc(t.text)}</span>
      <span class="eng-dot ${t.engine}"></span>
    </div>`).join("") : '<div class="empty">no current enhancements — add some on the board</div>';

  el.innerHTML = `
    <div class="greeting">
      <div>
        <div class="g-eyebrow">Jarvis online · ${esc(dash.today)}</div>
        <div class="g-text" id="g-text">${esc(GREETING)}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-end;flex-shrink:0">
        <button class="reroll" data-action="reroll" title="another greeting">↻</button>
        <button class="checkin-btn" data-action="open-checkin" title="daily check-in">check-in</button>
      </div>
    </div>

    ${flagsRow(dash.flags)}
    ${streakStrip(dash.streaks, dash.setup)}
    ${raceReport(dash.report)}

    <div class="kpis">
      <div class="kpi link" data-action="goto" data-tab="money">
        <div class="k-label">Net Worth</div>
        <div class="k-value">${fmtVal(nw.latest, "CAD")}</div>
        <div class="k-sub">liquid target ${fmtVal(nw.liquid_target, "CAD")} · ${nw.pct_to_target ?? 0}%</div>
        ${sparkline(nw.series, "var(--green)")}
        <div class="k-foot">${trendChip(nw.delta, nw.trend_good, "CAD")}<span class="hint">→ Money</span></div>
      </div>

      <div class="kpi link" data-action="goto" data-tab="health">
        <div class="k-label">Weight</div>
        <div class="k-value">${wt.latest != null ? (+wt.latest).toFixed(1) : "—"}<small> lb</small></div>
        <div class="k-sub">target ${fmtVal(wt.target, "lb")}${wt.to_target != null ? " · " + (wt.to_target > 0 ? wt.to_target.toFixed(1) + " to go" : "at target") : ""}</div>
        ${sparkline(wt.series, "var(--amber)")}
        <div class="k-foot">${trendChip(wt.delta, wt.trend_good, "lb")}<span class="hint">→ Health</span></div>
      </div>

      <div class="kpi link" data-action="goto" data-tab="health">
        <div class="k-label">Body Fat (approx)</div>
        <div class="k-value">${bf.latest != null ? (+bf.latest).toFixed(1) : "—"}<small> %</small></div>
        <div class="k-sub">target ${fmtVal(bf.target, "%")}${bf.to_target != null ? " · " + (bf.to_target > 0 ? bf.to_target.toFixed(1) + "% to go" : "at target") : ""}</div>
        ${sparkline(bf.series, "var(--blue)")}
        <div class="k-foot">${trendChip(bf.delta, bf.trend_good, "%")}<span class="hint">→ Health</span></div>
      </div>

      <div class="kpi">
        <div class="k-label">Money Made Online</div>
        <div class="k-value">$${(+mo.current).toFixed(0)}<small> / $${(+mo.target).toFixed(0)}</small></div>
        <div class="k-sub">first dollar is the hardest</div>
        <div class="k-foot" style="flex-direction:column;align-items:stretch;gap:6px">
          <div class="meter"><span style="width:${mo.pct}%"></span></div>
          <span class="hint">${mo.pct}% · manual for now</span>
        </div>
      </div>

      <div class="kpi span2">
        <div class="k-label">Peptides · Upcoming Doses</div>
        <div class="dose-list">${doseRows}</div>
        <div class="k-foot"><span class="hint" data-action="goto" data-tab="peptides" style="cursor:pointer">→ manage protocols</span></div>
      </div>

      <div class="kpi span2">
        <div class="k-label">Current TO-DO · ${dash.todo_done}/${dash.todo_total} done</div>
        <div class="todo-list">${todoRows}</div>
        <div class="k-foot"><span class="hint" data-action="goto" data-tab="rods" style="cursor:pointer">→ No Control Rods board</span></div>
      </div>
    </div>`;
  maybeCheckin();
}

async function reroll() {
  try {
    GREETING = (await api("/api/greeting")).greeting;
    $("#g-text").textContent = GREETING;
  } catch (e) { /* noop */ }
}

/* ---- daily check-in ------------------------------------------------------ */
async function maybeCheckin() {
  if (checkinHandled) return;            // already shown/dismissed this session
  try {
    const s = await api("/api/checkin/status");
    if (s.needed) { checkinHandled = true; renderCheckin(s); }
  } catch (e) { /* never block the home page on this */ }
}
async function openCheckin() {            // manual re-open from the button
  try { renderCheckin(await api("/api/checkin/status")); }
  catch (e) { toast(e.message, true); }
}
function closeCheckin() {
  const o = $("#overlay"); o.classList.remove("show"); o.innerHTML = "";
}
function renderCheckin(status) {
  ciAnswers = {};
  const qs = status.questions.map(q => {
    let input;
    if (q.type === "number") input = `<input type="number" step="0.1" id="ci-${q.id}" placeholder="…">`;
    else if (q.type === "text") input = `<input type="text" id="ci-${q.id}" placeholder="one line">`;
    else if (q.type === "bool") input = `<div class="ci-opts">
        <div class="ci-opt" data-action="ci-pick" data-q="${q.id}" data-v="yes">Yes</div>
        <div class="ci-opt" data-action="ci-pick" data-q="${q.id}" data-v="no">No</div></div>`;
    else input = `<div class="ci-opts">${[1, 2, 3, 4, 5].map(n =>
        `<div class="ci-opt" data-action="ci-pick" data-q="${q.id}" data-v="${n}">${n}</div>`).join("")}</div>`;
    return `<div class="ci-q"><div class="ci-prompt">${esc(q.prompt)}</div>${input}</div>`;
  }).join("");
  const note = status.sheet_connected
    ? "saved locally · <b>synced to your Sheet</b>"
    : "saved locally · connect a Sheet to sync";
  $("#overlay").innerHTML = `<div class="checkin">
    <h2>Morning Check-in</h2>
    <div class="ci-sub">${esc(status.date)} · first open of the day</div>
    ${qs}
    <div class="ci-foot">
      <span class="ci-note">${note}</span>
      <div class="ci-btns">
        <button class="checkin-btn" data-action="checkin-later">later</button>
        <button class="btn btn-amber" data-action="checkin-submit">log it</button>
      </div>
    </div>
  </div>`;
  $("#overlay").classList.add("show");
}
async function submitCheckin() {
  $$("#overlay input").forEach(inp => {
    const id = inp.id.replace("ci-", "");
    if (inp.value !== "") ciAnswers[id] = inp.value;
  });
  try {
    const resp = await api("/api/checkin", "POST", { answers: ciAnswers });
    if (resp && resp.profile) STATE = resp;
    closeCheckin();
    toast(resp && resp._sheet_pushed ? "Check-in logged + synced to Sheet" : "Check-in logged");
    renderTab("home");
  } catch (e) { toast(e.message, true); }
}

/* ========================================================================== */
/*  PEPTIDES                                                                    */
/* ========================================================================== */
async function renderPeptides() {
  const el = $("#tab-peptides");
  let schedules = [];
  try { schedules = await api("/api/peptides/schedules"); } catch (e) { /* fall back to none */ }
  const byId = Object.fromEntries(schedules.map(s => [s.id, s]));

  const active = new Set(STATE.peptides.map(p => p.key));
  const chips = CATALOG.map(c => `
    <button class="chip" data-action="add-pep" data-key="${c.key}" ${active.has(c.key) ? "disabled" : ""} title="${esc(c.blurb)}">
      <span class="plus">＋</span>${esc(c.label)}
    </button>`).join("");

  const cards = STATE.peptides.length ? STATE.peptides.map(p => {
    const s = byId[p.id] || {};
    const meta = CATALOG.find(c => c.key === p.key) || { full: p.key, blurb: "" };
    const nextTxt = s.finished ? "protocol complete"
      : (s.next_dose ? (s.is_today ? "TODAY" : fmtDate(s.next_dose) + " · " + relDay(s.days_until)) : "—");
    const progress = (s.doses_total != null)
      ? `<div class="pep-sched-row"><span>Progress</span><span>${s.doses_done}/${s.doses_total} doses · ${s.progress_pct}%</span></div>
         <div class="meter green"><span style="width:${s.progress_pct || 0}%"></span></div>`
      : `<div class="pep-sched-row"><span>Doses logged</span><span>${s.doses_done ?? 0} · ongoing</span></div>`;
    return `
    <div class="pep-card ${p.active ? "" : "inactive"}">
      <div class="pep-head">
        <div>
          <div class="pep-title">${esc(meta.label || p.key)}</div>
          <div class="pep-full">${esc(meta.full)}</div>
        </div>
        <button class="icon-btn danger" data-action="del-pep" data-id="${p.id}" title="remove">✕</button>
      </div>
      <div class="pep-blurb">${esc(meta.blurb)}</div>
      <div class="pep-fields">
        <div class="field"><label>Dosage</label>
          <input type="text" value="${esc(p.dosage)}" placeholder="e.g. 0.5 mg" data-action="pep-field" data-id="${p.id}" data-field="dosage"></div>
        <div class="field"><label>Start date</label>
          <input type="date" value="${p.start_date}" data-action="pep-field" data-id="${p.id}" data-field="start_date"></div>
        <div class="field"><label>Every N days</label>
          <input type="number" min="1" value="${p.interval_days}" data-action="pep-field" data-id="${p.id}" data-field="interval_days"></div>
        <div class="field"><label>Length (days, blank = ongoing)</label>
          <input type="number" min="1" value="${p.length_days ?? ""}" placeholder="ongoing" data-action="pep-field" data-id="${p.id}" data-field="length_days"></div>
      </div>
      <div class="pep-sched">
        <div class="pep-sched-row"><span>Next dose</span><span class="next ${s.is_today ? "today" : ""}">${nextTxt}</span></div>
        ${progress}
      </div>
      <div class="pep-foot">
        <label class="toggle"><input type="checkbox" ${p.active ? "checked" : ""} data-action="pep-active" data-id="${p.id}"> Active</label>
        <input type="text" value="${esc(p.note)}" placeholder="note…" style="flex:1;margin-left:10px"
          data-action="pep-field" data-id="${p.id}" data-field="note">
      </div>
    </div>`;
  }).join("") : '<div class="empty">No protocols yet. Add one from the catalogue above.</div>';

  el.innerHTML = `
    <div class="eyebrow"><span class="idx">01</span> Add a protocol <span class="rule"></span>
      <span class="meta">six compounds · one of each</span></div>
    <div class="add-chips">${chips}</div>

    <div class="eyebrow"><span class="idx">▶</span> Active protocols <span class="rule"></span>
      <span class="meta">dose · start · interval · length</span></div>
    <div class="pep-grid">${cards}</div>`;
}

/* ========================================================================== */
/*  HEALTH & GYM                                                                */
/* ========================================================================== */
function metricPanel(kind, m, color, fc) {
  const st = metricStats(m);
  const cutPct = st.pct != null ? st.pct.toFixed(0) : null;
  const hasFc = fc && fc.available;
  const anomIds = new Set(hasFc ? fc.anomalies.map(a => a.id) : []);

  const readingRows = st.rs.slice().reverse().slice(0, 30).map(r => `
    <div class="reading-row">
      <span class="rd-date">${fmtDate(r.date)}</span>
      <span class="rd-val">${fmtVal(r.value, m.unit)}</span>
      ${anomIds.has(r.id) ? '<span class="anom" title="off-trend reading">⚠ off-trend</span>' : ""}
      <span class="rd-note">${esc(r.note)}</span>
      <button class="icon-btn danger" data-action="del-reading" data-kind="${kind}" data-id="${r.id}" title="delete">✕</button>
    </div>`).join("") || '<div class="empty">no readings logged</div>';

  // forecast stats: weekly rate + ETA to target
  let fcStats = "";
  if (hasFc) {
    const r = fc.slope_per_week;
    const rate = `${r > 0 ? "+" : ""}${r} ${esc(m.unit)}/wk`;
    let eta;
    if (fc.eta && fc.eta.reached) eta = "reached ✓";
    else if (fc.eta && fc.eta.date) eta = `${fmtDate(fc.eta.date)} · ${fc.eta.days}d`;
    else eta = "not on track";
    fcStats = `
      <div class="stat"><span class="s-label">Trend rate</span><span class="s-value" style="font-size:20px">${rate}</span></div>
      <div class="stat"><span class="s-label">ETA to target</span><span class="s-value" style="font-size:20px">${eta}</span></div>`;
  }

  return `
  <div class="panel">
    <div class="panel-head">
      <h3>${esc(m.label)}</h3>
      <div class="row-actions">
        <span class="hint">target</span>
        <input type="number" step="0.1" id="tg-${kind}" value="${m.target ?? ""}" style="width:90px">
        <button class="btn btn-ghost" data-action="save-target" data-kind="${kind}">set</button>
      </div>
    </div>
    <div class="stat-row">
      <div class="stat"><span class="s-label">Latest</span><span class="s-value">${st.latest ? fmtVal(st.latest.value, m.unit) : "—"}</span></div>
      <div class="stat"><span class="s-label">Trend</span><span class="s-value" style="font-size:18px">${trendChip(st.delta, st.good, m.unit)}</span></div>
      <div class="stat"><span class="s-label">Target</span><span class="s-value">${fmtVal(m.target, m.unit)}</span></div>
      ${cutPct != null ? `<div class="stat"><span class="s-label">Progress</span><span class="s-value">${cutPct}%</span></div>` : ""}
      ${fcStats}
    </div>
    <div class="chart">${lineChart(st.rs.map(r => ({ date: r.date, value: r.value })), { color, target: m.target, unit: m.unit, forecast: hasFc ? fc.forecast : [] })}</div>
    ${hasFc ? `<div class="hint" style="margin:-2px 0 10px">dashed = projected trend (R²&nbsp;${fc.r2}) · band ≈ 95% range${fc.anomalies.length ? ` · ${fc.anomalies.length} off-trend point${fc.anomalies.length > 1 ? "s" : ""} flagged` : ""}</div>` : ""}
    <div class="inline-form">
      <div class="field"><label>Date</label><input type="date" id="rd-${kind}-date" value="${todayISO()}"></div>
      <div class="field"><label>Value (${esc(m.unit)})</label><input type="number" step="0.1" id="rd-${kind}-val" placeholder="0"></div>
      <div class="field grow"><label>Note</label><input type="text" id="rd-${kind}-note" placeholder="optional"></div>
      <button class="btn btn-amber" data-action="add-reading" data-kind="${kind}">＋ log</button>
    </div>
    <div class="reading-list">${readingRows}</div>
  </div>`;
}

async function renderHealth() {
  const el = $("#tab-health");
  const p = STATE.profile;
  const [wFc, bFc] = await Promise.all([
    api("/api/forecast/weight").catch(() => null),
    api("/api/forecast/bodyfat").catch(() => null),
  ]);
  el.innerHTML = `
    <div class="eyebrow"><span class="idx">02</span> Health &amp; Gym <span class="rule"></span>
      <span class="meta">finish lean · keep the build</span></div>

    <div class="panel" style="margin-bottom:16px">
      <div class="panel-head"><h3>Training inputs</h3></div>
      <div class="inline-form">
        <div class="field"><label>Protein target (g/day)</label><input type="number" id="protein" value="${p.protein_target_g}" style="width:120px"></div>
        <button class="btn btn-ghost" data-action="save-protein">save</button>
        <span class="hint">Hold protein while the deficit does the work — that's what keeps the upper-four abs.</span>
      </div>
    </div>

    <div class="grid-2">
      ${metricPanel("weight", STATE.weight, "var(--amber)", wFc)}
      ${metricPanel("bodyfat", STATE.bodyfat, "var(--blue)", bFc)}
    </div>`;
}

/* ========================================================================== */
/*  MONEY & RESOURCES                                                           */
/* ========================================================================== */
async function renderMoney() {
  const el = $("#tab-money");
  const p = STATE.profile;
  const st = metricStats(STATE.networth);
  const nFc = await api("/api/forecast/networth").catch(() => null);

  el.innerHTML = `
    <div class="eyebrow"><span class="idx">03</span> Money &amp; Resources <span class="rule"></span>
      <span class="meta">floor + skill + venture</span></div>

    ${metricPanel("networth", STATE.networth, "var(--green)", nFc)}

    <div class="grid-2" style="margin-top:16px">
      <div class="panel">
        <div class="panel-head"><h3>Targets</h3></div>
        <div class="inline-form">
          <div class="field"><label>Liquid target</label><input type="number" id="tg-liquid" value="${p.networth_liquid_target}"></div>
          <div class="field"><label>Total target</label><input type="number" id="tg-total" value="${p.networth_total_target}"></div>
          <div class="field"><label>Big-purchase fund</label><input type="number" id="tg-car" value="${p.car_fund_target}"></div>
          <button class="btn btn-amber" data-action="save-targets">save targets</button>
        </div>
        <div class="stat-row" style="margin-top:14px">
          <div class="stat"><span class="s-label">Now</span><span class="s-value">${st.latest ? fmtVal(st.latest.value, STATE.networth.unit) : "—"}</span></div>
          <div class="stat"><span class="s-label">To liquid target</span><span class="s-value">${st.latest ? fmtVal(Math.max(0, p.networth_liquid_target - st.latest.value), STATE.networth.unit) : "—"}</span></div>
          <div class="stat"><span class="s-label">To total target</span><span class="s-value">${st.latest ? fmtVal(Math.max(0, p.networth_total_target - st.latest.value), STATE.networth.unit) : "—"}</span></div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h3>Money Made Online</h3></div>
        <div class="inline-form">
          <div class="field"><label>Current (USD)</label><input type="number" step="1" id="mo-cur" value="${p.money_online_current}"></div>
          <div class="field"><label>Target (USD)</label><input type="number" step="1" id="mo-tgt" value="${p.money_online_target}"></div>
          <button class="btn btn-amber" data-action="save-money-online">save</button>
        </div>
        <div class="meter" style="margin-top:14px"><span style="width:${Math.min(100, p.money_online_target ? p.money_online_current / p.money_online_target * 100 : 0)}%"></span></div>
        <div class="hint" style="margin-top:8px">A first concrete revenue milestone — the proof-of-concept the venture engine is built on.</div>
      </div>
    </div>

    <div class="eyebrow"><span class="idx">⛁</span> The three engines <span class="rule"></span>
      <span class="meta">how the target decomposes</span></div>
    <div class="grid-2">
      <div class="panel" style="border-left:3px solid var(--blue)">
        <div class="panel-head"><h3>Floor</h3><span class="tag floor">guaranteed</span></div>
        <p class="hint">Job + savings — the bulk of the target. High savings rate, tax-advantaged accounts, and negotiating comp hard at offer. The near-certain base.</p>
      </div>
      <div class="panel" style="border-left:3px solid var(--amber)">
        <div class="panel-head"><h3>Skill</h3><span class="tag skill">compounds</span></div>
        <p class="hint">Portfolio projects, certifications, open-source. Turns a starting salary into a steeper trajectory and unlocks higher-paying / remote roles.</p>
      </div>
      <div class="panel" style="border-left:3px solid var(--red)">
        <div class="panel-head"><h3>Venture</h3><span class="tag venture">the ceiling</span></div>
        <p class="hint">Protected, low-intensity, nights/weekends. Never threatens the floor. The upside engine that can close the gap or blow past it — $0 is an acceptable outcome.</p>
      </div>
      <div class="panel" style="border-left:3px solid var(--green)">
        <div class="panel-head"><h3>The shape of it</h3><span class="tag personal">honest</span></div>
        <p class="hint">The floor alone gets you most of the way; negotiation and a job hop add more; the venture is the variable that decides whether you hit or exceed the number.</p>
      </div>
    </div>`;
}

/* ========================================================================== */
/*  NO CONTROL RODS — the four-section board                                    */
/* ========================================================================== */
let draggedId = null;

function goalCard(g) {
  const isCurrent = g.section === "current";
  const box = isCurrent
    ? `<div class="g-box" data-action="toggle-goal" data-id="${g.id}" title="tick"></div>`
    : "";
  return `
    <div class="goal-card ${g.engine} ${g.done ? "done" : ""}" draggable="true" data-id="${g.id}">
      <div class="g-top">
        ${box}
        <div class="g-text">${esc(g.text)}</div>
      </div>
      ${g.note ? `<div class="g-note">${esc(g.note)}</div>` : ""}
      <div class="g-actions">
        <span class="tag ${g.engine}" data-action="cycle-engine" data-id="${g.id}" title="click to change engine">${ENGINE_LABEL[g.engine]}</span>
        <button class="icon-btn" data-action="edit-goal" data-id="${g.id}" title="edit text">✎</button>
        <button class="icon-btn" data-action="note-goal" data-id="${g.id}" title="edit note">≣</button>
        <button class="icon-btn danger" data-action="del-goal" data-id="${g.id}" title="delete">✕</button>
      </div>
    </div>`;
}

function renderRods() {
  const el = $("#tab-rods");
  const cols = SECTIONS.map(sec => {
    const goals = STATE.goals
      .filter(g => g.section === sec.key)
      .sort((a, b) => (a.order - b.order) || a.text.localeCompare(b.text));
    const cards = goals.length ? goals.map(goalCard).join("") : '<div class="empty">drop goals here</div>';
    return `
      <div class="col ${sec.key === "current" ? "current" : ""}">
        <div class="col-head">
          <div class="c-idx">${sec.idx}</div>
          <div class="c-name">${esc(sec.name)}</div>
          <div class="c-meta">${esc(sec.meta)}${sec.key === "current" ? " · tick boxes" : " · pin board"}</div>
        </div>
        <div class="col-body" data-section="${sec.key}">${cards}</div>
        <div class="col-add">
          <input type="text" id="add-${sec.key}" placeholder="add to ${esc(sec.name)}…">
          <button class="btn btn-ghost" data-action="add-goal" data-section="${sec.key}">＋</button>
        </div>
      </div>`;
  }).join("");

  el.innerHTML = `
    <div class="eyebrow"><span class="idx">04</span> No Control Rods <span class="rule"></span>
      <span class="meta">drag between · only Current ticks</span></div>
    <div class="board" id="board">${cols}</div>`;

  wireBoardDnD();
}

function wireBoardDnD() {
  $$("#board .goal-card").forEach(card => {
    card.addEventListener("dragstart", e => {
      draggedId = card.dataset.id;
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", draggedId); } catch (_) {}
    });
    card.addEventListener("dragend", async () => {
      card.classList.remove("dragging");
      $$("#board .col-body").forEach(b => b.classList.remove("drag-over"));
      const body = card.closest(".col-body");
      if (!body) return;
      const section = body.dataset.section;
      const orderedIds = $$(".goal-card", body).map(c => c.dataset.id);
      draggedId = null;
      try {
        const ns = await api("/api/goals/reorder", "POST", { section, ordered_ids: orderedIds });
        STATE = ns;
        renderRods();
      } catch (e) { toast(e.message, true); renderRods(); }
    });
  });

  $$("#board .col-body").forEach(body => {
    body.addEventListener("dragover", e => {
      e.preventDefault();
      body.classList.add("drag-over");
      const dragging = $(".goal-card.dragging");
      if (!dragging) return;
      const after = dragAfter(body, e.clientY);
      if (after == null) body.appendChild(dragging);
      else body.insertBefore(dragging, after);
    });
    body.addEventListener("dragleave", e => {
      if (!body.contains(e.relatedTarget)) body.classList.remove("drag-over");
    });
    body.addEventListener("drop", e => e.preventDefault());
  });
}
function dragAfter(container, y) {
  const els = $$(".goal-card:not(.dragging)", container);
  let closest = { offset: -Infinity, el: null };
  for (const el of els) {
    const box = el.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) closest = { offset, el };
  }
  return closest.el;
}

/* ========================================================================== */
/*  WORKOUTS (Hevy import)                                                      */
/* ========================================================================== */
async function renderWorkouts() {
  const el = $("#tab-workouts");
  const [s, exList] = await Promise.all([
    api("/api/workouts/summary").catch(() => ({ available: false })),
    api("/api/workouts/exercises").catch(() => []),
  ]);

  const importPanel = `
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-head"><h3>Import from Hevy</h3>
        <span class="hint">Hevy → Profile → ⚙ → Export Data → CSV</span></div>
      <div class="inline-form">
        <label class="btn btn-amber" style="cursor:pointer">＋ choose CSV<input type="file" accept=".csv,text/csv" data-action="import-file" style="display:none"></label>
        <span class="hint">re-importing is safe — only new sessions are added</span>
      </div>
      <textarea id="hevy-csv" placeholder="…or paste the CSV contents here" style="width:100%;height:64px;margin-top:10px"></textarea>
      <div style="margin-top:8px"><button class="btn btn-ghost" data-action="import-paste">import pasted</button></div>
    </div>`;

  if (!s.available) {
    el.innerHTML = `
      <div class="eyebrow"><span class="idx">03</span> Workouts <span class="rule"></span><span class="meta">log in Hevy · study here</span></div>
      ${importPanel}
      <div class="empty">No sessions yet. Export from Hevy and import above — volume, strength curves and frequency show up here, and feed the Garage.</div>`;
    return;
  }

  const unit = s.unit;
  const volChart = lineChart(s.volume_series.map(v => ({ date: v.date, value: v.tonnage })), { color: "var(--violet)", unit });
  const pinned = new Set(STATE.profile.main_lifts || []);
  const picker = exList.slice(0, 24).map(e =>
    `<button class="lift-chip ${pinned.has(e.exercise) ? "on" : ""}" data-action="pin-lift" data-lift="${esc(e.exercise)}">${esc(e.exercise)} <span style="opacity:.5">${e.sessions}</span></button>`).join("");

  const strengthPanels = s.strength.map(st => {
    const d = st.delta, dCls = d > 0 ? "good" : d < 0 ? "bad" : "flat";
    const prBadge = st.recent_pr ? ' <span class="pr-badge">🏆 PR</span>' : "";
    const allTime = st.all_time != null
      ? `<div class="stat"><span class="s-label">all-time best</span><span class="s-value">${st.all_time} <small>${esc(unit)}</small></span></div>` : "";
    return `<div class="panel">
      <div class="panel-head"><h3 style="font-size:18px">${esc(st.exercise)}${prBadge}</h3>
        <span class="trend ${dCls}">${d > 0 ? "▲" : d < 0 ? "▼" : "•"} ${Math.abs(d)} ${esc(unit)}</span></div>
      <div class="stat-row">
        <div class="stat"><span class="s-label">current 1RM</span><span class="s-value">${st.current_e1rm} <small>${esc(unit)}</small></span></div>
        ${allTime}
      </div>
      <div class="chart">${lineChart(st.series, { height: 90, color: "var(--amber)" })}</div>
    </div>`;
  }).join("");

  const recent = s.recent.map(w => `
    <div class="reading-row">
      <span class="rd-date">${fmtDate(w.date)}</span>
      <span class="rd-val">${esc(w.title || "session")}</span>
      <span class="rd-note">${w.sets} sets · ${w.tonnage} ${esc(unit)}${w.duration_min ? ` · ${w.duration_min}m` : ""} · ${esc(w.exercises.slice(0, 4).join(", "))}${w.exercises.length > 4 ? "…" : ""}</span>
    </div>`).join("");

  el.innerHTML = `
    <div class="eyebrow"><span class="idx">03</span> Workouts <span class="rule"></span><span class="meta">volume · strength · frequency</span></div>
    ${importPanel}
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-head"><h3>Training load</h3></div>
      <div class="stat-row">
        <div class="stat"><span class="s-label">This week</span><span class="s-value">${s.sessions_7d}<small> sessions</small></span></div>
        <div class="stat"><span class="s-label">Avg / wk (28d)</span><span class="s-value">${s.per_week_28d}</span></div>
        <div class="stat"><span class="s-label">Total logged</span><span class="s-value">${s.count}</span></div>
      </div>
      <div class="chart">${volChart}</div>
      <div class="hint">session tonnage (Σ weight×reps), ${esc(unit)}</div>
    </div>
    <div class="eyebrow"><span class="idx">◎</span> Pinned lifts <span class="rule"></span><span class="meta">click to track on the curves</span></div>
    <div class="panel" style="margin-bottom:16px">
      <div class="lift-picker">${picker}</div>
      ${pinned.size ? "" : '<div class="hint" style="margin-top:10px">none pinned — showing your most-trained lifts by default. Pin Bench/Squat/Deadlift to track the big ones.</div>'}
    </div>
    <div class="eyebrow"><span class="idx">▦</span> Strength curves <span class="rule"></span><span class="meta">est. 1RM · ${s.pinned ? "pinned lifts" : "most-trained"}</span></div>
    <div class="grid-2">${strengthPanels}</div>
    <div class="eyebrow"><span class="idx">≡</span> Recent sessions <span class="rule"></span></div>
    <div class="panel"><div class="reading-list" style="max-height:none">${recent}</div></div>`;
}

async function importWorkouts(csv) {
  try {
    const resp = await api("/api/workouts/import", "POST", { csv });
    if (resp && resp.profile) STATE = resp;
    toast(`Imported ${resp._imported} new session${resp._imported === 1 ? "" : "s"} · ${resp._parsed} parsed`);
    renderTab("workouts");
  } catch (e) { toast(e.message, true); }
}

/* ========================================================================== */
/*  GARAGE — self-study / setup sheet                                          */
/* ========================================================================== */
async function renderGarage() {
  const el = $("#tab-garage");
  const s = await api("/api/study").catch(() => ({ available: false, have: 0, need: 6 }));
  const head = `<div class="eyebrow"><span class="idx">06</span> Garage <span class="rule"></span><span class="meta">study the car · find the levers</span></div>`;

  if (!s.available) {
    const pct = Math.min(100, Math.round((s.have || 0) / (s.need || 6) * 100));
    el.innerHTML = `${head}
      <div class="panel">
        <div class="panel-head"><h3>Telemetry warming up</h3></div>
        <p class="hint">The setup sheet unlocks once there's enough daily data to find patterns. Do the morning check-in each day (sleep · energy · deep-work · degging) and import your workouts — Jarvis then shows which inputs move which outputs.</p>
        <div class="meter" style="margin-top:10px"><span style="width:${pct}%"></span></div>
        <div class="meter-label" style="margin-top:6px"><span>${s.have || 0} of ${s.need || 6} days logged</span><b>${pct}%</b></div>
      </div>`;
    return;
  }

  const corr = s.correlations.length ? s.correlations.map(c => `
    <div class="corr-row">
      <span class="corr-read">${esc(c.reading)}</span>
      <span class="corr-r ${c.r > 0 ? "good" : "bad"}">r ${c.r > 0 ? "+" : ""}${c.r}</span>
      <span class="corr-meta">${esc(c.strength)} · n=${c.n}</span>
    </div>`).join("") : '<div class="empty">no clear relationships yet — keep logging</div>';

  let profile = "";
  if (s.peak_profile && s.peak_profile.deltas.length) {
    const p = s.peak_profile;
    const rows = p.deltas.map(d => `
      <div class="corr-row">
        <span class="corr-read">${esc(d.input_label)}</span>
        <span class="corr-r ${d.delta > 0 ? "good" : d.delta < 0 ? "bad" : "flat"}">${d.delta > 0 ? "+" : ""}${d.delta}</span>
        <span class="corr-meta">best ${d.best} · worst ${d.worst}</span>
      </div>`).join("");
    profile = `<div class="panel" style="margin-bottom:16px">
      <div class="panel-head"><h3>Peak-day setup</h3><span class="hint">best vs worst ${esc(p.output_label)} days</span></div>
      <p class="hint">What your highest-${esc(p.output_label)} days have more (or less) of — the repeatable setup to chase:</p>
      ${rows}</div>`;
  }

  let setupBlock = "";
  if (s.setup && s.setup.available) {
    const comps = s.setup.components.map(c =>
      `<div class="rr-tile"><span class="rr-l">${esc(c.label)}</span><span class="rr-v">${c.pct}%</span></div>`).join("");
    setupBlock = `<div class="panel" style="margin-bottom:16px">
      <div class="panel-head"><h3>Setup score</h3><span class="hint">how your days match your ideal-day recipe</span></div>
      <div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:12px">
        <div style="display:flex;align-items:center;gap:12px">${gaugeRing(s.setup.today, "var(--amber)")}
          <div><div class="hint">today · ${s.setup.avg7} avg (7d)</div></div></div>
        <div class="rr-grid" style="flex:1;min-width:240px">${comps}</div>
      </div>
      <div class="chart">${lineChart(s.setup.series, { height: 90, color: "var(--amber)" })}</div>
    </div>`;
  }

  el.innerHTML = `${head}
    ${setupBlock}
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-head"><h3>Levers → laps</h3><span class="hint">${s.days} days · correlation, not causation</span></div>
      ${corr}</div>
    ${profile}
    <div class="grid-2">
      <div class="panel"><div class="panel-head"><h3 style="font-size:18px">Deep-work hours</h3></div><div class="chart">${lineChart(s.deep_work_series, { height: 110, color: "var(--green)" })}</div></div>
      <div class="panel"><div class="panel-head"><h3 style="font-size:18px">Degging hours</h3></div><div class="chart">${lineChart(s.degging_series, { height: 110, color: "var(--red)" })}</div></div>
    </div>`;
}

/* ========================================================================== */
/*  CLAUDE (placeholder)                                                        */
/* ========================================================================== */
function renderClaude() {
  $("#tab-claude").innerHTML = `
    <div class="claude-shell">
      <div class="claude-orb"></div>
      <div class="pill">module reserved</div>
      <h2>Claude</h2>
      <p>This is the hook for the assistant layer — wired into the same state Jarvis already owns (peptides, body, money, the plan).</p>
      <p class="hint">Further instructions pending. When you're ready, this is where the conversational engine plugs in.</p>
      <div class="claude-input">
        <input type="text" placeholder="Ask Jarvis…" disabled>
        <button class="btn btn-amber" disabled>send</button>
      </div>
    </div>`;
}

/* ========================================================================== */
/*  EVENT DELEGATION                                                            */
/* ========================================================================== */
document.addEventListener("click", async (e) => {
  if (e.target.id === "overlay") { checkinHandled = true; return closeCheckin(); }
  const t = e.target.closest("[data-action]");
  if (!t) return;
  const a = t.dataset.action;

  if (a === "goto") return switchTab(t.dataset.tab);
  if (a === "reroll") return reroll();
  if (a === "open-checkin") return openCheckin();
  if (a === "checkin-later") { checkinHandled = true; return closeCheckin(); }
  if (a === "checkin-submit") return submitCheckin();
  if (a === "ci-pick") {
    const q = t.dataset.q;
    ciAnswers[q] = t.dataset.v;
    $$(`.ci-opt[data-q="${q}"]`).forEach(o => o.classList.toggle("sel", o === t));
    return;
  }
  if (a === "import-paste") {
    const txt = ($("#hevy-csv").value || "").trim();
    if (!txt) return toast("Paste the CSV first", true);
    return importWorkouts(txt);
  }
  if (a === "pin-lift") {
    const lift = t.dataset.lift;
    const cur = new Set(STATE.profile.main_lifts || []);
    cur.has(lift) ? cur.delete(lift) : cur.add(lift);
    return mutate("/api/profile", "PATCH", { main_lifts: [...cur] }, cur.has(lift) ? "Pinned" : "Unpinned");
  }

  if (a === "toggle-todo" || a === "toggle-goal") {
    const id = t.dataset.id;
    const g = STATE.goals.find(x => x.id === id);
    const next = !(g && g.done);
    tick(next);
    return mutate(`/api/goals/${id}`, "PATCH", { done: next });
  }

  if (a === "add-pep") {
    return mutate("/api/peptides", "POST", {
      key: t.dataset.key, dosage: "", start_date: todayISO(),
      interval_days: 7, length_days: null, active: true, note: "",
    }, "Protocol added");
  }
  if (a === "del-pep") {
    if (!confirm("Remove this protocol?")) return;
    return mutate(`/api/peptides/${t.dataset.id}`, "DELETE", undefined, "Removed");
  }

  if (a === "add-reading") {
    const kind = t.dataset.kind;
    const val = parseFloat($(`#rd-${kind}-val`).value);
    if (isNaN(val)) return toast("Enter a value first", true);
    const body = { date: $(`#rd-${kind}-date`).value || todayISO(), value: val, note: $(`#rd-${kind}-note`).value };
    return mutate(`/api/metrics/${kind}/readings`, "POST", body, "Logged");
  }
  if (a === "del-reading") {
    return mutate(`/api/metrics/${t.dataset.kind}/readings/${t.dataset.id}`, "DELETE", undefined, "Deleted");
  }
  if (a === "save-target") {
    const kind = t.dataset.kind;
    const v = parseFloat($(`#tg-${kind}`).value);
    return mutate(`/api/metrics/${kind}`, "PATCH", { target: isNaN(v) ? null : v }, "Target set");
  }
  if (a === "save-protein") {
    const v = parseInt($("#protein").value, 10);
    return mutate("/api/profile", "PATCH", { protein_target_g: isNaN(v) ? 0 : v }, "Saved");
  }
  if (a === "save-targets") {
    return mutate("/api/profile", "PATCH", {
      networth_liquid_target: parseFloat($("#tg-liquid").value) || 0,
      networth_total_target: parseFloat($("#tg-total").value) || 0,
      car_fund_target: parseFloat($("#tg-car").value) || 0,
    }, "Targets saved");
  }
  if (a === "save-money-online") {
    return mutate("/api/profile", "PATCH", {
      money_online_current: parseFloat($("#mo-cur").value) || 0,
      money_online_target: parseFloat($("#mo-tgt").value) || 1,
    }, "Saved");
  }

  if (a === "add-goal") {
    const sec = t.dataset.section;
    const input = $(`#add-${sec}`);
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    return mutate("/api/goals", "POST", { text, section: sec }, "Added");
  }
  if (a === "edit-goal") {
    const g = STATE.goals.find(x => x.id === t.dataset.id);
    const text = prompt("Edit goal:", g ? g.text : "");
    if (text && text.trim()) return mutate(`/api/goals/${t.dataset.id}`, "PATCH", { text: text.trim() });
    return;
  }
  if (a === "note-goal") {
    const g = STATE.goals.find(x => x.id === t.dataset.id);
    const note = prompt("Edit note (blank to clear):", g ? g.note : "");
    if (note !== null) return mutate(`/api/goals/${t.dataset.id}`, "PATCH", { note: note.trim() });
    return;
  }
  if (a === "cycle-engine") {
    const g = STATE.goals.find(x => x.id === t.dataset.id);
    const i = ENGINES.indexOf(g ? g.engine : "none");
    const next = ENGINES[(i + 1) % ENGINES.length];
    return mutate(`/api/goals/${t.dataset.id}`, "PATCH", { engine: next });
  }
  if (a === "del-goal") {
    if (!confirm("Delete this goal?")) return;
    return mutate(`/api/goals/${t.dataset.id}`, "DELETE");
  }
});

// peptide field edits (change events) + active toggle
document.addEventListener("change", (e) => {
  const t = e.target.closest("[data-action]");
  if (!t) return;
  const a = t.dataset.action;

  if (a === "import-file") {
    const file = t.files && t.files[0];
    if (!file) return;
    file.text().then(importWorkouts).catch(() => toast("Could not read that file", true));
    return;
  }
  if (a === "pep-active") {
    return mutate(`/api/peptides/${t.dataset.id}`, "PATCH", { active: t.checked });
  }
  if (a === "pep-field") {
    const field = t.dataset.field;
    const body = {};
    if (field === "length_days") {
      if (t.value === "" || t.value == null) { body.clear_length = true; }
      else body.length_days = parseInt(t.value, 10);
    } else if (field === "interval_days") {
      body.interval_days = parseInt(t.value, 10);
    } else {
      body[field] = t.value;
    }
    return mutate(`/api/peptides/${t.dataset.id}`, "PATCH", body);
  }
});

// enter-to-add in the board columns
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const inp = e.target;
  if (inp.id && inp.id.startsWith("add-")) {
    const sec = inp.id.slice(4);
    const text = inp.value.trim();
    if (text) { inp.value = ""; mutate("/api/goals", "POST", { text, section: sec }); }
  }
});

// nav
$("#nav").addEventListener("click", (e) => {
  const b = e.target.closest(".tab-btn");
  if (b) switchTab(b.dataset.tab);
});

/* ---- boot ---------------------------------------------------------------- */
async function boot() {
  startClock();
  try {
    const [state, catalog] = await Promise.all([api("/api/state"), api("/api/peptide-catalog")]);
    STATE = state; CATALOG = catalog;
    setStatus(true, "reactor online");
    switchTab("home");
  } catch (e) {
    setStatus(false, "offline");
    $("#tab-home").innerHTML = `<div class="err">Could not reach the Jarvis API: ${esc(e.message)}. Is the server running?</div>`;
  }
}
boot();
