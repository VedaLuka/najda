// Router + stage scaling + keyboard. Screens: live, learn, stop, results (hash routes, keys 1-4).
import * as live from './live.js';
import * as learn from './learn.js';
import * as stop from './stop.js';
import * as results from './results.js';

const SCREENS = { live, learn, stop, results };
const stage = document.getElementById('stage'), main = document.getElementById('main'), topright = document.getElementById('topright'), nav = document.getElementById('nav');
let current = null;

function fit() {
  const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
  stage.style.transform = `translate(-50%, -50%) scale(${s})`;
}
window.addEventListener('resize', fit); fit();

export function parse() {
  const [screen, query] = location.hash.replace(/^#\/?/, '').split('?');
  return { screen: SCREENS[screen] ? screen : 'live', ...Object.fromEntries(new URLSearchParams(query || '')) };
}
export function go(params) {
  const { screen, ...rest } = params;
  const q = new URLSearchParams(Object.entries(rest).filter(([, v]) => v != null && v !== '')).toString();
  location.hash = `#${screen}${q ? '?' + q : ''}`;
}

async function route() {
  const params = parse();
  for (const b of nav.querySelectorAll('button')) b.classList.toggle('active', b.dataset.screen === params.screen);
  document.body.dataset.screen = params.screen;
  try {
    current = await SCREENS[params.screen].render(main, topright, params, go);
  } catch (err) {
    console.error(err);
    main.innerHTML = `<section class="screen"><div class="panel"><h2>Could not load the demo pack</h2><pre class="mono">${String(err).replace(/</g, '&lt;')}</pre><p class="caption">Serve the app folder with <code>python -m http.server -d app 8765</code> and open /web/.</p></div></section>`;
  }
}
window.addEventListener('hashchange', route);
nav.addEventListener('click', e => { const b = e.target.closest('button'); if (b) go({ screen: b.dataset.screen }); });
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' && e.key !== ' ') return;
  if (/^[1-4]$/.test(e.key)) { go({ screen: Object.keys(SCREENS)[+e.key - 1] }); return; }
  if (current && current.keys) current.keys(e);
});
route();
