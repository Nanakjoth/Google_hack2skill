/* ============================================================
   Agentic Tele-Triage Portal - frontend
   Vanilla JS, no build step. Talks to API_BASE from config.js.

   The LLM proposes, code disposes. That principle is visible in this UI:
   every run shows WHICH path produced the decision, the score breakdown
   behind any routing choice, and why each facility was rejected.
   ============================================================ */

'use strict';

/* ---------------- icons ---------------- */
const ICON = {
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  warn: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>',
  bed: '<path d="M2 20v-8a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v8M2 16h20M6 10V6a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v4"/>',
  steth: '<path d="M4 3v6a5 5 0 0 0 10 0V3"/><path d="M9 14v3a5 5 0 0 0 10 0v-2"/><circle cx="19" cy="12" r="2"/>',
  move: '<path d="M4 8h13M14 5l3 3-3 3"/><path d="M20 16H7M10 13l-3 3 3 3"/>',
  in: '<path d="M12 3v12M8 11l4 4 4-4"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
  doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  bed: '<path d="M2 4v16M2 8h18a2 2 0 0 1 2 2v10M2 17h20M6 8v9"/>',
  warn: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  steth: '<path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6 6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.2.2 0 1 0 .3.3"/><path d="M8 15v1a6 6 0 0 0 6 6 6 6 0 0 0 6-6v-4"/><circle cx="20" cy="10" r="2"/>',
  // "Escalate to senior" - an arrow leaving a level.
  up: '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
  // Marks the model's advice, deliberately visually distinct from the
  // decision buttons so advice is never mistaken for an action.
  spark: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'
};

function svg(name, cls) {
  return `<svg ${cls ? `class="${cls}"` : ''} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[name] || ''}</svg>`;
}

/* ---------------- static data ---------------- */
const CASE_PROFILES = [
  { id: 'normal',   sev: 'Green',  title: 'Routine fever',    desc: 'Vitals normal, no bed or specialist needed' },
  { id: 'moderate', sev: 'Yellow', title: 'Dengue — moderate', desc: 'Platelets low, 2 units, haematologist' },
  { id: 'severe',   sev: 'Red',    title: 'Dengue — severe',  desc: 'Platelets critical, 1 ICU bed, 5 units' },
  { id: 'cardiac',  sev: 'Red',    title: 'Acute cardiac',    desc: 'ICU + cardiologist, no platelets' },
  { id: 'child_fever', sev: 'Yellow', title: 'Paediatric fever', desc: 'Child febrile, paediatrician review' },
  { id: 'anemia',   sev: 'Yellow', title: 'Severe anaemia',   desc: 'Transfusion assessment, haematologist' },
  { id: 'trauma',   sev: 'Red',    title: 'Polytrauma',       desc: 'Surgical emergency, theatre referral' },
  { id: 'chronic',  sev: 'Green',  title: 'Chronic review',   desc: 'Routine review at next OPD' }
];

const SAMPLE_SEVERE = `Name: Rekha Devi, 33 yrs F
C/O: Fever 6 days, severe body pain, vomiting, bleeding from gums.
Temp 101.2 F, HR 122/min, BP 90/60 mmHg, SpO2 96%
Platelets 11,000/uL
Haematocrit 51%, WBC 3,400, Hb 14.5
Dengue NS1: POSITIVE
Tourniquet test: strongly positive
Impression: Dengue haemorrhagic fever with plasma leak.
Plan: admit to ICU, IV ringer lactate, platelet transfusion.`;

/* Deliberately messy: SpO2 misread as Sp02, 11,000 rendered as 11000 with a
   swapped digit, Hb dropped, one line mangled. The eval set is built the
   same way - the point is that the triage decision must survive this. */
const SAMPLE_OCR = `NAME: RAKESH KUMAR, 58Y M
C/O fever 4 days, breathlessness, oliguria
T 103F  HR 138/min  BP 84/58  Sp02 91%
PLATELETS 11,000/UL
HB 6.2 gm%
CREAT 2.4
NS1 pos
impression: dengue with plasma leak
plan: admit icu`;

const PAGES = {
  intake:   ['New Patient',     'Paste a lab report for model triage, or pick a case profile.'],
  pipeline: ['Agent Pipeline',  'Every agent decision this session, with the reasoning and score behind it.'],
  doctor:   ['Queues',          'Patient, doctor and senior queues. You decide: remote review, admit, or escalate.'],
  portal:   ['Patient Portal',  'What a patient is told about their own case — position, wait, decision.'],
  compare:  ['Before / After',  'The repeated physical queue this replaces, and what the report-driven path does instead.'],
  command:  ['Command Center',  'Live facility inventory, shortage alerts and 30-day cover projection.']
};

const STATUS_META = {
  'awaiting_review':      { label: 'Awaiting review',  tone: 'warn' },
  'awaiting_specialist':  { label: 'With senior',      tone: 'accent' },
  'unassigned':           { label: 'Unassigned',       tone: 'bad' },
  'admitted':             { label: 'Admitted',         tone: 'ok' },
  'closed_remote':        { label: 'Closed remotely',  tone: 'ok' }
};

/* The three actions a reviewing doctor can take, in the order the product
   presents them. Each one has a different effect on scarce resources, so they
   are named explicitly rather than as a generic Approve / Reject pair - a
   doctor has to be able to see which button holds a bed and which does not. */
const DECISIONS = [
  {
    key: 'no_visit', label: 'No visit needed', short: 'Remote review',
    icon: 'check', tone: 'ok',
    blurb: 'Handles the report remotely. Frees the doctor slot. No bed or medicine is ever held for this case.'
  },
  {
    key: 'visit_required', label: 'Patient must be seen', short: 'Admit',
    icon: 'bed', tone: 'accent',
    blurb: 'Commits the ICU bed and medicines now, on your decision. Fails loudly if the facility cannot supply them.'
  },
  {
    key: 'escalate', label: 'Escalate to senior', short: 'Escalate',
    icon: 'up', tone: 'bad',
    blurb: 'Hands the case to a senior consultant of the same specialty. Any resources already held follow the case.'
  }
];

/* ---------------- state ---------------- */
const state = {
  tab: 'intake',
  mode: 'report',
  caseType: 'normal',
  history: [],
  patients: [],
  queue: { stats: null, patient_queue: [], doctor_queues: [], specialist_queues: [] },
  scope: 'doctors',        // doctors | network | specialists
  filter: 'all',
  // Secondary lens set by the header tiles, orthogonal to severity: which
  // cases lack a doctor, and which one has waited longest. `null` = no lens.
  lens: null,              // null | unassigned | longest
  query: '',
  sort: { inv: { key: 'name', dir: 1 }, cov: { key: 'days_of_cover', dir: 1 } },
  autoSec: 15,
  countdown: 15,
  apiOk: null,
  llmOk: null,
  lastRefresh: null
};

const LS_RUNS = 'att_runs_v3';

/* ---------------- utilities ---------------- */

// Escape before interpolating into innerHTML. Patient names, report text and
// hospital names all reach this UI; a name of `<img src=x onerror=...>` must
// never execute.
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function $(id) { return document.getElementById(id); }

function debounce(fn, ms) {
  let t;
  return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
}

async function api(path, opts = {}) {
  const o = { ...opts };
  // Default the JSON content type for any request that carries a body.
  //
  // `fetch` sends a string body as `text/plain;charset=UTF-8`, which FastAPI
  // will not parse - it answers 422 with a list of validation errors, and
  // `String([{...}])` is "[object Object]". So a call site that forgot the
  // header failed with a message that named neither the endpoint nor the
  // cause, on a button that otherwise worked everywhere else in the console.
  // Set it here, once, instead of trusting every call site to remember.
  if (o.body != null && !(o.headers && o.headers['Content-Type'])) {
    o.headers = { ...(o.headers || {}), 'Content-Type': 'application/json' };
  }
  const res = await fetch(API_BASE + path, o);
  let body = null;
  try { body = await res.json(); } catch (e) { /* empty or non-JSON body */ }
  if (!res.ok) throw new Error(errorText(body, res.status));
  return body;
}

// Turn an error body into one readable line.
//
// The decision endpoints refuse with a *structured* 409 - `{error, detail,
// hint}` - so that a refusal says which check failed and what to do next.
// `new Error(object)` stringifies to "[object Object]", which told the doctor
// nothing at all about why their escalate was refused. Prefer the hint, fall
// back to the detail, then to whatever the body offers, then the status.
function errorText(body, status) {
  const d = body && (body.detail !== undefined ? body.detail : body.message);
  if (Array.isArray(d)) {
    // FastAPI request-validation errors. `loc` ends with the offending field.
    const msgs = d.map(e => `${(e.loc || []).slice(-1)[0] || 'request'}: ${e.msg || 'invalid'}`);
    return msgs.length ? msgs.join('; ') : `HTTP ${status}`;
  }
  if (typeof d === 'string' && d.trim()) return d;
  if (d && typeof d === 'object') {
    const parts = [];
    if (d.hint) parts.push(d.hint);
    else if (d.error) parts.push(String(d.error).replace(/_/g, ' '));
    if (!parts.length && d.detail && typeof d.detail === 'object') {
      const inner = d.detail.error;
      if (inner) parts.push(String(inner).replace(/_/g, ' '));
    }
    if (parts.length) return parts.join(' ');
  }
  if (typeof d === 'string' && d.trim()) return d;
  return `HTTP ${status}`;
}

/* ---------------- toasts ---------------- */
const TOAST_ICON = { ok: 'check', err: 'x', info: 'info' };

function toast(kind, title, detail, ms) {
  const box = $('toasts');
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.innerHTML =
    `<span class="ti ${kind}">${svg(TOAST_ICON[kind] || 'info')}</span>
     <div><div class="tt">${esc(title)}</div>${detail ? `<div class="td">${esc(detail)}</div>` : ''}</div>`;
  box.appendChild(t);
  const life = ms || (kind === 'err' ? 7000 : 3800);
  setTimeout(() => {
    t.classList.add('out');
    setTimeout(() => t.remove(), 240);
  }, life);
}

/* ---------------- modal ---------------- */
function confirmModal({ title, body, kv, confirmLabel, danger }) {
  return new Promise(resolve => {
    const root = $('modal-root');
    const back = document.createElement('div');
    back.className = 'modal-back';
    back.innerHTML =
      `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
         <h3>${esc(title)}</h3>
         <p>${esc(body)}</p>
         ${(kv || []).map(k => `<div class="kv"><span class="psub">${esc(k[0])}</span><b>${esc(k[1])}</b></div>`).join('')}
         <div class="acts">
           <button class="ghost" data-no>Cancel</button>
           <button class="primary" data-yes>${esc(confirmLabel || 'Confirm')}</button>
         </div>
       </div>`;
    const done = v => { back.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') done(false); };
    back.addEventListener('click', e => {
      if (e.target === back || e.target.closest('[data-no]')) done(false);
      if (e.target.closest('[data-yes]')) done(true);
    });
    document.addEventListener('keydown', onKey);
    root.appendChild(back);
    back.querySelector('[data-yes]').focus();
  });
}

/* ---------------- theme ---------------- */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('att_theme', t); } catch (e) { /* private mode */ }
  $('themeLabel').textContent = t === 'dark' ? 'Light mode' : 'Dark mode';
  $('themeIcon').innerHTML = t === 'dark' ? ICON.sun : ICON.moon;
}

/* ---------------- status pills ---------------- */
function paintPills() {
  const api = $('pillApi');
  const dot = api.querySelector('.dot');
  dot.className = 'dot ' + (state.apiOk === null ? 'warn pulse' : state.apiOk ? 'ok' : 'bad');
  api.lastChild.textContent = 'API: ' + (state.apiOk === null ? 'checking…' : state.apiOk ? 'online' : 'offline');

  const llm = $('pillLlm');
  const ldot = llm.querySelector('.dot');
  // Three distinct states, not two. `llmOk` is only ever set from a successful
  // /healthz, so when the API is unreachable it stays null - and rendering that
  // as "checking…" left the pill spinning forever next to "API: offline",
  // implying a request was still in flight. Nothing is in flight: the answer
  // is unknown, and saying so is the honest report.
  const llmUnknown = state.llmOk === null && state.apiOk === false;
  ldot.className = 'dot ' + (state.llmOk === null ? (llmUnknown ? 'bad' : '') : state.llmOk ? 'ok' : 'warn');
  llm.lastChild.textContent = llmUnknown
    ? 'Model: unknown'
    : state.llmOk === null
      ? 'Model: checking…'
      : state.llmOk ? 'Model: ready' : 'Model: not configured';
  llm.title = llmUnknown
    ? 'Cannot tell whether the model is configured - the API is unreachable'
    : state.llmOk
      ? 'GOOGLE_API_KEY is set - pasted reports go to the model'
      : 'No GOOGLE_API_KEY - the conservative rule-based fallback is used instead';
}

// Probe liveness, but never depend on a single path to decide.
//
// `/healthz` is the intended probe and is tried first. It is not the only one,
// because a proxy in front is free to answer for any path it likes: Google
// Front End - which fronts Cloud Run - reserves `/healthz` and returns its own
// 404 HTML page without ever passing the request to the container. A console
// that read liveness only from `/healthz` therefore showed "API: offline" and
// "Model: unknown" while `/queue`, `/hospitals` and the rest of the same
// container answered 200. `loadQueue` also records liveness, so `/queue` works
// as the fallback and the API is only declared unreachable when nothing at all
// responds.
const HEALTH_PROBES = ['/healthz', '/queue'];

async function checkHealth() {
  let lastErr = null;
  for (const path of HEALTH_PROBES) {
    try {
      const h = await api(path);
      state.apiOk = true;
      // Only /healthz and /queue carry model config; a path that omits it
      // leaves the existing value alone rather than reporting "not configured".
      if (h && h.llm_configured !== undefined) state.llmOk = !!h.llm_configured;
      lastErr = null;
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (lastErr) {
    state.apiOk = false;
    state.probeError = lastErr.message;
  }
  paintPills();
  if (!state.apiOk) toast('err', 'Backend unreachable', unreachableWhy());
}

// Say where the console actually looked, and what that means.
//
// The old message hardcoded `Start it with: uvicorn main:app`, which is only
// true for a developer on their own machine. A console loaded from a deployed
// Cloud Run URL that could not reach its API was told to start a local server
// - advice that is impossible to follow and points at the wrong layer entirely.
function unreachableWhy() {
  const tried = HEALTH_PROBES.join(' and ');
  if (API_BASE) {
    return `No response from ${tried} at ${API_BASE} - check that the backend is running.`;
  }
  // Same-origin: the console and the API are served by the same app, so a
  // failure on every probe means the whole service is down, not one bad URL.
  return `No response from ${tried} at ${location.origin}. The console and API `
       + `are served together, so this is the service being unreachable - check `
       + `the deployment rather than a local server.`;
}

/* ---------------- navigation ---------------- */
function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll('.nav button').forEach(b => {
    const on = b.dataset.tab === tab;
    b.classList.toggle('active', on);
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === tab));
  const [title, sub] = PAGES[tab];
  $('pageTitle').textContent = title;
  $('pageSub').textContent = sub;
  if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: 'smooth' });

  if (tab === 'pipeline') { renderPipeline(); loadTrace(); }
  if (tab === 'doctor') loadQueue();
  if (tab === 'portal') loadPortal();
  if (tab === 'compare') renderCompare();
  if (tab === 'command') { loadCommandCenter(); }
  refreshLoop();
}

/* ---------------- persistence ---------------- */
// medicine key -> display name, learned from the API payloads. The alert
// transfer object only carries the raw key, so this keeps labels readable.
const medNames = Object.create(null);

function learnMedNames(rows) {
  rows.forEach(r => { if (r && r.medicine && r.medicine_name) medNames[r.medicine] = r.medicine_name; });
}

function medName(key) {
  if (!key) return '';
  if (!medNames[key]) medNames[key] = String(key).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return medNames[key];
}

function saveRuns() {
  try { localStorage.setItem(LS_RUNS, JSON.stringify(state.history.slice(0, 25))); } catch (e) { /* quota */ }
}
function loadRuns() {
  try {
    const raw = localStorage.getItem(LS_RUNS);
    if (raw) state.history = JSON.parse(raw) || [];
  } catch (e) { state.history = []; }
}

/* ============================================================
   INTAKE
   ============================================================ */
function buildCaseCards() {
  $('caseGrid').innerHTML = CASE_PROFILES.map(c =>
    `<button class="case-opt ${c.sev} ${c.id === state.caseType ? 'active' : ''}" data-case="${c.id}">
       <span class="t"><span class="badge ${c.sev}">${c.sev}</span>${esc(c.title)}</span>
       <span class="d">${esc(c.desc)}</span>
     </button>`).join('');
  $('caseGrid').querySelectorAll('[data-case]').forEach(b =>
    b.addEventListener('click', () => {
      state.caseType = b.dataset.case;
      buildCaseCards();
    }));
}

function setMode(mode) {
  state.mode = mode;
  $('modeReport').hidden = mode !== 'report';
  $('modeCase').hidden = mode !== 'case';
  $('modeSeg').querySelectorAll('button').forEach(b => {
    const on = b.dataset.mode === mode;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  if (mode === 'report') $('preport').focus(); else $('caseGrid').querySelector('.active')?.focus();
  updateRunLabel();
}

function updateRunLabel() {
  const hasReport = $('preport').value.trim().length > 0;
  $('hintMode').innerHTML = hasReport
    ? '<b>Model path</b> — report will be read by ' + (state.llmOk ? 'the model' : 'the model, if configured')
    : '<b>Blank</b> — falls back to the “Routine fever” profile';
  $('hintChars').textContent = $('preport').value.length + ' chars';
}

function setRunMode(busy, label) {
  const btn = $('runBtn');
  btn.disabled = busy;
  $('runLabel').textContent = label;
  $('runIcon').outerHTML = busy
    ? '<span class="spinner" id="runIcon"></span>'
    : '<svg id="runIcon" viewBox="0 0 24 24" fill="currentColor">' + ICON.play + '</svg>';
}

async function submitPatient() {
  const name = $('pname').value.trim() || 'Unnamed patient';
  const report = $('preport').value.trim();
  const caseType = state.caseType;
  // In case mode a report is still sent if one was pasted earlier - the
  // backend prefers report_text, and that is the intended behaviour.
  const usingLLM = report.length > 0;

  setRunMode(true, usingLLM ? 'Reading report…' : 'Running agents…');
  try {
    const data = await api('/patients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, case_type: caseType, report_text: report || null })
    });
    state.history.unshift(data);
    saveRuns();
    // The report is deliberately NOT cleared: re-running the same severe case
    // is how you watch capacity drain and then recover. Only the name resets.
    $('pname').value = '';
    updateRunLabel();
    paintCounts();
    renderPipeline();
    switchTab('pipeline');

    const sev = data.severity;
    const routed = !!data.hospital;
    toast(routed ? (sev === 'Red' ? 'err' : 'ok') : 'err',
      `${data.name} — ${sev}`,
      routed ? `Routed to ${data.hospital} · ${data.doctor}` : 'No facility has capacity. Case escalated for manual override.',
      routed ? 4200 : 7000);
  } catch (e) {
    if (e instanceof TypeError) {
      toast('err', 'Backend unreachable', unreachableWhy());
    } else {
      toast('err', 'Request rejected', e.message);
    }
  } finally {
    setRunMode(false, 'Run Triage');
  }
}

/* ============================================================
   PIPELINE
   ============================================================ */
function sourceBadge(s1) {
  if (!s1) return '';
  if (s1.source === 'llm') {
    const ms = s1.latency_ms != null ? ` · ${s1.latency_ms}ms` : '';
    return `<span class="chip ok">${svg('bolt')}LLM ${esc(s1.model || '')}${esc(ms)}</span>`;
  }
  if (s1.source === 'fallback') {
    return `<span class="chip warn">${svg('warn')}Conservative fallback</span>`;
  }
  return `<span class="chip">Rule-based</span>`;
}

function scoreBars(step) {
  const b = step.breakdown;
  if (!b) return '';
  const rows = [
    ['Proximity', b.proximity, `0.45 w`],
    ['Capacity', b.capacity, `0.35 w`],
    ['Availability', b.availability, `0.20 w`]
  ];
  return `<div class="score-bars">
    <div class="lbl">Routing score — ${esc(b.distance_km)} km from origin</div>
    ${rows.map(([k, v, w], i) => `
      <div class="score-row">
        <span class="k">${esc(k)} <span class="psub" style="font-size:.66rem">${esc(w)}</span></span>
        <span class="track"><span class="fill" style="--w:${Math.max(0, Math.min(1, v || 0)) * 100}%;animation-delay:${i * 90}ms"></span></span>
        <span class="v">${(v == null ? 0 : v).toFixed(2)}</span>
      </div>`).join('')}
    <div class="score-total">
      <span class="psub">Total</span>
      <span class="big">${(step.score == null ? 0 : step.score).toFixed(3)}</span>
    </div>
  </div>`;
}

function rejectedReasons(step) {
  const rej = step.rejected || [];
  if (!rej.length) return '';
  return `<details class="reasons">
    <summary>${rej.length} facilit${rej.length === 1 ? 'y was' : 'ies were'} filtered out — why</summary>
    <ul class="reasons-list">
      ${rej.map(r => `<li><b>${esc(r.name)}</b> — <span class="rs">${esc((r.reasons || []).join('; '))}</span></li>`).join('')}
    </ul>
  </details>`;
}

/* The plan's "N possible doctors, M eligible, 1 selected" as a funnel.

   Agent 2 narrows the network on physical capacity, Agent 3 narrows what is
   left on doctor availability and picks one. Showing the three numbers side by
   side is what makes "why this doctor" answerable: the drop from `possible` to
   `eligible` is the resource constraint, and it is a different reason from the
   drop from `eligible` to `selected`. */
function candidateFunnel(step) {
  const c = step.candidates;
  if (!c) return '';
  const stages = [
    ['Possible', c.possible, `every ${String(c.specialty).replace(/_/g, ' ')} doctor in the network`],
    ['At capacity', c.eligible, 'facilities that physically hold the beds and stock'],
    ['Free now', c.available, 'doctors with spare capacity right now'],
    ['Selected', c.selected, 'nearest with headroom, least loaded there']
  ];
  return `<div class="funnel">
    <div class="lbl">Candidate doctors — ${esc(c.specialty.replace(/_/g, ' '))}</div>
    <div class="funnel-stages">
      ${stages.map(([k, v, why], i) => `
        <div class="fstage" style="animation-delay:${i * 80}ms">
          <div class="fv">${v == null ? '—' : v}</div>
          <div class="fk">${esc(k)}</div>
          <div class="fw">${esc(why)}</div>
        </div>
        ${i < stages.length - 1 ? `<div class="farrow">${svg('chevron')}</div>` : ''}`).join('')}
    </div>
  </div>`;
}

/* The two panels the plan asks for side by side: what the model concluded, and
   what the system then verified about the real world.

   The split is the whole argument of the product, so it is drawn as two columns
   with the boundary labelled. Each check is derived from the actual step data -
   a check with no data behind it renders as "not recorded" rather than a green
   tick, because a decorative tick on an unverified claim is worse than no
   check at all. */
function assessmentPanels(run, s2, s3) {
  const rec = run.ai_recommendation || {};
  const c = s3.candidates || {};
  const b = s3.breakdown || {};
  const specLabel = c.specialty
    ? c.specialty.replace(/_/g, ' ')
    : (run.specialty_label || run.specialty || 'none');

  const checks = [
    {
      label: 'Specialist available',
      ok: (s2.eligible || []).length > 0,
      detail: (s2.eligible || []).length
        ? `${(s2.eligible || []).length} of the network's facilities staff a ${esc(specLabel)} with capacity`
        : 'no facility cleared the specialty check'
    },
    {
      label: 'Facility holds the resources',
      ok: (s2.eligible || []).length > 0,
      detail: (s2.rejected || []).length
        ? `${(s2.rejected || []).length} rejected on beds, stock or specialty — see step 2`
        : 'every facility passed the physical check'
    },
    {
      label: 'Doctor capacity available',
      ok: typeof c.available === 'number' && c.available > 0,
      detail: c.available != null
        ? `${c.available} of ${c.eligible} eligible doctor(s) had free capacity`
        : 'not recorded'
    },
    {
      label: 'Location considered',
      ok: b.distance_km != null,
      detail: b.distance_km != null
        ? `${b.distance_km} km from origin · proximity ${Number(b.proximity).toFixed(2)} (0.45 weight)`
        : 'not recorded'
    }
  ];

  const flag = run.manual_review
    ? `<div class="mr-flag">${svg('warn')}<span><b>Held for clinician review.</b>
        ${esc(run.triage_source === 'fallback'
          ? 'The model was unavailable, so this report was not auto-cleared.'
          : 'Model confidence was below the floor, so severity was not taken at face value.')}</span></div>`
    : '';

  return `<div class="assess">
    <div class="assess-col ai">
      <div class="assess-head">
        ${svg('spark')}<h4>AI Assessment</h4>
        <span class="chip ${run.triage_source === 'llm' ? 'ok' : 'warn'}">${esc(run.triage_source || 'rules')}</span>
      </div>
      <p class="assess-note">A proposal. No code path acts on any of this — the queue orders by
        severity and a doctor decides.</p>
      ${flag}
      <dl class="assess-dl">
        <dt>Severity</dt><dd><span class="badge ${esc(run.severity)}">${esc(run.severity)}</span></dd>
        <dt>Specialty</dt><dd>${esc(String(specLabel).replace(/\b\w/g, m => m.toUpperCase()))}</dd>
        <dt>Confidence</dt><dd>${run.confidence != null ? Math.round(run.confidence * 100) + '%' : '—'}</dd>
        <dt>Recommended action</dt><dd>${esc(rec.action || '—')}</dd>
      </dl>
      <div class="assess-flags">
        <div class="k">Red flags${(run.red_flags || []).length ? ` (${run.red_flags.length})` : ''}</div>
        ${(run.red_flags || []).length
          ? `<ul>${run.red_flags.map(f => `<li>${svg('warn')}${esc(f)}</li>`).join('')}</ul>`
          : '<p class="psub">None reported.</p>'}
      </div>
    </div>
    <div class="assess-col verify">
      <div class="assess-head">
        ${svg('check')}<h4>Routing Verification</h4>
        <span class="chip">deterministic</span>
      </div>
      <p class="assess-note">Arithmetic against live inventory. The model never asserts any of this.</p>
      <ul class="checks">
        ${checks.map(c2 => `<li class="${c2.ok ? 'pass' : 'fail'}">
          <span class="cmark">${svg(c2.ok ? 'check' : 'x')}</span>
          <span class="cbody"><b>${esc(c2.label)}</b><span class="cdetail">${c2.detail}</span></span>
        </li>`).join('')}
      </ul>
      <div class="verify-out">
        <div class="k">Assigned</div>
        <div class="doc">${esc(run.doctor || 'nobody — awaiting manual override')}</div>
        <div class="fac">${esc(run.hospital || 'no facility')}</div>
        ${run.reservation && !run.reservation.committed
          ? '<div class="psub nobed">No bed or medicine held. A report reserves a review slot only.</div>' : ''}
      </div>
    </div>
  </div>`;
}

function runCard(run) {
  const s1 = run.steps[0] || {};
  const s2 = run.steps[1] || {};
  const s3 = run.steps[2] || {};
  const conf = run.confidence != null
    ? `<span class="chip">${svg('info')}confidence ${Math.round(run.confidence * 100)}%</span>` : '';
  const st = STATUS_META[run.status] || { label: run.status, tone: '' };
  const steps = run.steps.map((s, i) => `
    <div class="step" data-n="${i + 1}">
      <div class="step-title">
        <h4>${esc(s.title)}</h4>
        ${i === 0 ? sourceBadge(s1) : `<span class="chip ghost-chip">deterministic</span>`}
      </div>
      <p class="step-text">${esc(s.text)}</p>
      ${i === 1 ? rejectedReasons(s2) : ''}
      ${i === 2 ? candidateFunnel(s3) : ''}
      ${i === 2 ? scoreBars(s3) : ''}
    </div>`).join('');

  return `<article class="run-card sev-${esc(run.severity)}">
    <div class="run-head">
      <div class="run-id">
        <h3>${esc(run.name)}
          <span class="badge ${esc(run.severity)}">${esc(run.severity)}</span>
          <span class="chip ${st.tone}">${esc(st.label)}</span>
        </h3>
        <div class="run-meta">
          <span>${svg('steth')}${esc(run.case_label || '—')}</span>
          <span class="sep">·</span>
          <span>#${esc(run.id)}</span>
          ${conf ? `<span class="sep">·</span>${conf}` : ''}
        </div>
      </div>
      <div class="verdict">
        <div class="k">Assigned facility</div>
        <div class="v">${esc(run.hospital || 'None — escalated')}</div>
        <div class="s">${esc(run.doctor || 'awaiting manual override')}</div>
      </div>
    </div>
    ${assessmentPanels(run, s2, s3)}
    <div class="steps">${steps}</div>
  </article>`;
}

function renderPipeline() {
  const el = $('pipeline-body');
  $('runCount').textContent = state.history.length
    ? `${state.history.length} run${state.history.length === 1 ? '' : 's'} this session`
    : 'No runs yet this session';
  paintCounts();
  if (!state.history.length) {
    el.innerHTML = `<div class="card empty">${svg('in')}<strong>No pipeline runs yet</strong>
      <p>Submit a patient from <b>New Patient</b> and the full four-agent trace will appear here.</p></div>`;
    return;
  }
  el.innerHTML = state.history.map(runCard).join('');
}

async function loadTrace() {
  const el = $('trace-body');
  try {
    const t = await api('/agents/llm-trace');
    $('traceSub').textContent = `${t.calls.length} of last 50 calls · ${t.model}`;
    if (!t.configured) {
      el.innerHTML = `<div class="empty">${svg('info')}<strong>No model configured</strong>
        <p>Set <code>GOOGLE_API_KEY</code> in the backend <code>.env</code> to enable the LLM triage path.
        Submissions use the conservative rule-based fallback meanwhile.</p></div>`;
      return;
    }
    if (!t.calls.length) {
      el.innerHTML = `<div class="empty">${svg('bolt')}<strong>No model calls yet</strong>
        <p>Every submitted report appears here with latency, token counts and the raw structured output.</p></div>`;
      return;
    }
    el.innerHTML = t.calls.map((c, i) => {
      const toks = c.tokens || {};
      const meta = [];
      if (c.latency_ms != null) meta.push(`${c.latency_ms}ms`);
      if (c.attempt > 1) meta.push(`attempt ${c.attempt}`);
      if (toks.prompt != null) meta.push(`${toks.prompt}→${toks.completion} tokens`);
      return `<div class="trace-item">
        <div class="trace-head">
          <span class="st ${esc(c.status)}">${esc(c.status)}</span>
          ${meta.map(m => `<span class="chip ghost-chip">${esc(m)}</span>`).join('')}
        </div>
        <p class="trace-reason">${esc(c.reason || (c.result ? c.result.reasoning : ''))}</p>
        ${c.result ? `<details class="json">
            <summary>${svg('doc')}Structured output (schema-constrained)</summary>
            <pre>${esc(JSON.stringify(c.result, null, 2))}</pre>
          </details>` : ''}
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="empty">${svg('warn')}<strong>Trace unavailable</strong><p>${esc(e.message)}</p></div>`;
  }
}

/* ============================================================
   QUEUES  (patient / doctor / specialist)
   ============================================================ */
function paintCounts() {
  $('navRuns').textContent = state.history.length;
  const stats = state.queue.stats;
  $('navPts').textContent = stats ? stats.open : state.patients.length;
}

/* ---- header tiles ---- */

// Every tile is a filter on the queue below it, so a number a supervisor is
// looking at is a thing they can act on rather than just read.
//
// The tile's identity is the `key` slug in `data-tile`, not its visible label.
// Those are deliberately separate: the label is copy that carries the unit
// ("longest wait (min)") and can be reworded for clarity, while the key is the
// contract with `TILES` below. Keying the lookup on the label meant the copy
// and the behaviour were the same string, so improving either one silently
// broke the other.
//
// A tile showing zero is disabled rather than clickable: filtering to an empty
// set would only ever render the "no matching cases" card, and a dead control
// that looks live is worse than one that looks inert.
function statTiles() {
  const s = state.queue.stats;
  if (!s) return '';
  const sev = s.by_severity || {};
  const on = (filter, lens, scope) =>
    (state.filter === filter && (lens || null) === (state.lens || null)
     && state.scope === scope) ? ' on' : '';

  const tile = (key, n, label, cls, filter, lens, scope, disabled, title) =>
    `<button class="stat-tile ${cls}${on(filter, lens, scope)}" data-tile="${key}"
       ${disabled ? 'disabled' : ''} ${title ? `title="${esc(title)}"` : ''}>
       <span class="n">${n}</span><span class="l">${esc(label)}</span></button>`;

  const zero = v => !v;
  return `<div class="stat-tiles">
    ${tile('open', s.open, 'in queue', '', 'all', null, 'network', zero(s.open),
           'Every open case, highest priority first')}
    ${tile('red', sev.Red || 0, 'critical', 'red', 'Red', null, 'network',
           zero(sev.Red), 'Red cases only')}
    ${tile('yellow', sev.Yellow || 0, 'moderate', 'warn', 'Yellow', null, 'network',
           zero(sev.Yellow), 'Yellow cases only')}
    ${tile('green', sev.Green || 0, 'routine', '', 'Green', null, 'network',
           zero(sev.Green), 'Green cases only')}
    ${tile('senior', s.escalated_pending, 'with senior',
           s.escalated_pending ? 'accent' : '', 'all', null, 'specialists',
           zero(s.escalated_pending), 'Open the senior consultant queues')}
    ${tile('unassigned', s.unassigned, 'unassigned',
           s.unassigned ? 'bad' : '', 'all', 'unassigned', 'network',
           zero(s.unassigned), 'Cases with no reviewing doctor')}
    ${tile('longest', s.longest_wait_minutes, 'longest wait (min)', '',
           'all', 'longest', 'network', zero(s.open),
           'Show only the case that has waited longest')}
  </div>`;
}

// The one place a tile's key is turned into queue state. Tiles drive the
// existing filter/lens/scope triple rather than a parallel mechanism, so the
// severity pills and the tiles can never disagree about what is being shown.
function applyTile(key) {
  const t = state.queue.stats ? TILES[key] : null;
  if (!t) return;
  state.filter = t.filter;
  state.lens = t.lens || null;
  state.scope = t.scope;
  renderQueue();
}

const TILES = {
  'open':       { filter: 'all',    lens: null,        scope: 'network' },
  'red':        { filter: 'Red',    lens: null,        scope: 'network' },
  'yellow':     { filter: 'Yellow', lens: null,        scope: 'network' },
  'green':      { filter: 'Green',  lens: null,        scope: 'network' },
  'senior':     { filter: 'all',    lens: null,        scope: 'specialists' },
  'unassigned': { filter: 'all',    lens: 'unassigned', scope: 'network' },
  'longest':    { filter: 'all',    lens: 'longest',    scope: 'network' },
};

/* ---- filters ---- */
function queueRows() {
  return state.queue.patient_queue || [];
}

// Cases matching the active lens, before severity and search are applied.
//
// These are the non-severity questions the header tiles ask. Kept separate
// from `state.filter` because they answer a different question - "which cases
// have nobody?" and "who has waited longest?" are not severities - and a
// single overloaded filter string would make the two indistinguishable in the
// UI and impossible to clear independently.
function lensRows() {
  const rows = queueRows();
  if (state.lens === 'unassigned') return rows.filter(p => !p.doctor);
  if (state.lens === 'longest') {
    if (!rows.length) return rows;
    const worst = rows.reduce((a, b) =>
      (Number(b.waiting_minutes) || 0) > (Number(a.waiting_minutes) || 0) ? b : a);
    return rows.filter(p => p.id === worst.id);
  }
  return rows;
}

function filteredQueue() {
  const q = state.query.trim().toLowerCase();
  return lensRows().filter(p => {
    if (state.filter !== 'all' && p.severity !== state.filter) return false;
    if (!q) return true;
    return [p.name, p.doctor, p.hospital, p.case_label, p.severity, p.specialty_label]
      .some(v => String(v || '').toLowerCase().includes(q));
  });
}

function renderFilters() {
  const scoped = lensRows();
  const counts = { all: scoped.length };
  scoped.forEach(p => { counts[p.severity] = (counts[p.severity] || 0) + 1; });
  const keys = ['all', 'Red', 'Yellow', 'Green'].filter(k => k === 'all' || counts[k]);
  $('statusFilters').innerHTML = keys.map(k => {
    const label = k === 'all' ? 'All' : k;
    return `<button class="filter ${state.filter === k ? 'active' : ''}" data-f="${k}">${esc(label)} <span class="n">${counts[k] || 0}</span></button>`;
  }).join('');
  $('statusFilters').querySelectorAll('[data-f]').forEach(b =>
    b.addEventListener('click', () => {
      state.filter = b.dataset.f;
      // Picking a severity is a fresh question, so drop any lens left over
      // from a tile. Intersecting "unassigned" with "Red" is a real query, but
      // it is never what someone clicking a severity pill meant, and the counts
      // beside the pills are computed within the active lens - so leaving it
      // set would show a pill reading 7 above an empty list.
      state.lens = null;
      renderQueue();
    }));
}

/* The AI's advice, shown next to the case. Labelled as a recommendation
   because that is exactly what it is: nothing here has acted on it. A doctor
   who cannot tell advice from a decision will either over-trust the model or
   ignore the panel entirely. */
function recChip(rec) {
  if (!rec) return '';
  const bits = [];
  if (rec.action) bits.push(esc(rec.action));
  if (rec.physical_visit) bits.push('in-person suggested');
  if (rec.specialist_escalation) bits.push('senior review suggested');
  if (!bits.length) return '';
  return `<div class="rec" title="Model recommendation only. A doctor makes the decision.">
    ${svg('spark')}<span>${bits.join(' · ')}</span></div>`;
}

function waitCell(p) {
  const mins = p.waiting_minutes;
  const tone = mins > 120 ? 'bad' : mins > 45 ? 'warn' : '';
  return `<div class="wait ${tone}" title="Waited ${mins} min · priority ${p.priority}">
    <span class="wait-v">${mins}</span><span class="wait-u">min</span></div>`;
}

function priorityCell(p) {
  const b = p.priority_breakdown || {};
  const why = `${b.severity} = ${b.severity_points} pts, waited ${b.waited_minutes} min = +${b.wait_points}`;
  return `<div class="prio" title="${esc(why)}">
    <span class="prio-v">${p.priority}</span>
    <span class="prio-bar"><span style="width:${Math.min(100, (b.wait_points || 0) / 3)}%"></span></span>
  </div>`;
}

function decisionButtons(p) {
  if (p.status === 'admitted' || p.status === 'closed_remote') {
    const st = STATUS_META[p.status] || {};
    return `<span class="chip ${esc(st.tone || '')}">${svg('check')}${esc(st.label || p.status)}</span>`;
  }
  if (p.status === 'awaiting_specialist') {
    return `<span class="chip accent">${svg('up')}with ${esc(p.doctor || 'senior')}</span>`;
  }
  if (p.status === 'unassigned' || !p.doctor) {
    return `<span class="chip warn" title="No eligible facility yet — needs command-centre placement">${svg('warn')}unassigned</span>`;
  }
  return `<div class="decide">${DECISIONS.map(d =>
    `<button class="ghost sm dec ${esc(d.tone)}" data-decide="${p.id}" data-kind="${d.key}"
       title="${esc(d.blurb)}">${svg(d.icon)}${esc(d.short)}</button>`).join('')}</div>`;
}

function queueRow(p) {
  const src = p.triage_source === 'llm' ? 'LLM' : p.triage_source === 'rules' ? 'rules' : '';
  return `<div class="pt-row q-row" data-pid="${esc(p.id)}">
    <div class="q-main">
      <div class="nm">${esc(p.name)}
        <span class="badge ${esc(p.severity)}">${esc(p.severity)}</span>
        ${p.seed ? '<span class="chip ghost-chip" title="Demo data, not a real report">demo</span>' : ''}
        ${src ? `<span class="chip ghost-chip">${esc(src)}</span>` : ''}
        <span class="chip ghost-chip">${esc(p.specialty_label || '')}</span>
        ${p.red_flags && p.red_flags.length ? `<span class="chip bad">${svg('warn')}${p.red_flags.length} flag${p.red_flags.length === 1 ? '' : 's'}</span>` : ''}
      </div>
      <div class="sub">${esc(p.case_label || '—')} · ${esc(p.doctor || 'unassigned')} · ${esc(p.hospital || 'no facility')} · #${esc(p.id)}</div>
      ${recChip(p.ai_recommendation)}
      ${p.escalated_from ? `<div class="esc-from">${svg('up')}escalated from ${esc(p.escalated_from.doctor || '')} at ${esc(p.escalated_from.hospital || '')}</div>` : ''}
    </div>
    ${waitCell(p)}
    ${priorityCell(p)}
    <div class="side">${decisionButtons(p)}</div>
  </div>`;
}

/* ---- doctor panels ---- */
function doctorPanel(g) {
  const initials = g.doctor.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
  return `<div class="doc-group">
    <div class="doc-head">
      <div class="avatar">${esc(initials)}</div>
      <div>
        <div class="nm">${esc(g.doctor)}
          ${g.senior ? '<span class="chip accent" title="Senior consultant">senior</span>' : ''}</div>
        <div class="fac">${esc(g.specialty_label || '')}</div>
      </div>
      <span class="spacer"></span>
      ${g.red_count ? `<span class="chip bad">${g.red_count} critical</span>` : ''}
      <span class="chip">${g.open_cases} open</span>
    </div>
    <div class="doc-rows">${g.cases.map(queueRow).join('')}</div>
  </div>`;
}

function renderQueue() {
  const el = $('doctor-body');
  const s = state.queue.stats;
  el.innerHTML = statTiles() + `
    <div class="scope-seg" id="scopeSeg" role="tablist" aria-label="Queue scope">
      <button data-scope="doctors"     class="${state.scope === 'doctors' ? 'active' : ''}"     role="tab" aria-selected="${state.scope === 'doctors'}">By doctor</button>
      <button data-scope="network"     class="${state.scope === 'network' ? 'active' : ''}"     role="tab" aria-selected="${state.scope === 'network'}">Whole network</button>
      <button data-scope="specialists" class="${state.scope === 'specialists' ? 'active' : ''}" role="tab" aria-selected="${state.scope === 'specialists'}">Senior queues</button>
    </div>`;

  $('scopeSeg').querySelectorAll('[data-scope]').forEach(b =>
    b.addEventListener('click', () => {
      state.scope = b.dataset.scope;
      // The senior-queue view renders its own groups and ignores the row
      // filter, so keeping a lens set here would hide it silently behind an
      // invisible filter. Drop it and show the senior queues as they are.
      if (b.dataset.scope === 'specialists') state.lens = null;
      renderQueue();
    }));

  el.querySelectorAll('[data-tile]').forEach(b =>
    b.addEventListener('click', () => applyTile(b.dataset.tile)));

  if (state.scope === 'specialists') return renderSpecialistQueue(el);
  renderFilters();

  const rows = filteredQueue();
  const total = lensRows().length;
  const lensNote = state.lens === 'unassigned' ? ' with no reviewing doctor'
                 : state.lens === 'longest'    ? ', longest wait first' : '';
  $('queueCount').textContent = rows.length === total
    ? `${total} case${total === 1 ? '' : 's'}${lensNote}`
    : `${rows.length} of ${total} shown`;

  if (!queueRows().length) {
    el.innerHTML += `<div class="card empty">${svg('steth')}<strong>Queue is empty</strong>
      <p>Submit a report and it will appear here, already ordered by clinical priority.</p></div>`;
    return;
  }
  if (!rows.length) {
    // Reached when the active lens or severity has no matches. Say which one,
    // because "no matching cases" next to a queue holding 22 open tells the
    // reader nothing about what to undo.
    const why = state.lens === 'unassigned' ? 'Every open case has a reviewing doctor.'
               : state.lens === 'longest'    ? 'Nothing is waiting.'
               : `No ${state.filter} cases in this view.`;
    el.innerHTML += `<div class="card empty">${svg('search')}<strong>No matching cases</strong>
      <p>${esc(why)} Try a different search term, or clear the filter.</p></div>`;
    return;
  }

  if (state.scope === 'network') {
    el.innerHTML += `<div class="doc-group">
      <div class="doc-head"><div>
        <div class="nm">Whole network</div>
        <div class="fac">Every open case, ${s ? s.open : 0} total, highest priority first</div>
      </div></div>
      <div class="doc-rows">${rows.map(queueRow).join('')}</div></div>`;
  } else {
    // Group into per-doctor panels, but only those that survive the filter.
    // The backend already returns each panel in priority order, so the top row
    // of a panel is that doctor's next patient.
    const shown = new Set(rows.map(r => r.doctor).filter(Boolean));
    const groups = (state.queue.doctor_queues || []).filter(g => shown.has(g.doctor));
    const orphan = rows.filter(r => !r.doctor);
    el.innerHTML += groups.map(doctorPanel).join('');
    if (orphan.length) {
      el.innerHTML += `<div class="doc-group">
        <div class="doc-head">
          <div class="avatar" style="background:var(--red-bg);color:var(--red)">!</div>
          <div><div class="nm">Unassigned</div>
          <div class="fac">No facility had capacity for these - still waiting, not escalated</div></div>
          <span class="spacer"></span><span class="chip bad">${orphan.length}</span>
        </div>
        <div class="doc-rows">${orphan.map(queueRow).join('')}</div></div>`;
    }
  }
  wireDecisions(el);
}

function renderSpecialistQueue(el) {
  const groups = state.queue.specialist_queues || [];
  const total = groups.reduce((n, g) => n + g.open_cases, 0);
  $('queueCount').textContent = `${total} awaiting senior review`;

  if (!groups.length) {
    el.innerHTML += `<div class="card empty">${svg('up')}<strong>No escalated cases</strong>
      <p>When a doctor hands a case to a senior consultant, it appears in that specialty's queue here.</p></div>`;
    return;
  }
  el.innerHTML += groups.map(g => `<div class="doc-group">
    <div class="doc-head">
      <div class="avatar">${esc(g.specialty_label.slice(0, 2).toUpperCase())}</div>
      <div><div class="nm">${esc(g.queue_name)}</div>
      <div class="fac">Cases handed up by duty doctors</div></div>
      <span class="spacer"></span>
      ${g.critical_count ? `<span class="chip bad">${g.critical_count} critical</span>` : ''}
      <span class="chip">${g.open_cases} open</span>
    </div>
    <div class="doc-rows">${g.cases.map(queueRow).join('')}</div>
  </div>`).join('');
  wireDecisions(el);
}

function wireDecisions(scope) {
  scope.querySelectorAll('[data-decide]').forEach(b =>
    b.addEventListener('click', () => decidePatient(b.dataset.decide, b.dataset.kind)));
}

async function loadQueue() {
  const el = $('doctor-body');
  try {
    state.queue = await api('/queue');
    // A successful /queue is proof the API is reachable, and it carries the
    // model config. Recording it here means the status pills are correct even
    // if every entry in HEALTH_PROBES is answered by something in front of the
    // app - `loadQueue` runs on page load and on every refresh.
    state.apiOk = true;
    if (state.queue.llm_configured !== undefined) {
      state.llmOk = !!state.queue.llm_configured;
    }
    renderQueue();
    paintCounts();
    paintPills();
  } catch (e) {
    el.innerHTML = `<div class="card empty">${svg('warn')}<strong>Could not load the queue</strong><p>${esc(e.message)}</p></div>`;
  }
}

/* ---- the decision ---- */
async function decidePatient(id, kind) {
  const spec = DECISIONS.find(d => d.key === kind);
  const row = queueRows().find(p => String(p.id) === String(id));
  if (!spec) return;

  const kv = row ? [
    ['Patient', row.name],
    ['Case', row.case_label || '—'],
    ['Severity', row.severity],
    ['Facility', row.hospital || 'no facility'],
    ['AI advice', (row.ai_recommendation && row.ai_recommendation.action) || 'none']
  ] : [];

  const ok = await confirmModal({
    title: spec.label + '?',
    body: spec.blurb,
    kv,
    confirmLabel: spec.label,
    danger: kind === 'visit_required' || kind === 'escalate'
  });
  if (!ok) return;

  try {
    const r = await api(`/patients/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision: kind })
    });
    // Refetch rather than patching local state: a decision can move a case
    // between queues, change another doctor's workload, and commit resources.
    // Guessing the new queue position client-side is exactly the kind of
    // optimistic UI that makes a queue lie to its users.
    await loadQueue();
    if (kind === 'no_visit') {
      toast('ok', 'Closed remotely', `${r.name} handled without a visit. No bed or medicine was held for this case.`);
    } else if (kind === 'visit_required') {
      toast('ok', 'Admitted', `${r.name} admitted at ${r.hospital}. ${describeReservation(r.reservation)} now held.`);
    } else {
      // `from` lives inside `escalated_to`, and it is null when the case was
      // already with a senior of that specialty - in which case no handover
      // happened and saying "duty doctor -> senior" would be a fiction.
      const et = r.escalated_to || {};
      const from = et.from;
      const detail = from
        ? `${from.doctor} → ${r.doctor}`
        : (et.already_with_senior
            ? `already with ${r.doctor}, the senior on call for ${et.specialty}`
            : `handed to ${r.doctor}`);
      toast('ok', 'Escalated', `${r.name}: ${detail}.`);
    }
  } catch (e) {
    toast('err', 'Decision failed', e.message);
    await loadQueue();
  }
}

function describeReservation(res) {
  if (!res) return 'nothing held';
  if (!res.committed) return 'review slot only - no resources held yet';
  const parts = [];
  if (res.icu) parts.push(`${res.icu} ICU bed`);
  const meds = Object.entries(res.medicines || {});
  if (meds.length) parts.push(meds.map(([k, v]) => `${v}× ${medName(k)}`).join(', '));
  return parts.length ? parts.join(' · ') : 'case load only';
}

/* ---------------- patient portal upload (§19 screen 1, "Upload Report") ---------------- */

// The file the patient chose, held until submit. Reading it on change rather
// than on submit means the size and type are known before anything is sent, so
// an oversized or wrong-typed file fails immediately instead of after a
// round-trip.
let portalFile = null;
const MAX_UPLOAD_BYTES = 200 * 1024;

function portalUploadError(msg) {
  $('pupdrop').classList.add('bad');
  toast('err', 'Cannot use that file', msg);
  portalFile = null;
  $('pupfile').value = '';
}

// Takes the file directly rather than reading it off an input element, so the
// picker and the drop handler share one validation path. Assigning to
// input.files is not reliable across browsers, and doing it just to normalise
// the two paths would be fragile for no gain.
function acceptPortalFile(f) {
  $('pupdrop').classList.remove('bad');
  if (!f) { portalFile = null; return; }
  if (f.size > MAX_UPLOAD_BYTES) {
    portalUploadError(`${f.name} is ${Math.round(f.size / 1024)} KB. The limit is 200 KB — a report is text, not an image.`);
    return;
  }
  portalFile = f;
  $('pupdrop').querySelector('.updrop-in b').textContent = f.name;
}

function resetPortalUpload() {
  portalFile = null;
  $('pupfile').value = '';
  $('pupdrop').classList.remove('bad');
  $('pupdrop').querySelector('.updrop-in b').textContent = 'Choose a report file';
}

async function onPortalUpload() {
  if (!portalFile) {
    toast('err', 'No file chosen', 'Pick a report file first, or enter a case ID below to track an existing case.');
    return;
  }
  const btn = $('pupGo');
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Submitting…';
  try {
    // FileReader rather than file.text(): the browser build this ships to may
    // be older than the Blob.text() method.
    const text = await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result || ''));
      r.onerror = () => reject(new Error('the file could not be read'));
      r.readAsText(portalFile);
    });

    const body = text.trim();
    if (!body) throw new Error('the file is empty');

    const data = await api('/patients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: $('pupname').value.trim() || 'Unnamed patient',
        case_type: 'normal',
        report_text: body
      })
    });

    toast(data.manual_review ? 'err' : 'ok',
      `${data.name} — ${data.severity}`,
      data.manual_review
        ? 'Held for a clinician. Nothing is decided automatically.'
        : `Queued · ${data.hospital || 'no facility with capacity'}`);

    resetPortalUpload();
    $('pupname').value = '';
    // The point of a portal is to see what happened, so show the new case
    // rather than dropping the patient on a queue they cannot interpret.
    $('portalId').value = data.id;
    loadPortal(data.id);
  } catch (e) {
    toast('err', 'Upload failed', e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

/* ============================================================
   PATIENT PORTAL  (§19 screen 1)

   The one screen in this app addressed to a patient rather than a clinician.
   It reads GET /patients/{id} - the same endpoint the patient would hit on a
   phone - and deliberately renders only the fields that endpoint returns. It
   does not reach for the internal record, because the whole point of the
   portal view is that it withholds stock levels, doctor workload and other
   patients. Building this screen from /queue data instead would quietly
   reintroduce exactly what the portal view exists to withhold.
   ============================================================ */
const PORTAL_TONE = {
  awaiting_review:     { tone: 'warn',   head: 'Waiting for a doctor to review your report' },
  awaiting_specialist: { tone: 'accent', head: 'A senior specialist is reviewing your case' },
  unassigned:          { tone: 'bad',    head: 'No doctor is free yet — your case is still in the queue' },
  admitted:            { tone: 'ok',     head: 'You have been asked to come in' },
  closed_remote:       { tone: 'ok',     head: 'Handled remotely — no visit needed' }
};

const DECISION_COPY = {
  no_visit: {
    title: 'No physical visit required',
    body: 'A doctor read your report and handled it remotely. You do not need to travel. ' +
          'Keep taking the medicines advised and get a review if you get worse.'
  },
  visit_required: {
    title: 'Please come to the facility',
    body: 'A doctor has decided you need to be examined in person. A bed and any medicines ' +
          'your case needs are already held for you.'
  },
  escalate: {
    title: 'Referred to a senior specialist',
    body: 'A doctor has passed your case to a senior consultant in the relevant specialty. ' +
          'They will review your report and contact you with the next step.'
  }
};

function portalDecision(p) {
  if (!p.decision) {
    return `<div class="pdec pending">
      <div class="pdec-t">${svg('clock')}Awaiting a doctor's decision</div>
      <p>Your report is in the queue. Nothing is decided until a doctor reviews it, and no
      appointment is needed from you yet.</p>
    </div>`;
  }
  const c = DECISION_COPY[p.decision] || { title: p.decision, body: '' };
  return `<div class="pdec ${esc(p.decision)}">
    <div class="pdec-t">${svg('check')}${esc(c.title)}</div>
    <p>${esc(c.body)}</p>
    ${p.decision_note ? `<div class="pnote"><b>Note from the doctor:</b> ${esc(p.decision_note)}</div>` : ''}
  </div>`;
}

function portalCard(p) {
  const t = PORTAL_TONE[p.status] || { tone: '', head: p.status };
  const waiting = p.position != null;
  return `<div class="pcard">
    <div class="pcard-head">
      <div>
        <h3>${esc(p.name)}</h3>
        <div class="pcard-meta">
          <span class="badge ${esc(p.severity)}">${esc(p.severity)}</span>
          <span>Case #${esc(p.id)}</span>
          <span class="sep">·</span>
          <span>${esc(p.case_label || '')}</span>
        </div>
      </div>
      <span class="chip ${t.tone}">${esc(t.head)}</span>
    </div>

    <div class="pstats">
      <div class="pstat">
        <div class="k">Your place in the queue</div>
        <div class="v">${waiting ? '#' + esc(p.position) : '—'}</div>
        <div class="s">${waiting ? `of ${esc(p.queue_length)} waiting` : 'left the queue'}</div>
      </div>
      <div class="pstat">
        <div class="k">Waiting for</div>
        <div class="v">${waiting ? Math.round(p.waiting_minutes) + ' min' : '—'}</div>
        <div class="s">${waiting ? 'since your report was submitted' : 'closed'}</div>
      </div>
      <div class="pstat">
        <div class="k">Reviewed by</div>
        <div class="v small">${esc(p.assigned_doctor || 'Not yet assigned')}</div>
        <div class="s">${esc(p.assigned_facility || p.specialty_label || '')}</div>
      </div>
    </div>

    ${portalDecision(p)}

    ${p.report_text ? `<details class="preport">
      <summary>${svg('doc')}The report you submitted</summary>
      <pre>${esc(p.report_text)}</pre>
    </details>` : ''}
  </div>`;
}

function renderPortal(p) {
  $('portal-body').innerHTML = p
    ? portalCard(p)
    : `<div class="card empty">${svg('info')}<strong>No case selected</strong>
       <p>Enter a case ID above, or pick one from the list.</p></div>`;
}

function renderPortalList(rows) {
  const el = $('portalList');
  if (!rows.length) {
    el.innerHTML = '<p class="psub">No open cases in the queue.</p>';
    return;
  }
  el.innerHTML = `<div class="plist-label psub">Open cases</div>
    <div class="plist">${rows.slice(0, 12).map(r => `
      <button class="pchip" data-pid="${esc(r.id)}">
        <span class="badge ${esc(r.severity)}">${esc(r.severity)}</span>
        <span class="pn">#${esc(r.id)}</span>
        <span class="pm">${esc(r.name)}</span>
      </button>`).join('')}</div>`;
  el.querySelectorAll('[data-pid]').forEach(b => b.addEventListener('click', () => {
    $('portalId').value = b.dataset.pid;
    loadPortal(b.dataset.pid);
  }));
}

async function loadPortal(id) {
  const el = $('portal-body');
  // The case list comes from the internal queue because this is a staff-side
  // console picking which record to inspect. Everything rendered *into* the
  // patient card still comes only from the portal endpoint.
  try {
    if (!state.queue.patient_queue || !state.queue.patient_queue.length) await loadQueue();
    renderPortalList(state.queue.patient_queue || []);
  } catch (e) { /* the list is a convenience; a failure must not block lookup */ }

  const want = id != null ? id : $('portalId').value;
  if (!want) { renderPortal(null); return; }
  el.innerHTML = `<div class="card empty">${svg('clock')}<strong>Loading case…</strong></div>`;
  try {
    renderPortal(await api('/patients/' + encodeURIComponent(want)));
  } catch (e) {
    el.innerHTML = `<div class="card empty">${svg('warn')}<strong>Could not load case #${esc(want)}</strong>
      <p>${esc(e.message)}</p></div>`;
  }
}

/* ============================================================
   BEFORE / AFTER  (§12)

   The plan calls this one of the strongest pitch visuals, so it is built from
   the real flow rather than a diagram: every "after" step names the component
   in this repo that performs it, and the counts on the left are the actual
   queues a report has to pass through today.
   ============================================================ */
const BA_FLOW = {
  before: [
    ['Patient travels to the facility', 'Queue outside the OPD, waiting on foot.'],
    ['Queue for a doctor', 'Position depends on who walked in, not on how sick anyone is.'],
    ['Doctor writes a test order', 'Vitals and history repeated from scratch.'],
    ['Queue again for the test', 'A second wait for the same complaint.'],
    ['Report is produced', 'Handwritten, then read by eye, often misread.'],
    ['Queue again for the report', 'A third wait, this time to interpret a page.'],
    ['Doctor reads it', 'The first time the severity is actually assessed.'],
    ['Possible specialist referral', 'And another queue, at another facility, another day.']
  ],
  after: [
    ['Report arrives as text', 'A photo of a report, OCR errors and all, read as-is.'],
    ['Model proposes a triage', 'Severity, specialty, red flags — as a proposal, not a verdict.'],
    ['System verifies reality', 'Agents 2–4 check beds, stock and doctor rosters. Pure arithmetic.'],
    ['Case enters one queue', 'Ordered by severity first, waiting time second.'],
    ['The right doctor reviews it', 'Already assigned; no second queue for the same complaint.'],
    ['One of three decisions', 'Remote review · come in · escalate to a senior consultant.'],
    ['Resources committed only then', 'A bed is held because a doctor decided, never because a file arrived.'],
    ['Patient is told the outcome', 'Position, wait and decision in the patient portal.']
  ]
};

const BA_NOTES = [
  ['One queue, not five', 'The old path makes a patient queue repeatedly for the same clinical question. Here the report carries the clinical content, so the only wait left is for a doctor\'s judgement.'],
  ['Severity decides order, not arrival time', 'Priority is severity bands of 1000 / 500 / 100 plus a wait bonus capped at 300. The cap is strictly below the narrowest band gap, so no amount of waiting lets a mild case out-rank a critical one.'],
  ['Waiting less does not mean being cleared less', 'A doctor still decides every case. The model\'s opinion is shown beside the case as advice and is never acted on by any code path.'],
  ['A digital queue does not hoard beds', 'Assignment reserves a review slot only. ICU beds and medicine are committed at the moment a doctor chooses to admit, so scarce stock is not tied up by a file sitting in a queue.'],
  ['An unreadable report is never auto-cleared', 'If the model is unavailable, slow or unsure, the case is held for a clinician with the reason shown. Failing open — marking a patient safe because triage did not run — is the failure mode that hurts.']
];

function renderCompare() {
  $('baGrid').innerHTML = ['before', 'after'].map(side => `
    <div class="ba-col ${side}">
      <div class="ba-head">
        <span class="chip ${side === 'before' ? 'bad' : 'ok'}">${side === 'before' ? 'Today' : 'AI Medical Queue'}</span>
        <div class="ba-sub">${side === 'before'
          ? 'Repeated physical queues for one report'
          : 'One report, one queue, one doctor decision'}</div>
      </div>
      <ol class="ba-steps">
        ${BA_FLOW[side].map(([t, d], i) => `
          <li style="animation-delay:${i * 60}ms">
            <span class="n">${i + 1}</span>
            <span class="b"><b>${esc(t)}</b><span class="d">${esc(d)}</span></span>
          </li>`).join('')}
      </ol>
      <div class="ba-foot">${side === 'before'
        ? `${BA_FLOW.before.length} separate waits before anyone assesses severity`
        : `${BA_FLOW.after.length} steps, and a report never consumes a bed`}</div>
    </div>`).join('');

  $('baNotes').innerHTML = `<div class="ba-note-grid">${BA_NOTES.map(([t, d]) => `
    <div class="banote">
      <b>${esc(t)}</b>
      <p>${esc(d)}</p>
    </div>`).join('')}</div>`;
}

/* ============================================================
   COMMAND CENTER
   ============================================================ */
function sortRows(rows, cfg) {
  const d = cfg.dir;
  return rows.slice().sort((a, b) => {
    const x = a[cfg.key], y = b[cfg.key];
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * d;
    return String(x ?? '').localeCompare(String(y ?? '')) * d;
  });
}

function th(label, group, key, numeric) {
  const s = state.sort[group];
  const on = s.key === key;
  return `<th class="sortable ${numeric ? 'num' : ''} ${on ? 'sorted' : ''}" data-sort="${group}.${key}">
    ${esc(label)}<span class="arrow">${on ? (s.dir === 1 ? '▲' : '▼') : '↕'}</span></th>`;
}

function icuCell(h) {
  if (h.icu_total === 0) return `<span class="stat-na">n/a</span>`;
  const pct = h.icu / h.icu_total;
  const cls = pct === 0 ? 'bad' : pct < 0.25 ? 'warn' : '';
  return `<div class="meter">
      <span class="meter-track"><span class="meter-fill ${cls}" style="width:${pct * 100}%"></span></span>
      <span class="meter-val ${cls ? 'stat-' + cls : ''}">${h.icu}/${h.icu_total}</span>
    </div>`;
}

function skeletonCard(rows) {
  return `<div class="card"><div class="card-head tight"><div class="sk sk-line" style="width:170px;height:15px"></div></div>
    ${Array.from({ length: rows }).map(() => '<div class="sk-row"><div class="sk sk-line"></div><div class="sk sk-line" style="max-width:90px"></div></div>').join('')}
  </div>`;
}

async function loadCommandCenter() {
  const el = $('command-body');
  if (!el.childElementCount) el.innerHTML = skeletonCard(4) + skeletonCard(3);
  try {
    const [hospitals, alerts, forecast] = await Promise.all([
      api('/hospitals'), api('/command-center/alerts'), api('/command-center/forecast')
    ]);
    learnMedNames(forecast);
    alerts.forEach(a => learnMedNames(a.reasons || []));

    const freeIcu = hospitals.reduce((n, h) => n + h.icu, 0);
    const totalIcu = hospitals.reduce((n, h) => n + h.icu_total, 0);
    const platelets = hospitals.reduce((n, h) => n + h.free_platelets, 0);
    const crit = alerts.filter(a => a.critical).length;
    const icuPct = totalIcu ? Math.round((freeIcu / totalIcu) * 100) : 0;
    const atRisk = forecast.filter(f => f.days_of_cover < 7).length;

    const kpi = (cls, k, n, u) =>
      `<div class="kpi ${cls}"><div class="k">${esc(k)}</div><div class="n">${esc(n)}</div><div class="u">${esc(u)}</div></div>`;

    const invRows = sortRows(hospitals, state.sort.inv).map(h => {
      const load = h.doctors.map(d => `${esc(d.name)} ${d.load}/${d.capacity}`).join(' · ');
      return `<tr>
        <td><b>${esc(h.name)}</b><div class="psub">${esc(h.district)} · ${esc(h.type)}</div></td>
        <td>${icuCell(h)}</td>
        <td class="num ${h.free_platelets < 3 ? 'stat-low' : h.free_platelets < 8 ? 'stat-mid' : ''}">${h.free_platelets}</td>
        <td class="num">${esc(h.distance_km)} km</td>
        <td class="psub" style="max-width:280px">${load || '—'}</td>
      </tr>`;
    }).join('');

    const alertsHtml = !alerts.length
      ? `<div class="empty">${svg('check')}<strong>Network is stocked</strong>
         <p>No facility is projected to run out within the reorder window.</p></div>`
      : alerts.map(a => {
          const body = (a.reasons || []).map(r => r.message).join(' · ');
          const t = a.transfer;
          const canMove = t && t.amount > 0 && a.donor;
          const mName = medName(t && t.medicine);
          const action = canMove
            ? `<button class="ghost sm" data-donor="${esc(a.donor_id)}" data-receiver="${esc(a.hospital_id)}"
                        data-med="${esc(t.medicine)}" data-amt="${t.amount}"
                        data-donorname="${esc(a.donor)}" data-recname="${esc(a.hospital)}"
                        data-medname="${esc(mName)}">
                 ${svg('move')}Move ${t.amount} × ${esc(mName)}</button>`
            : `<span class="psub">No facility has surplus to donate</span>`;
          return `<div class="alert ${a.critical ? 'crit' : ''}">
            <span class="alert-ic">${svg(a.critical ? 'alert' : 'warn')}</span>
            <div class="bd">
              <strong>${esc(a.hospital)}</strong>${a.critical ? ' <span class="chip bad">critical</span>' : ''}
              <p>${esc(body)}</p>
              ${canMove ? `<p class="psub" style="margin-top:4px">Suggested donor: <b>${esc(a.donor)}</b></p>` : ''}
            </div>
            <div class="side">${action}</div>
          </div>`;
        }).join('');

    const fRows = sortRows(forecast, state.sort.cov).slice(0, 14).map(f => {
      const pct = Math.max(0, Math.min(1, f.days_of_cover / 30));
      const cls = f.days_of_cover < 3 ? 'bad' : f.days_of_cover < 7 ? 'warn' : '';
      const rising = f.recent_daily > f.mean_daily * 1.15;
      return `<tr>
        <td><b>${esc(f.hospital)}</b></td>
        <td>${esc(f.medicine_name)}<div class="psub">${esc(f.medicine)}</div></td>
        <td class="num">${f.stock}<div class="psub">min ${f.reorder_threshold}</div></td>
        <td><div class="meter">
            <span class="meter-track"><span class="meter-fill ${cls}" style="width:${pct * 100}%"></span></span>
            <span class="meter-val ${cls ? 'stat-' + cls : ''}">${f.days_of_cover}d</span>
          </div></td>
        <td class="num ${rising ? 'stat-mid' : ''}">${f.mean_daily}/d${rising ? ' ↑' : ''}</td>
      </tr>`;
    }).join('');

    el.innerHTML = `
      <div class="kpis">
        ${kpi(freeIcu === 0 ? 'bad' : freeIcu / totalIcu < 0.25 ? 'warn' : 'good', 'Free ICU beds', `${freeIcu}/${totalIcu}`, `${icuPct}% of network capacity`)}
        ${kpi(platelets < 8 ? 'warn' : '', 'Platelet units', platelets, 'across all facilities')}
        ${kpi(crit ? 'bad' : alerts.length ? 'warn' : 'good', 'Shortage alerts', alerts.length, crit ? `${crit} critical` : 'no critical alerts')}
        ${kpi(atRisk ? 'warn' : 'good', 'Under 7 days cover', `${atRisk}/${forecast.length}`, 'facility × medicine pairs')}
      </div>

      <div class="card">
        <div class="card-head">
          <h3>Live facility inventory</h3>
          <span class="spacer"></span>
          <span class="legend">
            <span><i style="background:var(--green)"></i>healthy</span>
            <span><i style="background:var(--amber)"></i>&lt;25% free</span>
            <span><i style="background:var(--red)"></i>full</span>
          </span>
        </div>
        <div class="tbl-wrap"><table>
          <thead><tr>${th('Facility', 'inv', 'name')}${th('Free ICU', 'inv', 'icu')}${th('Platelets', 'inv', 'free_platelets', 1)}${th('Distance', 'inv', 'distance_km', 1)}<th>Doctor load</th></tr></thead>
          <tbody>${invRows}</tbody>
        </table></div>
      </div>

      <div class="card">
        <div class="card-head">
          <h3>Agent 4 — forecast &amp; redistribution</h3>
          <span class="spacer"></span>
          <span class="psub">Transfers never drain a donor below its reorder floor</span>
        </div>
        ${alertsHtml}
      </div>

      <div class="card">
        <div class="card-head">
          <h3>Days of cover</h3>
          <span class="psub">Worst 14 of ${forecast.length} facility/medicine pairs, from 30 days of consumption</span>
        </div>
        <div class="tbl-wrap"><table>
          <thead><tr>${th('Facility', 'cov', 'hospital')}${th('Medicine', 'cov', 'medicine_name')}${th('Stock', 'cov', 'stock', 1)}${th('Cover', 'cov', 'days_of_cover', 1)}${th('Draw rate', 'cov', 'mean_daily', 1)}</tr></thead>
          <tbody>${fRows}</tbody>
        </table></div>
      </div>`;

    el.querySelectorAll('[data-sort]').forEach(t => t.addEventListener('click', () => {
      const [g, k] = t.dataset.sort.split('.');
      const cur = state.sort[g];
      cur.dir = (cur.key === k) ? -cur.dir : 1;
      cur.key = k;
      loadCommandCenter();
    }));

    el.querySelectorAll('[data-donor]').forEach(b => b.addEventListener('click', () => {
      redistribute({
        donorId: b.dataset.donor, receiverId: b.dataset.receiver,
        medicine: b.dataset.med, amount: Number(b.dataset.amt),
        donorName: b.dataset.donorname, receiverName: b.dataset.recname,
        medicineName: b.dataset.medname
      });
    }));

    state.lastRefresh = Date.now();
    updateRefreshNote();
  } catch (e) {
    el.innerHTML = `<div class="card empty">${svg('warn')}<strong>Command center unavailable</strong><p>${esc(e.message)}</p></div>`;
  }
}

async function redistribute(info) {
  const ok = await confirmModal({
    title: 'Transfer stock?',
    body: 'Agent 4 recomputes the donor\'s true surplus before moving anything. If the donor has nothing above its floor, the transfer is refused.',
    kv: [
      ['Medicine', `${info.amount} × ${info.medicineName || info.medicine}`],
      ['From', info.donorName],
      ['To', info.receiverName]
    ],
    confirmLabel: 'Move stock'
  });
  if (!ok) return;
  try {
    const r = await api('/command-center/redistribute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        donor_id: info.donorId, receiver_id: info.receiverId,
        medicine: info.medicine, amount: info.amount
      })
    });
    if (r.moved > 0) {
      toast('ok', 'Stock moved', `${r.moved} × ${medName(r.medicine)}: ${r.donor} → ${r.receiver}.`);
    } else {
      toast('info', 'Nothing moved', `${r.donor} has no surplus ${medName(r.medicine)} above its floor.`, 5200);
    }
    await loadCommandCenter();
  } catch (e) {
    toast('err', 'Transfer failed', e.message);
  }
}

/* ---------------- auto refresh ---------------- */
let tickTimer = null;

function updateRefreshNote() {
  const ring = $('ringFg');
  const C = 2 * Math.PI * 8;
  const pct = state.autoSec ? 1 - state.countdown / state.autoSec : 0;
  ring.style.strokeDasharray = C;
  ring.style.strokeDashoffset = C * (1 - pct);
  if (state.autoSec) {
    const age = state.lastRefresh ? Math.round((Date.now() - state.lastRefresh) / 1000) : 0;
    $('refreshNote').textContent = `updated ${age}s ago · next in ${state.countdown}s`;
  } else {
    $('refreshNote').textContent = 'auto refresh paused';
  }
}

function refreshLoop() {
  if (tickTimer) clearInterval(tickTimer);
  state.countdown = state.autoSec;
  updateRefreshNote();
  // The queue is polled too, not just the command centre. Waiting time is a
  // live number on every queue row, so a queue left open on one screen must
  // still count up - a patient watching their own wait time frozen would be
  // actively misled about how long they have.
  const pollable = () => state.tab === 'command' || state.tab === 'doctor';
  if (!pollable() || !state.autoSec) return;
  tickTimer = setInterval(() => {
    if (!pollable() || !state.autoSec) { clearInterval(tickTimer); tickTimer = null; return; }
    state.countdown -= 1;
    if (state.countdown <= 0) {
      state.countdown = state.autoSec;
      if (state.tab === 'command') loadCommandCenter();
      else loadQueue();
    }
    updateRefreshNote();
  }, 1000);
}

/* ============================================================
   WIRING
   ============================================================ */
function init() {
  // theme
  let saved = null;
  try { saved = localStorage.getItem('att_theme'); } catch (e) { /* ignore */ }
  applyTheme(saved || 'dark');
  $('themeBtn').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });

  // nav
  $('nav').querySelectorAll('button').forEach(b =>
    b.addEventListener('click', () => switchTab(b.dataset.tab)));

  // intake
  $('modeSeg').querySelectorAll('button').forEach(b =>
    b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('preport').addEventListener('input', updateRunLabel);
  $('runBtn').addEventListener('click', submitPatient);
  $('sampleBtn').addEventListener('click', () => {
    $('preport').value = SAMPLE_SEVERE;
    setMode('report'); updateRunLabel();
    toast('info', 'Sample loaded', 'Severe dengue with plasma leak — will request 1 ICU bed and 5 platelet units.');
  });
  $('sampleOcrBtn').addEventListener('click', () => {
    $('preport').value = SAMPLE_OCR;
    setMode('report'); updateRunLabel();
    toast('info', 'OCR-degraded sample loaded', 'SpO2 misread as Sp02, Hb truncated, punctuation stripped. Watch whether triage still holds.');
  });
  $('clearBtn').addEventListener('click', () => {
    $('preport').value = ''; $('pname').value = ''; updateRunLabel(); $('preport').focus();
  });
  buildCaseCards();
  setRunMode(false, 'Run Triage');
  updateRunLabel();
  paintPills();

  // pipeline
  loadRuns();
  $('clearRunsBtn').addEventListener('click', () => {
    state.history = []; saveRuns(); renderPipeline();
    toast('info', 'Run history cleared', 'Server-side case records are untouched.');
  });

  // doctor
  $('qSearch').addEventListener('input', debounce(e => { state.query = e.target.value; renderQueue(); }, 140));
  $('qSearch').addEventListener('keydown', e => { if (e.key === 'Escape') { e.target.value = ''; state.query = ''; renderQueue(); } });

  // patient portal
  $('portalGo').addEventListener('click', () => loadPortal($('portalId').value));
  $('portalId').addEventListener('keydown', e => { if (e.key === 'Enter') loadPortal(e.target.value); });
  $('pupfile').addEventListener('change', e => acceptPortalFile(e.target.files && e.target.files[0]));
  $('pupGo').addEventListener('click', onPortalUpload);
  // Clicking anywhere on the drop zone opens the picker. The <input> is hidden
  // so the whole card can be the hit target; it stays keyboard-reachable through
  // the label, so this is an enhancement rather than the only way in.
  $('pupdrop').addEventListener('click', () => $('pupfile').click());
  $('pupdrop').addEventListener('dragover', e => { e.preventDefault(); $('pupdrop').classList.add('over'); });
  $('pupdrop').addEventListener('dragleave', () => $('pupdrop').classList.remove('over'));
  $('pupdrop').addEventListener('drop', e => {
    e.preventDefault();
    $('pupdrop').classList.remove('over');
    acceptPortalFile(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]);
  });

  // command
  $('refreshBtn').addEventListener('click', () => {
    state.countdown = state.autoSec || 15;
    loadCommandCenter();
  });
  $('refreshSeg').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    state.autoSec = b.dataset.auto === 'off' ? 0 : Number(b.dataset.auto);
    $('refreshSeg').querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b));
    refreshLoop();
    toast('info', state.autoSec ? `Auto refresh every ${state.autoSec}s` : 'Auto refresh paused');
  }));

  // keyboard
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
    const inIntake = e.target.id === 'pname' || e.target.id === 'preport';
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && (!typing || inIntake)) {
      e.preventDefault(); submitPatient(); return;
    }
    if (typing) return;
    if (e.key === '/') { e.preventDefault(); switchTab('doctor'); setTimeout(() => $('qSearch').focus(), 60); return; }
    const map = { '1': 'intake', '2': 'pipeline', '3': 'doctor', '4': 'portal', '5': 'compare', '6': 'command' };
    if (map[e.key]) switchTab(map[e.key]);
  });

  checkHealth();
  // Warm the queues on boot so the Doctor Queue and Patient Portal tabs have
  // content when opened. The backend seeds a demo backlog for exactly this.
  loadQueue();
  renderPipeline();
  setTimeout(updateRefreshNote, 1000);
}

document.addEventListener('DOMContentLoaded', init);
