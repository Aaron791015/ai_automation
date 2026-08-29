// 總覽主視覺下方的對話入口（2026-08-24 使用者裁示）
//
// > 「總覽主視覺下方的星塵光點，替換成對話視窗的入口，圖示由你設計，
// >   其他頁面維持在右下角與左下角即可」
//
// 先前那個位置是一顆會呼吸的青色圓點（全域 dock 鈕浮在主視覺腳下）——
// 它跟背景那三千顆星塵長得一樣，**看不出是入口**，更看不出按了會發生什麼。
//
// 這一支把它換成一條有字的通訊埠：圖示（六角埠 ＋ 對話泡）＋「與 Claude 對話」＋
// 一行說明目前狀態（線上與否、有幾條進行中的 session）。
// ⚠️ 總覽出現這個入口時，右下角那顆會自動隱藏（`body.is-overview`，見 hud.css）——
//    同一個畫面擺兩個一模一樣的入口只是雜訊。
import { api } from '../api.js';
import { html, raw } from './el.js';
import { portalGlyph, open as openDock, isOnline, onlineReady } from './dock.js';

// ⚠️ `html`` ` 會把插值**轉義** —— SVG 一定要走 `raw()`，
//    否則整段 `<svg …>` 標籤會原樣印在畫面上（2026-08-24 實測踩到）。

export async function renderChatPortal(container) {
  if (!container) return;
  const draw = (sub, off) => {
    container.innerHTML = html`<button class="chat-portal${off ? ' is-off' : ''}" id="cp-btn"
        title="${off ? 'Claude 未連線 —— 點擊查看設定' : '開啟對話視窗'}">
      <span class="ic">${raw(portalGlyph(30))}</span>
      <span class="tx"><b>與 Claude 對話</b><small>${sub}</small></span>
      <span class="go">↗</span>
    </button>`;
    container.querySelector('#cp-btn').onclick = () => {
      if (off) { location.hash = '#/settings/claude'; return; }
      openDock();
    };
  };
  draw('連線中…', false);
  // ⛔ 一定要等 `onlineReady` —— 探測還沒回來時 `isOnline()` 恆為 false，
  //    畫出來就是「未連線」，但 rail 上明明寫著 ONLINE（兩個地方講相反的話）。
  await onlineReady.catch(() => {});
  let n = 0;
  const off = !isOnline();
  try {
    const d = await api.get('/api/sessions');
    // ⛔ 用 `active_count`，**不要用 `d.active.length`** —— 那是給列表用的清單，
    //    一旦被截斷（先前是 `[:10]`）數字就會卡在上限（實際 14 條卻顯示 10）。
    n = d.active_count ?? (d.active || []).length;
  } catch (e) { /* 拿不到就只是不顯示條數 */ }
  draw(off ? '未連線 —— 點我到設定頁看怎麼上線'
    : (n ? `${n} 條進行中 · 問索引、起任務、重跑失敗案例` : '問索引、起任務、重跑失敗案例'), off);
}
