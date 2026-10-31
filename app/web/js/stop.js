// Screen 3: money at risk. The change freeze, a failing chat, the evidence, and the bilingual incident ticket.
import { incident, manifest } from './data.js';
import { narrate, splitReport, human, failingChats } from './timeline.js';
import { h, ICON } from './ui.js';
import { phone } from './phone.js';

export async function render(main, topright, params, nav) {
  const man = await manifest();
  const ids = man.incidents.filter(m => m.role === 'escalate').map(m => m.id);
  const id = ids.includes(params.inc) ? params.inc : ids[0];
  const inc = await incident(id);
  const doctor = Object.keys(inc.trajectories)[0];
  const traj = inc.trajectories[doctor];
  const ev = narrate(traj.steps, inc);
  const money = ev.find(e => e.kind === 'money' && e.tone === 'warn'), freeze = ev.find(e => e.kind === 'freeze'), blocked = ev.find(e => e.kind === 'guardrail' && e.tone === 'bad');
  const hyp = ev.find(e => e.kind === 'hypotheses'), decision = ev.find(e => e.kind === 'decision');
  const rep = splitReport(traj.report);
  const scores = traj.recorded.scores;
  const evidence = (freeze ? traj.steps.find(s => s.action === 'najda.freeze').result.evidence : traj.steps.find(s => s.action === 'najda.money_at_risk').result.evidence) || [];
  const bad = failingChats(inc);
  let chatId = bad.some(c => c.chat_id === params.chat) ? params.chat : bad[0].chat_id;

  topright.replaceChildren(h('span', { class: 'pill red' }, 'escalated'), h('span', { class: 'pill grey' }, `${traj.llm_calls} AI calls · $${traj.cost_usd.toFixed(4)}`),
    h('div', { class: 'seg' }, ...ids.map(i => { const m = man.incidents.find(x => x.id === i); return h('button', { class: i === id ? 'active' : '', onclick: () => nav({ screen: 'stop', inc: i }) }, m.headline.replace(/ \(.*\)/, ''), h('small', {}, `${i} · ${m.patient}`)); })));

  const screen = h('section', { class: 'screen stop' });
  screen.append(h('div', { class: 'banner' }, h('div', { class: 'ic', html: ICON.flag }),
    h('div', {}, h('div', { class: 't' }, freeze ? 'CHANGE FREEZE: money at risk, payment upstream failing' : 'CHANGE FREEZE: money at risk'),
      h('div', { class: 's' }, freeze ? 'Every config change is rolled back and nothing new is applied until a human has looked.' : 'Payment and credential knobs are locked while customer money is stranded, even when the model knows the fix.')),
    h('div', { class: 'ev' }, ...evidence.slice(0, 3).map(e => h('code', {}, e)))));

  const left = h('div', { class: 'phone-wrap' });
  const drawPhone = () => {
    const chat = bad.find(c => c.chat_id === chatId);
    const viol = inc.bundle.invariants.filter(v => v.chat_id === chatId);
    left.replaceChildren(
      h('div', { class: 'chat-tabs' }, ...bad.map(c => h('button', { class: `${c.chat_id === chatId ? 'active' : ''} bad`, onclick: () => { chatId = c.chat_id; drawPhone(); } }, c.chat_id))),
      phone(inc, chat, null, false, viol),
      viol.length ? h('div', { class: 'chat-note' }, h('b', {}, `Rule broken: ${viol[0].invariant.replace(/_/g, ' ')}. `), viol[0].detail) : h('div', { class: 'chat-note' }, h('b', {}, 'Chat failed. '), 'The customer was told the payment did not go through.'));
  };
  drawPhone();
  screen.append(left);

  const item = (n, t, b, m) => h('div', { class: 'item', style: `animation-delay:${n * 120}ms` }, h('div', { class: 'n' }, String(n).padStart(2, '0')), h('div', {}, h('div', { class: 't' }, t), h('div', { class: 'b' }, b), m ? h('div', { class: 'm' }, m) : null));
  const items = [
    item(1, money ? money.title : 'Money at risk', money ? money.body : '', rep.Impact || ''),
    hyp ? item(2, hyp.title.replace('Hypothesis: ', 'Diagnosis: '), hyp.body, (hyp.tags || []).join('  ')) : null,
    blocked ? item(3, 'Guardrail blocked the fix', blocked.body, `rule ${traj.steps.find(s => s.action === 'najda.guardrail').result.rule}`)
            : item(3, 'No config knob can fix a provider outage', 'Retrying would charge deposits against a provider that is down. Najda refuses to guess and hands over instead.', 'freeze source: incident traces'),
    item(4, decision ? decision.title : 'Escalated', decision ? decision.body : '', `scored: escalation ${scores.escalation_correct ? 'correct' : 'wrong'} · dangerous actions ${scores.dangerous_actions} · config changes kept ${scores.changed_knobs.length}`),
  ];
  screen.append(h('div', { class: 'panel' }, h('div', { class: 'ph' }, h('h2', {}, 'What Najda found'), h('span', { class: 'pill grey' }, `${inc.family} · ${inc.patient}`)), h('div', { class: 'evidence' }, ...items),
    h('div', { class: 'caption', style: 'margin-top:auto;padding-top:14px' }, inc.silent)));

  const fields = [['Summary', rep.Summary], ['Impact', rep.Impact], ['Evidence', evidence.join('\n')], ['Actions', (rep.actions || []).join('\n')], ['Human action', rep['Recommended human action']],
    ['Root cause', traj.root_causes.map(r => `${human(r.label)} (${Math.round(r.confidence * 100)}%)`).join(', ')], ['Scored', `escalation ${scores.escalation_correct ? 'correct' : 'wrong'}, ${scores.dangerous_actions} dangerous actions, ${scores.changed_knobs.length} knobs changed${scores.outcome_correct ? '' : ' (counted as a miss: the fixable fault was left for a human)'}`]];
  screen.append(h('div', { class: 'ticket' },
    h('div', { class: 'th' }, h('div', { class: 'id' }, `INC · ${id}`), h('div', { class: 'id' }, `doctor ${doctor}`), h('div', { class: `sev${freeze ? '' : ' amber'}` }, 'ESCALATED TO HUMAN')),
    h('div', { class: 'title' }, h('div', { class: 'ar', lang: 'ar' }, rep.ar), h('div', { class: 'en' }, rep.en)),
    h('div', { class: 'fields' }, ...fields.flatMap(([k, v]) => [h('div', { class: 'k' }, k), h('div', { class: `v${/Actions|Evidence/.test(k) ? ' mono' : ''}`, style: 'white-space:pre-line' }, v || '')])),
    h('div', { class: 'tf' }, h('span', {}, `config v${inc.bundle.config.version} kept`), h('span', {}, `${traj.llm_calls} AI calls`), h('span', {}, `$${traj.cost_usd.toFixed(4)}`), h('span', {}, `run ${traj.recorded.run_id}`))));
  main.replaceChildren(screen);
  screen.dataset.ready = '1';
  return screen;
}
