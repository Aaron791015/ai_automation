// 設定 → 設定檔分頁：直接開檔、編輯、存回（2026-08-24 使用者要求）
//
// > 「關於環境設定，也需要可以在介面上進行（可以直接開檔，編輯 json 後再存回）」
//
// ⛔ 三件事刻意做在這裡，因為缺一個就會出事：
//   ① **存之前先驗** —— 壞掉的 JSON 會讓 lint_docs／bug_paths／平台自己一起
//      靜默失效（多數呼叫端 try/except 吞掉例外）。所以編輯時就即時檢查，壞的存不下去。
//   ② **存之前先備份** —— 這幾份是產品定義的單一來源，貼錯一次就得回 git 撈。
//   ③ **敏感檔不在這裡** —— `config.local.json`（帳密／token）走「JIRA 憑證」分頁，
//      那一頁只寫不讀。這裡開得到的都是可版控、非敏感的檔案。
import { api } from '../api.js';
import { $, $$, html, raw, esc, fmt, copy } from '../ui/el.js';
import { toast } from '../ui/toast.js';
import { modal } from '../ui/modal.js';
import { pageLoading } from '../ui/loading.js';

let files = [], cur = null, dirty = false, ta = null;

export async function mount(root) {
  root.innerHTML = html`${pageLoading("讀取設定檔清單…")}`;
  try { files = (await api.get('/api/settings/files')).files || []; }
  catch (e) { root.innerHTML = html`<div class="alert is-error">${esc(e.message)}</div>`; return; }
  root.innerHTML = html`<div class="cfg-wrap">
    <aside class="cfg-list" id="cfg-list">${files.map((f) => html`<button class="cfg-item" data-key="${f.key}">
        <span class="nm">${f.label}</span>
        <span class="pt mono tiny">${f.path}</span>
        <span class="mt tiny muted">${f.exists ? `${fmt.int(f.size)} 位元組 · ${f.modified}` : '檔案不存在'}</span>
      </button>`)}</aside>
    <section class="cfg-edit" id="cfg-edit"><div class="muted small">← 左邊挑一份設定檔</div></section>
  </div>`;
  $('#cfg-list', root).onclick = async (e) => {
    const b = e.target.closest('[data-key]'); if (!b) return;
    if (dirty && !(await modal.confirm('未存的變更', '這一份有還沒儲存的編輯，切走就沒了。', { danger: true, okLabel: '不存了，切走' }))) return;
    await open(root, b.dataset.key);
  };
  await open(root, files[0]?.key);
}

async function open(root, key) {
  if (!key) return;
  cur = key; dirty = false;
  $$('#cfg-list .cfg-item', root).forEach((x) => x.classList.toggle('active', x.dataset.key === key));
  const box = $('#cfg-edit', root);
  box.innerHTML = html`${pageLoading("開檔中…")}`;
  let d;
  try { d = await api.get(`/api/settings/files/${key}`); }
  catch (e) { box.innerHTML = html`<div class="alert is-error">${esc(e.message)}</div>`; return; }
  if (cur !== key) return;
  box.innerHTML = html`
    <div class="cfg-head">
      <b>${d.label}</b><span class="pill">${d.kind === 'json' ? 'JSON' : 'Markdown'}</span>
      <span class="mono tiny muted">${d.path}</span>
      <span style="flex:1"></span>
      <span class="tiny muted" id="cfg-stat"></span>
    </div>
    <div class="tiny muted cfg-desc">${d.desc}</div>
    ${d.warn ? html`<div class="alert is-warn tiny" style="margin:6px 0">${d.warn}</div>` : ''}
    ${/* ⭐ 範例格式：接產品的人打開這一份時，最需要的是「我該寫成什麼樣子」
           （2026-08-24 使用者要求）。預設收合 —— 已經知道怎麼寫的人不必每次都看到。 */''}
    ${d.example ? html`<details class="cfg-example"><summary>${d.example_title || '範例格式'}</summary>
      <pre class="mono">${d.example}</pre>
      ${d.example_note ? html`<div class="tiny muted">${raw(d.example_note)}</div>` : ''}
      <button class="btn xs" id="cfg-copy-example">複製範例</button>
    </details>` : ''}
    <textarea class="cfg-ta mono" id="cfg-ta" spellcheck="false"></textarea>
    <div class="row cfg-actions">
      <button class="btn primary" id="cfg-save" disabled>儲存</button>
      <button class="btn" id="cfg-reset" disabled>還原這次編輯</button>
      <span style="flex:1"></span>
      ${d.backups ? html`<button class="btn sm ghost" id="cfg-bk">備份 ${d.backups} 份 →</button>` : html`<span class="tiny muted">尚無備份</span>`}
    </div>`;
  ta = $('#cfg-ta', root);
  ta.value = d.text;
  const original = d.text;
  const stat = $('#cfg-stat', root), save = $('#cfg-save', root), reset = $('#cfg-reset', root);

  // 即時檢查：JSON 壞掉時**當場**說在第幾行，而不是存下去之後才發現整個工作區壞了
  const check = () => {
    dirty = ta.value !== original;
    save.disabled = !dirty; reset.disabled = !dirty;
    if (d.kind !== 'json') { stat.innerHTML = dirty ? '● 已修改' : '已儲存'; stat.className = 'tiny muted'; return true; }
    try {
      JSON.parse(ta.value);
      stat.innerHTML = dirty ? '● 已修改 · JSON 有效' : 'JSON 有效';
      stat.className = 'tiny tone-ok';
      return true;
    } catch (err) {
      stat.textContent = '⚠️ ' + err.message;
      stat.className = 'tiny tone-warn';
      save.disabled = true;                      // ⛔ 壞的 JSON 不給存
      return false;
    }
  };
  ta.oninput = check; check();
  // 範例只是給人看的，複製到剪貼簿讓他貼進去自己改 —— 不要「一鍵填入」，
  // 那會把既有內容蓋掉（這份檔案裡通常已經有別的產品）。
  const cpEx = $('#cfg-copy-example', root);
  if (cpEx) cpEx.onclick = () => { copy(d.example); toast('範例已複製 —— 貼進去改成你的產品', 'success'); };
  // Tab 在 textarea 裡應該是縮排，不是跳到下一個欄位（編輯 JSON 一直跳走沒法用）
  ta.onkeydown = (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const s = ta.selectionStart, t = ta.selectionEnd;
      ta.value = ta.value.slice(0, s) + '  ' + ta.value.slice(t);
      ta.selectionStart = ta.selectionEnd = s + 2; check();
    } else if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save.click(); }
  };

  save.onclick = async () => {
    if (!check()) return;
    save.disabled = true;
    try {
      const r = await api.put(`/api/settings/files/${key}`, { text: ta.value });
      toast(`已存回 ${r.path}${r.backup ? '（舊版已備份）' : ''}`, 'success');
      await open(root, key);                     // 重讀：拿到正規化後的內容與新的備份數
    } catch (e) { toast(e.message, 'danger', 7000); save.disabled = false; }
  };
  reset.onclick = () => { ta.value = original; check(); };
  const bk = $('#cfg-bk', root);
  if (bk) bk.onclick = () => showBackups(root, key);
}

async function showBackups(root, key) {
  let list = [];
  try { list = (await api.get(`/api/settings/files/${key}/backups`)).backups || []; }
  catch (e) { toast(e.message, 'danger'); return; }
  const body = document.createElement('div');
  body.innerHTML = html`<div class="tiny muted" style="margin-bottom:6px">還原會先把現在的內容也備份起來，所以按錯了還救得回來。</div>
    <div class="stack">${list.map((b) => html`<button class="btn block" data-bk="${b.name}">${b.at}</button>`)}</div>`;
  const m = modal.open({ title: '備份（最近 20 份）', body, actions: [{ label: '關閉' }] });
  body.onclick = async (e) => {
    const b = e.target.closest('[data-bk]'); if (!b) return;
    m.close();
    if (!(await modal.confirm('還原備份', `用 <code>${esc(b.dataset.bk)}</code> 覆蓋目前的內容？`, { danger: true, okLabel: '還原' }))) return;
    try { await api.put(`/api/settings/files/${key}`, { restore: b.dataset.bk }); toast('已還原', 'success'); await open(root, key); }
    catch (err) { toast(err.message, 'danger'); }
  };
}

export function unmount() { files = []; cur = null; dirty = false; ta = null; }
