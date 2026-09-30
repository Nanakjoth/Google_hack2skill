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

async function api(path, opts) {
  const res = await fetch(API_BASE + path, opts);
  let body = null;
  try { body = await res.json(); } catch (e) { /* empty or non-JSON body */ }
  if (!res.ok) {
    const detail = (body && (body.detail || body.message)) || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
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
  ldot.className = 'dot ' + (state.llmOk === null ? '' : state.llmOk ? 'ok' : 'warn');
  llm.lastChild.textContent = state.llmOk === null
    ? 'Model: checking…'
    : state.llmOk ? 'Model: ready' : 'Model: not configured';
  llm.title = state.llmOk
    ? 'GROQ_API_KEY is set - pasted reports go to the model'
    : 'No GROQ_API_KEY - the conservative rule-based fallback is used instead';
}

async function checkHealth() {
  try {
    const h = await api('/');
    state.apiOk = true;
    state.llmOk = !!h.llm_configured;
  } catch (e) {
    state.apiOk = false;
  }
  paintPills();
  if (!state.apiOk) toast('err', 'Backend unreachable', `No response from ${API_BASE}. Start it with: uvicorn main:app`);
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
      toast('err', 'Backend unreachable', `Could not reach ${API_BASE}.`);
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

function runCard(run) {
  const s1 = run.steps[0] || {};
  const s2 = run.steps[1] || {};
  const s3 = run.steps[2] || {};
  const conf = run.confidence != null
    ? `<span class="chip">${svg('info')}confidence ${Math.round(run.confidence * 100)}%</span>` : '';
  const st = STATUS_META[run.status] || { label: run.status, tone: '' };
  const flags = (run.red_flags && run.red_flags.length)
    ? `<div class="flags">${run.red_flags.map(f => `<span class="flag">${svg('warn')}${esc(f)}</span>`).join('')}</div>` : '';

  const steps = run.steps.map((s, i) => `
    <div class="step" data-n="${i + 1}">
      <div class="step-title">
        <h4>${esc(s.title)}</h4>
        ${i === 0 ? sourceBadge(s1) : `<span class="chip ghost-chip">deterministic</span>`}
      </div>
      <p class="step-text">${esc(s.text)}</p>
      ${i === 2 ? scoreBars(s3) : ''}
      ${i === 1 ? rejectedReasons(s2) : ''}
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
        ${flags}
      </div>
      <div class="verdict">
        <div class="k">Assigned facility</div>
        <div class="v">${esc(run.hospital || 'None — escalated')}</div>
        <div class="s">${esc(run.doctor || 'awaiting manual override')}</div>
      </div>
    </div>
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
        <p>Set <code>GROQ_API_KEY</code> in the backend <code>.env</code> to enable the LLM triage path.
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
function statTiles() {
  const s = state.queue.stats;
  if (!s) return '';
  const sev = s.by_severity || {};
  return `<div class="stat-tiles">
    <div class="stat-tile"><span class="n">${s.open}</span><span class="l">in queue</span></div>
    <div class="stat-tile red"><span class="n">${sev.Red || 0}</span><span class="l">critical</span></div>
    <div class="stat-tile warn"><span class="n">${sev.Yellow || 0}</span><span class="l">moderate</span></div>
    <div class="stat-tile"><span class="n">${sev.Green || 0}</span><span class="l">routine</span></div>
    <div class="stat-tile ${s.escalated_pending ? 'accent' : ''}"><span class="n">${s.escalated_pending}</span><span class="l">with senior</span></div>
    <div class="stat-tile ${s.unassigned ? 'bad' : ''}"><span class="n">${s.unassigned}</span><span class="l">unassigned</span></div>
    <div class="stat-tile"><span class="n">${s.longest_wait_minutes}</span><span class="l">longest wait (min)</span></div>
  </div>`;
}

/* ---- filters ---- */
function queueRows() {
  return state.queue.patient_queue || [];
}

function filteredQueue() {
  const q = state.query.trim().toLowerCase();
  return queueRows().filter(p => {
    if (state.filter !== 'all' && p.severity !== state.filter) return false;
    if (!q) return true;
    return [p.name, p.doctor, p.hospital, p.case_label, p.severity, p.specialty_label]
      .some(v => String(v || '').toLowerCase().includes(q));
  });
}

function renderFilters() {
  const counts = { all: queueRows().length };
  queueRows().forEach(p => { counts[p.severity] = (counts[p.severity] || 0) + 1; });
  const keys = ['all', 'Red', 'Yellow', 'Green'].filter(k => k === 'all' || counts[k]);
  $('statusFilters').innerHTML = keys.map(k => {
    const label = k === 'all' ? 'All' : k;
    return `<button class="filter ${state.filter === k ? 'active' : ''}" data-f="${k}">${esc(label)} <span class="n">${counts[k] || 0}</span></button>`;
  }).join('');
  $('statusFilters').querySelectorAll('[data-f]').forEach(b =>
    b.addEventListener('click', () => { state.filter = b.dataset.f; renderQueue(); }));
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
    b.addEventListener('click', () => { state.scope = b.dataset.scope; renderQueue(); }));

  if (state.scope === 'specialists') return renderSpecialistQueue(el);
  renderFilters();

  const rows = filteredQueue();
  const total = queueRows().length;
  $('queueCount').textContent = rows.length === total
    ? `${total} case${total === 1 ? '' : 's'}`
    : `${rows.length} of ${total} shown`;

  if (!total) {
    el.innerHTML += `<div class="card empty">${svg('steth')}<strong>Queue is empty</strong>
      <p>Submit a report and it will appear here, already ordered by clinical priority.</p></div>`;
    return;
  }
  if (!rows.length) {
    el.innerHTML += `<div class="card empty">${svg('search')}<strong>No matching cases</strong>
      <p>Try a different search term or clear the severity filter.</p></div>`;
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
    renderQueue();
    paintCounts();
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
    const map = { '1': 'intake', '2': 'pipeline', '3': 'doctor', '4': 'command' };
    if (map[e.key]) switchTab(map[e.key]);
  });

  checkHealth();
  // Warm the queues on boot so the Doctor Queue tab has content when opened.
  // The backend seeds a demo backlog for exactly this reason.
  loadQueue();
  renderPipeline();
  setTimeout(updateRefreshNote, 1000);
}

document.addEventListener('DOMContentLoaded', init);
