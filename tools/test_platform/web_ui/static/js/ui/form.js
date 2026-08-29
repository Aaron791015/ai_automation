// ★ 動態表單引擎：由 registry 的 params.fields 描述子渲染控件。
// 型別 → 渲染器註冊表，新增控件＝加一筆，核心不動。
// 五條規則：① 條件重算只切 class 不重建 DOM ② available_when 不滿足時停用＋顯示 unavailable_reason
//          ③ 前端即時提示、後端 validate() 才是權威 ④ secret 永不回填 ⑤ help 渲染成 .tip-*
import { $, $$, esc, h, html, raw } from './el.js';
import { api } from '../api.js';

// 條件式：{key: [允許值…]}，全部 key 都滿足才成立。
// ★ 待測值是陣列時改判「交集非空」—— 這是給 _products 這類虛擬欄位用的：
//   `visible_when: {"_products": ["crux"]}` 在勾了 crux 案例（可能還混著 wbot）時就成立。
//   ⚠️ 純量路徑一字未動，既有的 visible_when/available_when 行為完全不變。
//   後端 adapters/base.py 的 _cond() 必須同步 —— 兩邊分歧會變成「前端顯示、後端丟棄」的鬼欄位。
export function evalCond(cond, values) {
  if (!cond) return true;
  for (const [k, allowed] of Object.entries(cond)) {
    let v = values[k];
    if (Array.isArray(v)) {
      if (!v.some((x) => allowed.some((a) => a === x || String(a) === String(x)))) return false;
      continue;
    }
    if (typeof v === 'string' && (v === 'true' || v === 'false')) v = v === 'true';
    if (!allowed.some((a) => a === v || String(a) === String(v))) return false;
  }
  return true;
}

function tip(f) {
  return f.help ? html`<span class="tip-wrap"><span class="tip-icon">?</span><span class="tip-content">${f.help}</span></span>` : '';
}

const R = {
  text: (f, v) => html`<input type="text" data-key="${f.key}" value="${v ?? ''}" placeholder="${f.placeholder || ''}">`,
  path_picker: (f, v) => html`<input type="text" data-key="${f.key}" value="${v ?? ''}" placeholder="${f.placeholder || ''}">`,
  secret: (f) => html`<input type="password" data-key="${f.key}" value="" placeholder="${f.placeholder || '（不會回填、不寫入 profile）'}" autocomplete="new-password">`,
  number: (f, v) => html`<div class="with-unit"><input type="number" data-key="${f.key}" value="${v ?? ''}" ${f.min != null ? raw(`min="${f.min}"`) : ''} ${f.max != null ? raw(`max="${f.max}"`) : ''} step="${f.step ?? 1}">${f.unit ? html`<span class="unit">${f.unit}</span>` : ''}</div>`,
  duration: (f, v) => html`<input type="text" data-key="${f.key}" value="${v ?? ''}" placeholder="30m / 2h / 1h30m" class="mono">`,
  textarea: (f, v) => html`<textarea data-key="${f.key}" rows="${f.rows || 2}" placeholder="${f.placeholder || ''}">${v ?? ''}</textarea>`,
  boolean: (f, v) => html`<div class="row"><span class="switch ${v ? 'on' : ''}" data-key="${f.key}" data-val="${v ? '1' : '0'}" role="switch" aria-checked="${v ? 'true' : 'false'}" tabindex="0"></span><span class="small muted">${v ? '開' : '關'}</span></div>`,
  select: (f, v) => html`<select data-key="${f.key}">${(f.options || []).map((o) => html`<option value="${o.value}" ${String(o.value) === String(v ?? '') ? raw('selected') : ''}>${o.label}${o.badge ? `　[${o.badge}]` : ''}</option>`)}</select>${optNote(f, v)}`,
  file_select: (f, v) => html`<select data-key="${f.key}"><option value="">${f.placeholder || '（預設）'}</option>${(f.options || []).map((o) => html`<option value="${o.value}" ${String(o.value) === String(v ?? '') ? raw('selected') : ''}>${o.label}</option>`)}</select>`,
  multiselect: (f, v) => html`<select data-key="${f.key}" multiple size="4">${(f.options || []).map((o) => html`<option value="${o.value}" ${(v || []).map(String).includes(String(o.value)) ? raw('selected') : ''}>${o.label}</option>`)}</select>`,
  number_list: (f, v) => html`<input type="text" data-key="${f.key}" value="${Array.isArray(v) ? v.join(',') : (v ?? '')}" placeholder="以逗號分隔，例：1,2,3,4,5" class="mono">`,
  case_picker: (f, v) => html`<div class="row"><span class="pill" data-key="${f.key}" data-count="${(v || []).length}">已選 <b class="mono">${(v || []).length}</b> 條</span><a href="#/cases" class="btn sm">到案例瀏覽器勾選 →</a></div>`,
};
function optNote(f, v) {
  const o = (f.options || []).find((x) => String(x.value) === String(v ?? ''));
  return o && o.note ? html`<span class="opt-note">${o.note}</span>` : '';
}

// 依 field 型別讀值
export function readValues(root, fields) {
  // ★ 虛擬欄位 _products：勾選案例所屬的產品集合。它不是表單控件，但要能被 visible_when 比對，
  //   否則跨產品工具（ui_tests 宣告 crux/wbot/qixing）就無法依「這批案例是誰的」切換環境欄位。
  //   維護者是 cases.js／tool.js（見 syncSelectionProducts），這裡只負責讀出來。
  const vals = { _products: window.__tp_selection_products ? Array.from(window.__tp_selection_products) : [] };
  for (const f of fields) {
    const el = $(`[data-key="${CSS.escape(f.key)}"]`, root);
    if (!el) continue;
    if (f.type === 'boolean') vals[f.key] = el.dataset.val === '1';
    else if (f.type === 'multiselect') vals[f.key] = Array.from(el.selectedOptions).map((o) => o.value);
    else if (f.type === 'case_picker') vals[f.key] = window.__tp_selection ? Array.from(window.__tp_selection) : [];
    else if (f.type === 'number') vals[f.key] = el.value === '' ? undefined : Number(el.value);
    else if (f.type === 'number_list') vals[f.key] = el.value.split(/[,，\s]+/).filter(Boolean).map(Number);
    else vals[f.key] = el.value;
  }
  return vals;
}

// 前端即時檢核（後端仍是權威）
export function validate(fields, vals) {
  const errs = {};
  for (const f of fields) {
    if (!evalCond(f.visible_when, vals) || !evalCond(f.available_when, vals)) continue;
    const v = vals[f.key];
    const req = f.required || (f.required_when && evalCond(f.required_when, vals));
    if (req && (v == null || v === '' || (Array.isArray(v) && !v.length))) { errs[f.key] = '必填'; continue; }
    if (v == null || v === '') continue;
    if (f.type === 'number') { if (f.min != null && v < f.min) errs[f.key] = `不可小於 ${f.min}`; if (f.max != null && v > f.max) errs[f.key] = `不可大於 ${f.max}`; }
    if (f.type === 'duration' && !/^(\d+h)?(\d+m)?(\d+s)?$/.test(String(v))) errs[f.key] = '格式：30m／2h／1h30m';
    // ⚠️ 只說「格式不符」等於沒說 —— 欄位的 `help` 通常已經寫了要什麼
    //    （「大寫英數」「小寫英數」），但那是 tooltip，要 hover 才看得到。
    //    Day-0 的人不知道它要什麼，只能瞎試（2026-08-23 情境 A 走查）。
    if (f.pattern && typeof v === 'string' && !new RegExp(f.pattern).test(v)) {
      const hint = (f.pattern_hint || f.help || '').split(/[。．\n]/)[0].trim();
      errs[f.key] = hint ? `格式不符 —— ${hint}` : '格式不符';
    }
  }
  return errs;
}

// ⛔ **`html` 是 tagged template —— 裡面一個反引號就會提前結束整串字串。**
//    2026-08-27 在欄位模板裡寫了一句含 `.reason` 的說明（markdown 習慣加反引號），
//    結果整個任務框打不開，錯誤是 `html(...).reason is not a function`。
//    ⚠️ **JS 語法檢查抓不到這一類** —— 提前結束後剩下的仍是合法 JS
//    （`html\`…\`.reason(…)`），`node --check` 一路綠燈。
//    → 模板內要說明就寫在**模板外面**（像這一段），或用「」代替反引號。
//
// `.opt-reason` 的用途：動態選項的說明（選單為什麼是空的、共幾張）。
// ⛔ 不能共用旁邊的 `.reason` —— 那個被「此組合不適用」佔用，
//    且 recalc() 會把它清空，共用的話這句話會被蓋掉。
export function renderForm(root, spec, command, initial = {}, { onChange } = {}) {
  const params = command.params || {};
  let fields = params.fields || [];
  let groups = params.groups && params.groups.length ? params.groups : [{ id: '_', label: '' }];
  // ⛔ **宣告了 groups 之後，沒有 `group` 的欄位會整個消失** ——
  //    下面是 `fields.filter(f => (f.group||'_') === g.id)`，而 `_` 不在任何一組裡。
  //    這不是理論問題：三支壓測工具合計 **19 個欄位**這樣被吃掉，
  //    而且**看不出來** —— 表單長得好好的，只是那些設定用了預設值
  //    （2026-08-24 使用者：「舊控制台的設定有部分沒有在平台出現」）。
  //    → 落單的一律收進一個附加在最後的「其他設定」組，寧可醜也不要消失。
  const known = new Set(groups.map((g) => g.id));
  if (fields.some((f) => !known.has(f.group || '_'))) {
    groups = groups.concat([{ id: '__orphan__', label: '其他設定' }]);
    fields = fields.map((f) => (known.has(f.group || '_') ? f : { ...f, group: '__orphan__' }));
  }
  const values = {};
  fields.forEach((f) => { values[f.key] = initial[f.key] !== undefined ? initial[f.key] : f.default; });
  if (fields.some((f) => f.type === 'case_picker')) values.selection = window.__tp_selection ? Array.from(window.__tp_selection) : [];

  const parts = [];
  for (const g of groups) {
    const gf = fields.filter((f) => (f.group || '_') === g.id);
    if (!gf.length) continue;
    parts.push(html`<fieldset class="section ${g.collapsed ? 'collapsed' : ''}" data-group="${g.id}">
      ${g.label ? html`<legend>${g.label}<span class="tog" title="展開／收合">${g.collapsed ? '▸' : '▾'}</span></legend>` : ''}
      <div class="settings-grid">
        ${gf.map((f) => html`<div class="field ${f.type} ${f.type === 'textarea' || f.type === 'case_picker' ? 'span3' : ''}" data-field="${f.key}">
          <label>${f.label}${f.required ? html`<span class="req">*</span>` : ''}${raw(tip(f))}</label>
          ${raw((R[f.type] || R.text)(f, values[f.key]))}
          <span class="err"></span><span class="reason"></span>
          <span class="opt-reason" data-reason hidden></span>
        </div>`)}
      </div>
    </fieldset>`);
  }
  root.innerHTML = parts.join('') || '<div class="empty small">此命令無參數</div>';

  // 事件
  // ⛔ 一律**屬性指派**，不可用 addEventListener：本函式每次 render 都會再跑一次
  //    （切命令頁籤、reloadDynamic 都會），而 innerHTML 換掉的是子節點，
  //    掛在 root 自己身上的監聽器不會被清掉 → 累積 → 一次點擊觸發兩次 →
  //    開關 toggle 兩下、淨值不變，看起來像「按下去沒反應」。
  //    （2026-08-23 範本端到端驗收：--dry-run 關不掉。）
  root.onclick = (e) => {
    const sw = e.target.closest('.switch');
    if (sw) { const on = sw.dataset.val !== '1'; sw.dataset.val = on ? '1' : '0'; sw.classList.toggle('on', on); sw.setAttribute('aria-checked', on ? 'true' : 'false'); sw.nextElementSibling.textContent = on ? '開' : '關'; recalc(); }
    const tog = e.target.closest('legend .tog');
    if (tog) { const fs = tog.closest('fieldset'); fs.classList.toggle('collapsed'); tog.textContent = fs.classList.contains('collapsed') ? '▸' : '▾'; }
  };
  root.onkeydown = (e) => { if (e.target.classList.contains('switch') && (e.key === ' ' || e.key === 'Enter')) { e.preventDefault(); e.target.click(); } };
  root.oninput = () => recalc();
  root.onchange = (e) => {
    recalc();
    const k = e.target.dataset.key;
    const f = fields.find((x) => x.key === k);
    if (!f) return;
    if (f.appends_to) appendInto(f, e.target);
    if (f.reload_on_change) reloadDynamic(k);
  };

  /** `appends_to`：把這個欄位選到的值**追加**進另一個欄位（2026-08-27）。
   *
   * ⭐ 為什麼是「追加」而不是「取代那個欄位」：目標欄位（例如 JIRA 單號）
   *    必須**still 打得進任何值** —— 別人指派的單、剛開的單都不會出現在選單裡。
   *    把輸入框換成下拉等於把那些正當用途一起擋掉（CLAUDE.md §7.0）。
   * ⛔ 要去重 —— 同一張單選兩次不該在欄位裡出現兩行。
   */
  function appendInto(f, el) {
    const dst = $(`[data-key="${CSS.escape(f.appends_to)}"]`, root);
    if (!dst) return;
    const picked = Array.from(el.selectedOptions || []).map((o) => o.value);
    if (!picked.length) return;
    const have = String(dst.value || '').split(/[\s,、]+/).map((x) => x.trim()).filter(Boolean);
    const add = picked.filter((p) => !have.includes(p));
    if (!add.length) return;
    dst.value = have.concat(add).join('\n');
    recalc();                      // ⛔ 目標欄位可能是 required —— 不重算會一直顯示「必填」
  }

  async function reloadDynamic(changedKey) {
    let touched = false;
    for (const f of fields) {
      if (!f.options_from) continue;
      // ⛔ 這裡原本是 `f.options_from.kind !== 'api' → continue` —— 而 tool.json 裡
      //    **沒有任何一支**寫 `kind: "api"`，寫的都是宣告式的 `{source: "products"|"files"}`。
      //    於是所有動態選項在畫面上都是**空下拉**：`#/tool/setup` 的「接一個產品」
      //    「收尾體檢」等命令的產品欄是空的、required 過不了，整個命令按不下去
      //    （2026-08-24 走查發現；後端 `/api/tools/<id>/options/<key>` 一直是好的，
      //    只是前端從來沒去問）。
      //    → 有 `options_from` 就去問該工具的選項端點；`kind: "api"` ＋ 自訂 url 仍照舊。
      const url = f.options_from.url
        || (spec && spec.id ? `/api/tools/${encodeURIComponent(spec.id)}/options/${encodeURIComponent(f.key)}` : null);
      if (!url) continue;
      const el = $(`[data-key="${CSS.escape(f.key)}"]`, root);
      if (!el) continue;
      try {
        const cur = readValues(root, fields);
        const q = new URLSearchParams(Object.fromEntries(Object.entries(cur).filter(([, v]) => v != null && typeof v !== 'object').map(([k, v]) => [k, String(v)])));
        const d = await api.get(`${url}?${q}`);
        const keep = el.value;
        el.innerHTML = (f.type === 'file_select' ? `<option value="">${esc(f.placeholder || '（預設）')}</option>` : '') + (d.options || []).map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
        if ([...el.options].some((o) => o.value === keep)) el.value = keep;
        // ⭐ 把後端給的一句話顯示出來 —— 選單空的時候**一定要說得出為什麼**
        //    （沒設 JIRA 憑證／這個產品沒有 JIRA 專案／真的沒有指派給你的單），
        //    否則人只看到一個空下拉，會以為是壞了（2026-08-27）。
        const why = el.parentElement?.querySelector('[data-reason]');
        if (why) { why.textContent = d.reason || ''; why.hidden = !d.reason; }
        touched = true;
      } catch (e) { /* 動態選項失敗不阻塞 */ }
    }
    // ⛔ 填完選項要**重算一次**：選項是非同步來的，而第一次 `recalc()` 早就跑完了。
    //    不重算的話，`required` 的下拉會一直掛著「必填」的紅字、
    //    「執行」按鈕停用 —— 明明畫面上已經選好了一個值（2026-08-24 走查）。
    if (touched) recalc();
  }
  reloadDynamic(null);

  function recalc() {
    const vals = readValues(root, fields);
    const errs = validate(fields, vals);
    for (const f of fields) {
      const wrap = $(`[data-field="${CSS.escape(f.key)}"]`, root);
      if (!wrap) continue;
      const vis = evalCond(f.visible_when, vals);
      const avail = evalCond(f.available_when, vals);
      wrap.classList.toggle('hidden-by-cond', !vis);
      wrap.classList.toggle('unavailable', !avail);
      $$('input,select,textarea,.switch', wrap).forEach((el) => { if (el.classList.contains('switch')) el.style.pointerEvents = avail ? '' : 'none'; else el.disabled = !avail; });
      $('.reason', wrap).textContent = !avail ? (f.unavailable_reason || '此組合不適用') : '';
      const err = $('.err', wrap); err.textContent = errs[f.key] || '';
      $$('input,select', wrap).forEach((el) => el.classList.toggle('invalid', !!errs[f.key]));
      if (f.type === 'select') { const note = $('.opt-note', wrap); const o = (f.options || []).find((x) => String(x.value) === String(vals[f.key])); if (note) note.textContent = o && o.note ? o.note : ''; }
    }
    onChange && onChange(vals, errs);
  }
  recalc();
  return { read: () => readValues(root, fields), validate: () => validate(fields, readValues(root, fields)), recalc, fields };
}
