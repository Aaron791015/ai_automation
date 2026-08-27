// #/reports 報告中心：跨工具 run 清單＋篩選、趨勢（純 inline SVG）、內嵌檢視
import { api } from '../api.js';
import { openDoc } from '../ui/docview.js';
import { $, $$, html, raw, esc, fmt } from '../ui/el.js';
import { state } from '../store.js';
import { sparkline, dot } from '../ui/hud.js';
import { modal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';

export async function mount(root) {
  let f = { product: '', tool: '', status: '' };
  root.innerHTML = html`<div class="page">
    <div class="page-head"><h2>報告中心</h2><span class="crumb" id="rp-cnt"></span></div>
    <!-- ⭐ 2026-08-24 使用者裁示：**驗證報告排第一**。
         這一頁叫「報告中心」，而人來這裡要找的是**寫給人看的那份報告**；
         「執行紀錄」是機器產出的原始資料，屬於追查時才會打開的第二層。 -->
    <div class="tabs" id="rp-tabs">
      <button class="tab-btn active" data-view="docs">驗證報告 <span class="cnt" id="rp-doccnt"></span></button>
      <button class="tab-btn" data-view="runs">執行紀錄</button>
    </div>
    <div class="page-bar" id="rp-bar">
      <select id="rp-prod"><option value="">全部產品</option>${(state.products || []).map((p) => html`<option value="${p.id}">${p.label}</option>`)}</select>
      <select id="rp-tool"><option value="">全部工具</option>${(state.tools || []).map((t) => html`<option value="${t.id}">${t.name}</option>`)}</select>
      <div class="seg" id="rp-status" role="tablist">
        ${[['', '全部'], ['completed', '完成'], ['failed', '失敗'], ['stopped', '已停止']].map(([v, l], i) =>
          html`<button class="seg-btn ${i === 0 ? 'active' : ''}" data-v="${v}">${l}</button>`)}
      </div>
    </div>
    <div class="grid two" id="rp-trend" style="flex-shrink:0"></div>
    <section class="card" style="margin-top:10px;flex:1;min-height:0;display:flex;flex-direction:column">
      <div id="rp-cmpbar" class="row" style="display:none;gap:8px;padding-bottom:8px;border-bottom:1px solid var(--border);margin-bottom:6px">
        <span class="small" id="rp-cmpnote"></span><span style="flex:1"></span>
        <button class="btn sm primary" id="rp-cmpgo" disabled>對比這兩次</button>
        <button class="btn sm ghost" id="rp-cmpclr">清除</button></div>
      <div class="table-scroll" style="flex:1;min-height:0"><table class="tbl small" id="rp-tbl"></table></div></section>
  </div>`;
  // ── 分頁：執行紀錄 ／ 驗證報告 ─────────────────────────
  //    `bugs/_reports/` 是**人寫給人看**的產出（需求驗證、JIRA 重驗、效能）——
  //    先前平台上完全沒有入口，落了檔也看不到（2026-08-23）。
  $('#rp-tabs', root).onclick = async (e) => {
    const b = e.target.closest('[data-view]');
    if (!b) return;
    $$('.tab-btn', $('#rp-tabs', root)).forEach((x) => x.classList.toggle('active', x === b));
    const isDocs = b.dataset.view === 'docs';
    $('#rp-bar', root).style.display = isDocs ? 'none' : '';
    $('#rp-trend', root).style.display = isDocs ? 'none' : '';
    if (isDocs) await loadDocs(); else await load();
  };
  async function loadDocs() {
    const box = $('#rp-tbl', root);
    let d;
    try { d = await api.get('/api/verification-reports'); }
    catch (err) { box.innerHTML = `<tbody><tr><td class="muted">讀不到報告：${esc(err.message)}</td></tr></tbody>`; return; }
    const items = d.reports || [];
    $('#rp-doccnt', root).textContent = items.length || '';
    $('#rp-cnt', root).textContent = `${items.length} 份 · 已確認 ${d.acked || 0}`;
    if (!items.length) {
      box.innerHTML = '<tbody><tr><td class="muted">還沒有驗證報告 —— 跑「需求驗證」或「驗 JIRA 修復」任務會產出。</td></tr></tbody>';
      return;
    }
    // ⭐「已確認」勾選框（2026-08-24 使用者要求）——「哪些已經確認完畢、哪些還沒看」。
    //    ⚠️ 它是**閱讀狀態**，存平台這邊（`logs/acks.json`），不動報告本身。
    //    報告被改過會自動退回未確認並標「已更新」—— 只記「看過」的話，
    //    內容變了畫面還是綠的，那比沒有標記更糟（會讓人跳過新內容）。
    box.innerHTML = html`<thead><tr><th title="看完了就打勾">✓</th><th>日期</th><th>類型</th><th>標題</th><th>產品</th><th>檔案</th><th></th></tr></thead>
      <tbody>${items.map((r, i) => html`<tr class="${r.acked ? 'is-acked' : ''}">
        <td><input type="checkbox" class="rp-ack" data-ack="${i}" ${r.acked ? raw('checked') : ''}
            title="${r.acked ? '已確認於 ' + (r.at || '') : (r.stale ? '確認過，但報告之後又被改了' : '還沒確認')}"></td>
        <td class="tiny mono">${r.date || r.mtime}${r.stale ? html`<span class="pill tone-warn" title="確認之後檔案又被改過">已更新</span>` : ''}</td>
        <td><span class="pill">${r.kind}</span></td>
        ${/* ⭐ 2026-08-24 使用者：「列表標題應可以點擊併開啟」——
               先前只有最右邊那顆「看全文」可點，而人的直覺是點標題。
               按鈕留著（它明說得出「會發生什麼」），標題只是多一個入口。 */''}
        <td><a href="#" class="row-open" data-open="${i}">${r.title || '（無標題）'}</a></td>
        <td class="tiny">${r.product}</td>
        <td class="tiny mono" title="${r.path}">${r.name}</td>
        <td><button class="btn xs primary" data-open="${i}">看全文</button></td>
      </tr>`)}</tbody>`;
    box.onclick = (e) => {
      const b2 = e.target.closest('[data-open]');
      if (!b2) return;
      e.preventDefault();          // ⛔ 標題是 <a href="#">，不擋的話 hash 變 "#" → 跳回總覽
      const r = items[Number(b2.dataset.open)];
      openDoc(r.path, { title: r.title || r.name });
    };
    // 勾選要用 change（checkbox 的 click 也會冒泡到上面那個 onclick，但 data-open 撈不到就 return 了）
    box.onchange = async (e) => {
      const cb = e.target.closest('[data-ack]'); if (!cb) return;
      const r = items[Number(cb.dataset.ack)];
      try {
        const d = await api.post('/api/verification-reports/ack', { path: r.path, acked: cb.checked });
        Object.assign(r, d);
        cb.closest('tr').classList.toggle('is-acked', !!d.acked);
        cb.title = d.acked ? '已確認於 ' + (d.at || '') : '還沒確認';
        const n = items.filter((x) => x.acked).length;
        $('#rp-cnt', root).textContent = `${items.length} 份 · 已確認 ${n}`;
      } catch (err) { cb.checked = !cb.checked; toast(err.message, 'danger'); }
    };
  }

  ['prod', 'tool'].forEach((k) => ($(`#rp-${k}`, root).onchange = (e) => { f[k === 'prod' ? 'product' : k] = e.target.value; load(); }));
  // 狀態改用膠囊分段控制（對齊參考圖的 1D/1W/1M 那種切換）
  $('#rp-status', root).onclick = (e) => {
    const b = e.target.closest('.seg-btn'); if (!b) return;
    $$('#rp-status .seg-btn', root).forEach((x) => x.classList.toggle('active', x === b));
    f.status = b.dataset.v; load();
  };
  // 預設分頁＝驗證報告 → 篩選列與趨勢圖（都只服務「執行紀錄」）先收起來
  $('#rp-bar', root).style.display = 'none';
  $('#rp-trend', root).style.display = 'none';
  await loadDocs();
  bindCompare(root);
  async function load() {
    const q = new URLSearchParams({ limit: 200, ...(f.product && { product: f.product }), ...(f.tool && { tool: f.tool }), ...(f.status && { status: f.status }) });
    let rows = [];
    try { rows = (await api.get('/api/runs?' + q)).runs || []; } catch (e) { $('#rp-tbl', root).innerHTML = `<tr><td class="alert is-error">${esc(e.message)}</td></tr>`; return; }
    $('#rp-cnt', root).textContent = `${rows.length} 筆`;
    // 趨勢
    const py = rows.filter((r) => r.kind === 'pytest' && r.summary).slice(0, 30).reverse();
    const pf = rows.filter((r) => r.kind === 'cli' && r.summary?.total_bets != null).slice(0, 30).reverse();
    $('#rp-trend', root).innerHTML = html`
      <section class="card"><h3>pytest 通過率 <span class="cnt">最近 ${py.length} 次</span></h3>${raw(sparkline(py.map((r) => { const s = r.summary; const t = (s.passed || 0) + (s.failed || 0) + (s.skipped || 0); return t ? (s.passed || 0) / t * 100 : 0; }), { w: 420, h: 60, max: 100 }))}<div class="tiny muted">縱軸 0–100%</div></section>
      <section class="card"><h3>壓測累計注數 <span class="cnt">最近 ${pf.length} 次</span></h3>${raw(sparkline(pf.map((r) => r.summary.total_bets), { w: 420, h: 60 }))}<div class="tiny muted">各工具混列，僅供量級參考</div></section>`;
    // ★ 分批塞列，不要一次寫進 200 列。
    //   一列 9 格，200 列就是約 1,800 個儲存格 —— 一次 innerHTML 實測會產生
    //   **71ms 與 89ms 兩個 long task**（PerformanceObserver 量到），換到報告頁就是明顯一頓。
    //   先塞滿一屏的量，其餘每個 rAF 補一批：總時間差不多，但**每一幀都還得動**，
    //   使用者感受到的是順的（2026-08-21 使用者回報「頁面轉換不夠滑順」）。
    const tbl = $('#rp-tbl', root);
    tbl.innerHTML = '<thead><tr><th></th><th></th><th>run_id</th><th>工具</th><th>產品</th><th>結果</th><th>時長</th><th>開始</th><th>備註</th><th>報告</th></tr></thead><tbody></tbody>';
    const tb = tbl.querySelector('tbody');
    const my = ++renderToken;
    let i = 0;
    const step = () => {
      // ⚠️ 兩道保險：token 過期（又載入了一次）或節點已被卸下，就停手
      if (my !== renderToken || !tb.isConnected) return;
      const part = rows.slice(i, i + CHUNK);
      if (!part.length) return;
      tb.insertAdjacentHTML('beforeend', part.map(rowHtml).join(''));
      i += CHUNK;
      if (i < rows.length) requestAnimationFrame(step);
    };
    step();
  }
}

const CHUNK = 25;              // 一批的列數：略少於一屏，讓第一批夠便宜
let renderToken = 0;           // 分批塞列的續行守衛（換頁或重新載入時作廢）

// 首欄 checkbox：只有「有 summary」的 run 才選得起來 —— 沒有 summary 就沒有共同指標可比
// ⚠️ Demo 假歷史只有索引列、沒有 run 目錄，點進去必定 404 —— 標示出來並且不導頁
const rowHtml = (r) => html`<tr class="clickable" onclick="location.hash='#/run/${r.run_id}'"><td onclick="event.stopPropagation()">${r.summary ? html`<input type="checkbox" class="rp-pick" data-rid="${r.run_id}">` : ''}</td><td>${raw(dot(r.phase))}</td><td class="mono tiny">${r.run_id}</td><td>${r.tool_name}</td><td><span class="pill ${r.product}">${r.product}</span></td><td>${r.headline || r.phase}</td><td class="num">${fmt.dur(r.duration_sec)}</td><td class="tiny muted">${r.started_at}</td><td class="tiny">${r.remark || ''}</td><td>${r.primary_report ? html`<a class="report-link" href="${r.primary_report}" target="_blank" onclick="event.stopPropagation()">報告</a>` : ''}</td></tr>`;


// ── run 對比（最多兩筆）。判準是 summary.kind：crux_perf 可比 qixing_perf，pytest 不能比 perf。
let picked = [];
function bindCompare(root) {
  const bar = $('#rp-cmpbar', root), note = $('#rp-cmpnote', root), go = $('#rp-cmpgo', root);
  const sync = () => {
    bar.style.display = picked.length ? 'flex' : 'none';
    note.textContent = picked.length === 1 ? `已選 1 筆，再選一筆即可對比` : picked.length === 2 ? `已選 ${picked.join('　vs　')}` : '';
    go.disabled = picked.length !== 2;
  };
  $('#rp-tbl', root).addEventListener('change', (e) => {
    const cb = e.target.closest('.rp-pick'); if (!cb) return;
    const rid = cb.dataset.rid;
    if (cb.checked) {
      if (picked.length >= 2) { cb.checked = false; toast('一次只能對比兩筆，請先清除', 'warn'); return; }
      picked.push(rid);
    } else picked = picked.filter((x) => x !== rid);
    sync();
  });
  $('#rp-cmpclr', root).onclick = () => { picked = []; $$('.rp-pick', root).forEach((c) => (c.checked = false)); sync(); };
  go.onclick = async () => {
    let d;
    try { d = await api.get('/api/runs/compare?ids=' + picked.join(',')); }
    catch (e) { toast(e.message, 'warn', 6000); return; }
    modal.open({ title: '執行對比', wide: true, body: compareBody(d), actions: [{ label: '關閉', cls: 'primary' }] });
  };
  sync();
}

function compareBody(d) {
  const [a, b] = d.runs;
  const head = `<div class="grid two" style="gap:10px">${[a, b].map((r, i) => `
    <div class="confirm-sum" style="margin-top:0">
      <div class="row between"><span class="muted">${i ? 'B' : 'A'}</span><b class="mono tiny">${esc(r.run_id)}</b></div>
      <div class="row between"><span class="muted">工具</span><b>${esc(r.tool_name || r.tool_id)}　${esc(r.command_label || '')}</b></div>
      <div class="row between"><span class="muted">開始</span><b>${esc(r.started_at || '')}</b></div>
      <div class="row between"><span class="muted">狀態</span><b>${esc(r.phase)}${r.summary?.partial ? '（中途停止）' : ''}</b></div>
      ${r.remark ? `<div class="row between"><span class="muted">備註</span><b>${esc(r.remark)}</b></div>` : ''}
    </div>`).join('')}</div>`;

  const arrow = (m) => {
    if (m.delta == null) return `<span class="muted">—</span>`;
    if (!m.delta) return `<span class="muted">持平</span>`;
    const up = m.delta > 0;
    return `<span style="color:var(--${up ? 'accent' : 'accent-amber'})">${up ? '▲' : '▼'} ${Math.abs(m.delta)}${m.pct != null ? `（${up ? '+' : ''}${m.pct}%）` : ''}</span>`;
  };
  const metrics = (d.metrics || []).length
    ? `<table class="tbl small"><thead><tr><th>指標</th><th class="num">A</th><th class="num">B</th><th>變化</th></tr></thead><tbody>${
        d.metrics.map((m) => `<tr><td>${esc(METRIC_LABEL[m.key] || m.key)}</td><td class="num">${esc(m.a)}</td><td class="num">${esc(m.b)}</td><td>${arrow(m)}</td></tr>`).join('')}</tbody></table>`
    : '<div class="muted small">兩次的 summary 沒有可比的數值欄位。</div>';

  const shortId = (n) => esc(String(n).split('::').pop().slice(0, 40));
  const params = (d.params || []).length
    ? `<table class="tbl small"><thead><tr><th>參數</th><th>A</th><th>B</th></tr></thead><tbody>${
        d.params.map((p) => `<tr><td>${esc(p.key)}</td><td>${esc(p.a ?? '—')}</td><td>${esc(p.b ?? '—')}
          ${p.added_n || p.removed_n ? `<div class="tiny muted">
            ${p.added_n ? `＋${p.added_n}：${p.added.map(shortId).join('、')}${p.added_n > p.added.length ? ' …' : ''}<br>` : ''}
            ${p.removed_n ? `−${p.removed_n}：${p.removed.map(shortId).join('、')}${p.removed_n > p.removed.length ? ' …' : ''}` : ''}
          </div>` : ''}</td></tr>`).join('')}</tbody></table>`
    : '<div class="muted small">兩次的參數完全相同。</div>';

  const g = d.regression;
  const grp = (title, hint, items, tone) => `<div style="margin-top:8px">
    <div class="row"><b style="color:var(--${tone})">${title} ${items.length}</b><span class="tiny muted" style="margin-left:8px">${hint}</span></div>
    ${items.length ? `<table class="tbl small">${items.map((c) => `<tr><td>${esc(c.title || c.nodeid)}<div class="mono tiny muted">${esc(c.nodeid)}</div></td></tr>`).join('')}</table>`
      : '<div class="muted tiny">（無）</div>'}</div>`;
  const reg = g ? `${grp('🔴 新壞的', '前一次過、這次壞 ＝ 回歸，最該先看', g.newly_broken, 'danger')}
    ${grp('🟢 修好的', '前一次壞、這次過 ＝ 修復生效的佐證', g.fixed, 'success')}
    ${grp('⚪ 一直壞的', '兩次都壞 ＝ 本次沒有變化', g.still_broken, 'text-dim')}` : '';

  const box = document.createElement('div');
  box.innerHTML = `${head}
    <h4 style="margin:12px 0 4px">指標</h4>${metrics}
    ${reg ? `<h4 style="margin:12px 0 4px">回歸差異</h4>${reg}` : ''}
    <h4 style="margin:12px 0 4px">參數差異</h4>${params}`;
  return box;
}

const METRIC_LABEL = {
  passed: '通過', failed: '失敗', skipped: '略過', duration_sec: '時長（秒）',
  total_bets: '累計注數', fail_ratio: '失敗率', periods_seen: '經歷期數', users: '併發會員數',
  rps: '每秒請求', p95_ms: 'P95 延遲（ms）', rtt_p95_ms: 'RTT P95（ms）', ack_rate: '回應率', cancelled: '取消數',
};

export function unmount() { renderToken++; picked = []; }
