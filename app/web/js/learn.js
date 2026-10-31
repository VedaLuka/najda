// Screen 2: the same fault twice. Run 1 investigates and learns; run 2 matches the playbook with zero AI calls.
import { repeat, csv, incident } from './data.js';
import { narrate, patchText } from './timeline.js';
import { h, ICON, countUp } from './ui.js';
import { lines, legend } from './charts.js';

const TEAL = '#19C2A0', SLATE = '#8DA2B5';

function runCard(run, inc, i) {
  const ev = narrate(run.steps, inc);
  const verify = ev.find(e => e.kind === 'verify'), hyp = ev.find(e => e.kind === 'hypotheses'), hit = ev.find(e => e.kind === 'playbook_hit'), learned = ev.find(e => e.kind === 'learned');
  const row = (ok, text) => h('div', { class: 'row' }, h('span', { class: `ic${ok ? ' good' : ''}`, html: ok ? ICON.check : ICON.brain }), text);
  const calls = h('div', { class: `big ${i ? 'teal' : 'amber'}` }, '0'), cost = h('div', { class: `big ${i ? 'teal' : 'amber'}` }, '$0.000');
  setTimeout(() => { countUp(calls, run.llm_calls, v => String(Math.round(v)), 900); countUp(cost, run.cost_usd, v => `$${v.toFixed(3)}`, 900); }, 200 + i * 300);
  return h('div', { class: 'run-card', style: `animation-delay:${i * 150}ms` },
    h('div', { class: 'head' }, h('div', { class: 't' }, i ? 'Run 2: the same fault, a new incident' : 'Run 1: a fault Najda has never seen'), h('div', { class: 'id' }, `${run.incident_id} · ${run.family}`)),
    h('div', {}, calls, h('div', { class: 'l' }, 'AI calls')),
    h('div', {}, cost, h('div', { class: 'l' }, 'spent')),
    h('div', { class: 'foot' },
      hit ? row(true, `Matched playbook ${run.playbook_events.find(e => e.event === 'match').id} from ${run.playbook_events.find(e => e.event === 'match').source_incident} (similarity ${run.playbook_events.find(e => e.event === 'match').score.toFixed(2)})`)
          : row(false, `Investigated by ${ev.filter(e => e.kind === 'llm').length} model calls: ${hyp ? hyp.title.replace('Hypothesis: ', '') : ''}`),
      row(true, `Patch ${patchText(run.actions[0].patch)} passed the same guardrails and canary`),
      row(true, verify ? verify.title : 'verified'),
      learned ? row(true, 'Playbook learned: signature plus patch template, no free text') : row(true, 'Nothing new to learn; the playbook keeps its record')));
}

export async function render(main, topright) {
  topright.replaceChildren(h('span', { class: 'pill teal' }, 'memory on'), h('span', { class: 'pill grey' }, 'replayed from the recorded run'));
  const rep = await repeat();
  const [r1, r2] = rep.runs;
  const inc = await incident(r1.incident_id);
  const rows = (await csv('learning_curve_streams.csv')).filter(r => r.doctor === 'najda_v4');
  const curve = (await csv('learning_curve.csv')).filter(r => r.doctor === 'najda_v4');
  // 5-incident moving average with an expanding window at the start (the pack's ma5 column pads with zeros).
  const MIN = 3;  // the mean starts once three incidents are in the window; a single $0 healthy incident is not a trend
  const ma = costs => costs.map((_, i) => { const w = costs.slice(Math.max(0, i - 4), i + 1); return w.reduce((a, b) => a + b, 0) / w.length; }).slice(MIN - 1);
  const stream = (arm, seed) => rows.filter(r => r.arm === arm && r.seed === seed).sort((a, b) => +a.position - +b.position).map(r => +r.cost_usd);
  const off = ma(stream('off', '1')).map((y, i) => ({ x: i + MIN, y }));
  const onSeeds = [...new Set(rows.filter(r => r.arm === 'on').map(r => r.seed))].map(seed => ma(stream('on', seed)));
  const on = onSeeds[0].map((_, i) => ({ x: i + MIN, y: onSeeds.reduce((a, s) => a + s[i], 0) / onSeeds.length }));
  const cOff = curve.find(r => r.memory === 'off'), cOn = curve.find(r => r.memory === 'on');

  const screen = h('section', { class: 'screen learn' });
  screen.append(h('div', { class: 'intro' }, h('div', { class: 'big-caption' }, 'After a fix is ', h('b', {}, 'verified by replay'), ', Najda stores a playbook: the failing-only span signature and a patch template. The next incident with the same signature skips the investigator and goes straight to guardrails, canary and replay.')));
  screen.append(h('div', { class: 'twin' }, runCard(r1, inc, 0), h('div', { class: 'arrow', html: ICON.arrow }), runCard(r2, inc, 1)));
  const chart = h('div', { class: 'chart' });
  screen.append(h('div', { class: 'panel', style: 'grid-column: 1 / -1; min-height: 0' },
    h('div', { class: 'ph' }, h('h2', {}, 'Cost per incident along a stream of 42 dev incidents', h('span', { class: 'n' }, '5-incident moving average from incident 3 · najda_v4 · memory ON is the mean of 3 stream orders')),
      legend([{ name: 'memory OFF', color: SLATE }, { name: 'memory ON', color: TEAL }])),
    h('div', { class: 'stat-row', style: 'margin-bottom:14px' },
      h('div', { class: 'stat' }, h('div', { class: 'v' }, `$${(+cOff.cost_per_incident).toFixed(4)}`), h('div', { class: 'l' }, 'per incident, memory OFF')),
      h('div', { class: 'stat' }, h('div', { class: 'v teal' }, `$${(+cOn.cost_per_incident).toFixed(4)}`), h('div', { class: 'l' }, `per incident, memory ON (${Math.round((1 - cOn.cost_per_incident / cOff.cost_per_incident) * 100)}% cheaper)`)),
      h('div', { class: 'stat' }, h('div', { class: 'v teal' }, `${Math.round(cOn.hit_rate * 100)}%`), h('div', { class: 'l' }, `playbook hits · ${cOn.zero_llm_incidents} of ${3 * 42} incidents (3 streams) fixed with zero AI calls`)),
      h('div', { class: 'stat' }, h('div', { class: 'v' }, `${(+cOn.accuracy).toFixed(3)} vs ${(+cOff.accuracy).toFixed(3)}`), h('div', { class: 'l' }, `accuracy ON vs OFF · false matches ${cOn.false_match_rate}`))),
    chart));
  main.replaceChildren(screen);
  requestAnimationFrame(() => lines(chart, [{ name: 'memory OFF', color: SLATE, points: off }, { name: 'memory ON', color: TEAL, points: on }], { xLabel: 'incident number in the stream', yFmt: v => `$${v.toFixed(3)}` }));
  screen.dataset.ready = '1';
  return screen;
}
