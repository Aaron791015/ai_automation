// #/registry 註冊表檢視：所有 tool spec 卡片 ＋ schema 驗證結果 ＋ 接入說明 —— 給同事看的自助頁
import { api } from '../api.js';
import { $, html, raw, esc } from '../ui/el.js';
import { state, set, worstDanger } from '../store.js';
import { modal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';
import { navigate } from '../router.js';
import { pageLoading } from '../ui/loading.js';

export async function mount(root) {
  // ⭐ 先畫殼再抓資料（2026-08-24）—— 見 `views/tools.js` 同一段說明
  root.innerHTML = html`<div class="page">
    <div class="page-head"><h2>註冊表</h2><span class="crumb">registry/*.tool.json</span></div>
    <div class="page-body">${pageLoading('讀取工具註冊表…')}</div>
  </div>`;

  let d;
  try { d = await api.get('/api/tools'); } catch (e) { root.innerHTML = `<div class="alert is-error">${esc(e.message)}</div>`; return; }
  root.innerHTML = html`<div class="page">
    <div class="page-head"><h2>註冊表</h2><span class="crumb">registry/*.tool.json · ${d.tools.length} 個工具</span><span style="flex:1"></span><button class="btn sm primary" id="rg-new">＋ 接一支新工具</button><button class="btn sm" id="rg-reload">↻ 重新載入</button></div>
    <div class="page-body">
    ${(d.notes || []).length ? html`<div class="alert is-warn" style="margin-top:10px"><b>${d.notes.length} 支 tool.json 建議升級</b>${d.notes.map((n) => html`<div class="mono small">${n.file}: ${n.note}</div>`)}</div>` : ''}
    ${(d.errors || []).length ? html`<div class="alert is-error" style="margin-top:10px"><b>${d.errors.length} 個 spec 錯誤</b>${d.errors.map((e) => html`<div class="mono small">${e.file}: ${e.error}</div>`)}</div>` : html`<div class="alert is-info small" style="margin-top:10px">✅ 全部 spec 通過結構檢查</div>`}
    <div class="grid auto" style="margin-top:12px">${d.tools.map((t) => html`<div class="card"><h3>${t.name} <span class="cnt">${t.id}</span></h3>
      <div class="small muted">${t.subtitle || ''}</div>
      <table class="tbl tiny" style="margin-top:8px"><tr><th>kind</th><td>${t.kind}</td></tr><tr><th>產品</th><td>${(t.products || []).length ? (t.products || []).join(', ') : (t.scope === 'workspace' ? '工作區（不分產品）' : '—')}</td></tr><tr><th>命令</th><td title="${t.commands.map((c) => c.id).join(', ')}">${t.commands.slice(0, 6).map((c) => `${c.id}(${c.mode})`).join(', ')}${t.commands.length > 6 ? ` … 另 ${t.commands.length - 6} 個` : ''}</td></tr><tr><th>併發</th><td>${t.run?.concurrency || 'single'}${t.run?.exclusive_group ? ' · 互斥 ' + t.run.exclusive_group : ''}</td></tr><tr><th>停止</th><td>${t.stop?.strategy || 'tree'}</td></tr><tr><th>危險</th><td class="${worstDanger(t) === 'high' ? 'is-danger' : ''}">${worstDanger(t)}${worstDanger(t) !== (t.danger?.level || 'low') ? `（工具 ${t.danger?.level || 'low'}，但有命令更高）` : ''}</td></tr><tr><th>owner</th><td>${t.owner || '—'}</td></tr></table>
      <div class="row" style="margin-top:8px"><button class="btn xs" data-json="${t.id}">看 JSON</button><a class="btn xs" href="#/tool/${t.id}">開啟</a></div></div>`)}</div>
    <section class="card" style="margin-top:14px"><h3>如何接入新工具（同事自助）</h3>
      <div class="md small">
        <p class="alert is-info small" style="margin:0 0 10px">⭐ <b>骨架可以用上方「＋ 接一支新工具」直接建</b>（會即時驗證 spec、收不下就不寫檔）。建好之後<b>還是要手動補 <code>params.fields</code></b> —— 平台不會替你猜欄位，猜出來的欄位會變成「填了不生效」。</p><p><b>1.</b> 在 <code>tools/test_platform/registry/</code> 新增 <code>&lt;tool_id&gt;.tool.json</code>（依 <code>_schema.json</code>；<b>一工具一檔</b>，各產品線只改自己那支，結構上不可能撞檔）。</p>
        <p><b>2.</b> 宣告 <code>kind</code>（cli／pytest／http）、<code>runtime.cwd</code>、<code>commands[]</code>（每個命令的 <code>argv</code> 固定前綴 ＋ <code>params.fields</code> 欄位描述子）。欄位的 <code>emit</code> 決定怎麼變成命令列：<code>opt</code>（--arg v）／<code>flag_when_true</code>／<code>repeat</code>／<code>env</code>（secret 一律走這條）／<code>positional</code>／<code>argsfile</code>。</p>
        <p><b>3.</b> 長時執行用 <code>mode:"run"</code>（會建 run 目錄、可監控、可停止）；秒級指令用 <code>mode:"sync"</code>（結果依 <code>result.kind</code> 就地渲染：text／json_table／checklist／copy_chip／artifact_dir）；有函式沒 CLI 用 <code>mode:"python_call"</code>。</p>
        <p><b>4.</b> 若工具會寫自己的 run_status.json，在 <code>run.status_source</code> 指過去，並用 <code>run.phases[]</code> 宣告自己的狀態機（平台不需認識任何工具專屬狀態）。</p>
        <p><b>5.</b> 會寫入測試站的工具設 <code>danger.level:"high"</code>；會與別的工具搶同一站台的設 <code>run.exclusive_group</code>。</p>
        <p><b>6.</b> 存檔 → 本頁「重新載入」→ 通過驗證即出現在工具清單。統一使用工作區 <code>.venv</code>，需要的套件寫進 <code>runtime.requires.python_modules</code>，缺件會在 Dashboard 亮紅並給修復指令。</p>
        <p class="muted">完整說明：<code>tools/test_platform/docs/CONTRIB_TOOL.md</code>、<code>docs/REGISTRY.md</code></p>
      </div></section></div></div>`;
  root.onclick = async (e) => { const b = e.target.closest('[data-json]'); if (!b) return; const t = d.tools.find((x) => x.id === b.dataset.json); modal.open({ title: `${t.id}.tool.json`, wide: true, body: `<pre style="max-height:70vh">${esc(JSON.stringify(t, null, 2))}</pre>`, actions: [{ label: '關閉' }] }); };
  $('#rg-new', root).onclick = () => openNewToolForm(root, d);
  $('#rg-reload', root).onclick = async () => {
    const r = await api.post('/api/registry/reload');
    // ⚠️ 伺服器端 reload 完，**全域 store 也要跟著更新** —— 否則新接的產品
    //    只存在於後端：接工具表單的產品下拉會是空的，同事的
    //    「接產品 → 接工具」動線直接卡死（2026-08-23 範本端到端驗收）。
    await refreshStore();
    toast(`已重新載入：${r.tools} 個工具${r.errors?.length ? `，${r.errors.length} 個錯誤` : ''}`, r.errors?.length ? 'warn' : 'success');
    mount(root);
  };
}

// 重新抓 /api/bootstrap 灌回全域 store。
// registry 一改，products／tools 兩份就都變了 —— 只 re-render 本頁不夠。
async function refreshStore() {
  const b = await api.bootstrap();
  set({ boot: b, tools: b.tools, products: b.products });
}

// ── 接一支新工具：draft → 預覽 → 寫檔 → 驗證（core/tool_draft.py 的四段式）──
//
// ⛔ 刻意只問「組得出骨架所需的最少欄位」。params.fields 留給人依 CONTRIB_TOOL.md 補
//    —— 平台替你猜欄位的話，會生出「填了不生效」的假欄位，那正是階段 G 花最多
//    力氣在防的事。
function openNewToolForm(root, d) {
  const products = (state.products || []).filter((p) => !p.virtual);
  const F = (id, label, opts = {}) => `
    <label class="fld">
      <span>${label}${opts.req ? ' <b style="color:var(--danger)">*</b>' : ''}</span>
      ${opts.select
        ? `<select id="nt-${id}">${opts.select.map((o) => `<option value="${esc(o.v)}">${esc(o.t)}</option>`).join('')}</select>`
        : `<input id="nt-${id}" placeholder="${esc(opts.ph || '')}" autocomplete="off">`}
      ${opts.help ? `<em class="small muted">${opts.help}</em>` : ''}
    </label>`;

  modal.open({
    title: '接一支新工具',
    wide: true,
    body: `
      <div class="alert is-info small">產生的是<b>骨架</b> —— 寫檔後還要補 <code>params.fields</code>（這支工具要問使用者什麼）。
      平台不替你猜欄位：猜錯的欄位會變成「填了不生效」，而且看不出來。</div>
      <div class="grid two" style="margin-top:10px">
        ${F('id', '工具 id', { req: true, ph: 'my_tool', help: '小寫英數與底線，會直接當檔名 &lt;id&gt;.tool.json' })}
        ${F('name', '顯示名稱', { req: true, ph: '我的工具' })}
        ${F('subtitle', '一句話說明', { ph: '這支工具在做什麼' })}
        ${F('kind', 'kind', { select: [{ v: 'cli', t: 'cli — 跑一支命令列程式' }, { v: 'pytest', t: 'pytest — 跑測試案例' }, { v: 'http', t: 'http — 代理既有的 HTTP 服務' }] })}
        ${F('scope', '歸屬', { select: [{ v: 'product', t: '某個產品' }, { v: 'workspace', t: '工作區級（初始化／體檢／盤點）' }] })}
        ${F('product', '產品', { select: products.map((p) => ({ v: p.id, t: `${p.label || p.id}（${p.product_id || p.id}）` })), help: 'scope 選「工作區級」時本欄忽略' })}
        ${F('cwd', 'runtime.cwd', { ph: 'tools/my_tool', help: 'argv 相對於它；留空＝ repo 根目錄' })}
        ${F('executable', 'runtime.executable', { ph: '留空＝工作區 .venv', help: '裸名（如 python）走 PATH ⚠️ 需要 locust/gevent 的工具要填 python' })}
        ${F('python_modules', '需要的套件', { ph: 'flask, requests', help: '缺件會在健康檢查亮紅並給安裝指令' })}
        ${F('danger', '危險等級', { select: [{ v: 'low', t: 'low — 唯讀／本機' }, { v: 'medium', t: 'medium — 會改東西' }, { v: 'high', t: 'high — 會寫入測試站／破壞性' }] })}
        ${F('command_id', '第一個命令 id', { req: true, ph: 'run' })}
        ${F('command_label', '命令顯示名', { ph: '執行' })}
        ${F('mode', '命令型態', { select: [{ v: 'sync', t: 'sync — 秒～分鐘級，結果就地顯示' }, { v: 'run', t: 'run — 長時執行，可監控可停止' }] })}
        ${F('argv', 'argv', { req: true, ph: '-m my_tool.main  或  scripts/go.py', help: '真正要執行的東西（不含直譯器）' })}
      </div>
      <div id="nt-out" style="margin-top:10px"></div>`,
    // ⚠️ modal 的約定：`onClick` **回 false 才保持開啟**，其餘一律關閉。
    //    預覽要留在框裡看 JSON，所以永遠回 false；建立成功才讓它關。
    actions: [
      { label: '取消' },
      { label: '預覽 JSON', onClick: () => runNewTool(root, false) },
      { label: '建立', cls: 'primary', onClick: () => runNewTool(root, true) },
    ],
  });
}

function collectNewTool() {
  const g = (k) => (document.getElementById('nt-' + k) || {}).value || '';
  return {
    id: g('id').trim(), name: g('name').trim(), subtitle: g('subtitle').trim(),
    kind: g('kind'), scope: g('scope'), product: g('product'),
    cwd: g('cwd').trim(), executable: g('executable').trim(),
    python_modules: g('python_modules').trim(), danger: g('danger'),
    command_id: g('command_id').trim(), command_label: g('command_label').trim(),
    mode: g('mode'), argv: g('argv').trim(),
  };
}

async function runNewTool(root, commit) {
  const out = document.getElementById('nt-out');
  const draft = collectNewTool();
  const showErrs = (list) => {
    out.innerHTML = `<div class="alert is-error"><b>還不能建立</b>${list.map((e) => `<div class="small">· ${esc(e)}</div>`).join('')}</div>`;
  };
  try {
    if (!commit) {
      const pv = await api.post('/api/registry/tools/preview', draft);
      if (pv.errors && pv.errors.length) { showErrs(pv.errors); return false; }
      if (pv.spec_errors && pv.spec_errors.length) { showErrs(pv.spec_errors.map((e) => e.error)); return false; }
      out.innerHTML = `<div class="alert is-info small">將寫入 <code>${esc(pv.path)}</code></div>
        <pre style="max-height:44vh;margin-top:8px">${esc(pv.text)}</pre>`;
      return false;
    }
    const r = await api.post('/api/registry/tools', draft);
    // ⚠️ 寫檔了不代表前端知道 —— 不刷新 store 就直接 navigate，新工具頁會顯示
    //    「未知的工具」。使用者的感受正是 tool_draft.py 檔頭警告的那句
    //    「建好了但不見了」，只是成因在前端（2026-08-23 範本端到端驗收）。
    await refreshStore();
    toast(`已建立 ${r.tool_id} → ${r.path}`, 'success');
    navigate(`/tool/${r.tool_id}`);
    return true;                       // 關閉 modal
  } catch (e) {
    showErrs(String(e.message || e).split('；'));
  }
  return false;                        // 有錯就留在框裡，讓人改
}

export function unmount() {}
