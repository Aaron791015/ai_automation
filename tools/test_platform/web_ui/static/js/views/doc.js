// #/doc?path=<repo 相對路徑>[&line=N] 文件全文（**整頁**，不是浮層）
//
// ⛔ 為什麼要有這一頁：`views/overview.js` 的空狀態引導有一顆
//    「看 README 的完整上手五步」按鈕指向 `#/doc?path=README.md`，
//    而**這個路由根本不存在** —— 按下去是「找不到頁面：/doc」。
//    那是新同事看到的**第一個畫面**（一個產品都還沒接的時候），
//    第一顆按鈕就是壞的（2026-08-24 走查）。
//
// ★ 與浮層版（`ui/docview.js` 的 `openDoc()`）的分工：
//    · **浮層** ＝ 我正在做別的事，順手瞄一眼（待辦看全文、Bug 看來源、報告看全文）
//    · **整頁** ＝ 我就是來讀這份文件的（從網址進來、或引導按鈕帶過來）
//    兩者共用同一個 `renderMarkdown()`，不會有兩套排版。
import { api } from '../api.js';
import { $, html, raw, esc } from '../ui/el.js';
import { renderMarkdown, openDoc } from '../ui/docview.js';
import { toast } from '../ui/toast.js';
import { pageLoading } from '../ui/loading.js';

export async function mount(root) {
  const qs = new URLSearchParams(location.hash.split('?')[1] || '');
  const path = qs.get('path') || '';
  const line = Number(qs.get('line') || 0) || null;
  if (!path) {
    root.innerHTML = html`<div class="page"><div class="empty">
      網址少了 <code>?path=</code> —— 例：<code>#/doc?path=README.md</code></div></div>`;
    return;
  }

  root.innerHTML = html`<div class="page">
    <div class="page-head">
      <a class="crumb" href="#/">← 總覽</a>
      <h2>${path.split('/').pop()}</h2>
      <span class="crumb mono" id="dc-path">${path}</span>
      <span style="flex:1"></span>
      <span class="tiny muted" id="dc-lines"></span>
      <button class="btn sm ghost" id="dc-copy">複製路徑</button>
    </div>
    <div class="page-body"><div class="md docview-body" id="dc-body"
      style="max-height:none;overflow:visible">${pageLoading("開檔中…")}</div></div>
  </div>`;

  let d;
  try { d = await api.get(`/api/doc?path=${encodeURIComponent(path)}`); }
  catch (e) {
    const b = $('#dc-body', root);
    if (b) b.innerHTML = html`<div class="alert is-error">讀不到檔案：${esc(e.message)}</div>`;
    return;
  }
  const body = $('#dc-body', root);
  if (!body) return;                       // 載入途中被切走（同 cases.js／settings.js 的守衛）
  body.innerHTML = renderMarkdown(d.text);
  $('#dc-lines', root).textContent = `${d.lines} 行`;
  $('#dc-copy', root).onclick = () => {
    navigator.clipboard?.writeText(d.path);
    toast('已複製路徑', 'success');
  };

  // 文件內的 .md 連結：同一頁換一份（維持「我在讀文件」的脈絡，不要跳出浮層）
  body.addEventListener('click', (e) => {
    const a = e.target.closest('[data-doclink]');
    if (!a) return;
    e.preventDefault();
    const [p, frag] = a.dataset.doclink.split('#');
    const ln = /^L\d+$/.test(frag || '') ? `&line=${frag.slice(1)}` : '';
    location.hash = `#/doc?path=${encodeURIComponent(resolveRel(d.path, p))}${ln}`;
  });

  if (line) {
    // 整頁模式捲的是 `.page-body`（浮層模式捲的是 `.docview-body` 自己）
    requestAnimationFrame(() => {
      const scroller = root.querySelector('.page-body');
      let best = null;
      for (const n of body.querySelectorAll('[data-line]')) {
        if (Number(n.dataset.line) <= line) best = n; else break;
      }
      if (!best || !scroller) return;
      scroller.scrollTop += best.getBoundingClientRect().top
        - scroller.getBoundingClientRect().top - 56;
      best.classList.add('line-hit');
    });
  }
}

/** 與 `ui/docview.js` 同一套相對路徑解析（那裡是模組私有的，這裡重寫一份最小版）。 */
function resolveRel(from, rel) {
  if (!rel.startsWith('.')) return rel.replace(/^\/+/, '');
  const base = from.split('/').slice(0, -1);
  for (const seg of rel.split('/')) {
    if (seg === '.' || !seg) continue;
    if (seg === '..') base.pop();
    else base.push(seg);
  }
  return base.join('/');
}

// 讓「順手瞄一眼」那條路仍然可用（例如從這一頁再開別的浮層）
export { openDoc };
