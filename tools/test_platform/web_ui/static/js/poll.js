// 單一輪詢器：每 N 秒打一次 `/api/runs/active` ＋ `/api/sessions/active`；
// document.hidden 時暫停；沒有東西在跑就降頻到 10s
// （仍要抓「剛結束保留 15 分鐘」的變化）。
//
// ⭐ 2026-08-24 加上 session：使用者「平台啟 session 執行任務，尚無法追蹤執行狀態」。
//    run 與 session 對使用者是同一件事 —— **我按下去的東西現在怎麼樣了** ——
//    所以同一個輪詢器抓、同一張卡顯示。
// ⚠️ 兩支端點各自 try，其中一支掛掉不可以讓另一支也不更新。
import { api } from './api.js';
import { set, state } from './store.js';
let timer = null;
// ⭐ 連續失敗才判離線（2026-08-24 走查盲點 ⑦）——
//    先前兩支端點各自靜默吞掉例外，平台掛掉時畫面停在最後一次的資料、
//    一切看起來正常，人只會覺得「怎麼都不更新」。
//    ⚠️ 一次失敗不報：平台重啟只要兩三秒，每次都跳警告反而變成雜訊。
let failStreak = 0;
const OFFLINE_AFTER = 2;

export async function tick() {
  if (document.hidden) { schedule(); return; }
  let anyOk = false;
  try {
    const d = await api.active();
    set({ active: d.runs || [], serverTime: d.server_time });
    anyOk = true;
  } catch (e) { /* 輪詢失敗不打斷畫面 */ }
  try {
    const s = await api.get('/api/sessions/active');
    set({ sessionRunning: s.running || [], sessionReview: s.review || [] });
    anyOk = true;
  } catch (e) { /* 同上 */ }

  if (anyOk) {
    if (failStreak >= OFFLINE_AFTER) markOnline();
    failStreak = 0;
  } else if (++failStreak === OFFLINE_AFTER) {
    markOffline();
  }
  schedule();
}

/** header 亮紅點 ＋ 整條變暗 —— 讓人一眼看出畫面上的數字是舊的。 */
function markOffline() {
  document.body.classList.add('is-offline');
  const ws = document.querySelector('#ws-badge');
  if (ws && !ws.dataset.prev) {
    ws.dataset.prev = ws.textContent;
    ws.textContent = '平台已斷線 —— 畫面上的資料是舊的';
    ws.title = '連不上 http://127.0.0.1:5300 —— 服務可能已關閉。重新啟動後會自動連回。';
  }
}

function markOnline() {
  document.body.classList.remove('is-offline');
  const ws = document.querySelector('#ws-badge');
  if (ws && ws.dataset.prev) {
    ws.textContent = ws.dataset.prev;
    delete ws.dataset.prev;
    ws.title = '';
  }
  // ⭐ 連回來要講 —— 人才知道剛才那段時間看到的是舊畫面
  import('./ui/toast.js').then(({ toast }) => toast('已重新連上平台', 'success'));
}
function schedule() {
  clearTimeout(timer);
  const live = (state.active || []).some((r) => !['completed', 'failed', 'stopped'].includes(r.phase))
    || (state.sessionRunning || []).length > 0;
  const base = (state.boot?.poll_seconds || 2) * 1000;
  // ⚠️ 離線時降頻到 5 秒 —— 對著關掉的服務每 2 秒打一次只是徒增 console 噪音
  const wait = failStreak >= OFFLINE_AFTER ? 5000 : (live ? base : 10000);
  timer = setTimeout(tick, wait);
}
export function start() {
  tick();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) kick(); });
}
export function kick() { clearTimeout(timer); tick(); }
