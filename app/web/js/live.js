// Screen 1: live incident. Phone chat, plain-word timeline, business rules, config diff, cost, playback.
import { incident, manifest } from './data.js';
import { narrate, state, failingChats, splitReport, knob, patchText } from './timeline.js';
import { h, ICON, KIND_ICON, countUp, reduceMotion } from './ui.js';
import { phone } from './phone.js';

const STATUSES = ['DETECTED', 'INVESTIGATING', 'FIXING', 'VERIFYING', 'RECOVERED'];
const DOCTOR_NAMES = { najda_v6: 'v6 (final)', najda_v5: 'v5' };
const fmtMoney = v => `$${v.toFixed(4)}`;
const fmtSec = v => `${v.toFixed(1)}s`;
const STEP_MS = 1500;
let player = null;

function timelineEvents(events, k) {
  const wrap = h('div', { class: 'tl-scroll' });
  if (k === 0) wrap.append(h('div', { class: 'tl-empty' }, 'Press play, or step with the arrow keys.'));
  events.slice(0, k).forEach((e, i) => {
    const node = h('div', { class: `ev ${e.tone || ''} ${e.kind}${i === k - 1 ? ' now' : ''}` });
    node.append(h('div', { class: 'dot', html: ICON[KIND_ICON[e.kind] || 'read'] }));
    const col = h('div', {});
    col.append(h('div', { class: 'ttl' }, e.title));
    if (e.body) col.append(h('div', { class: 'body' }, e.body));
    if (e.conf != null) col.append(h('div', { class: 'conf' }, h('div', { class: 'bar' }, h('i', { style: `width:${Math.round(e.conf * 100)}%` })), h('span', { class: 'v' }, `${Math.round(e.conf * 100)}%`)));
    if (e.tags && e.tags.length) col.append(h('div', { class: 'tags' }, ...e.tags.map(t => h('span', { class: 'tag' }, t))));
    if (e.detail) col.append(h('details', {}, h('summary', {}, 'technical detail'), h('pre', {}, e.detail)));
    node.append(col);
    wrap.append(node);
  });
  return wrap;
}

function checklist(st) {
  return h('ul', { class: 'check' }, ...st.checklist.map(c => h('li', { class: c.cls }, h('span', { class: 'ic', html: c.cls === 'bad' ? ICON.cross : c.cls === 'frozen' ? ICON.flag : ICON.check }), c.label)));
}

function diffCard(st, inc) {
  const d = h('div', { class: 'diff' });
  if (!st.diff.length) { d.append(h('div', { class: 'none' }, st.frozen ? '# frozen: no change allowed' : '# no change yet'), h('div', { class: 'h' }, `config v${inc.bundle.config.version}, ${Object.keys(inc.bundle.config.current).length} knobs`)); return d; }
  d.append(h('div', { class: 'h' }, `config v${inc.bundle.config.version} -> v${inc.bundle.config.version + st.diff.length}`));
  for (const x of st.diff) { d.append(h('span', { class: 'del' }, `- ${x.knob}: ${JSON.stringify(x.before)}`)); d.append(h('span', { class: 'add' }, `+ ${x.knob}: ${JSON.stringify(x.after)}`)); }
  if (st.rolledBack) d.append(h('div', { class: 'rb' }, 'rolled back'));
  return d;
}

function statusTrack(status) {
  const track = h('div', { class: 'status-track' });
  const list = status === 'ESCALATED' ? [...STATUSES.slice(0, 4), 'ESCALATED'] : STATUSES;
  const idx = list.indexOf(status);
  list.forEach((s, i) => {
    if (i) track.append(h('span', { class: 'sep' }));
    track.append(h('span', { class: `st${i < idx ? ' done' : ''}${i === idx ? ' now' : ''}${s === 'RECOVERED' && i === idx ? ' good' : ''}${s === 'ESCALATED' && i === idx ? ' bad' : ''}` }, s));
  });
  return track;
}

export async function render(main, topright, params, nav) {
  const man = await manifest();
  const liveIds = man.incidents.filter(m => m.role === 'live').map(m => m.id);
  const id = liveIds.includes(params.inc) ? params.inc : liveIds[0];
  const inc = await incident(id);
  const doctors = Object.keys(inc.trajectories).sort().reverse();
  const doctor = doctors.includes(params.doctor) ? params.doctor : doctors[0];
  const traj = inc.trajectories[doctor];
  const events = narrate(traj.steps, inc);
  const bad = failingChats(inc);
  const afterById = Object.fromEntries((inc.after_fix[doctor] || []).map(c => [c.chat_id, c]));
  let k = Math.min(events.length, Math.max(0, +params.k || 0));
  let chatId = bad.some(c => c.chat_id === params.chat) ? params.chat : bad[0].chat_id;
  let speed = +params.speed || 1, playing = params.play === '1';
  if (player) clearInterval(player); player = null;

  const screen = h('section', { class: 'screen live' });
  const left = h('div', { class: 'phone-wrap' });
  const mid = h('div', { class: 'panel timeline' });
  const right = h('div', { class: 'rail' });
  const bar = h('div', { class: 'panel playback' });
  screen.append(left, mid, right, bar);
  main.replaceChildren(screen);

  const counters = { calls: h('div', { class: 'v' }, '0'), cost: h('div', { class: 'v' }, '$0.0000'), elapsed: h('div', { class: 'v' }, '0.0s') };
  const statusHost = h('div', {});
  topright.replaceChildren(statusHost, h('div', { class: 'counters' },
    h('div', { class: 'counter' }, counters.calls, h('div', { class: 'l' }, 'AI calls')),
    h('div', { class: 'counter' }, counters.cost, h('div', { class: 'l' }, 'cost')),
    h('div', { class: 'counter' }, counters.elapsed, h('div', { class: 'l' }, 'elapsed'))));

  const costCells = { cost: h('div', { class: 'v teal' }, '$0.0000'), calls: h('div', { class: 'v' }, '0'), steps: h('div', { class: 'v' }, '0') };
  let lastK = -1, lastChat = null, lastVerified = null;

  function draw() {
    const st = state(inc, events, k, traj);
    statusHost.replaceChildren(statusTrack(st.status));
    countUp(counters.calls, st.llmCalls, v => String(Math.round(v)));
    countUp(counters.cost, st.cost, fmtMoney);
    countUp(counters.elapsed, st.elapsed, fmtSec);
    countUp(costCells.cost, st.cost, fmtMoney);
    countUp(costCells.calls, st.llmCalls, v => String(Math.round(v)));
    countUp(costCells.steps, k, v => String(Math.round(v)));
    // phone
    const chat = bad.find(c => c.chat_id === chatId);
    const viol = inc.bundle.invariants.filter(v => v.chat_id === chatId);
    if (chatId !== lastChat || st.verified !== lastVerified) {
      const tabs = h('div', { class: 'chat-tabs' }, ...bad.map(c => h('button', { class: `${c.chat_id === chatId ? 'active' : ''} bad`, onclick: () => { chatId = c.chat_id; draw(); } }, c.chat_id)));
      const note = st.verified && afterById[chatId]
        ? h('div', { class: 'chat-note teal' }, h('b', {}, 'Verified by replay. '), `The same customer messages, replayed on config v${inc.bundle.config.version + st.diff.length}: every business rule holds.`)
        : viol.length ? h('div', { class: 'chat-note' }, h('b', {}, `Rule broken: ${viol[0].invariant.replace(/_/g, ' ')}. `), viol[0].detail)
        : h('div', { class: 'chat-note' }, h('b', {}, 'Chat failed. '), inc.silent);
      left.replaceChildren(tabs, phone(inc, chat, afterById[chatId], st.verified, viol), note);
      lastChat = chatId; lastVerified = st.verified;
    }
    // timeline
    if (k !== lastK) {
      const docSeg = doctors.length > 1 ? h('div', { class: 'seg' }, ...doctors.map(d => {
        const ok = !inc.trajectories[d].escalated;
        return h('button', { class: `${d === doctor ? 'active' : ''} ${ok ? 'good' : 'bad'}`, onclick: () => nav({ screen: 'live', inc: id, doctor: d, k: 99 }) }, `najda ${DOCTOR_NAMES[d] || d}`, h('small', {}, ok ? 'verified by replay' : 'rejected as ungrounded'));
      })) : h('span', { class: `pill ${st.status === 'RECOVERED' ? 'teal' : st.status === 'ESCALATED' ? 'red' : 'amber'}` }, `najda ${DOCTOR_NAMES[doctor] || doctor}`);
      mid.replaceChildren(h('div', { class: 'ph' }, h('h2', {}, "Najda's steps", h('span', { class: 'n' }, `${k} / ${events.length}`)), docSeg), timelineEvents(events, k));
      const sc = mid.querySelector('.tl-scroll'); sc.scrollTop = sc.scrollHeight;
      lastK = k;
    }
    // right rail
    const report = splitReport(traj.report);
    const outcome = st.done ? h('div', { class: `outcome ${st.escalated ? 'red' : 'teal'}` }, h('b', {}, st.escalated ? 'Escalated. ' : 'Recovered. '), report.en.replace(/^Najda: /, ''),
      h('div', { class: 'ar', dir: 'rtl', style: 'margin-top:6px;font-size:16px' }, report.ar.replace(/^نجدة: /, ''))) : null;
    right.replaceChildren(
      h('div', { class: 'panel' }, h('div', { class: 'ph' }, h('h2', {}, 'Business rules'), h('span', { class: `pill ${st.verified ? 'teal' : st.frozen ? 'amber' : 'red'}` }, st.verified ? 'all hold' : st.frozen ? 'frozen' : `${inc.bundle.invariants.length} violations`)), checklist(st)),
      h('div', { class: 'panel' }, h('div', { class: 'ph' }, h('h2', {}, 'Config change'), h('span', { class: 'pill grey' }, st.diff.length ? `${st.diff.map(d => knob(d.knob)).join(', ')}` : 'none')), diffCard(st, inc)),
      h('div', { class: 'panel', style: 'flex:1' }, h('div', { class: 'ph' }, h('h2', {}, 'Cost of this recovery')),
        h('div', { class: 'cost-grid' }, h('div', { class: 'cell' }, costCells.cost, h('div', { class: 'l' }, 'spent')), h('div', { class: 'cell' }, costCells.calls, h('div', { class: 'l' }, 'AI calls')), h('div', { class: 'cell' }, costCells.steps, h('div', { class: 'l' }, 'steps')))
        , outcome));
    // playback bar
    const btn = (icon, title, fn, cls = '') => h('button', { class: cls, title, html: ICON[icon], onclick: fn });
    const seg = h('div', { class: 'seg' }, ...liveIds.map(i => { const m = man.incidents.find(x => x.id === i); return h('button', { class: i === id ? 'active' : '', onclick: () => nav({ screen: 'live', inc: i }) }, m.headline, h('small', {}, `${i} · ${m.family}`)); }));
    const range = h('input', { type: 'range', min: 0, max: events.length, value: k, style: `--p:${k / events.length * 100}%`, oninput: e => { k = +e.target.value; stop(); draw(); } });
    bar.replaceChildren(
      h('div', { class: 'switcher' }, h('span', { class: 'lbl' }, 'incident'), seg),
      h('div', { class: 'pb-btns' }, btn('first', 'Restart', () => { k = 0; stop(); draw(); }), btn('back', 'Step back', () => { k = Math.max(0, k - 1); stop(); draw(); }),
        btn(playing ? 'pause' : 'play', playing ? 'Pause' : 'Play', toggle, 'play'), btn('fwd', 'Step forward', () => { k = Math.min(events.length, k + 1); stop(); draw(); }), btn('last', 'Jump to end', () => { k = events.length; stop(); draw(); })),
      h('div', { class: 'scrub' }, range, h('span', { class: 'pos' }, `step ${k} / ${events.length}`)),
      h('div', { style: 'display:flex;gap:16px;align-items:center' },
        h('div', { class: 'speed' }, ...[1, 2].map(s => h('button', { class: s === speed ? 'active' : '', onclick: () => { speed = s; if (playing) { stop(); start(); } draw(); } }, `${s}x`))),
        h('div', { class: 'keys' }, h('span', {}, h('kbd', {}, 'space'), 'play'), h('span', {}, h('kbd', {}, '←'), h('kbd', {}, '→'), 'step'), h('span', {}, h('kbd', {}, '1-4'), 'screen'))));
  }
  function start() { if (k >= events.length) k = 0; playing = true; player = setInterval(() => { k++; if (k >= events.length) { k = events.length; stop(); } draw(); }, (reduceMotion() ? 2500 : STEP_MS) / speed); }
  function stop() { playing = false; if (player) clearInterval(player); player = null; }
  function toggle() { if (playing) stop(); else start(); draw(); }
  screen.keys = e => {
    if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowRight') { k = Math.min(events.length, k + 1); stop(); draw(); }
    else if (e.key === 'ArrowLeft') { k = Math.max(0, k - 1); stop(); draw(); }
    else if (e.key === 'Home') { k = 0; stop(); draw(); }
    else if (e.key === 'End') { k = events.length; stop(); draw(); }
    else if (e.key === 's') { speed = speed === 1 ? 2 : 1; if (playing) { stop(); start(); } draw(); }
  };
  draw();
  if (playing) { playing = false; start(); draw(); }
  screen.dataset.ready = '1';
  return screen;
}
