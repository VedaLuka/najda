// Loads the demo pack (app/data/). Everything is fetched relative to the page, so the folder deploys anywhere.
const ROOT = document.querySelector('meta[name="data-root"]').content;
const cache = new Map();

async function getJSON(rel) {
  if (!cache.has(rel)) {
    cache.set(rel, fetch(`${ROOT}/${rel}`).then(r => { if (!r.ok) throw new Error(`${rel}: ${r.status}`); return r.json(); }));
  }
  return cache.get(rel);
}
async function getText(rel) {
  const r = await fetch(`${ROOT}/${rel}`);
  if (!r.ok) throw new Error(`${rel}: ${r.status}`);
  return r.text();
}

export const manifest = () => getJSON('manifest.json');
export const incident = id => getJSON(`incidents/${id}.json`);
export const repeat = () => getJSON('repeat.json');
export const sections = () => getJSON('results/sections.json');

export async function csv(name) {
  const text = await getText(`results/${name}`);
  const lines = text.trim().split(/\r?\n/);
  const head = lines[0].split(',');
  return lines.slice(1).map(ln => Object.fromEntries(ln.split(',').map((c, i) => [head[i], c])));
}

/** Rows of the first markdown table under the section whose heading starts with `prefix`. */
export async function mdTable(doc, prefix) {
  const secs = (await sections())[doc];
  const sec = secs.find(s => s.heading.startsWith(prefix));
  if (!sec) return [];
  const lines = sec.body.split('\n');
  const start = lines.findIndex(l => l.startsWith('|'));
  const block = [];
  for (const l of lines.slice(start)) { if (!l.startsWith('|')) break; block.push(l); }
  const rows = block.map(l => l.replace(/^\||\|$/g, '').split('|').map(c => c.trim()));
  const head = rows[0];
  return rows.slice(2).map(r => Object.fromEntries(r.map((c, i) => [head[i], c])));
}

/** "**0.840 [0.680, 0.960]**" -> {v, lo, hi} */
export function parseCI(cell) {
  const m = cell.replace(/\*/g, '').match(/([\d.]+)\s*\[([\d.]+),\s*([\d.]+)\]/);
  return m ? { v: +m[1], lo: +m[2], hi: +m[3] } : null;
}
