// 任務的「第一段」：先挑好一個難挑的值，再進設定框（2026-08-27 使用者要求）。
//
// 為什麼要拆兩段：「驗 JIRA 修復」原本把**挑單**與**設定**塞在同一個框裡，
// 於是一個 4 列高的 multiselect 夾在必填的單號欄與安全邊界之間 ——
// 挑單需要「掃過幾十張、看狀態與摘要、挑三張」，那是這個任務**最花時間的一步**，
// 卻被擠成整個表單裡最小的控件。拆開之後：第一段整框都用來挑，第二段只剩三個設定。
//
// ⭐ 這一層是**宣告式**的：任務 json 寫 `prestep: {field: "mine"}` 就有，
//    不是為 verify_jira 寫死的分支。欄位怎麼取選項、選完要填到哪，
//    仍然沿用該欄位既有的 `options_from` 與 `appends_to`（form.js 那套）。
import { api } from '../api.js';
import { html, h, raw } from './el.js';
import { modal } from './modal.js';

// ⛔ 說明一律寫在模板**外面** —— `html` 是 tagged template，模板內一個反引號
//    就會提前結束整串字串，而 `node --check` 抓不到（2026-08-27 踩過兩次）。
//
// `st-done`/`st-prog`/`st-todo`：狀態只是**視覺分組**，不是篩選 ——
// 讓「In Progress 的那幾張」在幾十列裡一眼可辨（jira-verify §4：狀態用來解讀，不用來拒驗）。
function statusClass(s) {
  const t = String(s || '').toLowerCase();
  if (/progress|review|test/.test(t)) return 'st-prog';
  if (/resolved|done|closed|fixed/.test(t)) return 'st-done';
  return 'st-todo';
}

function rowHtml(o) {
  return html`<label class="jp-row" data-value="${o.value}">
    <input type="checkbox" value="${o.value}">
    <span class="jp-key mono">${o.key || o.value}</span>
    <span class="jp-st ${statusClass(o.status)}">${o.status || '—'}</span>
    <span class="jp-sum">${o.summary || o.label || ''}</span>
  </label>`;
}

/** 後端可能只給 `{value,label}`（舊格式）—— 從 label 拆回三欄，不要讓畫面掉成一坨。 */
function normalize(list) {
  return (list || []).map((o) => {
    if (o.status !== undefined || o.summary !== undefined) return o;
    const parts = String(o.label || '').split(' · ');
    return { ...o, key: parts[0] || o.value, status: parts[1] || '', summary: parts.slice(2).join(' · ') };
  });
}

/**
 * 跑任務的第一段。
 * @returns `{[dstKey]: 值, product}`；使用者取消時回 `null`（呼叫端要中止，不可以硬開第二段）。
 */
export function runPrestep(task, { product = null } = {}) {
  const pre = task.prestep || {};
  const fields = task.fields || [];
  const f = fields.find((x) => x.key === pre.field);
  if (!f) return Promise.resolve({});
  const dst = f.appends_to || pre.field;
  const prodField = fields.find((x) => x.key === (pre.product_field || 'product'));
  const url = (f.options_from || {}).url;

  const body = h('div', { class: 'jp' });
  body.innerHTML = html`
    ${prodField ? html`<div class="jp-top">
      <label class="jp-prod">產品
        <select data-prod>${(prodField.options || []).map((o) => html`<option value="${o.value}" ${String(o.value) === String(product || prodField.default || '') ? raw('selected') : ''}>${o.label}</option>`)}</select>
      </label>
      <input type="search" data-filter placeholder="輸入單號或關鍵字過濾…">
      <span class="jp-count" data-count></span>
    </div>` : ''}
    <div class="jp-list" data-list><div class="empty small">載入中…</div></div>
    <div class="jp-why small muted" data-why></div>
    <div class="jp-manual">
      <label>${pre.manual_label || '直接輸入單號（一行一個；別人指派的、剛開的、已結案要複驗的都打這裡）'}</label>
      <textarea data-manual rows="2" placeholder="CRUX-1234"></textarea>
    </div>`;

  const listEl = body.querySelector('[data-list]');
  const whyEl = body.querySelector('[data-why]');
  const countEl = body.querySelector('[data-count]');
  const filterEl = body.querySelector('[data-filter]');
  const prodEl = body.querySelector('[data-prod]');
  let options = [];
  const picked = new Set();

  function paint() {
    const q = String(filterEl?.value || '').trim().toLowerCase();
    const show = !q ? options : options.filter((o) => (o.value + ' ' + (o.status || '') + ' ' + (o.summary || o.label || '')).toLowerCase().includes(q));
    listEl.innerHTML = show.length
      ? show.map(rowHtml).join('')
      : '<div class="empty small">沒有符合的單</div>';
    // ⚠️ 過濾之後**不可以清掉已勾的** —— 人常「搜 A 勾一張、再搜 B 勾一張」，
    //    清掉的話第一張會無聲消失（他不會回頭確認）。所以勾選狀態存在 picked，重畫時還原。
    listEl.querySelectorAll('input[type=checkbox]').forEach((c) => { c.checked = picked.has(c.value); });
    if (countEl) countEl.textContent = picked.size ? `已選 ${picked.size} 張` : '';
  }

  async function load() {
    if (!url) { listEl.innerHTML = '<div class="empty small">這個欄位沒有動態選項</div>'; return; }
    listEl.innerHTML = '<div class="empty small">載入中…</div>';
    try {
      const p = prodEl ? prodEl.value : (product || '');
      const d = await api.get(`${url}?product=${encodeURIComponent(p)}`);
      options = normalize(d.options);
      whyEl.textContent = d.reason || '';
    } catch (e) {
      options = [];
      // ⛔ 選單壞掉不可以擋住任務 —— 下面的手動輸入永遠是可行的那條路。
      whyEl.textContent = '讀不到 JIRA（' + e.message + '）—— 直接在下面輸入單號即可';
    }
    paint();
  }

  listEl.addEventListener('change', (e) => {
    const c = e.target.closest('input[type=checkbox]');
    if (!c) return;
    if (c.checked) picked.add(c.value); else picked.delete(c.value);
    if (countEl) countEl.textContent = picked.size ? `已選 ${picked.size} 張` : '';
  });
  filterEl?.addEventListener('input', paint);
  prodEl?.addEventListener('change', () => { picked.clear(); load(); });
  load();

  return new Promise((res) => {
    let done = false;
    modal.open({
      title: `${task.icon || ''} ${task.label} — ${pre.title || '先挑要處理的項目'}`,
      body,
      size: 'wide',
      actions: [
        { label: '取消' },
        {
          label: pre.next_label || '下一步',
          cls: 'primary',
          onClick: () => {
            const manual = String(body.querySelector('[data-manual]').value || '')
              .split(/[\s,、]+/).map((x) => x.trim()).filter(Boolean);
            const all = [];
            for (const v of [...picked, ...manual]) if (!all.includes(v)) all.push(v);
            done = true;
            res({ [dst]: all.join('\n'), ...(prodEl ? { [prodField.key]: prodEl.value } : {}) });
            return true;
          },
        },
      ],
      // ⛔ 取消（或按 Esc、點背景）要回 null —— 回 {} 的話呼叫端會照樣開第二段，
      //    看起來像「取消沒有用」。
      onClose: () => { if (!done) res(null); },
    });
  });
}
