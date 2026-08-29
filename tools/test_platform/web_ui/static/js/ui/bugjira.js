// 回填 JIRA 單號 —— Bug 明細與「看全文」共用同一份。
//
// ⭐ 2026-08-27 從 `views/product.js` 抽出來：使用者要在**看全文頁**也能回填
//    （動線是「看完全文 → 貼進 JIRA → 回填單號」，先前得先關掉全文、
//    回到列表、再開一次明細才找得到那顆按鈕）。
//    ⛔ 抽出來而不是複製一份 —— 兩處的行為必須一致，尤其是「寫完要刷新畫面」
//    那一段（見下方註解，那是踩過的坑）。
//
// ⛔ 平台**不寫 JIRA**（`jira-verify` §0 的唯讀邊界）—— 開單請在 JIRA 網頁上做，
//    這裡只把單號記回本地單的 `reported` 欄。
import { api } from '../api.js';
import { esc } from './el.js';
import { modal } from './modal.js';
import { toast } from './toast.js';

/** 這張單需不需要回填（已經有 JIRA 單號就不必）。 */
export function needsJira(bug) {
  return !((bug && bug.jira) || []).length;
}

/**
 * 產生「回填 JIRA 單號」這顆 action。
 * @param {object} bug        至少要有 `id`；`product` 沒有時用 `productId` 補
 * @param {string} productId  呼叫端已知的產品（列表頁帶得出來）
 * @param {function} onChanged 寫完之後要重抓資料的回呼（**不可省**，見下方）
 */
export function jiraBackfillAction(bug, productId = '', onChanged = null) {
  return {
    label: '回填 JIRA 單號',
    onClick: async () => {
      const key = await modal.prompt('回填 JIRA 單號',
        `把 <b>${esc(bug.id)}</b> 在 JIRA 上的單號記回本地單的 <code>reported</code> 欄。<br>`
        + '⛔ 平台不會替你開 JIRA —— 開單請在 JIRA 網頁上做。',
        { placeholder: '例：CRUX-1042', okLabel: '回填' });
      if (!key) return false;
      try {
        const r = await api.post(`/api/bugs/${bug.id}/jira`,
          { jira_key: key.trim(), product: bug.product || productId });
        toast(`已回填 ${r.jira_key} → ${r.path}`, 'success', 6000);
        // ⛔ **寫完要把畫面刷新** —— 後端已經把單號寫進檔案、也清了索引快取，
        //    但前端不重抓的話「漏開單」那個數字**不會變**，看起來就像沒生效
        //    （2026-08-24 拍手冊截圖時實測：檔案已是 reported: CRUX-1099、
        //     後端算出 20，畫面卻還停在 21）。
        if (typeof onChanged === 'function') await onChanged();
        return true;              // 關掉視窗，讓人直接看到更新後的清單
      } catch (e) { toast(e.message, 'danger', 8000); }
      return false;
    },
  };
}
