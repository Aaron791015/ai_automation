// 載入指示：全站共用。
//
// ⭐ 2026-08-24 使用者回報：「各個不同頁面切換後，若目標頁面內容還未出現時，無載入中動畫」。
//    實測換頁後的空窗（本機、平台已暖機）：
//      #/settings/claude   靜止文字 4,414ms（它真的要跑 claude --version / auth status / doctor）
//      #/tool/ui_tests     全空白 198ms ＋ 靜止文字 1,976ms
//      #/product/crux      靜止文字 292ms  ／  #/cases 靜止文字 248ms
//      #/tools、#/registry 全空白 —— 連「載入中」三個字都沒有
//
// ⚠️ 所以症狀是兩種，修法也不同：
//    ① **有字但不會動** —— 「靜止的文字看起來像卡死」。這個結論 `chatpanel.js` 已經下過一次
//       （2026-08-24「對話視窗載入中需增加載入動畫」），但那支 spinner() 只服務對話面板，
//       其餘十處仍是靜止文字。→ 本檔把它升級成全站共用元件。
//    ② **連字都沒有** —— view 在 `await` 拿到資料「之後」才第一次 innerHTML，
//       而 router 早在那之前就把上一頁收掉了。→ view 先畫殼（見各 view）＋ router 補網（見 router.js）。
import { html } from './el.js';

/** 三顆依序跳動的點 ＋ 一行說明。回傳 SafeString，可直接放進 html`` 插值。
 *
 * ⚠️ `label` 要講**它正在做什麼**，不要只寫「載入中」——
 *    等 4 秒的時候，「檢查 Claude 連線中」與「載入中」對人的意義差很多。
 */
export function spinner(label) {
  return html`<div class="loading-dots"><span class="dots"><i></i><i></i><i></i></span><span class="lb">${label || ''}</span></div>`;
}

/** 整塊頁面內容的載入態：置中、撐開，讓版面不會在內容進來時整個跳一下。 */
export function pageLoading(label) {
  return html`<div class="loading-block">${spinner(label || '載入中…')}</div>`;
}
