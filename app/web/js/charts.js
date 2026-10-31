// Hand-drawn SVG charts: thin marks, recessive axes, direct labels, hover tooltips. No library.
import { h, hover } from './ui.js';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, text) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
};
const size = container => ({ W: container.clientWidth || 600, H: container.clientHeight || 300 });

/** Horizontal dot + CI bars: rows [{label, v, lo, hi, color, note}], domain [lo, hi]. */
export function ciDots(container, rows, { domain = [0, 1], fmt = v => v.toFixed(2), ticks = [0, 0.25, 0.5, 0.75, 1], labelW = 190 } = {}) {
  container.replaceChildren();
  const { W, H } = size(container);
  const m = { l: labelW, r: 70, t: 12, b: 30 };
  const x = v => m.l + (v - domain[0]) / (domain[1] - domain[0]) * (W - m.l - m.r);
  const rowH = (H - m.t - m.b) / rows.length;
  const s = el('svg', { viewBox: `0 0 ${W} ${H}` });
  const grid = el('g', { class: 'grid' });
  for (const t of ticks) { grid.append(el('line', { x1: x(t), x2: x(t), y1: m.t, y2: H - m.b })); grid.append(el('text', { x: x(t), y: H - 8, 'text-anchor': 'middle', class: 'ann' }, fmt(t))); }
  s.append(grid);
  rows.forEach((r, i) => {
    const y = m.t + rowH * (i + 0.5);
    const g = el('g', { class: 'row' });
    g.append(el('text', { x: m.l - 14, y: y + 5, 'text-anchor': 'end', class: 'lab' }, r.label));
    if (r.lo != null) {
      g.append(el('line', { x1: x(r.lo), x2: x(r.hi), y1: y, y2: y, stroke: r.color, 'stroke-width': 2, 'stroke-linecap': 'round', opacity: 0.55 }));
      for (const v of [r.lo, r.hi]) g.append(el('line', { x1: x(v), x2: x(v), y1: y - 6, y2: y + 6, stroke: r.color, 'stroke-width': 2, opacity: 0.55 }));
    }
    g.append(el('circle', { cx: x(r.v), cy: y, r: 7, fill: r.color, stroke: '#10263A', 'stroke-width': 2 }));
    g.append(el('text', { x: x(r.hi != null ? r.hi : r.v) + 14, y: y + 5, class: 'val' }, fmt(r.v)));
    const hit = el('rect', { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: 'transparent' });
    hover(hit, r.lo != null ? `${r.label}\n${fmt(r.v)}  [${fmt(r.lo)}, ${fmt(r.hi)}]${r.note ? '\n' + r.note : ''}` : `${r.label}\n${fmt(r.v)}${r.note ? '\n' + r.note : ''}`);
    g.append(hit);
    s.append(g);
  });
  container.append(s);
}

/** Horizontal bars: rows [{label, v, color, note}], with the value printed at the bar end. */
export function barsH(container, rows, { domain, fmt = v => v.toFixed(2), labelW = 190 } = {}) {
  container.replaceChildren();
  const { W, H } = size(container);
  const max = domain ? domain[1] : Math.max(...rows.map(r => r.v)) * 1.25 || 1;
  const m = { l: labelW, r: 80, t: 8, b: 8 };
  const x = v => m.l + v / max * (W - m.l - m.r);
  const rowH = (H - m.t - m.b) / rows.length, bh = Math.min(26, rowH * 0.55);
  const s = el('svg', { viewBox: `0 0 ${W} ${H}` });
  s.append(el('line', { x1: m.l, x2: m.l, y1: m.t, y2: H - m.b, stroke: 'rgba(141,162,181,0.32)' }));
  rows.forEach((r, i) => {
    const y = m.t + rowH * (i + 0.5);
    const g = el('g');
    g.append(el('text', { x: m.l - 14, y: y + (r.sub ? -3 : 5), 'text-anchor': 'end', class: 'lab' }, r.label));
    if (r.sub) g.append(el('text', { x: m.l - 14, y: y + 14, 'text-anchor': 'end', class: 'ann' }, r.sub));
    const w = Math.max(0, x(r.v) - m.l);
    g.append(el('path', { d: w > 0 ? `M${m.l},${y - bh / 2} H${m.l + w - 4} a4,4 0 0 1 4,4 v${bh - 8} a4,4 0 0 1 -4,4 H${m.l} Z` : `M${m.l},${y - bh / 2} v${bh}`, fill: r.color, stroke: r.color, 'stroke-width': w > 0 ? 0 : 3 }));
    g.append(el('text', { x: m.l + w + 12, y: y + 5, class: 'val' }, fmt(r.v)));
    const hit = el('rect', { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: 'transparent' });
    hover(hit, `${r.label}\n${fmt(r.v)}${r.note ? '\n' + r.note : ''}`);
    g.append(hit);
    s.append(g);
  });
  container.append(s);
}

/** Line chart: series [{name, color, points:[{x,y}]}], one shared y axis; direct label at line end + crosshair tooltip. */
export function lines(container, series, { xLabel = '', yFmt = v => v.toFixed(3), yMax } = {}) {
  container.replaceChildren();
  const { W, H } = size(container);
  const m = { l: 70, r: 150, t: 16, b: 40 };
  const xs = series.flatMap(s => s.points.map(p => p.x)), ys = series.flatMap(s => s.points.map(p => p.y));
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y1 = yMax || Math.max(...ys) * 1.15;
  const x = v => m.l + (v - x0) / (x1 - x0 || 1) * (W - m.l - m.r);
  const y = v => H - m.b - v / y1 * (H - m.t - m.b);
  const s = el('svg', { viewBox: `0 0 ${W} ${H}` });
  const grid = el('g', { class: 'grid' });
  const yt = 4;
  for (let i = 0; i <= yt; i++) { const v = y1 * i / yt; grid.append(el('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) })); grid.append(el('text', { x: m.l - 10, y: y(v) + 4, 'text-anchor': 'end', class: 'ann' }, yFmt(v))); }
  const xt = 6;
  for (let i = 0; i <= xt; i++) { const v = Math.round(x0 + (x1 - x0) * i / xt); grid.append(el('text', { x: x(v), y: H - 14, 'text-anchor': 'middle', class: 'ann' }, v)); }
  grid.append(el('text', { x: (m.l + W - m.r) / 2, y: H - 0, 'text-anchor': 'middle', class: 'ann' }, xLabel));
  s.append(grid);
  for (const ser of series) {
    const d = ser.points.map((p, i) => `${i ? 'L' : 'M'}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`).join(' ');
    s.append(el('path', { d, fill: 'none', stroke: ser.color, 'stroke-width': 2.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    const last = ser.points[ser.points.length - 1];
    s.append(el('circle', { cx: x(last.x), cy: y(last.y), r: 5, fill: ser.color, stroke: '#10263A', 'stroke-width': 2 }));
    s.append(el('text', { x: x(last.x) + 12, y: y(last.y) + 4, class: 'lab' }, `${ser.name} ${yFmt(last.y)}`));
  }
  const cross = el('line', { x1: 0, x2: 0, y1: m.t, y2: H - m.b, stroke: 'rgba(238,243,248,0.35)', 'stroke-dasharray': '3 3', visibility: 'hidden' });
  s.append(cross);
  const hit = el('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' });
  const tip = document.getElementById('tooltip');
  hit.addEventListener('mousemove', e => {
    const pt = s.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(s.getScreenCTM().inverse());
    const xv = Math.round(x0 + (p.x - m.l) / (W - m.l - m.r) * (x1 - x0));
    cross.setAttribute('x1', x(xv)); cross.setAttribute('x2', x(xv)); cross.setAttribute('visibility', 'visible');
    tip.textContent = `${xLabel} ${xv}\n` + series.map(ser => { const q = ser.points.find(q => q.x === xv); return q ? `${ser.name}: ${yFmt(q.y)}` : null; }).filter(Boolean).join('\n');
    tip.hidden = false;
    const stage = document.getElementById('stage').getBoundingClientRect(), scale = stage.width / 1920;
    tip.style.left = `${(e.clientX - stage.left) / scale + 14}px`; tip.style.top = `${(e.clientY - stage.top) / scale + 14}px`;
  });
  hit.addEventListener('mouseleave', () => { cross.setAttribute('visibility', 'hidden'); tip.hidden = true; });
  s.append(hit);
  container.append(s);
}

export const legend = items => h('div', { class: 'legend' }, ...items.map(i => h('span', {}, h('i', { class: i.dot ? 'dot' : '', style: `background:${i.color}` }), i.name)));
