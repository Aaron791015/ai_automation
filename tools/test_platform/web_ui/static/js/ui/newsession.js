// 「＋ 新對話」對話框 —— **對話面板（dock）與 `#/sessions` 頁共用這一份**。
//
// ⚠️ 2026-08-27 抽出來的原因：`views/sessions.js` 的「＋ 新對話」原本是
//    `api.post('/api/sessions', { title: '' })` 一行 —— **不問標題、不問模型、不帶上下文**，
//    直接吃 `platform_config.json` 的 `default_model`。
//    而對話面板那顆同名按鈕會開一個有模型下拉的 modal。
//    同一個名字的按鈕在兩個地方做不同的事，且**沒有任何一側能看出另一側缺了什麼** ——
//    使用者從 `#/sessions` 進來就永遠選不到 Opus，只能先建再分叉。
//
// ⭐ 模型**只在建立時決定**（`sessions.py` 的 meta 寫死 `model`，之後每一輪都拿它去
//    `claude_ask`）—— 所以這個對話框是唯一的選擇點，中途換模型＝開新 session 或分叉。
import { api } from '../api.js';
import { $, html, raw } from './el.js';
import { modal } from './modal.js';
import { state } from '../store.js';

//: `/api/settings/claude` 的模型清單。整個分頁存活期間只問一次。
//  ⭐ 清單本身是**後端寫死的**（`web_ui/api/settings.py` 的 `models=`），不會在執行期改，
//     所以不需要失效機制。⛔ 先前寫了一支 `resetClaudeCache()` 匯出、**沒有任何人呼叫**
//     —— 那就是本次 review 自己在測試裡釘過的「假宣告」，已拿掉。
let _claude = null;
async function claudeSettings() {
  if (_claude) return _claude;
  try { _claude = await api.get('/api/settings/claude'); } catch (e) { _claude = {}; }
  return _claude;
}

//: 後端拿不到時的墊底 —— ⛔ 只是不要讓下拉變空的，**不是**清單的來源
//   （來源是 `web_ui/api/settings.py` 的 `models=`）。
const FALLBACK = [{ value: 'sonnet', label: 'Sonnet' }, { value: 'opus', label: 'Opus' }];

/** 目前畫面的上下文（勾了「帶入」才會送）。與原本對話面板的組法一致。 */
export function currentContext() {
  return {
    selection_count: state.selection ? state.selection.size : 0,
    hash: location.hash,
    active_runs: (state.active || []).map((r) => r.run_id),
  };
}

/**
 * 開「新對話」對話框並建立 session。
 *
 * @param {object|null} context 預設帶入的上下文；不給就用 `currentContext()`
 * @returns {Promise<object|null>} 建好的 session（取消回 `null`）
 */
export async function newSessionDialog({ context = null } = {}) {
  const c = await claudeSettings();
  const models = (c && c.models && c.models.length) ? c.models : FALLBACK;
  const def = (c && c.default_model) || 'sonnet';
  // ⛔ 排掉沒有 skill 的（`common` 是虛擬產品）—— 選了也載不了東西，只是多一個會選錯的選項
  const prods = (state.products || []).filter((p) => p.skill && !p.virtual);
  const body = document.createElement('div');
  body.innerHTML = html`<div class="field"><label>標題（可留空自動取）</label><input id="ns-title" type="text" placeholder="例：ZS 階段失敗分析"></div>
    <div class="field" style="margin-top:8px"><label>模型</label><select id="ns-model">${models.map((m) => html`<option value="${m.value}" ${m.value === def ? raw('selected') : ''}>${m.label}</option>`)}</select><span class="tiny muted">⚠ 模型在 session 建立時決定，中途不能切；要換模型＝開新 session 或分叉。</span></div>
    <div class="field" style="margin-top:8px"><label>產品（選填）</label><select id="ns-prod"><option value="">不指定 —— 乾淨 session</option>${prods.map((p) => html`<option value="${p.id}">${p.label}</option>`)}</select><span class="tiny muted">選了才會載入該產品的 skill（意圖對照表、必記不變量）；⛔ 不選就只有 <code>CLAUDE.md</code> 與 memory，適合臨時問一件事。<br>⚠️ 一個 session 一個產品 —— 中途換產品建議另開一條。</span></div>
    <div class="field boolean" style="margin-top:8px"><label><input type="checkbox" id="ns-ctx" checked> 帶入目前上下文（選取的案例、正在看的 run）</label></div>`;
  return new Promise((res) => {
    let done = false;
    modal.open({
      title: '新對話',
      body,
      actions: [{ label: '取消' }, {
        label: '建立', cls: 'primary', onClick: async (b) => {
          const d = await api.post('/api/sessions', {
            title: $('#ns-title', b).value.trim(),
            model: $('#ns-model', b).value,
            context: $('#ns-ctx', b).checked ? (context || currentContext()) : null,
            // ⭐ 選填：有選才會在前言叫它載入該產品 skill（見 `chat.py::_chat_preamble`）
            product: $('#ns-prod', b).value || null,
          });
          done = true;
          res(d.session);
        },
      }],
      // ⚠️ 取消／Esc／點背景都走這裡 —— 不回 `null` 的話呼叫端會永遠 await 下去
      onClose: () => { if (!done) res(null); },
    });
  });
}
