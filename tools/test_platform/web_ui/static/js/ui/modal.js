// 自製 modal（不用原生 alert/confirm/prompt —— 沿用壓測控制台慣例）
import { h, html, raw, overlayOpened, overlayClosed } from './el.js';

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])';

// 目前開著的 modal 的 close()。⛔ **換頁時要一起關掉** ——
// modal 是掛在 <body> 上的，router 換頁只重建 `#view`，動不到它：
// 於是在產品頁點開一張 Bug 單、接著切到案例頁，那張單**還浮在新頁面上**
// （2026-08-24 拍手冊截圖時撞到 —— 案例頁的截圖裡整片是 Bug 明細框）。
const openModals = new Set();
export function closeAllModals() {
  for (const close of [...openModals]) {
    try { close(); } catch (e) { /* 已經關掉的忽略 */ }
  }
  openModals.clear();
}

/** `size`：'' 一般（560px）／'wide' 表單與確認卡（880px）／'doc' 長文（1360px）。
 *  `wide: true` 等同 `size: 'wide'`，既有呼叫端不必改。 */
function open({ title, body, actions, danger = false, wide = false, size = '', onClose }) {
  const sz = size || (wide ? 'wide' : '');
  const box = h('div', { class: 'box' + (sz ? ' ' + sz : ''), role: 'dialog', 'aria-modal': 'true' });
  // ⚠️ body 可能是三種東西：DOM 節點、純字串、或 html`` 回傳的 SafeString（String 子類）。
  //    先前只認 `typeof body === 'string'`，於是 SafeString 兩個分支都不中、**整段 body 被丟掉**
  //    —— `modal.alert()` 從來沒顯示過訊息內容，只有標題與按鈕（2026-08-21 走查時才發現）。
  const bodyHtml = body && !body.nodeType && (typeof body === 'string' || body.__safe)
    ? String(body) : '';
  box.innerHTML = html`<h3>${title}</h3>` + bodyHtml;
  if (body && body.nodeType) box.append(body);
  const act = h('div', { class: 'actions' });
  box.append(act);
  const wrap = h('div', { class: 'modal' + (danger ? ' danger' : '') }, box);
  // 記住開啟前的焦點，關閉時還回去 —— 否則 Esc 之後焦點落在 <body>，鍵盤使用者要從頭 Tab 起
  const opener = document.activeElement;
  const close = () => {
    if (!openModals.has(close)) return;      // 重複呼叫不可以扣兩次浮層計數
    openModals.delete(close);
    overlayClosed();
    wrap.remove();
    document.removeEventListener('keydown', onKey, true);
    if (opener && opener.isConnected && opener.focus) opener.focus();
    onClose && onClose();
  };
  openModals.add(close);
  // ★ focus trap：Tab 鎖在框內。先前確認框開啟後焦點還留在背景的「執行」鈕，
  //   按 Enter 會再觸發一次執行 —— 對高風險命令（結算重置）是實打實的誤觸風險。
  const onKey = (e) => {
    if (e.key === 'Escape') { close(); return; }
    if (e.key !== 'Tab') return;
    const items = Array.from(box.querySelectorAll(FOCUSABLE)).filter((n) => n.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!box.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener('keydown', onKey, true);
  wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
  (actions || []).forEach((a) => {
    const b = h('button', { class: 'btn ' + (a.cls || ''), onclick: async () => { const r = a.onClick ? await a.onClick(box) : true; if (r !== false) close(); } }, a.label);
    if (a.disabled) b.disabled = true;
    act.append(b);
    if (a.ref) a.ref(b);
  });
  document.body.append(wrap);
  overlayOpened();                            // 背後的迴圈動畫先凍結（見 base.css）
  // 有輸入框就聚焦它（typed confirm 開了就是要打字），否則聚焦第一個按鈕
  const target = box.querySelector('input,textarea') || box.querySelector(FOCUSABLE);
  if (target) setTimeout(() => target.focus(), 20);
  return { close, box };
}

export const modal = {
  open,
  alert(title, msg) { return new Promise((res) => open({ title, body: html`<div class="md">${raw(msg)}</div>`, actions: [{ label: '知道了', cls: 'primary', onClick: () => res(true) }], onClose: () => res(true) })); },
  confirm(title, msg, { danger = false, okLabel = '確定', typed = null } = {}) {
    return new Promise((res) => {
      let okBtn;
      const body = h('div');
      body.innerHTML = html`<div class="md">${raw(msg)}</div>`;
      if (typed) {
        const inp = h('input', { type: 'text', placeholder: `請輸入「${typed}」以確認`, style: { width: '100%', marginTop: '10px', padding: '6px 8px', background: 'var(--code-bg)', border: '1px solid var(--danger)', color: 'var(--text)', borderRadius: '4px' } });
        inp.addEventListener('input', () => { okBtn.disabled = inp.value.trim() !== typed; });
        body.append(inp);
      }
      open({
        title, body, danger,
        actions: [
          { label: '取消', onClick: () => { res(false); } },
          { label: okLabel, cls: danger ? 'danger' : 'primary', disabled: !!typed, ref: (b) => (okBtn = b), onClick: () => { res(true); } },
        ],
        onClose: () => res(false),
      });
    });
  },
  /** 第三個參數可以是預設值（字串），也可以是 `{ def, placeholder, okLabel, multiline }`。
   *  ⚠️ `label` 支援 HTML —— 說明常要標重點（先前是純文字節點，`<b>` 會原樣印出來）。 */
  prompt(title, label, opts = '') {
    const o = typeof opts === 'string' ? { def: opts } : (opts || {});
    return new Promise((res) => {
      const inp = o.multiline
        ? h('textarea', { rows: 3, style: { width: '100%', padding: '6px 8px', background: 'var(--code-bg)', border: '1px solid var(--border-strong)', color: 'var(--text)', borderRadius: '4px' } })
        : h('input', { type: 'text', value: o.def || '', placeholder: o.placeholder || '', style: { width: '100%', padding: '6px 8px', background: 'var(--code-bg)', border: '1px solid var(--border-strong)', color: 'var(--text)', borderRadius: '4px' } });
      if (o.multiline && o.def) inp.value = o.def;
      const lab = h('div', { class: 'small muted', style: { marginBottom: '6px' } });
      lab.innerHTML = String(label || '');
      const body = h('div', {}, lab, inp);
      open({ title, body, actions: [{ label: '取消', onClick: () => res(null) }, { label: o.okLabel || '確定', cls: 'primary', onClick: () => res(inp.value) }], onClose: () => res(null) });
      setTimeout(() => inp.focus(), 30);
    });
  },
};
