// #/settings/credentials 憑證設定（階段 F-1，2026-08-23）
//
// 為什麼要這一頁：JIRA 的 `session_cookie` **會過期** —— Jira Server 8.6.1 早於 PAT，
// 附件下載走 web 層不吃 Basic Auth，要貼已通過 2FA 的 JSESSIONID。
// 原本只能手動編輯 config/config.local.json，這一頁就是為了取代那件事。
//
// ⛔ 頁面**永遠拿不到已存的密碼** —— 後端只回「有沒有設定 ＋ 最後更新」。
//    空欄位送出 ＝ 不改（不是清空），要清空按「清除」。
import { api } from '../api.js';
import { $, html, esc, raw } from '../ui/el.js';
import { md } from '../ui/docview.js';
import { toast } from '../ui/toast.js';
import { modal } from '../ui/modal.js';
import { pageLoading } from '../ui/loading.js';

const FIELDS = [
  { key: 'username', label: 'JIRA 帳號', type: 'text',
    help: 'Jira Server 8.6.1 早於 PAT（8.14 才支援），只能用帳號密碼 Basic Auth' },
  { key: 'password', label: 'JIRA 密碼', type: 'password' },
  { key: 'session_cookie', label: 'Session Cookie', type: 'password',
    help: '⚠️ 選填但**會過期** —— 只有下載附件會用到。從瀏覽器開發者工具複製 JSESSIONID' },
];

export async function mount(root) {
  // ⚠️ 只畫內容 —— 頁殼由 `views/settings.js` 的分頁中樞提供（見該檔檔頭）
  root.innerHTML = html`<div class="tiny muted" id="cr-path" style="margin-bottom:8px"></div>
    <div id="cr-body">${pageLoading("讀取憑證設定…")}</div>`;
  await draw(root);
}

async function draw(root) {
  let s;
  try { s = await api.get('/api/settings/credentials'); }
  catch (e) { $('#cr-body', root).innerHTML = html`<div class="alert is-error">${esc(e.message)}</div>`; return; }

  const j = s.groups.jira;
  $('#cr-path', root).textContent = `寫入 ${s.path}（不版控）`;
  $('#cr-body', root).innerHTML = html`
    <section class="card">
      <h3>JIRA <span class="cnt">${s.jira_base_url || '未設定 base_url'}</span></h3>
      <div class="tiny muted" style="margin-bottom:10px">
        ⛔ 這一頁<b>看不到</b>已存的密碼 —— 只顯示「有沒有設定」。
        留空送出 ＝ 不改該欄，要清空請按「清除」。
      </div>
      ${FIELDS.map((f) => html`<div class="credfld">
        <div class="credhead">
          <b>${f.label}</b>
          <span class="pill ${j[f.key].set ? 'tone-ok' : 'tone-warn'}">${j[f.key].set ? '已設定' : '未設定'}</span>
          ${j[f.key].hint ? html`<span class="tiny muted">目前：${j[f.key].hint}</span>` : ''}
          <span style="flex:1"></span>
          ${j[f.key].set ? html`<button class="btn xs ghost" data-clear="${f.key}">清除</button>` : ''}
        </div>
        <input type="${f.type}" id="cr-${f.key}" placeholder="${j[f.key].set ? '留空 ＝ 不改；要換值就直接輸入' : '尚未設定，請輸入'}" autocomplete="off">
        ${f.help ? raw(`<div class="tiny muted credhelp">${md(f.help)}</div>`) : ''}
      </div>`)}
      <div class="tiny muted">最後更新：${j._updated || '—'}</div>
      <div class="row" style="margin-top:10px;gap:6px">
        <button class="btn primary" id="cr-save">儲存</button>
        <button class="btn" id="cr-test">連線測試</button>
        <button class="btn" id="cr-test-att">附件測試（驗 cookie 沒過期）</button>
      </div>
      <div id="cr-result" class="tiny" style="margin-top:8px"></div>
    </section>`;

  $('#cr-save', root).onclick = async () => {
    const values = { jira: {} };
    FIELDS.forEach((f) => { values.jira[f.key] = $(`#cr-${f.key}`, root).value; });
    try {
      const r = await api.post('/api/settings/credentials', { values });
      toast(r.changed.length ? `已更新 ${r.changed.join('、')}` : '沒有變更（欄位都是空的）', 'success');
      await draw(root);
    } catch (e) { toast(e.message, 'danger'); }
  };

  const showResult = (r) => {
    $('#cr-result', root).innerHTML = html`<span class="${r.ok ? 'tone-ok' : 'tone-warn'}">${r.ok ? '✅' : '⚠️'} ${r.detail}</span>`;
  };
  $('#cr-test', root).onclick = async () => {
    $('#cr-result', root).textContent = '測試中…';
    try { showResult(await api.post('/api/settings/credentials/test', { which: 'jira' })); }
    catch (e) { showResult({ ok: false, detail: e.message }); }
  };
  $('#cr-test-att', root).onclick = async () => {
    // ⛔ 不要用原生 `prompt()` —— 它長得跟平台完全不一樣，而且在部分瀏覽器
    //    設定下會被擋掉（按了完全沒反應）。平台自己的 modal.prompt 是同一套視覺。
    // ⚠️ 第三個參數就是 options（不是預設值後面再接一個物件）——
    //    多傳的那個會被靜默忽略，placeholder 與按鈕字都不會生效。
    const key = await modal.prompt('附件測試', '用哪一張<b>有附件</b>的單來測？',
      { placeholder: '例：CRUX-1007', okLabel: '測試' });
    if (!key) return;
    $('#cr-result', root).textContent = '測試中…';
    try { showResult(await api.post('/api/settings/credentials/test', { which: 'jira_attachment', issue_key: key })); }
    catch (e) { showResult({ ok: false, detail: e.message }); }
  };
  root.querySelectorAll('[data-clear]').forEach((b) => {
    b.onclick = async () => {
      try { await api.del(`/api/settings/credentials/jira/${b.dataset.clear}`); toast('已清除', 'success'); await draw(root); }
      catch (e) { toast(e.message, 'danger'); }
    };
  });
}

export function unmount() {}
