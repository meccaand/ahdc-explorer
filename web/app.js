// AHDC Data Explorer: front end. Renders the locked design (design/DESIGN.md) from the agent's event stream.
'use strict';

const DEMO = [
  'What was the malaria mortality rate in Sub-Saharan Africa in 2025?',
  'How does that compare to 2015, and which countries drove the change?',
  'How has child vaccination coverage changed in India over the last decade?',
  'Compare health spending per capita across Southeast Asian countries.',
];
const HINT = '↵ send · ⇧↵ newline · / for commands';

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const turnsEl = $('#turns');
const input = $('#prompt');

let sid = null;
let busy = false;

// Replay mode (?replay=demo): plays recorded event streams from web/replays/ instead of calling the agent.
// &autoplay=1 plays every turn; otherwise each submitted question plays the next recorded turn.
// &speed=instant|fast. It's an offline fallback for the live demo, and it makes screenshots deterministic.
const params = new URLSearchParams(location.search);
const REPLAY = params.get('replay');
const SPEED = params.get('speed') === 'instant' ? 0 : params.get('speed') === 'fast' ? 0.25 : 1;
let replayData = null;
let replayIdx = 0;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let demoIdx = 0;
const history = [];
let histIdx = 0;

// ---------------------------------------------------------------------------------------------- formatting
function fmtNum(v) {
  if (v == null || v === '') return '';
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  const a = Math.abs(n);
  let s;
  if (a >= 1000) s = Math.round(n).toLocaleString('en-US');
  else if (Number.isInteger(n)) s = String(n);
  else if (a < 1) s = n.toFixed(2);
  else s = String(Math.round(n * 10) / 10);
  return s.replace(/^-/, '−');
}
const kfmt = (n) => (n == null ? '?' : n >= 10000 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// ---------------------------------------------------------------------------------------------- session
async function newSession() {
  if (REPLAY) return;
  if (sid) navigator.sendBeacon(`/api/session/${sid}/close`);
  const r = await fetch('/api/session', { method: 'POST' });
  sid = (await r.json()).session;
}
window.addEventListener('beforeunload', () => sid && navigator.sendBeacon(`/api/session/${sid}/close`));

// ---------------------------------------------------------------------------------------------- turn DOM
function createTurn(question) {
  const el = document.createElement('section');
  el.className = 'turn pending';
  el.setAttribute('aria-label', `Turn ${turnsEl.children.length + 1}`);
  el.innerHTML = `
    <div class="question"><span class="gt">&gt;</span><span>${esc(question)}</span></div>
    <div class="answer-row">
      <div class="headline-wrap"><span class="bullet">●</span><h2 class="headline">working…</h2></div>
      <span class="connector" aria-hidden="true"></span>
      <div class="steps-head"><span><span class="adot">●</span> <span class="n">0 steps</span></span><span class="secs">0s</span></div>
    </div>
    <div class="body">
      <div class="answer-col"></div>
      <div class="steps-col"><div class="steps-inner">
        <div class="steps-viewport">
          <div class="steps-scroll" tabindex="0" aria-label="Agent steps"></div>
          <div class="fade" aria-hidden="true" hidden></div>
          <button class="more-btn" hidden></button>
        </div>
        <div class="steps-foot"><span class="usage">…</span><a class="trace" target="_blank" rel="noopener" hidden>raw trace</a></div>
      </div></div>
    </div>`;
  const t = {
    el, steps: new Map(), count: 0, finished: false, follow: true,
    headline: $('.headline', el), n: $('.steps-head .n', el), secs: $('.steps-head .secs', el),
    answerCol: $('.answer-col', el), scroll: $('.steps-scroll', el), fade: $('.fade', el),
    more: $('.more-btn', el), usage: $('.usage', el), trace: $('.trace', el),
  };
  t.scroll.addEventListener('scroll', () => {
    t.follow = t.scroll.scrollTop + t.scroll.clientHeight >= t.scroll.scrollHeight - 30;
    measure(t);
  });
  t.more.addEventListener('click', () => t.scroll.scrollBy({ top: t.scroll.clientHeight * 0.8, behavior: 'smooth' }));
  return t;
}

// "+N more ↓": count steps whose midpoint is below the visible bottom of the list.
function measure(t) {
  const bottom = t.scroll.scrollTop + t.scroll.clientHeight;
  let hidden = 0;
  t.scroll.querySelectorAll('.step').forEach((s) => { if (s.offsetTop + s.offsetHeight / 2 > bottom) hidden++; });
  t.fade.hidden = t.more.hidden = hidden === 0;
  t.more.textContent = `+${hidden} more ↓`;
  t.more.setAttribute('aria-label', `Scroll to ${hidden} more steps`);
}
window.addEventListener('resize', () => document.querySelectorAll('.turn').forEach((el) => el._t && measure(el._t)));

function upsertStep(t, ev) {
  let s = t.steps.get(ev.id);
  if (!s) {
    const last = t.scroll.lastElementChild;
    if (last && !last.querySelector('.rail')) last.insertAdjacentHTML('afterbegin', '<span class="rail" aria-hidden="true"></span>');
    s = document.createElement('div');
    s.className = 'step';
    s.innerHTML = '<span class="sdot" aria-hidden="true"></span><div class="txt"><span class="call"><span class="tool"></span><span class="args"></span></span><span class="out"></span></div>';
    $('.tool', s).textContent = ev.tool;
    $('.args', s).textContent = ev.args || '';
    t.scroll.appendChild(s);
    t.steps.set(ev.id, s);
    t.count++;
    t.n.textContent = plural(t.count, 'step', 'steps');
  }
  s.className = `step ${ev.status}`;
  $('.tool', s).textContent = ev.tool;
  $('.args', s).textContent = ev.args || '';
  $('.out', s).textContent = `⎿ ${ev.status === 'running' ? ev.out || '…' : ev.out}`;
  if (t.el.classList.contains('pending')) {
    // Natural-height mode: keep the newest step in view if the reader is already near the bottom of the page.
    const nearBottom = window.innerHeight + window.scrollY >= document.body.scrollHeight - 200;
    if (nearBottom) s.scrollIntoView({ block: 'nearest', behavior: SPEED ? 'smooth' : 'auto' });
  } else {
    if (t.follow) t.scroll.scrollTop = t.scroll.scrollHeight;
    measure(t);
  }
}

// ---------------------------------------------------------------------------------------------- answer block
function details(label, count, inner) {
  return `<details><summary><span class="chev">▸</span><span class="sl">${label}</span><span class="count">${count}</span></summary>${inner}</details>`;
}
const list = (items, glyph, ordered = false) =>
  `<${ordered ? 'ol' : 'ul'} class="items">${items.map((x, i) =>
    `<li><span class="g">${typeof glyph === 'function' ? glyph(x, i) : glyph}</span><span>${esc(typeof x === 'string' ? x : x.text)}</span></li>`).join('')}</${ordered ? 'ol' : 'ul'}>`;

function renderAnswer(t, ev) {
  t.el.classList.remove('pending');
  t.headline.textContent = ev.headline;
  t.headline.title = ev.headline;
  const c = ev.confidence;
  const meter = [1, 2, 3, 4, 5].map((i) => `<span class="${i <= c.score ? 'on' : ''}"></span>`).join('');
  let html = `<div class="conf"><span class="lbl">Confidence</span><span class="meter" aria-hidden="true">${meter}</span>
    <span class="level">${esc(c.level)} · ${c.score}/5</span></div><div class="block">`;
  if (ev.chart) html += chartFigure(ev.chart);
  html += details('Confidence', plural(c.factors.length, 'factor', 'factors'), list(c.factors, (f) => (f.sign === '-' ? '−' : '+')));
  html += details('Caveats', ev.caveats.length, list(ev.caveats, '-'));
  html += details('Assumptions', ev.assumptions.length, list(ev.assumptions, '-'));
  html += details('Method', plural(ev.method.length, 'step', 'steps'), list(ev.method, (x, i) => `${i + 1}.`, true));
  if (ev.sql.length) html += details('SQL', plural(ev.sql.length, 'query', 'queries'), '<div class="sqlbox"></div>');
  if (ev.sources.length) {
    html += details('Source data', plural(ev.sources.length, 'table', 'tables'), `<div class="sources">${ev.sources.map((s) =>
      `<div class="src"><span><span class="t">${esc(s.table)}</span> <span class="m">${esc([s.label, ...s.filters].filter(Boolean).join(' · '))}</span></span><span class="m">${plural(s.rows, 'row', 'rows')}</span></div>`).join('')}</div>`);
  }
  t.answerCol.innerHTML = html + '</div>';
  const box = $('.sqlbox', t.answerCol);
  if (box) renderSql(box, ev.sql, 0);
  if (params.get('expand')) t.answerCol.querySelectorAll('details').forEach((d) => { d.open = true; });  // screenshots
}

// The SQL row shows one query in full (the headline's query first) and names the others; click a name to show it.
function renderSql(box, queries, shown) {
  const others = queries.map((q, i) => ({ q, i })).filter((o) => o.i !== shown);
  box.innerHTML = `<pre>${esc(queries[shown].sql)}</pre>` + (others.length
    ? `<span class="more">${shown === 0 ? `+${others.length} more: ` : 'other queries: '}${others.map((o) =>
      `<button data-i="${o.i}">${esc(o.q.purpose || o.q.id)}</button>`).join(', ')}</span>` : '');
  box.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => renderSql(box, queries, Number(b.dataset.i))));
}

function showError(t, message) {
  t.el.classList.remove('pending');
  t.el.classList.add('failed');
  t.headline.textContent = message;
  t.headline.title = message;
}

function finish(t, ev) {
  t.finished = true;
  const s = ev.stats || {};
  if (t.el.classList.contains('pending')) showError(t, 'The agent stopped without an answer.');
  t.secs.textContent = s.seconds != null ? `${s.seconds}s` : t.secs.textContent;
  const cost = s.cost_usd != null ? ` · $${s.cost_usd.toFixed(2)}` : '';
  t.usage.textContent = `${plural(s.tool_calls ?? 0, 'tool call', 'tool calls')} · ${kfmt(s.tokens_in)} in / ${kfmt(s.tokens_out)} out${cost}`;
  if (s.num_turns != null) t.usage.title = `${s.num_turns} model turns · session ${s.session_id}`;
  if (t.rawTrace) {
    t.trace.href = URL.createObjectURL(new Blob([JSON.stringify(t.rawTrace, null, 1)], { type: 'application/json' }));
    t.trace.hidden = false;
  } else if (ev.turn && sid) {
    t.trace.href = `/api/session/${sid}/trace/${ev.turn}`;
    t.trace.hidden = false;
  }
  if (s.ctx_tokens) $('#ctx').textContent = `ctx ${kfmt(s.ctx_tokens)} tokens`;
  t.scroll.scrollTo({ top: 0, behavior: SPEED ? 'smooth' : 'auto' });
  setTimeout(() => measure(t), 400);
}

// ---------------------------------------------------------------------------------------------- charts (SVG)
function niceStep(range, n) {
  if (!(range > 0)) return 1;
  const raw = range / n;
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}
const MONO = 'font-family="JetBrains Mono, monospace"';

function chartFigure(ch) {
  const many = ch.series.length > 1;
  const unit = ch.unit && !ch.title.toLowerCase().includes(ch.unit.toLowerCase()) ? ` · ${ch.unit}` : '';
  const legend = many && ch.type === 'line'
    ? '   ' + ch.series.slice(1).map((s) => `<span>- - ${esc(s.name)}</span>`).join('   ') + `   <span class="s1">— ${esc(ch.series[0].name)}</span>`
    : '';
  const svg = ch.type === 'bar' ? barChart(ch) : lineChart(ch);
  return `<figure><figcaption><span>${esc(ch.title + unit)}${legend}</span><span>[synthetic data]</span></figcaption>${svg}</figure>`;
}

function lineChart(ch) {
  const X0 = 40, X1 = 510, Y0 = 145, YT = 17.5;
  const series = ch.series.map((s) => ({ name: s.name, pts: s.points.map(([x, y]) => [x, Number(y)]) }));
  const all = series.flatMap((s) => s.pts);
  const numericX = all.every(([x]) => Number.isFinite(Number(x)));
  const cats = [...new Set(all.map(([x]) => String(x)))];
  let sx, xticks;
  if (numericX) {
    const xs = all.map(([x]) => Number(x));
    const xmin = Math.min(...xs), xmax = Math.max(...xs), span = xmax - xmin || 1;
    sx = (x) => X0 + ((Number(x) - xmin) / span) * (X1 - X0);
    const st = span >= 10 ? 5 : span >= 5 ? 2 : 1;
    xticks = [];
    for (let v = Math.ceil(xmin / st) * st; v <= xmax; v += st) xticks.push(v);
  } else {
    sx = (x) => X0 + (cats.indexOf(String(x)) / Math.max(1, cats.length - 1)) * (X1 - X0);
    const every = Math.ceil(cats.length / 8);
    xticks = cats.filter((_, i) => i % every === 0);
  }
  const ys = all.map(([, y]) => y);
  const ymin = Math.min(...ys), hi = Math.max(...ys);
  // Start at zero unless the values sit in a narrow band well above it (e.g. coverage 85-93%), where a zero
  // baseline would flatten the trend.
  const lo = ymin > 0 && hi - ymin < 0.35 * hi ? ymin : Math.min(0, ymin);
  const step = niceStep(hi - lo, 3);
  const top = Math.ceil(hi / step) * step || step;
  const bottom = lo !== 0 ? Math.floor(lo / step) * step : 0;
  const sy = (y) => Y0 - ((y - bottom) / (top - bottom)) * (Y0 - YT);

  let g = '<g stroke="#3a3936" stroke-width="1" stroke-dasharray="2 4">';
  for (let v = bottom + step; v <= top + 1e-9; v += step) if (Math.abs(v) > 1e-9) g += `<line x1="${X0}" y1="${sy(v)}" x2="${X1}" y2="${sy(v)}"></line>`;
  g += '</g>';
  g += `<line x1="${X0}" y1="${Y0}" x2="${X1}" y2="${Y0}" stroke="#5a5852" stroke-width="1"></line>`;
  if (bottom < 0 && top > 0) g += `<line x1="${X0}" y1="${sy(0)}" x2="${X1}" y2="${sy(0)}" stroke="#5a5852" stroke-width="1"></line>`;
  g += `<g fill="#9b998f" font-size="11" ${MONO}>`;
  for (let v = bottom; v <= top + 1e-9; v += step) g += `<text x="32" y="${sy(v) + 4}" text-anchor="end">${fmtNum(v)}</text>`;
  xticks.forEach((v) => {
    const x = sx(v);
    g += `<text x="${x}" y="163" text-anchor="${x > X1 - 14 ? 'end' : 'middle'}">${esc(v)}</text>`;
  });
  g += '</g>';

  const path = (s) => s.pts.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' ');
  series.slice(1).forEach((s) => { g += `<polyline points="${path(s)}" fill="none" stroke="#7a786f" stroke-width="1.5" stroke-dasharray="4 3" stroke-linejoin="round"></polyline>`; });
  const p = series[0];
  g += `<polyline points="${path(p)}" fill="none" stroke="#d97757" stroke-width="2" stroke-linejoin="round"></polyline>`;
  if (p.pts.length) {
    const [fx, fy] = p.pts[0], [lx, ly] = p.pts[p.pts.length - 1];
    g += `<g fill="#d97757"><circle cx="${sx(fx)}" cy="${sy(fy)}" r="3"></circle><circle cx="${sx(lx)}" cy="${sy(ly)}" r="3"></circle></g>`;
  }
  // End-of-line value labels: above the point, or below it if two labels would collide.
  const labels = series.filter((s) => s.pts.length).map((s, i) => {
    const [x, y] = s.pts[s.pts.length - 1];
    return { x: sx(x) - 6, py: sy(y), y: sy(y) - 9.4, text: fmtNum(y), fill: s === p ? '#e5e3da' : '#9b998f', v: y };
  }).sort((a, b) => a.py - b.py);
  for (let i = 1; i < labels.length; i++) if (labels[i].y - labels[i - 1].y < 12) labels[i].y = labels[i].py + 16.6;
  g += `<g font-size="11" text-anchor="end" ${MONO}>` + labels.map((l) =>
    `<text x="${l.x}" y="${Math.min(Y0 - 4, Math.max(11, l.y))}" fill="${l.fill}">${l.text}</text>`).join('') + '</g>';
  return `<svg viewBox="0 0 520 170" role="img" aria-label="${esc(ch.title)}">${g}</svg>`;
}

function barChart(ch) {
  const many = ch.series.length > 1;
  const clip = (l) => (l.length > 24 ? `${l.slice(0, 23)}…` : l);
  const rows = ch.series.flatMap((s) => s.points.map(([x, y]) => [clip(many ? `${x} · ${s.name}` : String(x)), Number(y)]));
  const W = 520, rowH = 20, padTop = 6, axisH = 20, H = padTop + rows.length * rowH + axisH;
  const labelW = Math.min(190, Math.max(60, Math.max(...rows.map(([l]) => l.length)) * 6.7 + 12));
  const vals = rows.map(([, v]) => v);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const step = niceStep(hi - lo, 4);
  const start = lo < 0 ? Math.floor(lo / step) * step : 0, end = hi > 0 ? Math.ceil(hi / step) * step : 0;
  const A = labelW + (lo < 0 ? 52 : 4), B = W - 10 - (hi > 0 ? 52 : 4);
  const sx = (v) => A + ((v - start) / (end - start)) * (B - A);
  const plotBottom = padTop + rows.length * rowH;

  let g = '<g stroke="#3a3936" stroke-width="1" stroke-dasharray="2 4">';
  for (let v = start; v <= end + 1e-9; v += step) if (Math.abs(v) > 1e-9) g += `<line x1="${sx(v)}" y1="${padTop}" x2="${sx(v)}" y2="${plotBottom}"></line>`;
  g += `</g><line x1="${sx(0)}" y1="${padTop}" x2="${sx(0)}" y2="${plotBottom}" stroke="#5a5852" stroke-width="1"></line>`;
  g += `<g fill="#9b998f" font-size="11" ${MONO} text-anchor="middle">`;
  for (let v = start; v <= end + 1e-9; v += step) g += `<text x="${sx(v)}" y="${H - 5}">${fmtNum(v)}</text>`;
  g += '</g>';
  rows.forEach(([label, v], i) => {
    const y = padTop + i * rowH + 3, cy = y + 7 + 4;
    const x0 = sx(Math.min(0, v)), w = Math.abs(sx(v) - sx(0));
    g += `<rect x="${x0}" y="${y}" width="${Math.max(1, w)}" height="14" fill="#d97757"></rect>`;
    g += `<text x="${labelW - 8}" y="${cy}" fill="#9b998f" font-size="11" text-anchor="end" ${MONO}>${esc(label)}</text>`;
    g += v >= 0
      ? `<text x="${sx(v) + 6}" y="${cy}" fill="#e5e3da" font-size="11" ${MONO}>${fmtNum(v)}</text>`
      : `<text x="${sx(v) - 6}" y="${cy}" fill="#e5e3da" font-size="11" text-anchor="end" ${MONO}>${fmtNum(v)}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(ch.title)}">${g}</svg>`;
}

// ---------------------------------------------------------------------------------------------- asking
function addTurn(question) {
  const t = createTurn(question);
  t.el._t = t;
  turnsEl.appendChild(t.el);
  if (SPEED) t.el.scrollIntoView({ block: 'start', behavior: 'smooth' });
  return t;
}

async function playReplayTurn() {
  const rec = replayData.turns[replayIdx++];
  if (!rec) return flashHint('replay finished');
  busy = true;
  const t = addTurn(rec.question);
  t.rawTrace = { replay: REPLAY, recorded: replayData.recorded, question: rec.question, messages: rec.raw_trace };
  let last = 0;
  for (const ev of rec.events) {
    if (SPEED) await sleep((ev.t - last) * 1000 * SPEED);
    last = ev.t;
    if (!t.finished) t.secs.textContent = `${Math.floor(ev.t)}s`;
    handle(t, ev);
  }
  busy = false;
}

async function ask(question) {
  if (busy) return;
  if (replayData) return playReplayTurn();
  busy = true;
  if (!sid) await newSession();
  const t = addTurn(question);
  const t0 = performance.now();
  const timer = setInterval(() => { if (!t.finished) t.secs.textContent = `${Math.floor((performance.now() - t0) / 1000)}s`; }, 250);
  try {
    const r = await fetch(`/api/session/${sid}/ask`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, i).split('\n').find((l) => l.startsWith('data: '));
        buf = buf.slice(i + 2);
        if (line) handle(t, JSON.parse(line.slice(6)));
      }
    }
  } catch (e) {
    showError(t, `Error: ${e.message}`);
  } finally {
    clearInterval(timer);
    if (!t.finished) finish(t, {});
    busy = false;
    input.focus();
  }
}

function handle(t, ev) {
  if (ev.type === 'step') upsertStep(t, ev);
  else if (ev.type === 'answer') renderAnswer(t, ev);
  else if (ev.type === 'error') showError(t, ev.message);
  else if (ev.type === 'done') finish(t, ev);
}

// ---------------------------------------------------------------------------------------------- input
function autosize() {
  input.style.height = 'auto';
  input.style.height = `${input.scrollHeight}px`;
}

function flashHint(text) {
  const el = $('#hint-left');
  el.textContent = text;
  clearTimeout(flashHint.t);
  flashHint.t = setTimeout(() => { el.textContent = HINT; }, 6000);
}

async function submit() {
  const q = input.value.trim();
  if (!q || busy) return;
  input.value = '';
  autosize();
  history.push(q);
  histIdx = history.length;
  if (q === '/new') {
    turnsEl.innerHTML = '';
    $('#ctx').textContent = '';
    await newSession();
    flashHint('new session');
    return;
  }
  if (q === '/help' || q.startsWith('/')) {
    flashHint('/new  start a new session · /help  this help · Tab  fill a demo question');
    return;
  }
  ask(q);
}

input.addEventListener('input', autosize);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submit();
  } else if (e.key === 'Tab' && !input.value) {
    // Demo helper: Tab on an empty prompt fills the next demo question (no typing on stage).
    e.preventDefault();
    input.value = DEMO[demoIdx++ % DEMO.length];
    autosize();
  } else if (e.key === 'ArrowUp' && !input.value.includes('\n') && history.length && input.selectionStart === 0) {
    e.preventDefault();
    histIdx = Math.max(0, histIdx - 1);
    input.value = history[histIdx];
    autosize();
  }
});

async function init() {
  if (REPLAY) {
    replayData = await (await fetch(`/static/replays/${encodeURIComponent(REPLAY)}.json`)).json();
    DEMO.splice(0, DEMO.length, ...replayData.turns.map((x) => x.question));
    if (params.get('autoplay')) {
      while (replayIdx < replayData.turns.length) {
        await playReplayTurn();
        if (SPEED) await sleep(1500 * SPEED);
      }
    }
  } else {
    await newSession();
  }
  if (params.get('q')) {  // ?q=... pre-fills the prompt; &go=1 also submits it (testing)
    input.value = params.get('q');
    autosize();
    if (params.get('go')) submit();
  }
  input.focus();
}
init();
