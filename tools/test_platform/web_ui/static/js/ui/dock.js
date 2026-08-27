// 全域對話入口：右下角按鈕 → **畫面置中的大視窗**（重用 chatpanel.js，所有頁面可用）
//
// 2026-08-24 使用者裁示的兩件事：
//   ① 「總覽主視覺下方的星塵光點，替換成對話視窗的入口，圖示由你設計；
//       其他頁面維持在右下角與左下角即可」
//      → 入口圖示改為**通訊埠**（六角框 ＋ 對話泡 ＋ 三顆訊號點，見 `portalGlyph()`）；
//        右下角按鈕與左下角 rail 燈都是同一個入口。
//        總覽另有一個**主視覺下方的大入口**（見 `ui/chatportal.js`），
//        那一頁的右下角按鈕會自動隱藏 —— 同一頁擺兩個一樣的入口只是雜訊。
//   ② 「對話視窗需放大並且於畫面置中顯示」
//      → 從「貼右下角的 400×560 小面板」改成**置中的 min(1080px, 92vw) 大視窗**＋遮罩。
//        小面板連一張判定表都放不下，而 session 交回來的幾乎都是 markdown 表格。
//
// Esc 或點遮罩關閉；狀態同步 rail 底部的 CLAUDE 燈；面板只在第一次開啟時初始化（省一次 API）。
import { $, h, overlayOpened, overlayClosed } from './el.js';
import { api } from '../api.js';
import { state } from '../store.js';

let btn = null, panel = null, scrim = null, inited = false, online = false, shownSession = null;
// ⚠️ 上線狀態是**非同步**探測來的（`/api/settings/claude` 要跑 claude auth status）。
//    總覽的大入口與 rail 燈都要等它 —— 先前直接讀 `isOnline()`，
//    在探測回來之前恆為 false，於是明明 ONLINE 卻寫「未連線」（2026-08-24 實測）。
let onlineResolve = null;
export const onlineReady = new Promise((r) => { onlineResolve = r; });

/** 對話入口的圖示：六角通訊埠 ＋ 對話泡 ＋ 三顆訊號點。
 *
 * 為什麼是這個形狀：平台整套視覺是 HUD 線框（六角 ＝ 註冊表圖示、細線 ＋ 輝光），
 * 而先前那顆會呼吸的純圓點沒有任何語意 —— 使用者看到的就是「一顆星塵光點」，
 * 說不出它是對話入口。對話泡負責「這是講話的地方」，六角框負責「這是這套系統的東西」。
 */
export function portalGlyph(size = 26) {
  return `<svg class="portal-glyph" viewBox="0 0 32 32" width="${size}" height="${size}" aria-hidden="true">
    <path class="hex" d="M16 1.9 27.7 8.6v14.8L16 30.1 4.3 23.4V8.6z"/>
    <path class="bub" d="M9.4 10.6h13.2v8.6h-6.9l-4 3.4v-3.4H9.4z" rx="1"/>
    <circle class="sig" cx="13.1" cy="14.9" r="1.05"/>
    <circle class="sig s2" cx="16" cy="14.9" r="1.05"/>
    <circle class="sig s3" cx="18.9" cy="14.9" r="1.05"/>
  </svg>`;
}

export async function installDock() {
  // ⭐ 2026-08-24：**右下角的浮動按鈕已移除**（使用者要求）——
  //    它與 rail 底部的 CLAUDE 燈點下去做的是同一件事，卻是 `position: fixed`，
  //    永遠壓在頁面右下角的內容上（表格最後一列、底部工具列）。
  //    ⚠️ 總覽本來就沒有它（`body.is-overview .dock-btn` 早就 display:none），
  //       所以這個移除對總覽是零變化。
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && isOpen()) close(); });

  // rail 底部的 CLAUDE 燈＝現在**唯一**的常駐入口（總覽另有主視覺腳下的大入口）
  btn = $('#ai-status');
  if (btn) {
    btn.addEventListener('click', toggle);
    btn.setAttribute('role', 'button');
    btn.setAttribute('tabindex', '0');
    btn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  }

  try {
    const d = await api.get('/api/settings/claude');
    online = !!d.ok;
  } catch (e) { online = false; }
  setOnline(online);
  onlineResolve(online);
}

/** 上線狀態同步到三處：右下按鈕、左下 rail 燈、總覽的大入口。 */
export function setOnline(ok) {
  online = !!ok;
  if (btn) btn.title = online ? '與 Claude 對話（點擊開啟）' : 'Claude 未連線 —— 點擊查看設定';
  const st = $('#ai-st');
  if (st) { st.textContent = online ? 'ONLINE' : 'OFFLINE'; $('#ai-status').classList.toggle('off', !online); }
}
export function isOnline() { return online; }

export function toggle() { isOpen() ? close() : open(); }

export async function open() {
  if (!panel) {
    scrim = h('div', { class: 'dock-scrim' });
    scrim.addEventListener('click', close);
    panel = h('div', { class: 'dock-panel', role: 'dialog', 'aria-label': 'Claude 對話' });
    panel.innerHTML = `<h3>${portalGlyph(18)}<span>與 Claude 對話</span><span class="cnt" id="dock-tag"></span><span class="x" title="關閉（Esc）">✕</span></h3>
      <div id="dock-body" style="flex:1;min-height:0;display:flex;flex-direction:column"></div>`;
    panel.querySelector('.x').addEventListener('click', close);
    document.body.append(scrim, panel);
  }
  const wasOpen = isOpen();
  scrim.classList.remove('hidden');
  panel.classList.remove('hidden');
  document.body.classList.add('dock-open');
  if (!wasOpen) overlayOpened();
  btn?.querySelector('.unread')?.remove();
  btn?.classList.remove('has-unread');
  // 面板只在「首次開啟」或「別處換過 session」時重畫 ——
  // 否則在 #/sessions 按了「開啟／續接」再回來，會停在舊的那條對話。
  if (!inited || shownSession !== state.session) {
    inited = true;
    const { renderChatPanel } = await import('./chatpanel.js');
    const host = $('#dock-body', panel);
    // chatpanel 會自建 <h3> ＋ .chat；這裡把它的 h3 隱藏，用視窗自己的標題
    await renderChatPanel(host, { context: { hash: location.hash } });
    const inner = host.querySelector('h3');
    if (inner) { $('#dock-tag', panel).innerHTML = inner.innerHTML.replace(/^Claude 對話\s*/, ''); inner.remove(); }
    shownSession = state.session;
  }
  setTimeout(() => $('#ch-in', panel)?.focus(), 60);
}

export function close() {
  const wasOpen = isOpen();
  panel && panel.classList.add('hidden');
  scrim && scrim.classList.add('hidden');
  document.body.classList.remove('dock-open');
  if (wasOpen) overlayClosed();
}
export function isOpen() { return !!panel && !panel.classList.contains('hidden'); }
export function markUnread() {
  if (!btn || isOpen()) return;
  if (!btn.querySelector('.unread')) btn.append(h('span', { class: 'unread' }));
  btn.classList.add('has-unread');       // ⭐ 未讀時整顆燈轉琥珀並加快呼吸
}
