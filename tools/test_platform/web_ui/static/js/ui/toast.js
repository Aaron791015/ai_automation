// toast 通知
import { h } from './el.js';
let box;
export function toast(msg, tone = 'info', ms = 3200) {
  if (!box) { box = h('div', { class: 'toasts' }); document.body.append(box); }
  const t = h('div', { class: 'toast ' + tone }, msg);
  box.append(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; setTimeout(() => t.remove(), 300); }, ms);
}
