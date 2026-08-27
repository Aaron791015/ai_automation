// hash 路由：#/、#/tools、#/tool/<id>、#/product/<id>、#/cases、#/run/<id>、#/reports、#/registry、#/settings/claude、#/sessions
//
// ★ 每個 view 畫在自己的 `.view-pane` 容器裡，而不是共用 `#view`。
//   這是為了讓**重的頁面可以留在文件裡**（view 宣告 `keepAlive = true`）：
//   切走時只加 `.pane-off`（`content-visibility: hidden`），切回來時拿掉。
//
//   為什麼要這樣做（2026-08-20 使用者：「畫面切換會有不夠滑順的體感」）——
//   總覽主視覺是 5,347 個 SVG 節點，實測「讓它重新出現」的成本差距很大：
//     重建 DOM 86ms ／ 搬回既有節點 58ms ／ display:none→顯示 38ms ／
//     visibility 27ms ／ **content-visibility: hidden→visible 8–12ms**
//   `content-visibility: hidden` 會保留算好的排版狀態，所以恢復幾乎不用重排 ——
//   這是唯一能把換頁壓進一格 16ms 預算的做法。
//   ⚠️ 換成 display:none 或直接重建都會讓這個體感問題回來，改動前先重量一次。
import { $$ } from './ui/el.js';
import { closeAllModals } from './ui/modal.js';
import { close as closeDock, isOpen as dockIsOpen } from './ui/dock.js';
import { pageLoading } from './ui/loading.js';
//: 換頁後多久還沒畫出任何東西，才補上載入指示。
//  ⚠️ 太短會「閃一下就不見」，那比沒有更糟 —— 實測各頁畫殼都在 20ms 內，
//     慢的是後面的資料；240ms 才是人開始覺得「是不是沒反應」的區間。
const PENDING_AFTER_MS = 240;

/** 安全網：view 遲遲沒畫出東西時，補一個會動的載入指示。
 *
 * ⛔ 這是**補網，不是正解** —— 正解是 view 自己先畫殼（各 view 的「先畫殼」註解）。
 *    留著它的理由是這個平台反覆出現的那一類缺陷：**宣告存在、效果不存在**。
 *    以後新增的 view 若忘了先畫殼，至少不會是一片空白到底。
 */
function watchPending(el) {
  let node = null;
  const t = setTimeout(() => {
    if (el.childElementCount) return;      // view 已經自己畫了殼 → 不插手
    node = document.createElement('div');
    node.className = 'view-pending';
    node.innerHTML = String(pageLoading('載入中…'));
    el.appendChild(node);
  }, PENDING_AFTER_MS);
  // ⚠️ 一定要回傳收尾函式並在 finally 呼叫：mount 丟例外時也得把指示收掉，
  //    否則畫面會永遠停在「載入中」，而真正的錯誤訊息被蓋住。
  return () => { clearTimeout(t); if (node) node.remove(); };
}

const routes = [];
const panes = new Map();          // path → { el, view }，只放 keepAlive 的頁
let current = null, currentPane = null;

export function route(pattern, view) {
  routes.push({ re: new RegExp('^' + pattern.replace(/:(\w+)/g, '(?<$1>[^/]+)') + '/?$'), view });
}
export function navigate(hash) { location.hash = hash.startsWith('#') ? hash : '#' + hash; }
export function currentHash() { return (location.hash.replace(/^#/, '') || '/').split('?')[0]; }

function newPane(root) {
  const el = document.createElement('div');
  el.className = 'view-pane';
  root.appendChild(el);
  return el;
}

/** 進場轉場：先掛 class、等 view 插入內容時動畫才起跑（CSS 動畫是在元素**開始符合選擇器**時啟動）。
 *  remove → 讀 offsetWidth → add 是重啟動畫的標準做法；少了中間那行，連續換頁時 class 沒變化就不會重跑。 */
function playEnter(root) {
  root.classList.remove('view-enter');
  void root.offsetWidth;
  root.classList.add('view-enter');
}

function setRailActive(path) {
  $$('.rail a.nav').forEach((a) => {
    const href = (a.getAttribute('href') || '').replace(/^#/, '');
    const pre = a.dataset.prefix;
    // ⚠️ 一定要轉成 boolean：沒有 data-prefix 時 `pre && …` 會是 undefined，
    // 而 classList.toggle(cls, undefined) 等同「沒給第二參數」→ 變成每次切換（會誤亮）。
    a.classList.toggle('active', !!(href === path || (pre && path.startsWith(pre))));
  });
}

/** 收起目前這一頁：keepAlive 的只暫停並隱藏，其餘照舊拆掉。 */
function leave() {
  if (!currentPane) { current = null; return; }
  const { el, view } = currentPane;
  try {
    if (view.keepAlive) { view.pause?.(); el.classList.add('pane-off'); }
    else { view.unmount?.(); el.remove(); }
  } catch (e) { /* 收尾失敗不能擋住換頁 */ }
  current = null; currentPane = null;
}

export async function dispatch(root) {
  const path = currentHash();
  // ⛔ 換頁前先關掉所有 modal —— 它掛在 <body> 上，換頁只重建 `#view` 動不到它。
  //    不關的話：在產品頁點開一張 Bug 單、切到案例頁，那張單還浮在新頁面上
  //    （2026-08-24 拍手冊截圖時撞到）。
  closeAllModals();
  // ⛔ 對話視窗也一樣要關 —— 它跟 modal 同樣掛在 <body> 上，換頁動不到它。
  //    使用者回報：在對話視窗裡按「全部」，畫面已經跳到 #/sessions，
  //    但那個置中大視窗還蓋在上面（2026-08-24）。
  //    ⚠️ 判斷「本來就開著」再關 —— 直接呼叫 close() 會讓浮層計數扣成負的。
  if (dockIsOpen()) closeDock();
  for (const r of routes) {
    const m = path.match(r.re);
    if (!m) continue;
    leave();
    setRailActive(path);
    window.scrollTo(0, 0);

    const keep = !!r.view.keepAlive;
    const cached = keep ? panes.get(path) : null;
    const pane = cached || { el: newPane(root), view: r.view };
    if (keep && !cached) panes.set(path, pane);
    pane.el.dataset.route = path;      // 給 CSS 用：個別頁可以覆寫轉場（見 base.css 的總覽例外）
    pane.el.classList.remove('pane-off');
    current = r.view; currentPane = pane;
    playEnter(root);
    // 快取命中走 resume（不重建 DOM）；沒有 resume 的頁就退回 mount，行為與過去一致
    const settle = watchPending(pane.el);
    try {
      if (cached && r.view.resume) await r.view.resume(m.groups || {});
      else await r.view.mount(pane.el, m.groups || {});
    } finally { settle(); }
    return;
  }
  leave();
  const pane = { el: newPane(root), view: {} };
  currentPane = pane;
  pane.el.innerHTML = '<div class="empty">找不到頁面：' + path + '</div>';
}

export function start(root) { window.addEventListener('hashchange', () => dispatch(root)); return dispatch(root); }
