// 設定 → 工作區分頁：把 `scope: workspace` 的工具搬進設定頁（2026-08-24 使用者裁示）
//
// > 「設定相關的操作應放在設定頁面，而非在工具頁面出現工作區設定功能」
//
// ⛔ **不重寫一份表單** —— 工具頁（`views/tool.js`）已經有動態表單、危險確認、
//    gate 檢查、profile、執行監控整套。這裡只是換一個入口，內容仍是同一支 view
//    以 `embed` 模式掛進來（它會略過自己的頁殼與麵包屑）。
//    重寫等於多一份會分岔的實作，而底下的腳本才是唯一實作（`scripts/`）。
import { html } from '../ui/el.js';
import { state } from '../store.js';

let inner = null;

export async function mount(root) {
  const ws = (state.tools || []).filter((t) => t.scope === 'workspace');
  if (!ws.length) {
    root.innerHTML = html`<div class="alert is-info small">
      找不到工作區工具（<code>registry/setup.tool.json</code>）—— 註冊表若被移除，這一頁就沒有東西可以顯示。</div>`;
    return;
  }
  const want = new URLSearchParams(location.hash.split('?')[1] || '').get('tool');
  const t = ws.find((x) => x.id === want) || ws[0];
  root.innerHTML = html`${ws.length > 1 ? html`<div class="tabs" id="ws-pick">${ws.map((x) => html`<button class="tab-btn ${x.id === t.id ? 'active' : ''}" data-ws="${x.id}">${x.name}</button>`)}</div>` : ''}
    <div id="ws-host"></div>`;
  const pick = root.querySelector('#ws-pick');
  if (pick) pick.onclick = (e) => { const b = e.target.closest('[data-ws]'); if (b) location.hash = `#/settings/workspace?tool=${b.dataset.ws}`; };
  const mod = await import('./tool.js');
  inner = mod;
  await mod.mount(root.querySelector('#ws-host'), { id: t.id, embed: true });
}

export function unmount() { inner?.unmount?.(); inner = null; }
