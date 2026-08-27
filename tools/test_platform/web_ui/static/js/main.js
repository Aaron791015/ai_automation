// 啟動：fetch /api/bootstrap → store → router → poll → dock → 開機序列
import { api } from './api.js';
import { $, $$ } from './ui/el.js';
import { set, state, toggleMotion } from './store.js';
import { route, start as startRouter } from './router.js';
import { start as startPoll } from './poll.js';
import { installHotkey, openCmdbar } from './ui/cmdbar.js';
import { installDock } from './ui/dock.js';
import { toast } from './ui/toast.js';

import * as overview from './views/overview.js';
import * as tools from './views/tools.js';
import * as tool from './views/tool.js';
import * as product from './views/product.js';
import * as cases from './views/cases.js';
import * as run from './views/run.js';
import * as reports from './views/reports.js';
import * as registry from './views/registry.js';
import * as settings from './views/settings.js';
import * as sessions from './views/sessions.js';
import * as doc from './views/doc.js';

route('/', overview);
route('/tools', tools);
route('/tool/:id', tool);
route('/product/:id', product);
route('/cases', cases);
route('/run/:id', run);
route('/reports', reports);
route('/registry', registry);
// 設定是一個**分頁中樞**（Claude／JIRA 憑證／工作區／設定檔）——
// 2026-08-24 使用者裁示「設定相關的操作應放在設定頁面」。
route('/settings', settings);
route('/settings/:tab', settings);
route('/sessions', sessions);
// ⛔ 這一條先前**沒有註冊**，而總覽的空狀態引導就有一顆按鈕指過來
//    （`#/doc?path=README.md`）—— 新同事的第一個畫面上第一顆按鈕是壞的
//    （2026-08-24 走查）。整頁版與浮層版共用同一個 renderMarkdown。
route('/doc', doc);

async function boot() {
  document.documentElement.dataset.motion = state.motion ? '1' : '0';
  let b;
  try { b = await api.bootstrap(); }
  catch (e) { $('#view').innerHTML = `<div class="page"><div class="alert is-error">無法連到平台 API：${e.message}</div></div>`; finishBoot(); return; }
  set({ boot: b, tools: b.tools, products: b.products });
  window.__tp_selection = state.selection;

  const env = $('#env-badge');
  const envText = (b.products || []).map((p) => p.env_badge).find(Boolean);
  if (envText) env.textContent = envText; else env.classList.add('hidden');

  // ⭐ header 中間：工作區識別（2026-08-24 取代裝飾性的 "Situational Awareness"）。
  //    ⚠️ 範本情境下同事常同時開著原型與自己那一份，**兩個平台長得一模一樣** ——
  //       這一格要回答的是「我現在開的是哪一個工作區」。
  const ws = $('#ws-badge');
  if (ws) {
    // ⚠️ 要扣掉虛擬產品（`common`）—— 它是平台自己保證存在的一列，不是接上來的產品。
    //    不扣的話乾淨範本會顯示「1 個產品」，而同一畫面的空狀態寫「還沒有接任何產品」
    //    （2026-08-24 拍手冊截圖時抓到）。
    const n = (b.products || []).filter((p) => !p.virtual).length;
    ws.textContent = (b.workspace?.name || '工作區') + (n ? ` · ${n} 個產品` : ' · 尚未接產品');
    ws.title = b.workspace?.path || '';
  }

  if (b.registry_errors?.length) toast(`registry 有 ${b.registry_errors.length} 個錯誤，見「註冊表」頁`, 'warn', 6000);

  // ★ 首次使用：一個產品都沒有 → 直接落在初始化頁，不要讓人自己找
  //   （使用者 2026-08-23 要求：「避免同事還要找該怎麼進行初始化」）
  //   ⚠️ 只在「沒指定路由」時才轉 —— 別人貼 #/registry 的連結進來不該被搶走。
  //   ⚠️ 用 replace 不留歷史，否則按上一頁會被彈回來。
  const bare = !location.hash || location.hash === '#' || location.hash === '#/';
  if (bare && !(b.products || []).length) {
    location.replace('#/settings/workspace?first=1');
  }

  installHotkey();
  $('#btn-cmd').addEventListener('click', () => openCmdbar());
  $('#btn-motion').addEventListener('click', () => { toggleMotion(); toast(state.motion ? '動態效果：開' : '動態效果：關'); });
  clock();
  await startRouter($('#view'));
  startPoll();
  installDock();
  finishBoot();
}

function finishBoot() {
  const el = $('#boot');
  const seen = sessionStorage.getItem('tp.booted');
  // 開機序列全長 1.82s（見 css/base.css 的三幕說明），跑完再停約 0.78s 才進場
  // —— 讓成形的最後一格看得完整，而不是字剛顯影就被淡出（2026-08-20 使用者要求）。
  // ⚠️ 改動畫時間軸就要回頭改這個數字，且「全長」要算最晚結束的那一條動畫
  //    （delay + duration × iterations）。一個 session 只播一次（sessionStorage 記住）。
  const delay = seen || !state.motion ? 0 : 2600;
  setTimeout(() => { el.classList.add('done'); setTimeout(() => el.remove(), 400); sessionStorage.setItem('tp.booted', '1'); }, delay);
}

function clock() {
  const el = $('#clock');
  const tick = () => { el.textContent = new Date().toTimeString().slice(0, 8); };
  tick(); setInterval(tick, 1000);
}

boot();
