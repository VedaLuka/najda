// WhatsApp-style phone frame: RTL bubbles, timestamps, ticks, amber highlight on the wrong line, teal after the fix.
import { h, ICON } from './ui.js';

const isArabic = s => /[؀-ۿ]/.test(s);

function highlight(text, mode) {
  const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const money = /((?:الإجمالي|العربون|Total)\s*[\d٠-٩.,]+\s*(?:ريال|SAR))/g;
  const qty = /([\d٠-٩]+\s*x\s*[^,.]+)/g;
  if (mode === 'money' && money.test(esc)) return esc.replace(money, '<span class="hl">$1</span>');
  if (mode === 'qty' && qty.test(esc)) return esc.replace(qty, '<span class="hl">$1</span>');
  return esc;
}

export function phone(inc, chat, after, verified, violations) {
  const mode = violations.some(v => /qty/.test(v.invariant)) ? 'qty' : violations.some(v => /total|deposit/.test(v.invariant)) ? 'money' : 'last';
  const transcript = verified && after ? after.transcript : chat.transcript;
  const botIdx = transcript.map((m, i) => m.role === 'bot' ? i : -1).filter(i => i >= 0);
  const flagIdx = new Set();
  if (mode === 'last') { if (chat.outcome === 'failed') flagIdx.add(botIdx[botIdx.length - 1]); }
  else transcript.forEach((m, i) => { if (m.role === 'bot' && highlight(m.text, mode) !== m.text.replace(/&/g, '&amp;').replace(/</g, '&lt;')) flagIdx.add(i); });
  const body = h('div', { class: 'phone-body' });
  const base = 14 * 60 + 2 + (chat.chat_id.charCodeAt(chat.chat_id.length - 1) % 7) * 3;
  transcript.forEach((m, i) => {
    const t = `${String(Math.floor((base + i) / 60)).padStart(2, '0')}:${String((base + i) % 60).padStart(2, '0')}`;
    const flagged = flagIdx.has(i);
    const b = h('div', { class: `bubble ${m.role}${flagged ? (verified && after ? ' fixed' : ' flag') : ''}`, dir: isArabic(m.text) ? 'rtl' : 'ltr', style: `animation-delay:${i * 60}ms` });
    b.innerHTML = (flagged ? highlight(m.text, mode) : m.text.replace(/&/g, '&amp;').replace(/</g, '&lt;')) + `<div class="meta"><span>${t}</span>${m.role === 'customer' ? ICON.ticks : ''}</div>`;
    body.append(b);
  });
  const who = inc.patient === 'hajz' ? 'Hajz · حجز' : 'Order bot · مطعم';
  return h('div', { class: 'phone' },
    h('div', { class: 'phone-head' }, h('div', { class: 'avatar' }, inc.patient === 'hajz' ? 'H' : 'B'), h('div', {}, h('div', { class: 'who' }, who), h('div', { class: 'state' }, verified && after ? 'replayed on the fixed config' : `incident transcript · ${chat.outcome}`)),
    verified && after ? h('span', { class: 'pill teal' }, 'verified by replay') : null,
      h('div', { class: 'right' }, chat.chat_id)),
    body,
    h('div', { class: 'phone-foot' }, h('div', { class: 'input' }), h('div', { class: 'send' })));
}

