// #/tool/<id> 工具操作頁：commands 分頁（run／sync）、動態表單、profile、危險確認、sync 結果就地渲染、互斥鎖佔用提示
import { api, ApiError } from '../api.js';
import { $, $$, html, raw, esc, fmt, copy } from '../ui/el.js';
import { state, toolOf, productOf, setCaseProductMap, syncSelectionProducts, worstDanger } from '../store.js';
import { renderForm } from '../ui/form.js';
import { modal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';
import { navigate } from '../router.js';
import { kick } from '../poll.js';
import { md } from '../ui/docview.js';
import { spinner } from '../ui/loading.js';
import { pageLoading } from '../ui/loading.js';

let form = null;

// 危險等級的判斷抽到 `store.js` 的 `worstDanger()` —— 三個畫面共用一份。


export async function mount(root, { id, embed = false }) {
  const t = toolOf(id);
  if (!t) { root.innerHTML = `<div class="alert is-error">未知的工具：${esc(id)}</div>`; return; }
  // ⭐ `scope: workspace` 的工具（接產品／裝 memory／匯出範本）屬於**設定**，不是「挑一支工具跑一輪」
  //    —— 2026-08-24 使用者裁示。舊網址 `#/tool/setup` 轉址過去，別讓既有連結斷掉。
  if (t.scope === 'workspace' && !embed) {
    const q = location.hash.split('?')[1] || '';
    navigate(`/settings/workspace?tool=${id}${q ? '&' + q : ''}`);
    return;
  }
  // 頁首 pill：優先用點進來時帶的產品（跨產品工具從哪一欄點的），否則才退回宣告的主產品。
  // 先前恆顯示 t.product，於是 ui_tests 不論從哪欄點進來都印「CRUX」。
  const fromCol = new URLSearchParams(location.hash.split('?')[1] || '').get('product');
  const prod = productOf(fromCol && (t.products || [t.product]).includes(fromCol) ? fromCol : t.product);
  const cmds = t.commands;
  const prefill = JSON.parse(sessionStorage.getItem('tp.prefill') || 'null'); sessionStorage.removeItem('tp.prefill');
  // ★ 首次使用（main.js 因為「一個產品都沒有」把人直接送來這裡）——
  //   預設選中「接一個產品」，而不是 primary 的「工作區體檢」：
  //   體檢對還沒接產品的人沒有意義，而第一次用的人不會知道要自己切頁籤。
  const first = new URLSearchParams(location.hash.split('?')[1] || '').get('first') === '1'
    && !(state.products || []).length;
  let curCmd = (prefill && prefill.tool_id === id && cmds.find((c) => c.id === prefill.command_id))
    || (first && cmds.find((c) => c.id === 'new_product'))
    || cmds.find((c) => c.primary) || cmds[0];
  // ⭐ 頁首抽成變數：它只用得到 `t`／`prod`（都在 store 裡，同步可得），
  //    所以可以在抓資料**之前**就先畫出來 —— 見下方「先畫殼」那段。
  const headHtml = embed ? html`<div class="row" style="gap:8px;align-items:center;margin-bottom:8px">
      <b>${t.name}</b>
      <span class="tiny muted">${t.subtitle || ''}</span><span style="flex:1"></span>
      <span class="danger-lvl ${worstDanger(t)}">${{ high: '高風險 · 有不可逆的命令', medium: '中 · 會寫入', low: '低 · 本機唯讀' }[worstDanger(t)]}</span>
    </div>` : html`<div class="page-head">
      <a href="#/tools" class="crumb">← 工具</a>
      <h2><span class="pill ${prod?.id || t.product}">${prod?.label || t.product}</span>${t.name}</h2>
      <span class="crumb" style="text-transform:none;letter-spacing:0">${t.subtitle || ''}</span>
      <span style="flex:1"></span>
      <span class="danger-lvl ${worstDanger(t)}" title="取工具與所有命令的最高等級">${{ high: '高風險 · 有不可逆的命令', medium: '中 · 會寫入', low: '低 · 本機唯讀' }[worstDanger(t)]}</span>${(t.docs || []).map((d) => html`<span class="pill" title="${d}">📄 ${d.split('/').pop()}</span>`)}
    </div>`;

  let profiles = [];
  let gates = {};          // 必須在 drawForm() 被呼叫之前宣告：drawGate() 讀它，而 let 有 TDZ
  // 案例索引只在 mount 取一次，同時餵兩件事：① _products 虛擬欄位 ② write_action 判斷。
  // 先前 selectionHasWrite() 是每次按「執行」都重打整包 /api/cases，且失敗 fail-open。
  let caseFlat = null;
  let lastRuns = {};       // {command_id: 上次執行紀錄}（sync 專用，見 loadLast）
  // ⭐ 先畫殼再抓資料（2026-08-24 使用者回報「換頁後沒有載入中動畫」）——
  //    這一頁原本要等 profiles ＋ 1,201 條案例索引都回來才第一次 innerHTML，
  //    實測全空白 198ms。頁首不依賴那兩包資料，先畫出來。
  root.innerHTML = html`<div class="${embed ? 'tool-embed' : 'page'}">
    ${headHtml}
    <div class="page-body">${pageLoading('讀取工具設定…')}</div>
  </div>`;

  const [pRes, cRes] = await Promise.allSettled([
    api.get(`/api/tools/${id}/profiles`),
    t.kind === 'pytest' ? api.get('/api/cases') : Promise.resolve(null),
  ]);
  if (pRes.status === 'fulfilled') profiles = pRes.value.profiles || [];
  if (t.kind === 'pytest') {
    if (cRes.status === 'fulfilled' && cRes.value) { caseFlat = cRes.value.flat || []; setCaseProductMap(caseFlat); }
    else syncSelectionProducts();          // 取不到索引：沿用既有對照表（可能是從案例瀏覽器帶過來的）
  } else {
    syncSelectionProducts(t.products || (t.product ? [t.product] : []));
  }

  // embed＝掛在別的頁殼裡（設定頁的「工作區」分頁）：不畫 .page 外框與麵包屑，
  // 否則會疊出兩層標題、兩層捲軸。只留一行工具說明與危險等級。
  root.innerHTML = html`<div class="${embed ? 'tool-embed' : 'page'}">
    ${headHtml}
    ${first ? raw(`
    <div class="alert is-info" style="margin:0 0 10px">
      <b>👋 這是你的第一步 —— 接上第一個產品</b>
      <div class="small" style="margin-top:4px">
        這個工作區還沒有任何產品。下面這張表會<b>一次建好</b>
        <code>docs/&lt;目錄&gt;/</code>、產品 skill 骨架、交接檔，
        並註冊到 <code>config/products.json</code>（產品定義的<b>單一來源</b>）。
        ⛔ 不要手動建 —— 漏一步就不會被 lint 檢查到。
      </div>
      <div class="small" style="margin-top:4px">
        <b>先留著「只試算不寫檔」跑一次</b>看它會建什麼，確認無誤再取消勾選。
        接完後回<a href="#/">總覽</a>，儀表板就會活起來。
      </div>
    </div>`) : ''}
    <div class="tabs" id="cmd-tabs">${cmds.map((c) => html`<button class="tab-btn ${c.id === curCmd.id ? 'active' : ''}" data-cmd="${c.id}" title="${c.mode === 'run' ? '長時間執行，會進報告中心' : '同步執行，結果直接顯示'}">${c.label}${c.danger?.level === 'high' ? raw('<span class="cnt danger">高風險</span>') : ''}</button>`)}</div>
    <div class="grid" style="grid-template-columns:minmax(0,1fr) 288px;gap:12px;flex:1;min-height:0" id="tool-grid">
      <section class="card" style="display:flex;flex-direction:column;min-height:0">
        <div style="flex:1;min-height:0;overflow-y:auto;padding-right:4px">
          <div id="cmd-desc" class="card-hint"></div><div id="form"></div>
          <div id="gate-alert"></div><div id="lock-alert"></div><div id="result"></div>
        </div>
        <div class="row" style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border);flex-shrink:0"><button class="btn primary" id="btn-go">執行</button><button class="btn" id="btn-reset">重設</button><span class="muted small" id="est"></span></div>
      </section>
      <aside class="stack" style="overflow-y:auto;min-height:0">
        <section class="card"><h3>執行設定檔 <span class="cnt">${profiles.length}</span></h3>
          <div class="stack" id="profiles">${profiles.length ? profiles.map((p) => html`<div class="row between"><button class="btn sm block" data-load="${p.id}" title="${p.note || ''}" style="justify-content:flex-start">${p.label}</button><button class="btn xs ghost" data-delp="${p.id}" title="刪除">✕</button></div>`) : raw('<div class="muted small">尚無。填好參數後可「另存」。</div>')}</div>
          <button class="btn sm" id="btn-save" style="margin-top:8px">另存目前參數</button>
          <div class="tiny muted" style="margin-top:6px">secret 欄位永不寫入 profile。</div></section>
        <section class="card"><h3>最近執行</h3><div id="recent" class="stack small">${spinner("讀取中…")}</div></section>
        <section class="card"><h3>健康</h3><div id="health" class="small muted">${spinner("檢查中…")}</div></section>
      </aside></div></div>`;
  $('#cmd-tabs', root).onclick = (e) => { const b = e.target.closest('[data-cmd]'); if (!b) return; curCmd = cmds.find((c) => c.id === b.dataset.cmd); $$('.tab-btn', root).forEach((x) => x.classList.toggle('active', x.dataset.cmd === curCmd.id)); drawForm(); };
  drawForm(prefill && prefill.tool_id === id ? prefill.params : {});
  loadRecent();
  loadLast(); loadHealth(); checkLock(); loadGates();

  // 前置檢查提醒（gate）：只提示不硬擋 —— 有時就是要在環境不全的情況下跑
  async function loadGates() {
    try { gates = (await api.get(`/api/tools/${id}/checks`)).gates || {}; } catch (e) { gates = {}; }
    drawGate();
  }
  function drawGate() {
    const el = $('#gate-alert', root); if (!el) return;
    const g = gates[curCmd.id];
    if (!g) { el.innerHTML = ''; return; }
    const tone = g.state === 'failed' ? 'is-warn' : 'is-info';
    el.innerHTML = html`<div class="alert ${tone} small">${g.state === 'failed' ? '⚠ ' : ''}${g.message}
      <button class="btn xs" data-goto-check="${g.check}" style="margin-left:8px">去跑一次 →</button></div>`;
    el.querySelector('[data-goto-check]').onclick = () => {
      curCmd = cmds.find((c) => c.id === g.check) || curCmd;
      $$('.tab-btn', root).forEach((x) => x.classList.toggle('active', x.dataset.cmd === curCmd.id));
      drawForm();
    };
  }

  function drawForm(initial = {}) {
    // ⚠️ 不要再寫「秒級完成」—— `verify_platform` 是 600 秒、`crux_bet_demo.verify` 是 900 秒，
    //    而那句話正是讓人以為「怎麼還沒好、是不是掛了」的來源（2026-08-24 走查）。
    $('#cmd-desc', root).textContent = curCmd.description || (curCmd.mode === 'run'
      ? '長時執行：會建立 run 目錄、可監控、可停止、產報告。'
      : '同步命令：等它跑完，結果直接顯示在下方，不建立 run。');
    $('#result', root).innerHTML = '';
    if (curCmd.mode !== 'run') restoreLast();     // ⭐ 還原上次的結果（見 loadLast）
    form = renderForm($('#form', root), t, curCmd, initial, { onChange: (vals, errs) => estimate(vals, errs) });
    $('#btn-go', root).textContent = curCmd.mode === 'run' ? '▶ 執行' : '⚡ 執行';
    drawGate();
    estimate(form.read(), form.validate());
  }
  function estimate(vals, errs) {
    const el = $('#est', root); const bad = Object.keys(errs).length;
    $('#btn-go', root).disabled = bad > 0;
    let s = bad ? `${bad} 個欄位待修正` : '';
    if (!bad && curCmd.mode === 'run') {
      if (vals.users && vals.run_time) s = `約 ${vals.users} 名會員 × ${vals.run_time}`;
      if (t.kind === 'pytest') { const n = (window.__tp_selection || new Set()).size; s = n ? `已選 ${n} 條案例` : '⚠ 尚未選取案例 → 到案例瀏覽器勾選'; $('#btn-go', root).disabled = !n; }
    }
    el.textContent = s;
  }
  $('#btn-reset', root).onclick = () => drawForm({});
  $('#btn-go', root).onclick = go;
  $('#profiles', root).onclick = async (e) => {
    const l = e.target.closest('[data-load]'); if (l) { const p = profiles.find((x) => x.id === l.dataset.load); if (p) { if (p.command_id && p.command_id !== curCmd.id) { curCmd = cmds.find((c) => c.id === p.command_id) || curCmd; $$('.tab-btn', root).forEach((x) => x.classList.toggle('active', x.dataset.cmd === curCmd.id)); } drawForm(p.params); toast(`已載入「${p.label}」`); } }
    const d = e.target.closest('[data-delp]'); if (d && await modal.confirm('刪除 profile', `刪除「${esc(d.dataset.delp)}」？`, { danger: true })) { await api.del(`/api/tools/${id}/profiles/${d.dataset.delp}`); mount(root, { id }); }
  };
  $('#btn-save', root).onclick = async () => {
    const pid = await modal.prompt('另存執行設定檔', 'id（英數／底線），會存成 registry/profiles/' + id + '/<id>.json'); if (!pid) return;
    const label = await modal.prompt('顯示名稱', '例：日常基準 100u/30m', pid); if (label == null) return;
    try { await api.post(`/api/tools/${id}/profiles`, { id: pid, label, command_id: curCmd.id, params: form.read(), overwrite: false }); toast('已儲存', 'success'); mount(root, { id }); }
    catch (e) { if (e.status === 409 && await modal.confirm('覆蓋？', '同名 profile 已存在。')) { await api.post(`/api/tools/${id}/profiles`, { id: pid, label, command_id: curCmd.id, params: form.read(), overwrite: true }); mount(root, { id }); } else toast(e.message, 'danger'); }
  };

  async function go() {
    const vals = form.read();
    // ⚠️ 要**講出是哪一欄、錯在哪** —— 只說「請先修正欄位」等於沒說：
    //    欄位可能被捲出畫面，而 toast 幾秒就消失，人只會覺得「按了沒反應」。
    const errs = form.validate();
    if (Object.keys(errs).length) {
      const label = (k) => (form.fields || []).find((f) => f.key === k)?.label || k;
      const say = Object.entries(errs).slice(0, 3).map(([k, v]) => `${label(k)}：${v}`).join('　');
      const more = Object.keys(errs).length > 3 ? `　…另有 ${Object.keys(errs).length - 3} 個` : '';
      toast(`請先修正：${say}${more}`, 'warn', 6000);
      // 捲到第一個出問題的欄位並聚焦，不用自己找
      const first = $(`[data-key="${CSS.escape(Object.keys(errs)[0])}"]`, root);
      if (first) { first.scrollIntoView({ block: 'center' }); first.focus?.(); }
      return;
    }
    // 命令未宣告 danger 時：run 型繼承工具層（壓測本體高風險）；sync／python_call 視為 low（前置檢查、查期數這類唯讀動作不該跳真金流確認）
    const dz = curCmd.danger || (curCmd.mode === 'run' ? t.danger : null) || {};
    const level = dz.level || 'low';
    const writeSel = t.kind === 'pytest' && selectionHasWrite();
    if (level === 'high' || dz.require_typed_confirm || writeSel) {
      // 預覽由後端組（adapters/argv.py），因為只有後端知道 emit 規則、也只有它做過 visible_when 過濾。
      // ⛔ 不可回頭用 JSON.stringify(vals)：那是「表單上所有欄位」，含被條件隱藏的值與 secret 明文。
      const sel = t.kind === 'pytest' ? Array.from(window.__tp_selection || []) : [];
      let pv = null;
      try { pv = await api.post('/api/runs/preview', { tool_id: id, command_id: curCmd.id, params: vals, selection: sel }); }
      catch (e) { toast(`預覽失敗：${e.message}`, 'danger'); return; }
      const typed = dz.require_typed_confirm ? String(pv.typed_value || id) : null;
      const human = (pv.human || []).filter((x) => x.emitted !== false);
      const meta = (pv.human || []).filter((x) => x.emitted === false);
      const envRows = Object.entries(pv.env || {});
      const ok = await modal.confirm(`確認執行：${t.name} · ${curCmd.label}`, `
        ${/* ⚠️ `confirm_text` 與 gate 訊息一樣是**寫給人看的 markdown**（`**重點**`）——
              先前只有 gate 走 `md()`，confirm_text 走 `esc()`，於是星號原樣印在確認卡上
              （2026-08-24 走查 `crux_perf.api_load` 的警語時看到）。兩者統一。 */''}
        <div class="alert is-warn small md">${md(dz.confirm_text || t.danger?.confirm_text || '此操作會寫入測試站。')}</div>
        ${/* ⚠️ 工具自己的 confirm_text 通常已經講過「會寫入 QAT」——
              再補一句只是把同一件事說兩遍，反而稀釋了下面真正該讀的 gate 警告
              （2026-08-24 拍手冊截圖時看到兩句幾乎一樣的黃底提示疊在一起）。*/
          writeSel && !(dz.confirm_text || t.danger?.confirm_text)
            ? '<div class="alert is-warn small" style="margin-top:6px">選取範圍含 <b>write_action</b> 案例，會實際寫入 QAT。</div>' : ''}
        ${/* gate 的訊息是**寫給人看的 markdown**（`**重點**`、`` `路徑` ``）——
              先前直接 esc()，於是星號與反引號原樣印在確認卡上，
              最該被看到的那句反而變成一堆符號。 */
          gates[curCmd.id] ? `<div class="alert is-warn small md" style="margin-top:6px">${md(gates[curCmd.id].message)}</div>` : ''}
        <div class="confirm-sum">${human.map((x) => `<div class="row between"><span class="muted">${esc(x.label)}</span><b>${esc(x.value)}</b></div>`).join('') || '<div class="muted small">（此命令不帶參數）</div>'}</div>
        ${envRows.length ? `<div class="confirm-sum" style="margin-top:6px">${envRows.map(([k, v]) => `<div class="row between"><span class="muted">環境變數 ${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}</div>` : ''}
        ${meta.length ? `<div class="tiny muted" style="margin-top:6px">不進命令列：${meta.map((x) => esc(x.label) + '＝' + esc(x.value)).join('　')}</div>` : ''}
        <div class="tiny muted" style="margin-top:8px">實際執行的命令（工作目錄 <code>${esc(pv.cwd)}</code>）</div>
        <pre class="cmd-preview">${esc(pv.cmdline)}</pre>
        ${(pv.notes || []).map((n) => `<div class="tiny" style="color:var(--accent-amber)">⚠ ${esc(n)}</div>`).join('')}
        ${typed ? `<div class="small muted">請輸入 <b>${esc(typed)}</b> 確認</div>` : ''}`,
        { danger: true, okLabel: '執行', typed });
      if (!ok) return;
    }
    const btn = $('#btn-go', root); btn.disabled = true; btn.classList.add('loading');
    // ⭐ sync 的 timeout 最高 900 秒 —— 只有一顆轉圈的按鈕時，人分不出
    //    「還在跑」與「掛了」。計時器至少證明它還活著（2026-08-24 走查盲點 ①）。
    const tick = curCmd.mode === 'run' ? null : startTicker();
    try {
      if (curCmd.mode === 'run') {
        const sel = t.kind === 'pytest' ? Array.from(window.__tp_selection || []) : [];
        const d = await api.post('/api/runs/start', { tool_id: id, command_id: curCmd.id, params: vals, selection: sel, remark: vals.remark || '' });
        toast(`已啟動 ${d.run_id}`, 'success'); kick(); navigate(`/run/${d.run_id}`);
      } else {
        const d = await api.post('/api/runs/command', { tool_id: id, command_id: curCmd.id, params: vals });
        renderResult(d); loadGates();
      }
    } catch (e) {
      if (e.status === 409) { showLock(e); }
      else toast(e.message, 'danger', 6000);
    } finally { if (tick) tick(); btn.disabled = false; btn.classList.remove('loading'); }
  }

  /** 執行中的計時條。回一個「停止並清掉」的函式。 */
  function startTicker() {
    const el = $('#result', root); if (!el) return () => {};
    const t0 = Date.now();
    const limit = curCmd.timeout_sec || 0;
    el.innerHTML = `<div class="result-box running"><div class="row between small">
      <span>執行中 · ${esc(curCmd.label)}</span><span class="mono" id="tick">0 秒</span></div>
      <div class="tiny muted" style="margin-top:4px">${limit
        ? `這個命令最長跑 ${limit} 秒；期間請不要離開這一頁 —— 離開會中止它。`
        : '期間請不要離開這一頁 —— 離開會中止它。'}</div></div>`;
    const h = setInterval(() => {
      const el2 = $('#tick', root); if (!el2) return;
      const sec = Math.round((Date.now() - t0) / 1000);
      el2.textContent = sec < 60 ? `${sec} 秒` : `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`;
      // 逼近上限時提醒 —— 逾時的表現是「什麼都沒發生」，事先講比事後解釋有用
      if (limit && sec > limit * 0.8) el2.style.color = 'var(--accent-amber)';
    }, 1000);
    return () => clearInterval(h);
  }
  function selectionHasWrite() {
    const sel = window.__tp_selection || new Set(); if (!sel.size) return false;
    // 索引在 mount 時已取；取不到就 fail-closed —— 判不出來時寧可多跳一次確認，也不要放行寫入
    if (!caseFlat) return true;
    return caseFlat.some((c) => sel.has(c.nodeid) && (c.markers || []).includes('write_action'));
  }
  function showLock(e) {
    const el = $('#lock-alert', root);
    el.innerHTML = html`<div class="alert is-warn small">⛔ ${e.message}${e.data?.blocking_run_id ? html`　<a href="#/run/${e.data.blocking_run_id}">查看該 run →</a>` : ''}</div>`;
  }
  async function checkLock() {
    const live = (state.active || []).find((r) => r.tool_id === id && !['completed', 'failed', 'stopped'].includes(r.phase));
    if (live) $('#lock-alert', root).innerHTML = html`<div class="alert is-info small">此工具已有進行中的 run：<a href="#/run/${live.run_id}">${live.run_id}</a>（同一工具同時只能一個）</div>`;
    const grp = t.run?.exclusive_group;
    if (grp) { const other = (state.active || []).find((r) => r.tool_id !== id && !['completed', 'failed', 'stopped'].includes(r.phase) && state.tools.find((x) => x.id === r.tool_id)?.run?.exclusive_group === grp); if (other) $('#lock-alert', root).innerHTML = html`<div class="alert is-warn small">⛔ 互斥群組「${grp}」被 <a href="#/run/${other.run_id}">${other.tool_name} ${other.run_id}</a> 佔用</div>`; }
  }
  function renderResult(d, { stale = false } = {}) {
    const r = d.result || {}; const el = $('#result', root);
    let body = '';
    if (r.kind === 'checklist') body = `<div class="checklist">${(r.items || []).map((i) => `<div class="it"><span>${i.ok ? '✅' : '❌'}</span><div>${esc(i.label)}<div class="d">${esc(i.detail || '')}${i.hint ? ` · <span class="pc-crux" style="color:var(--accent-amber)">${esc(i.hint)}</span>` : ''}</div></div></div>`).join('')}</div>`;
    else if (r.kind === 'json_table') { const rows = r.rows || []; const cols = rows.length ? Object.keys(rows[0]) : []; body = `<div class="table-scroll"><table class="tbl"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${cols.map((c) => `<td class="${typeof row[c] === 'number' ? 'num' : ''}">${esc(row[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`; }
    else if (r.kind === 'copy_chip') body = `<div class="copy-chip"><span>${esc(r.label || '')}</span><b>${esc(r.value)}</b><button class="btn xs" id="cp">複製</button></div>`;
    else if (r.kind === 'artifact_dir') body = `<div class="small">輸出目錄：<code>${esc(r.dir)}</code></div><div class="row" style="margin-top:6px">${(r.files || []).map((f) => `<span class="report-link">${esc(f)}</span>`).join('')}</div>`;
    else body = `<pre>${esc(r.text || JSON.stringify(r, null, 1))}</pre>`;
    // 退出碼非 0 不代表「這次白跑了」—— verify 有失敗筆數就回 1，結果表才是要看的東西。
    // 所以只標示，不擋渲染。
    const bad = d.tool_ok === false;
    // ⭐ 「上一次的結果」要標得出來 —— 不然人會以為是剛剛按的那次
    const head = `<span>${stale ? '上次執行' : '結果'} · ${esc(curCmd.label)}`
      + (bad ? ` · <span style="color:var(--accent-amber)">退出碼 ${d.exit_code}</span>` : '') + '</span>';
    el.innerHTML = `<div class="result-box${stale ? ' is-stale' : ''}"><div class="row between small muted">${head}<span>${d.checked_at ? esc(d.checked_at) + ' · ' : ''}${d.elapsed_ms ? d.elapsed_ms + ' ms' : ''}${r.headline ? ' · ' + esc(r.headline) : ''}${r.note ? ' · ' + esc(r.note) : ''}</span></div>`
      + (d.cmdline ? `<pre class="cmd-preview" style="margin-top:6px">${esc(d.cmdline)}</pre>` : '')
      + `<div style="margin-top:8px">${body}</div>`
      + (bad && d.stderr_tail ? `<details style="margin-top:6px"><summary class="tiny muted" style="cursor:pointer">stderr 尾巴</summary><pre class="tiny">${esc(d.stderr_tail)}</pre></details>` : '')
      + nextActions(bad)
      + '</div>';
    const cp = $('#cp', el); if (cp) cp.onclick = () => { copy(r.value); toast('已複製', 'success'); };
  }

  /** 「跑完之後去哪」—— 命令用 `next` 宣告（2026-08-24 走查盲點 ②）。
   *
   * ⭐ 先前 sync 命令跑完就是一段文字，沒有任何導引。最典型的是
   *    `new_product`：**新同事接完第一個產品**，畫面上只有一段輸出。
   * ⛔ 不做自動跳轉 —— 人可能還想看輸出（`export` 的四條驗收、
   *    `new_product` 印出的「還要人做的事」）。跳走等於把結果吃掉。
   */
  function nextActions(bad) {
    const items = (curCmd.next || []).filter((n) =>
      !n.when || (n.when === 'ok' ? !bad : bad));
    if (!items.length) return '';
    const vals = form ? form.read() : {};
    return `<div class="next-actions"><span class="tiny muted">接下來</span>`
      + items.map((n) => {
        // `{欄位鍵}` 帶入這次填的值 —— 接完 alpha 產品就直接指向 #/product/alpha
        const href = n.href.replace(/\{(\w+)\}/g, (m, k) =>
          encodeURIComponent(String(vals[k] ?? '').trim()));
        // ⚠️ 佔位沒填到就不給那顆按鈕：連過去只會是壞路由
        if (/\{\w+\}/.test(href) || /\/\s*$/.test(href.replace('#/', ''))) return '';
        return `<a class="btn xs ${n.primary ? 'primary' : ''}" href="${esc(href)}">${esc(n.label)} →</a>`;
      }).join('')
      + '</div>';
  }
  /** 這支工具每個 sync 命令的最近一次執行（含完整結果）。
   *
   * ⭐ sync 不建 run 目錄，先前結果離開頁面就沒了 —— 而它佔 28/33 條命令。
   */
  async function loadLast() {
    try { lastRuns = (await api.get(`/api/tools/${id}/last-runs`)).last || {}; }
    catch (e) { lastRuns = {}; }
    if (curCmd && curCmd.mode !== 'run') restoreLast();
  }

  /** 把上次的結果畫回結果區，並標明「這是上一次的，不是剛剛跑的」。 */
  function restoreLast() {
    const rec = lastRuns[curCmd.id];
    const el = $('#result', root);
    if (!rec || !el) return;
    renderResult({ result: rec.result, cmdline: rec.cmdline, elapsed_ms: rec.elapsed_ms,
                   tool_ok: rec.tool_ok, exit_code: rec.exit_code, checked_at: rec.at },
                 { stale: true });
  }

  async function loadRecent() {
    try { const d = await api.get(`/api/runs?tool=${id}&limit=6`); $('#recent', root).innerHTML = (d.runs || []).map((r) => html`<div class="row between"><a href="#/run/${r.run_id}" class="mono tiny">${r.run_id.slice(0, 15)}</a><span class="pill tone-${{ completed: 'success', failed: 'danger', stopped: 'warn' }[r.phase] || 'info'}">${r.headline || r.phase}</span></div>`).join('') || '<span class="muted">尚無</span>'; } catch (e) { /* ignore */ }
  }
  async function loadHealth() {
    try { const d = await api.get(`/api/tools/${id}/health`); const h = d.health || {}; $('#health', root).innerHTML = (h.checks || []).map((c) => `<div>${c.ok ? '✅' : '❌'} ${esc(c.label)} <span class="muted">${esc(c.detail || '')}</span></div>`).join('') || (h.ok ? '✅ 正常' : '❌'); } catch (e) { $('#health', root).textContent = '無法取得'; }
  }
}
export function unmount() { form = null; }
