// 極簡 DOM 工具：h() 建元素、html 樣板跳脫、$/$$ 查詢、fmt 系列。零相依。
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
// 標籤樣板：html`<b>${x}</b>` —— 插值一律跳脫；要塞已信任的 HTML 用 raw()。
// ★ html`` 回傳的是 SafeString（String 子類，帶 __safe 標記）：巢狀 html`` 或 .map(() => html``) 的結果
//   不會被二次跳脫，而外部來的純字串仍會被 esc —— 這是把 XSS 防線放在型別上，而不是靠人記得包 raw()。
class SafeString extends String { get __safe() { return true; } }
export function html(strings, ...vals) {
  return new SafeString(strings.reduce((acc, s, i) => acc + s + (i < vals.length ? _v(vals[i]) : ''), ''));
}
function _v(v) {
  if (v == null || v === false) return '';
  if (v && typeof v === 'object' && '__raw' in v) return v.__raw;
  if (v && v.__safe) return String(v);
  if (Array.isArray(v)) return v.map(_v).join('');
  return esc(v);
}
// raw() 回的也是 SafeString（不是普通物件）—— 這樣它**同時**能用在兩個地方：
//   · html`${raw(x)}` → 走 __safe 分支，不二次跳脫（與原本相同）
//   · el.innerHTML = raw(x) → String 子類，字串化成 HTML 本身
// ⚠️ 原本回的是 { __raw }，直接指派給 innerHTML 會印出「[object Object]」——
//    而且**畫面上真的就長那樣**，沒有任何錯誤（2026-08-23 範本端到端驗收，
//    儀表板「最近報告」的空狀態）。
export const raw = (s) => new SafeString(String(s ?? ''));

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function mount(container, htmlStr) {
  container.innerHTML = htmlStr;
  return container;
}

export const fmt = {
  int: (n) => (n == null ? '—' : Number(n).toLocaleString('en-US')),
  // token 這類「量級才是重點」的大數字：1,236 → 1.2K、10,294,870,236 → 10.3B。
  // ⚠️ 只給展示用，明細一律還是給 fmt.int 的完整數字（用量的 tooltip 就是這樣）。
  compact: (n) => {
    if (n == null) return '—';
    const x = Number(n);
    for (const [d, u] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) {
      if (Math.abs(x) >= d) { const v = x / d; return (v >= 100 ? Math.round(v) : v.toFixed(1)) + u; }
    }
    return String(Math.round(x));
  },
  float1: (n) => (n == null ? '—' : Number(n).toFixed(1)),
  percent: (n) => (n == null ? '—' : (Number(n) * 100).toFixed(2) + '%'),
  ms: (n) => (n == null ? '—' : Math.round(n) + ' ms'),
  dur: (s) => {
    if (s == null) return '—';
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return (h ? h + 'h' : '') + (m ? m + 'm' : '') + (x || (!h && !m) ? x + 's' : '');
  },
  time: (s) => (s ? String(s).slice(11, 19) : '—'),
  date: (s) => (s ? String(s).slice(0, 10) : '—'),
  ago: (s) => {
    if (!s) return '—';
    const d = (Date.now() - new Date(String(s).replace(' ', 'T')).getTime()) / 1000;
    if (d < 60) return '剛剛';
    if (d < 3600) return Math.floor(d / 60) + ' 分鐘前';
    if (d < 86400) return Math.floor(d / 3600) + ' 小時前';
    return Math.floor(d / 86400) + ' 天前';
  },
  by: (kind, v) => (fmt[kind] ? fmt[kind](v) : (v ?? '—')),
};

export function debounce(fn, ms = 150) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
export function copy(text) { return navigator.clipboard?.writeText(text); }

// ── 個資遮罩 ────────────────────────────────────────────────────────────
// 平台是給人看著操作的，但也常被投影／截圖／貼進報告 —— 登入 email 與
// `C:\Users\<帳號>\…` 這種路徑不該預設就攤在畫面上。
// 遮罩是「顯示層」的事：值本身完全不動，要看時點一下就展開（見 revealable）。
const RE_EMAIL = /([\w.+-])[\w.+-]*(@[\w.-]+)/g;
const RE_HOME = /([A-Za-z]:[\\/]+Users[\\/]+)([^\\/\s"']+)/g;

export function redactPII(text) {
  return String(text ?? '')
    .replace(RE_EMAIL, (_m, a, d) => `${a}${'•'.repeat(5)}${d}`)
    .replace(RE_HOME, (_m, p, u) => `${p}${u[0]}${'•'.repeat(4)}`);
}

export function hasPII(text) {
  const s = String(text ?? '');
  RE_EMAIL.lastIndex = RE_HOME.lastIndex = 0;
  return RE_EMAIL.test(s) || RE_HOME.test(s);
}

/** 產生「預設遮罩、點一下展開」的行內元素。回傳 HTML 字串，需搭配 bindReveal 掛事件。 */
export function revealable(text, { cls = '' } = {}) {
  const s = String(text ?? '');
  if (!hasPII(s)) return `<span class="${cls}">${esc(s)}</span>`;
  return `<span class="${cls} pii" data-pii="${esc(s)}" title="點一下顯示完整內容">${esc(redactPII(s))}</span>`;
}

/** 委派：容器內任何 .pii 被點到就換成原文（不可逆，重新載入才會再遮起來）。 */
export function bindReveal(root) {
  root.addEventListener('click', (e) => {
    const n = e.target.closest('.pii'); if (!n) return;
    e.stopPropagation();
    n.textContent = n.dataset.pii;
    n.classList.remove('pii');
    n.removeAttribute('title');
  });
}

// ── 全螢幕浮層的計數 ────────────────────────────────────────────
// 有任何浮層（modal／指令列／對話視窗）開著時，`<body>` 掛上 `.overlay-open`。
// 用途見 `base.css` 的說明：那三層都是全螢幕 `backdrop-filter`，
// **背後只要有任何迴圈動畫，模糊就得每一幀重算** —— 所以要把背後凍結。
// ⚠️ 必須用計數而不是布林：modal 與對話視窗可以同時開著（對話裡按「檢視並執行」就是），
//    關掉其中一個時不可以把 class 一起拿掉。
let _overlays = 0;
export function overlayOpened() { _overlays += 1; document.body.classList.add('overlay-open'); }
export function overlayClosed() {
  _overlays = Math.max(0, _overlays - 1);
  if (!_overlays) document.body.classList.remove('overlay-open');
}
