// #/settings/<tab> 設定中樞：Claude／憑證／工作區／設定檔 四個分頁
//
// 為什麼要有這一層（2026-08-24 使用者裁示）：
//   「設定相關的操作應放在設定頁面，而非在工具頁面出現工作區設定功能」
//
// 先前「工作區設定」是一支 `scope: workspace` 的工具（`#/tool/setup`），
// 於是它跟壓測、UI 測試並排在 #/tools 的看板上 —— 但那一欄做的是
// **接產品、裝 memory、匯出範本**，跟「挑一支工具跑一輪」不是同一件事。
// 現在它是設定的一個分頁；`#/tool/setup` 會轉址過來（見 views/tool.js）。
//
// ⚠️ 分頁內容各自是一支 view 模組，且**只畫內容不畫頁殼** —— 頁殼在這裡統一畫，
//    否則四份內容各畫一次 `.page-head` 會疊出兩層標題。
import { $, $$, html } from '../ui/el.js';
import { state } from '../store.js';
import { pageLoading } from '../ui/loading.js';

const TABS = [
  { id: 'claude', label: 'Claude', crumb: 'Claude 上線檢查（唯讀、零額度）',
    load: () => import('./settings_claude.js') },
  { id: 'credentials', label: 'JIRA 憑證', crumb: 'JIRA 帳密與 Session Cookie —— 只寫不讀，永不回傳瀏覽器',
    load: () => import('./credentials.js') },
  { id: 'workspace', label: '工作區', crumb: '接產品／裝 memory／體檢／匯出範本 —— 底下是腳本，介面只是觸發器',
    load: () => import('./settings_workspace.js') },
  { id: 'files', label: '設定檔', crumb: '直接開檔編輯再存回（寫入前驗證 ＋ 自動備份）',
    load: () => import('./configfiles.js') },
];

let curTab = null, curMod = null;

export async function mount(root, params) {
  const tab = TABS.find((t) => t.id === (params?.tab || 'claude')) || TABS[0];
  curTab = tab.id;
  root.innerHTML = html`<div class="page">
    <div class="page-head"><h2>設定</h2><span class="crumb" id="set-crumb">${tab.crumb}</span></div>
    <div class="tabs" id="set-tabs">${TABS.map((t) => html`<button class="tab-btn ${t.id === tab.id ? 'active' : ''}" data-tab="${t.id}">${t.label}</button>`)}</div>
    <div class="page-body" id="set-body">${pageLoading("載入中…")}</div>
  </div>`;
  // 分頁切換走 hash（可以直接貼網址、上一頁也回得去）
  $('#set-tabs', root).onclick = (e) => {
    const b = e.target.closest('[data-tab]');
    if (b && b.dataset.tab !== curTab) location.hash = `#/settings/${b.dataset.tab}`;
  };
  await show(root, tab);
}

async function show(root, tab) {
  const body = $('#set-body', root);
  let mod;
  try { mod = await tab.load(); }
  catch (e) { body.innerHTML = html`<div class="alert is-error">分頁載入失敗：${e.message}</div>`; return; }
  if (curTab !== tab.id) return;                 // 載入途中又被切走
  curMod?.unmount?.();
  curMod = mod;
  body.innerHTML = '';
  try { await mod.mount(body, { state }); }
  catch (e) { body.innerHTML = html`<div class="alert is-error">${e.message}</div>`; }
  $$('#set-tabs .tab-btn', root).forEach((x) => x.classList.toggle('active', x.dataset.tab === tab.id));
  const c = $('#set-crumb', root); if (c) c.textContent = tab.crumb;
}

export function unmount() { curMod?.unmount?.(); curMod = null; curTab = null; }
