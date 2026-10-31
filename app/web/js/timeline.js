// Turns a doctor trajectory (raw steps from the pack) into plain-word events for the console.
// Every number shown comes from the step results; nothing is typed by hand.
const READS = new Set(['read_traces', 'read_metrics', 'read_invariants', 'read_chats', 'read_config', 'config_history_diff']);

export const INVARIANT_LABELS = {
  order: {
    total_matches_menu: 'Totals match the menu (SAR)', qty_matches_request: 'Quantities match the customer',
    confirmed_has_payment: 'Confirmed means paid', payment_has_confirmed_order: 'Paid means confirmed',
    reply_matches_ledger: "Bot's reply matches the ledger", turns_under_cap: 'Turns under the hard cap', no_unhandled_error: 'No unhandled errors',
  },
  hajz: {
    confirmed_has_deposit: 'Confirmed means deposit paid', deposit_has_confirmed_booking: 'Deposit means confirmed booking',
    deposit_charged_once: 'Deposit charged once', deposit_matches_party: 'Deposit matches party size',
    booking_time_matches_request: 'Booking time matches the customer', no_double_booking: 'No double booking',
    reply_matches_ledger: "Bot's reply matches the ledger", turns_under_cap: 'Turns under the hard cap', no_unhandled_error: 'No unhandled errors',
  },
};
const LABELS = {
  unit_mismatch: 'price unit mismatch', input_format: 'input format', missing_event: 'missing payment event',
  upstream_outage: 'upstream outage', schema_drift: 'schema drift', prompt_regression: 'prompt regression',
  rate_limit: 'rate limiting', auth_expired: 'expired credentials', infinite_loop: 'runaway loop', stale_data: 'stale data',
};
const MODELS = { 'claude-haiku-5-5': 'Haiku 5.5', 'claude-sonnet-5-5': 'Sonnet 5.5', 'claude-opus-5-5': 'Opus 5.5' };
const KNOBS = { price_unit: 'price unit', normalize_numerals: 'numeral normalisation', payment_verify: 'payment verification', timeout_s: 'timeout', max_turns: 'turn cap' };

export const human = label => LABELS[label] || (label || '').replace(/_/g, ' ');
export const knob = k => KNOBS[k] || k;
const fmtVal = v => typeof v === 'string' ? v : JSON.stringify(v);
export const patchText = p => Object.entries(p || {}).map(([k, v]) => `${k}: ${fmtVal(v)}`).join(', ') || '(no change)';
const pct = c => `${Math.round(c * 100)}%`;
const list = (xs, n = 3) => xs.slice(0, n).join(', ') + (xs.length > n ? ` +${xs.length - n}` : '');
const json = o => JSON.stringify(o, null, 1).replace(/\n\s*/g, ' ');

/** @returns {Array<{kind, title, body?, detail?, tone?, conf?, t, cost?, patch?}>} */
export function narrate(steps, inc) {
  const labels = INVARIANT_LABELS[inc.patient] || INVARIANT_LABELS.order;
  const events = [];
  let reads = null;   // the read event of the current phase; later reads in the same phase merge into it
  let verified = false;
  const describe = r => {
    const parts = [];
    if (r.chats) parts.push(`${r.chats} chats`);
    if (r.spans) parts.push(`${r.spans} trace spans`);
    if (r.metrics) parts.push('the metrics');
    if (r.invariants) parts.push(`${r.invariants} rule violations`);
    if (r.config) parts.push('the config');
    if (r.history) parts.push('the change history');
    const body = [];
    if (r.errorsOnly !== null) body.push(r.errorsOnly ? `${r.errorsOnly} spans carry an error` : 'no span carries an error');
    if (r.history) body.push(r.historyVersions ? `${r.historyVersions} earlier config versions` : 'config change history: none');
    const what = parts.length ? parts.join(', ') : 'the incident bundle';
    r.title = verified ? `Checked ${what} after the fix` : r.again ? `Investigator re-read ${what}` : `Read ${what}`;
    r.body = body.join(' · ');
    r.detail = r.raw.join('\n');
  };
  for (const s of steps) {
    const a = s.action, r = s.result || {}, args = s.args || {};
    if (READS.has(a)) {
      if (!reads) {
        reads = { kind: 'read', tone: 'plain', t: s.t, chats: 0, spans: 0, metrics: false, invariants: 0, config: false, history: false, historyVersions: 0, errorsOnly: null, raw: [], again: events.some(e => e.kind === 'llm') };
        events.push(reads);
      }
      reads.raw.push(`${a} ${json(args)} -> ${json(r)}`);
      if (a === 'read_chats') reads.chats = Math.max(reads.chats, r.chats || 0);
      if (a === 'read_traces') { if (args.errors_only) reads.errorsOnly = r.returned || 0; else reads.spans = Math.max(reads.spans, r.returned || 0); }
      if (a === 'read_metrics') reads.metrics = true;
      if (a === 'read_invariants') reads.invariants = Math.max(reads.invariants, r.violations || 0);
      if (a === 'read_config') reads.config = true;
      if (a === 'config_history_diff') { reads.history = true; reads.historyVersions = r.versions || 0; }
      describe(reads);
      continue;
    }
    if (a === 'llm' || a === 'najda.verify' || a === 'najda.decision') reads = null;
    const ev = { kind: a, t: s.t, tone: 'plain', detail: `${a} ${json(args)}\n-> ${json(r)}` };
    if (a === 'replay' && args.config_version === 1 && args.chats === 'failed') {
      const broken = (r.violations || []).map(v => labels[v] || v);
      Object.assign(ev, { kind: 'baseline', title: `Replayed the ${r.n_total} failed chats on the current config: ${r.n_pass}/${r.n_total} pass`,
        body: broken.length ? `Business rule broken: ${broken.join(', ')}` : 'No invariant violated', tone: 'bad' });
    } else if (a === 'replay' || a === 'najda.baseline_replay') { continue;
    } else if (a === 'najda.money_at_risk') {
      const e = r.evidence || [];
      Object.assign(ev, e.length
        ? { kind: 'money', title: e.some(x => /invariant/.test(x)) ? `Money at risk: ${e.length} payments taken without a confirmed order` : `Money at risk: ${e.length} payment calls failing upstream`, body: list(e), tone: 'warn' }
        : { kind: 'money', title: 'Checked for money at risk: none', body: 'No payment is stranded, so config knobs are not frozen' });
    } else if (a === 'najda.freeze') {
      Object.assign(ev, { kind: 'freeze', title: 'CHANGE FREEZE: the payment upstream is failing', tone: 'warn',
        body: `No config change is allowed until a human looks. ${list(r.evidence || [])}` });
    } else if (a === 'najda.bisect') {
      Object.assign(ev, r.applicable
        ? { kind: 'bisect', title: `Bisected the config history: version ${r.culprit} is the culprit`, body: `tested ${(r.tested || []).length} versions by replay` }
        : { kind: 'bisect', title: 'Config change history: none', body: `Nothing was deployed before the incident (${r.reason}), so the fault is in the data, not a recent change` });
    } else if (a === 'najda.differential') {
      const top = r.top || [];
      Object.assign(ev, { kind: 'differential', title: 'Compared failing chats with passing ones', body: `${top.length} span signatures appear mostly in failing chats`,
        detail: top.map(x => `${x.signature}  fail ${x.n_fail} / pass ${x.n_pass}  w=${x.weight}`).join('\n') });
    } else if (a === 'najda.playbook') {
      const e = r.event;
      if (e === 'miss') Object.assign(ev, { kind: 'playbook', title: 'Memory: no playbook matches this signature', body: 'New kind of fault, so Najda investigates from scratch', detail: (r.key || []).join('\n') });
      else if (e === 'match') Object.assign(ev, { kind: 'playbook_hit', title: `Memory: playbook ${r.id} matches (similarity ${(r.score || 1).toFixed(2)})`, tone: 'ok',
        body: `Learned on ${r.source_incident}; proposes ${patchText(r.patches && r.patches[0])} without calling a model` });
      else if (e === 'learned') Object.assign(ev, { kind: 'learned', title: `Memory: playbook ${r.id} learned`, tone: 'ok', body: r.kind === 'fix' ? 'Next time this signature appears the fix is applied with no AI call' : 'Next time this signature appears Najda escalates immediately' });
      else if (e === 'hit') Object.assign(ev, { kind: 'playbook_hit', title: 'Memory: playbook verified end to end', tone: 'ok', body: `${r.llm_calls || 0} AI calls` });
      else continue;
    } else if (a === 'llm') {
      const model = MODELS[args.model] || args.model;
      Object.assign(ev, { kind: 'llm', title: `AI call: ${args.purpose || args.role} (${model})`, cost: r.cost_usd || 0,
        body: `${(r.input_tokens || 0).toLocaleString()} tokens in, ${(r.output_tokens || 0).toLocaleString()} out, $${(r.cost_usd || 0).toFixed(4)}` + (r.tool_calls ? ` · called ${r.tool_calls.join(', ')}` : '') });
    } else if (a === 'najda.triage') {
      Object.assign(ev, { kind: 'triage', title: `Triage: ${r.class === 'novel' ? 'no known pattern' : r.class}`, body: r.brief || 'The small model has no shortcut, so the investigator takes over' });
    } else if (a === 'najda.turn') {
      if (!r.text) continue;
      Object.assign(ev, { kind: 'turn', title: "Investigator's note", body: r.text });
    } else if (a === 'najda.hypotheses') {
      const top = (r.ranked || [])[0];
      if (!top) continue;
      const rejected = top.status && top.status !== 'proposed';
      Object.assign(ev, { kind: 'hypotheses', conf: top.confidence, tone: rejected ? 'bad' : 'warn',
        title: rejected ? `Hypothesis rejected as ${top.status}: ${human(top.label)}` : `Hypothesis: ${human(top.label)}, ${pct(top.confidence)}`,
        body: rejected ? `${top.note}. Proposed ${patchText(top.patch)} but the grounding rule discards it` : top.rationale,
        tags: [...(top.evidence || []).slice(0, 5), ...(Object.keys(top.patch || {}).length ? [`patch ${patchText(top.patch)}`] : [])] });
    } else if (a === 'najda.guardrail') {
      Object.assign(ev, r.allowed
        ? { kind: 'guardrail', title: 'Guardrail: patch allowed', body: `${patchText(r.patch)} is an unprotected knob within the blast radius`, tone: 'ok' }
        : { kind: 'guardrail', title: 'Guardrail: patch BLOCKED', body: `${patchText(r.patch)} touches payments while money is at risk, so Najda escalates instead`, tone: 'bad' });
    } else if (a === 'apply_patch') {
      Object.assign(ev, { kind: 'patch', title: `Applied the smallest patch, config v${r.version}`, body: patchText(args.patch), patch: args.patch || {}, tone: 'warn' });
    } else if (a === 'rollback') {
      Object.assign(ev, { kind: 'rollback', title: 'Rolled the change back', body: json(r).slice(0, 160), tone: 'warn' });
    } else if (a === 'najda.canary') {
      const n = (r.chats || []).length;
      Object.assign(ev, { kind: 'canary', title: `Canary: ${r.n_pass}/${n} pass`, body: `Replayed ${r.chats.join(' and ')} on the new config first`, tone: r.passed ? 'ok' : 'bad' });
    } else if (a === 'najda.regression_check') {
      const broke = (r.broke || []).length;
      Object.assign(ev, { kind: 'regression', title: `Regression replay: ${r.checked - broke}/${r.checked} chats that were passing still pass`, body: broke ? `broke ${r.broke.join(', ')}` : 'Nothing that worked before is broken', tone: broke ? 'bad' : 'ok' });
    } else if (a === 'najda.verify') {
      const ok = r.status === 'verified';
      verified = ok;
      Object.assign(ev, { kind: 'verify', title: `Full replay: ${r.n_pass}/${r.n_total} failed chats now pass`, tone: ok ? 'ok' : 'bad',
        body: ok ? 'Every business rule holds on every replayed chat. Fix verified.' : `Not verified, ${(r.remaining || []).length} chats still fail` });
    } else if (a === 'najda.decision') {
      const rec = r.status === 'recovered';
      Object.assign(ev, { kind: 'decision', status: r.status, tone: rec ? 'ok' : 'bad',
        title: rec ? `Recovered: root cause ${human(r.label)}, config v${r.kept_version} kept` : `Escalated to a human: ${human(r.label)}, config v${r.kept_version} kept`,
        body: rec ? 'The bot is serving customers correctly again' : 'No safe fix from the control panel; the report below says what a human must do' });
    } else if (a === 'escalate') {
      Object.assign(ev, { kind: 'escalate', title: 'Handed over with a bilingual incident report', tone: 'bad' });
    } else continue;
    events.push(ev);
  }
  for (const e of events) { delete e.raw; }
  return events;
}

/** Status pill, checklist, diff and counters after the first k events. */
export function state(inc, events, k, traj) {
  const shown = events.slice(0, k);
  const labels = INVARIANT_LABELS[inc.patient] || INVARIANT_LABELS.order;
  const violated = new Set(inc.bundle.invariants.map(v => v.invariant));
  const has = kind => shown.some(e => e.kind === kind);
  const verified = shown.some(e => e.kind === 'verify' && e.tone === 'ok');
  const frozen = has('freeze') || shown.some(e => e.kind === 'guardrail' && e.tone === 'bad');
  const decision = shown.find(e => e.kind === 'decision');
  const escalated = has('escalate') || (decision && decision.status === 'escalated');
  let status = 'DETECTED';
  if (has('read')) status = 'INVESTIGATING';
  if (has('patch')) status = 'FIXING';
  if (has('canary') || has('regression')) status = 'VERIFYING';
  if (decision) status = decision.status === 'recovered' ? 'RECOVERED' : 'ESCALATED';
  const checklist = [...violated].sort().map(n => ({ label: labels[n] || n, cls: verified ? 'good' : frozen ? 'frozen' : 'bad' }))
    .concat(Object.keys(labels).filter(n => !violated.has(n)).map(n => ({ label: labels[n], cls: 'ok' })));
  const cfg0 = inc.bundle.config.current;
  const diff = [];
  for (const e of shown) if (e.kind === 'patch') for (const [key, after] of Object.entries(e.patch)) diff.push({ knob: key, before: key.split('.').reduce((o, p) => (o || {})[p], cfg0), after });
  const llmCalls = shown.filter(e => e.kind === 'llm').length;
  const cost = shown.reduce((s, e) => s + (e.cost || 0), 0);
  const tLast = [...shown].reverse().find(e => e.t != null)?.t || 0, tEnd = [...events].reverse().find(e => e.t != null)?.t || 0;
  const wall = traj.recorded?.scores?.wall_s || traj.wall_s || 0;
  return { status, checklist, diff, verified, frozen, escalated, llmCalls, cost, elapsed: tEnd ? wall * tLast / tEnd : 0,
    rolledBack: has('rollback'), done: k >= events.length, steps: k };
}

export function splitReport(report) {
  const lines = (report || '').trim().split('\n');
  const [ar, en] = (lines[0] || '').split(' | ');
  const out = { ar: (ar || '').trim(), en: (en || '').trim(), rest: lines.slice(1).join('\n').trim() };
  for (const key of ['Summary', 'Impact', 'Recommended human action']) {
    const ln = lines.find(l => l.startsWith(key + ':'));
    if (ln) out[key] = ln.slice(key.length + 1).trim();
  }
  const i = lines.findIndex(l => l.startsWith('Actions:'));
  if (i >= 0) out.actions = lines.slice(i + 1).filter(l => l.startsWith('  - ')).map(l => l.slice(4));
  return out;
}

export function failingChats(inc) {
  const bad = new Set(inc.bundle.invariants.map(v => v.chat_id));
  for (const c of inc.bundle.chats) if (c.outcome === 'failed') bad.add(c.chat_id);
  return inc.bundle.chats.filter(c => bad.has(c.chat_id));
}
