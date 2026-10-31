// Tiny DOM helpers and shared icons (inline SVG, no icon font, no emoji).
export const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v; else if (k === 'html') el.innerHTML = v; else if (k.startsWith('on')) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
};
export const svg = (paths, vb = '0 0 24 24') => `<svg viewBox="${vb}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
export const ICON = {
  check: svg('<path d="M5 12.5l4.5 4.5L19 7"/>'),
  cross: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  play: svg('<path d="M7 5v14l12-7z" fill="currentColor" stroke="none"/>'),
  pause: svg('<path d="M8 5v14M16 5v14" stroke-width="3"/>'),
  first: svg('<path d="M6 5v14M19 6l-9 6 9 6z" fill="currentColor"/>'),
  last: svg('<path d="M18 5v14M5 6l9 6-9 6z" fill="currentColor"/>'),
  back: svg('<path d="M15 5l-7 7 7 7"/>'),
  fwd: svg('<path d="M9 5l7 7-7 7"/>'),
  read: svg('<path d="M4 6h16M4 12h10M4 18h7"/>'),
  search: svg('<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>'),
  brain: svg('<path d="M12 4a4 4 0 0 0-4 4v8a4 4 0 0 0 8 0V8a4 4 0 0 0-4-4z"/><path d="M8 10h8M8 14h8"/>'),
  shield: svg('<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/>'),
  patch: svg('<path d="M12 5v14M5 12h14"/>'),
  replay: svg('<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v5h5"/>'),
  memory: svg('<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 9h8M8 13h5"/>'),
  money: svg('<circle cx="12" cy="12" r="8"/><path d="M12 7v10M9.5 9.5h4a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3h4"/>'),
  flag: svg('<path d="M5 21V4h11l-2 4 2 4H5"/>'),
  warn: svg('<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5v.5"/>'),
  hand: svg('<path d="M7 11V6a1.5 1.5 0 0 1 3 0v5M10 10V4a1.5 1.5 0 0 1 3 0v6M13 10V5a1.5 1.5 0 0 1 3 0v8M16 12a1.5 1.5 0 0 1 3 0v3a6 6 0 0 1-6 6h-2a6 6 0 0 1-5-3l-2-4a1.5 1.5 0 0 1 2.5-1.5L7 14"/>'),
  arrow: svg('<path d="M5 12h14M13 6l6 6-6 6"/>'),
  ticks: '<svg viewBox="0 0 16 11" fill="none" stroke="#53BDEB" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 6l3 3 5-7M6 9l1 1 6-8"/></svg>',
};
export const KIND_ICON = { read: 'read', baseline: 'replay', money: 'money', freeze: 'flag', bisect: 'search', differential: 'search', playbook: 'memory', playbook_hit: 'memory', learned: 'memory',
  llm: 'brain', triage: 'brain', turn: 'brain', hypotheses: 'search', guardrail: 'shield', patch: 'patch', rollback: 'replay', canary: 'replay', regression: 'replay', verify: 'check', decision: 'check', escalate: 'hand' };

export const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Animate a number in `el` from its last value to `to` (count-up), formatted by fmt. */
export function countUp(el, to, fmt, ms = 450) {
  const from = +(el.dataset.v || 0);
  el.dataset.v = to;
  if (reduceMotion() || from === to) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const tick = now => {
    const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(from + (to - from) * e);
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

const tip = document.getElementById('tooltip');
export function hover(el, text) {
  el.addEventListener('mouseenter', () => { tip.textContent = text; tip.hidden = false; });
  el.addEventListener('mousemove', e => {
    const stage = document.getElementById('stage').getBoundingClientRect();
    const scale = stage.width / 1920;
    tip.style.left = `${(e.clientX - stage.left) / scale + 14}px`; tip.style.top = `${(e.clientY - stage.top) / scale + 14}px`;
  });
  el.addEventListener('mouseleave', () => { tip.hidden = true; });
}
