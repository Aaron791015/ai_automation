// 任務啟動器：一排按鈕 → 填幾個欄位 → 開一個帶 skill 與提示的 Claude session。
//
// 為什麼要有這一層：平台做得了「聚合與觸發」，做不了「創作」——
// 探索、設計、判斷、寫報告需要判斷力，那是 session 在做的事。
// 這排按鈕就是兩者的接點：平台帶好上下文，把判斷交給 session。
//
// ⚠️ 只加元件，不重排既有版面（ROADMAP §5 視覺凍結）。
import { api } from '../api.js';
import { html, raw } from './el.js';
import { modal } from './modal.js';
import { toast } from './toast.js';
import { renderForm, readValues, validate } from './form.js';
import { runPrestep } from './taskprestep.js';
import { navigate } from '../router.js';

let cache = null;
let claudeCache = null;

/** 模型清單與預設值 —— 與對話面板的「新對話」同一個來源（`/api/settings/claude`）。
 *  ⚠️ 取不到時退回單一預設就好，**不要擋住任務** —— 選模型是加分項，
 *     而任務本身在 default_model 下本來就跑得動。 */
async function loadClaude() {
  if (claudeCache) return claudeCache;
  try { claudeCache = await api.get('/api/settings/claude'); }
  catch (e) { claudeCache = {}; }
  return claudeCache;
}

/** 任務框裡的「執行設定」區塊：目前只有模型。
 *
 * ⚠️ 刻意擺在**任務欄位之外**：模型不是任務參數 —— 它不進 `prompt_template`。
 *    混進 `fields` 會被 `readValues()` 收進 `values`，跟著送給 session 當成填答內容。
 */
function modelBlock(claude, task) {
  let models = (claude.models || []).slice();
  if (!models.length) models = [{ value: 'sonnet', label: 'Sonnet' }];
  // 預設：任務自己宣告的 > 平台設定的 default_model > sonnet
  const def = task.model || claude.default_model || 'sonnet';
  // ⚠️ 預設值不在清單裡時要補進去，否則下拉會顯示成清單第一個 ——
  //    畫面上看起來是「選了別的模型」，而人不會發現。
  if (!models.some((m) => m.value === def)) models.unshift({ value: def, label: def });
  const el = document.createElement('fieldset');
  el.className = 'section';
  el.innerHTML = String(html`<legend>執行設定</legend>
    <div class="settings-grid">
      <div class="field select" data-field="__model">
        <label>模型</label>
        <select data-model>${models.map((m) => html`<option value="${m.value}" ${m.value === def ? raw('selected') : ''}>${m.label}</option>`)}</select>
        <span class="tiny muted">⚠ 模型在 session 建立時決定，中途不能切 —— 要換就重開一次任務。</span>
      </div>
    </div>`);
  return el;
}

async function loadTasks() {
  if (cache) return cache;
  try { cache = await api.get('/api/tasks'); } catch (e) { cache = { tasks: [], available: false, unavailable_reason: e.message }; }
  return cache;
}

// entry：'overview' | 'product' | 'run'
export async function renderTaskBar(container, { entry = 'overview', product = null, ctx = {} } = {}) {
  const d = await loadTasks();
  const items = (d.tasks || []).filter((t) => (t.entry || []).includes(entry));
  if (!items.length) { container.innerHTML = ''; return; }

  // claude.exe 不在時停用按鈕並說明原因 —— 不要讓人按下去才失敗
  const off = !d.available;
  container.innerHTML = html`<div class="task-bar">
    ${/* ⛔ 標題已移除（2026-08-24 使用者：「此文字沒有任何意義」）——
           下面就是一排寫著「探索新功能」「撰寫案例」的按鈕，
           再加一句「開始一件事」只是把「這裡是按鈕」重講一次。
           ⚠️ 但 off 時那顆提示要留：它解釋了**為什麼按鈕是灰的**。 */''}
    ${off ? html`<div class="task-bar-head">
      <span class="pill tone-warn" title="${d.unavailable_reason || ''}">對話未就緒</span>
    </div>` : ''}
    <div class="task-btns">${items.map((t) => html`<button class="btn task-btn${off ? ' is-off' : ''}"
        data-task="${t.id}" ${off ? 'disabled' : ''} title="${t.subtitle || ''}">
        <span class="ic">${t.icon || '•'}</span><span class="lb">${t.label}</span>
      </button>`)}</div>
    ${off ? html`<div class="tiny muted">${d.unavailable_reason || ''}</div>` : ''}
  </div>`;

  container.onclick = async (e) => {
    const b = e.target.closest('[data-task]');
    if (!b || off) return;
    // ⭐ **按下去要立刻有反應**（2026-08-27 使用者回報「會以為沒點到」）。
    //    ⚠️ 實測開窗只要 ~54ms —— 問題不是慢，是**完全沒有回饋**：
    //    按鈕沒有按下狀態、視窗也沒有進場動畫，眼睛盯著按鈕就什麼都看不到，
    //    於是會再按一次。所以修的是「回饋」而不是「速度」。
    //    ⛔ 也要擋重複點擊：連按兩下會開兩個任務框疊在一起。
    if (b.classList.contains('is-busy')) return;
    b.classList.add('is-busy');
    try { await openTask(b.dataset.task, { product, ctx }); }
    finally { b.classList.remove('is-busy'); }
  };
}

// 讓別的頁面也能開任務框（帶入預填的欄位值）。
// ⛔ 只是換一個入口 —— 表單、驗證、送出一律沿用同一條路。
export function openTaskWith(taskId, { product = null, ctx = {} } = {}) {
  return openTask(taskId, { product, ctx });
}

async function openTask(taskId, { product, ctx }) {
  let task;
  try { task = (await api.get(`/api/tasks/${taskId}`)).task; }
  catch (e) { toast('讀取任務失敗：' + e.message, 'danger'); return; }

  // ★ 兩段式：任務宣告了 `prestep` 就先開挑選框（2026-08-27）。
  //    ⛔ 取消時要**整個中止** —— 回 null 就 return，不可以接著開設定框。
  let pre = {};
  if (task.prestep) {
    const got = await runPrestep(task, { product });
    if (got === null) return;
    pre = got;
  }

  // 第一段挑過的欄位不再出現在設定框裡 —— 留著等於同一件事問兩次，
  // 而且第二個控件是空的（值已經進了目標欄位），看起來像「剛才選的沒生效」。
  const fields = (task.fields || []).filter((f) => !(task.prestep && f.key === task.prestep.field));
  const body = document.createElement('div');
  // 帶入呼叫端已知的值（產品頁帶產品、run 結果頁帶 run_id 與 nodeid）
  const initial = { ...(ctx || {}), ...pre };
  if (product && !initial.product) initial.product = product;
  // 重用既有的動態表單引擎 —— 任務欄位的格式與 registry 的 params.fields 相同，
  // 所以不必為任務另寫一套渲染（第②層擴充的精神）。
  renderForm(body, { id: 'tasks' }, { id: taskId, params: { fields } }, initial);
  const exec = modelBlock(await loadClaude(), task);
  body.appendChild(exec);

  modal.open({
    title: `${task.icon || ''} ${task.label}`,
    body,
    actions: [
      { label: '取消' },
      {
        label: '開始', cls: 'primary',
        onClick: async () => {
          const values = readValues(body, fields);
          // ⚠️ `validate` 回的是 **{欄位key: 訊息} 物件**，不是陣列 ——
          //    寫成 `errs.length` 會永遠是 undefined，等於沒驗證。
          const errs = validate(fields, values);
          const bad = Object.keys(errs || {});
          if (bad.length) {
            const f = fields.find((x) => x.key === bad[0]);
            toast(`${f ? f.label : bad[0]}：${errs[bad[0]]}`, 'warn');
            return false;
          }
          let r;
          const model = exec.querySelector('[data-model]')?.value || undefined;
          try { r = await api.post(`/api/tasks/${taskId}/launch`, { values, model }); }
          catch (e) { toast(e.message, 'danger'); return false; }
          // 導到對話並自動送出第一則提示 —— 使用者仍看得到串流過程
          navigate(`/sessions?session=${r.session.id}&send=${encodeURIComponent(r.prompt)}`);
          return true;
        },
      },
    ],
  });
}
