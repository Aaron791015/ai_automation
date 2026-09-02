// #/cases 案例瀏覽器：左樹（可勾選、半選）／中搜尋＋篩選 chip／右詳情／底浮動選取列（涵蓋 N 階段、含 M 條 write）
import { api } from '../api.js';
import { $, $$, html, raw, esc, debounce, copy } from '../ui/el.js';
import { state, set, setCaseProductMap, syncSelectionProducts } from '../store.js';
import { renderTree } from '../ui/tree.js';
import { toast } from '../ui/toast.js';
import { navigate } from '../router.js';
import { pageLoading } from '../ui/loading.js';

let idx = null, filters = { q: '', product: '', marker: '', prereq: false, browser: '' };

// ⚠️ 這裡顯示的是**靜態解析**結果（`pytest_case_export.py` 用 AST 抓 `allure.step`／
//    `allure.attach` 的字面文字），不是執行結果——`--collect-only` 不會真的跑案例，
//    抓不到「這次跑出來的值」。要看實際跑出來的結果，去看 allure report。
function renderStepsAndCriteria(c) {
  const scope = c.scope || [], steps = c.steps || [], criteria = c.criteria || [];
  if (!steps.length && !criteria.length) {
    return html`<div class="alert is-warn small" style="margin-top:10px">⚠️ 沒解析到步驟／判准——案例本身可能沒寫 <span class="mono">allure.step</span>／<span class="mono">allure.attach</span>，或寫法是 <span class="mono">scripts/lint_cases.py</span> 抓不到的形式（見該檔說明）</div>`;
  }
  // ★ 測試範圍：目前僅新綜合(xzh)案例會有（`allure.attach(name="測試範圍：...")`），
  //   其餘產品案例的 scope 是空陣列，這塊不會顯示，不影響既有版面。
  return html`
    ${scope.length ? html`<div style="margin-top:10px"><b>測試範圍</b><ul class="small" style="margin:4px 0 0;padding-left:20px">${scope.map((s) => html`<li>${s}</li>`)}</ul></div>` : ''}
    ${steps.length ? html`<div style="margin-top:10px"><b>步驟</b><ol class="small" style="margin:4px 0 0;padding-left:20px">${steps.map((s) => html`<li>${s}</li>`)}</ol></div>` : ''}
    ${criteria.length ? html`<div style="margin-top:8px"><b>判准（attach 佐證）</b><ul class="small" style="margin:4px 0 0;padding-left:20px">${criteria.map((s) => html`<li>${s}</li>`)}</ul></div>` : ''}
    ${c.has_assert && !criteria.length ? html`<div class="alert is-warn small" style="margin-top:6px">有 <span class="mono">assert</span> 卻沒有 <span class="mono">allure.attach</span>——判准看不到實際值 vs 期望值</div>` : ''}`;
}

export async function mount(root) {
  const qs = new URLSearchParams(location.hash.split('?')[1] || '');
  filters.q = qs.get('q') || ''; filters.product = qs.get('product') || '';
  root.innerHTML = html`<div class="page">
    <div class="page-head"><h2>案例瀏覽器</h2><span class="crumb" id="cs-cnt"></span><span style="flex:1"></span>
      <button class="btn sm" id="cs-rebuild">↻ 重建索引</button><span class="tiny muted" id="cs-meta"></span></div>
    ${/* ⭐ 產品分頁（2026-08-24 使用者要求）：擺在搜尋框**之上**，
           用來先把案例樹砍短。1,201 條全展開時，光找到自己的產品就要捲很久 ——
           而人來這一頁幾乎都已經知道自己要看哪個產品。
           ⚠️ 這一排與下面的「全部產品」下拉是**同一個 filters.product** ——
              兩個控制項共用一個狀態，不可以各記各的（那會出現「上面選 CRUX、
              下面顯示全部」這種對不起來的畫面）。 */''}
    ${/* ⭐ 新寫入待確認（2026-08-24）—— 自動寫檔省掉的是按鈕，不是「要有人看過」。
           擺在最上面且只在有待確認時出現：它是**這一頁唯一有時效性的東西**，
           其餘內容（案例樹、搜尋）隨時回來看都一樣。 */''}
    <div id="cs-newwrap"></div>
    <div class="tabs" id="cs-ptabs" style="margin:0 0 8px"></div>
    <div class="page-bar">
      <input id="cs-q" type="text" placeholder="搜尋中文標題／nodeid／函式名…" value="${filters.q}" style="flex:1;min-width:220px;padding:5px 9px;background:var(--code-bg);border:1px solid var(--border-strong);color:var(--text)">
      <select id="cs-marker"><option value="">全部標記</option><option value="smoke">smoke（不寫入）</option><option value="write_action">write_action</option><option value="none">無標記</option></select>
      <label class="small row" style="gap:4px"><input type="checkbox" id="cs-prereq"> 只看需前置</label>
      <select id="cs-browser"><option value="">瀏覽器：全部</option><option value="1">需瀏覽器</option><option value="0">純單元</option></select>
      <button class="btn sm ghost" id="cs-clear">清除選取</button>
    </div>
    <div class="grid" style="grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:10px;flex:1;min-height:0">
      <section class="card" style="display:flex;flex-direction:column;min-height:0"><div id="cs-tree" style="flex:1;min-height:0;overflow:auto">${pageLoading("讀取案例索引…")}</div></section>
      <section class="card" id="cs-detail" style="overflow:auto;min-height:0"><div class="empty small">點一條案例看詳情</div></section>
    </div>
    <div class="card page-foot" id="cs-bar" style="margin-top:10px;display:flex;align-items:center;gap:14px;flex-wrap:wrap"></div>
  </div>`;
  await load();
  if (!$('#cs-q', root)) return;      // load 期間被切走，root 已被 router 清空
  loadNewWrites(root);                // ⭐ 不 await —— 確認清單掛了不該擋住案例樹
  const re = debounce(() => { filters.q = $('#cs-q', root).value.trim().toLowerCase(); draw(); }, 150);
  $('#cs-q', root).oninput = re;
  drawProductTabs();
  $('#cs-ptabs', root).onclick = (e) => {
    const b = e.target.closest('[data-p]'); if (!b) return;
    filters.product = b.dataset.p; drawProductTabs(); draw();
  };
  $('#cs-marker', root).onchange = (e) => { filters.marker = e.target.value; draw(); };
  $('#cs-prereq', root).onchange = (e) => { filters.prereq = e.target.checked; draw(); };
  $('#cs-browser', root).onchange = (e) => { filters.browser = e.target.value; draw(); };
  $('#cs-clear', root).onclick = () => { state.selection.clear(); draw(); };
  $('#cs-rebuild', root).onclick = async () => { const b = $('#cs-rebuild', root); b.classList.add('loading'); try { const d = await api.post('/api/cases/rebuild'); toast(`已重建：${d.count} 條`, 'success'); await load(); } catch (e) { toast(e.message, 'danger'); } b.classList.remove('loading'); };

  async function load() {
    // ⚠️ router 換頁時會清空同一個 root，await 期間被切走的話這些選取器就會是 null
    try { idx = await api.get('/api/cases'); }
    catch (e) { const t = $('#cs-tree', root); if (t) t.innerHTML = `<div class="alert is-error">${esc(e.message)}</div>`; return; }
    setCaseProductMap(idx.flat);   // 供工具頁的 _products 虛擬欄位用（見 store.js）
    const meta = $('#cs-meta', root); if (!meta) return;
    meta.textContent = `${idx.generated_at || ''}${idx.stale ? '（索引更新中…）' : ''}`;
    if (idx.collect_error) meta.title = idx.collect_error;
    drawProductTabs();
    draw();
  }
  // ── 新寫入待確認 ──────────────────────────────────────────
  // ⭐ `verified` 是這份清單唯一真正的分流：跑過的掃一眼就好、
  //    沒跑過的要自己去站台走一遍 —— 給它一個一眼看得出來的記號。
  const VER_IC = { yes: '✅', partial: '◐', no: '⚠️' };
  const VER_TIP = { yes: '站台上實際跑過', partial: '只跑了一部分',
                    no: '沒有在站台上跑過 —— 這條要自己走一遍' };
  let writes = [], expanded = false;
  const openBatches = new Set();

  async function loadNewWrites(rt) {
    try { const d = await api.get('/api/case-writes'); writes = d.writes || []; }
    catch (e) { return; }                       // 拿不到就當沒有，不吵人
    // ⭐ `#/cases?write=<路徑>`：從「待確認」的產出連結點過來時，
    //    直接展開並打開那一批 —— 只到列表首頁的話，人要在 1,201 條裡自己找。
    const want = qs.get('write');
    if (want) {
      const hit = writes.find((w) => w.path === want);
      if (hit) { expanded = true; openBatches.add(hit.path); }
      else toast('找不到那一批案例（可能檔案已被刪或改名）', 'warn');
    }
    drawNewWrites(rt);
    bindNewWrites(rt);
    if (want) {
      requestAnimationFrame(() => {
        const el = $('#cs-newwrap', rt);
        if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
      });
    }
  }

  function drawNewWrites(rt) {
    const wrap = $('#cs-newwrap', rt); if (!wrap) return;
    const pending = writes.filter((w) => !w.acked);
    if (!pending.length && !expanded) { wrap.innerHTML = ''; return; }
    const cnt = pending.reduce((n, w) => n + (w.collected || 0), 0);
    const unver = pending.reduce((n, w) => n + (w.unverified || 0), 0);
    wrap.innerHTML = html`<div class="newwrite-bar${pending.length ? '' : ' done'}">
      <span class="nw-ic">${pending.length ? '🆕' : '✓'}</span>
      <span>${pending.length
        ? html`<b>${pending.length}</b> 批新案例待確認 · 共 <b>${cnt}</b> 條${
            unver ? html`<span>（<b class="warn">${unver}</b> 條沒在站台上跑過）</span>` : ''}`
        : '新寫入的案例都確認過了'}</span>
      <span style="flex:1"></span>
      <button class="btn xs" data-nw-toggle>${expanded ? '收起' : '逐份檢視'}</button></div>
      ${expanded ? html`<div class="newwrite-list">${writes.map(batchRow)}</div>` : ''}`;
  }

  /** 一批＝一次寫檔。展開後才列每一條案例（一批可能十來條，全展開會很長）。 */
  function batchRow(w, i) {
    const open = openBatches.has(w.path);
    return html`<div class="nw-batch${w.acked ? ' is-acked' : ''}">
      <div class="nw-head">
        <label class="nw-ack" title="${w.acked ? '已確認於 ' + (w.ack_at || '') : '看完這一批就打勾'}">
          <input type="checkbox" data-nw-ack="${i}" ${w.acked ? raw('checked') : ''}> 已確認</label>
        <a href="#" class="nw-title" data-nw-open="${i}">${w.title || w.path}</a>
        ${w.product ? html`<span class="pill ${w.product}">${w.product}</span>` : ''}
        <span class="tiny mono muted">${w.path}</span>
        <span class="tiny muted">${w.collected} 條 · ${w.at || ''}</span>
        ${w.stale ? html`<span class="pill tone-warn" title="確認之後這個檔又被改過">已更新</span>` : ''}
        <span style="flex:1"></span>
        ${w.unverified ? html`<span class="pill tone-warn" title="這幾條 session 沒有在站台上實際跑過">${w.unverified} 條沒跑過</span>` : ''}
        <button class="btn xs" data-nw-code="${i}">看程式碼</button>
        <button class="btn xs ghost" data-nw-more="${i}">${open ? '收起' : '看案例'}</button>
      </div>
      ${open ? html`<ul class="nw-cases">${(w.cases || []).map((c) => html`<li>
        <span class="nw-v ${c.verified}" title="${VER_TIP[c.verified] || VER_TIP.no}">${VER_IC[c.verified] || VER_IC.no}</span>
        <span>${c.title}</span>
        ${(c.markers || []).map((m) => html`<span class="pill tiny">${m}</span>`)}
        ${c.note ? html`<span class="tiny muted">${c.note}</span>` : ''}
      </li>`)}</ul>` : ''}
    </div>`;
  }

  async function showCode(w) {
    const { modal } = await import('../ui/modal.js');
    let d;
    try { d = await api.get('/api/cases/source?path=' + encodeURIComponent(w.path)); }
    catch (e) { toast(e.message, 'danger'); return; }
    const body = document.createElement('div');
    body.className = 'docview';
    body.innerHTML = html`<div class="row between tiny muted docview-head">
      <span class="mono">${d.path}</span><span>${d.lines} 行</span></div>
      <div class="docview-body raw"><pre class="doc-raw"></pre></div>`;
    body.querySelector('pre').textContent = d.text;
    const m = modal.open({ title: w.title || w.path.split('/').pop(), body, size: 'doc',
      actions: [{ label: '複製路徑', onClick: () => { copy(d.path); toast('已複製', 'success'); return false; } },
                { label: '關閉' }] });
    m.box.classList.add('no-scroll');
  }

  function bindNewWrites(rt) {
    const wrap = $('#cs-newwrap', rt); if (!wrap) return;
    const repaint = () => { drawNewWrites(rt); bindNewWrites(rt); };
    wrap.onclick = async (e) => {
      if (e.target.closest('[data-nw-toggle]')) { expanded = !expanded; repaint(); return; }
      const mo = e.target.closest('[data-nw-more]');
      if (mo) {
        const w = writes[Number(mo.dataset.nwMore)];
        if (openBatches.has(w.path)) openBatches.delete(w.path); else openBatches.add(w.path);
        repaint(); return;
      }
      const cd = e.target.closest('[data-nw-code]');
      if (cd) { showCode(writes[Number(cd.dataset.nwCode)]); return; }
      const op = e.target.closest('[data-nw-open]');
      if (op) {
        e.preventDefault();     // ⭐ <a href="#"> 不擋的話 hash 變 "#" 會跳回總覽
        // ⭐ 點標題＝順手把案例樹篩到這一批的產品，人可以就地對照
        const w = writes[Number(op.dataset.nwOpen)];
        if (w.product) { filters.product = w.product; drawProductTabs(); draw(); }
        showCode(w);
      }
    };
    wrap.onchange = async (e) => {
      const cb = e.target.closest('[data-nw-ack]'); if (!cb) return;
      const w = writes[Number(cb.dataset.nwAck)];
      try {
        const d = await api.post('/api/case-writes/ack', { path: w.path, acked: cb.checked });
        Object.assign(w, d);
        repaint();
      } catch (err) { cb.checked = !cb.checked; toast(err.message, 'danger'); }
    };
  }

  function filterFn(c) {
    if (filters.product && c.product !== filters.product) return false;
    if (filters.marker === 'smoke' && !c.markers.includes('smoke')) return false;
    if (filters.marker === 'write_action' && !c.markers.includes('write_action')) return false;
    if (filters.marker === 'none' && c.markers.length) return false;
    if (filters.prereq && !c.needs_prereq) return false;
    if (filters.browser === '1' && !c.needs_browser) return false;
    if (filters.browser === '0' && c.needs_browser) return false;
    if (filters.q && !(c.title + ' ' + c.nodeid + ' ' + c.func).toLowerCase().includes(filters.q)) return false;
    return true;
  }
  /** 產品分頁：一排按鈕 ＋ 各自的案例數。數字直接取自索引的 `by_product`。 */
  function drawProductTabs() {
    const box = $('#cs-ptabs', root); if (!box || !idx) return;
    const by = idx.by_product || {};
    // ⚠️ 只列**真的有案例**的產品 —— 列出 0 條的分頁只是雜訊，
    //    而且它會讓人以為「這個產品的案例不見了」。
    const items = (state.products || [])
      .filter((p) => (by[p.id]?.total || 0) > 0)
      .map((p) => [p.id, p.short || p.label, by[p.id].total]);
    const total = idx.count || 0;
    box.innerHTML = html`<button class="tab-btn ${filters.product ? '' : 'active'}" data-p="">全部<span class="cnt">${total}</span></button>`
      + items.map(([id, label, n]) => html`<button class="tab-btn ${filters.product === id ? 'active' : ''}" data-p="${id}"><span class="pc-${id}">${label}</span><span class="cnt">${n}</span></button>`).join('');
  }

  function draw() {
    if (!idx) return;
    const anyFilter = filters.q || filters.product || filters.marker || filters.prereq || filters.browser;
    // ⚠️ 2026-08-28 修正：`expandAll` 原本跟 `anyFilter` 綁在一起，導致單純點「新綜合」
    // 這類產品分頁（只是縮小顯示範圍，不是在裡面搜東西）也會被強制全展開，
    // 使用者完全無法再收合裡面的檔案／子頁節點——「可以展開/收合」的訴求因此形同虛設。
    // 只有真的「在裡面找東西」（文字搜尋／標記／前置／瀏覽器篩選）才需要自動展開好讓
    // 命中結果看得見；純粹選產品分頁不該連帶關掉收合功能。
    const searching = filters.q || filters.marker || filters.prereq || filters.browser;
    renderTree($('#cs-tree', root), idx.tree || [], { selection: state.selection, filter: anyFilter ? filterFn : null, expandAll: !!searching, onToggle: () => { window.__tp_selection = state.selection; syncSelectionProducts(); drawBar(); }, onOpenCase: openCase });
    const total = idx.count || 0, vis = anyFilter ? (idx.flat || []).filter(filterFn).length : total;
    $('#cs-cnt', root).textContent = anyFilter ? `${vis} / ${total} 條` : `${total} 條`;
    drawBar();
  }
  function drawBar() {
    const sel = state.selection; const bar = $('#cs-bar', root);
    const cases = (idx.flat || []).filter((c) => sel.has(c.nodeid));
    const stages = new Set(cases.map((c) => c.stage).filter(Boolean));
    const needPre = cases.filter((c) => c.needs_prereq && !cases.some((x) => x.stage === c.requires_stage));
    const write = cases.filter((c) => c.markers.includes('write_action')).length;
    const prods = new Set(cases.map((c) => c.product));
    bar.innerHTML = html`<div><b class="mono">${sel.size}</b> 條已選${stages.size ? html` · 涵蓋 <b>${stages.size}</b> 個階段` : ''}${write ? html` · 含 <b style="color:var(--danger)">${write}</b> 條 write_action` : ''}${prods.size > 1 ? html` · <span style="color:var(--accent-amber)">跨 ${prods.size} 個產品</span>` : ''}</div>
      ${needPre.length ? html`<div class="alert is-warn small">🔗 ${needPre.length} 條需先跑前置階段（wbot 階段0）而未選 → <button class="btn xs" id="cs-addpre">自動加入階段0</button></div>` : ''}
      <div style="margin-left:auto" class="row"><button class="btn sm ghost" id="cs-copy" ${sel.size ? '' : 'disabled'}>複製 nodeid</button><button class="btn primary" id="cs-run" ${sel.size ? '' : 'disabled'}>▶ 執行選取（${sel.size}）</button></div>`;
    $('#cs-run', bar).onclick = () => { window.__tp_selection = state.selection; navigate('/tool/ui_tests'); };
    $('#cs-copy', bar).onclick = () => { copy(Array.from(sel).join('\n')); toast('已複製 nodeid 清單', 'success'); };
    const ap = $('#cs-addpre', bar); if (ap) ap.onclick = () => { (idx.flat || []).filter((c) => c.stage === 'wbot_z0').forEach((c) => sel.add(c.nodeid)); draw(); toast('已加入階段0', 'success'); };
  }
  function openCase(nodeid) {
    const c = (idx.flat || []).find((x) => x.nodeid === nodeid); if (!c) return;
    const a = c.allure || {};
    $('#cs-detail', root).innerHTML = html`
      <h3 style="margin:0 0 6px;font-size:1rem">${c.title}</h3>
      <div class="row"><span class="pill ${c.product}">${c.product}</span>${c.markers.map((m) => html`<span class="pill ${m === 'write_action' ? 'write' : m === 'smoke' ? 'smoke' : ''}">${m}</span>`)}${c.needs_prereq ? html`<span class="pill prereq">🔗 需先跑 ${c.requires_stage}</span>` : ''}${c.needs_browser ? html`<span class="pill">Playwright</span>` : html`<span class="pill">純單元</span>`}${c.stage_label ? html`<span class="pill">${c.stage_label}</span>` : ''}</div>
      <table class="tbl small" style="margin-top:10px">
        <tr><th>nodeid</th><td class="mono">${c.nodeid} <button class="btn xs ghost" id="cd-copy">複製</button></td></tr>
        <tr><th>檔案</th><td class="mono">${c.file}:${c.lineno}</td></tr>
        <tr><th>函式</th><td class="mono">${c.func}${c.param_id ? html` <span class="muted">[${c.param_id}]</span>` : ''}</td></tr>
        <tr><th>標題來源</th><td>${{ allure_title: '@allure.title', docstring: 'docstring 首行', function_name: '函式名（建議補 @allure.title）' }[c.title_source]}</td></tr>
        ${a.feature?.length ? html`<tr><th>feature</th><td>${a.feature.join(' / ')}</td></tr>` : ''}
        ${a.story?.length ? html`<tr><th>story</th><td>${a.story.join(' / ')}</td></tr>` : ''}
        ${a.parent_suite ? html`<tr><th>suite</th><td>${a.parent_suite} › ${a.suite} › ${a.sub_suite}</td></tr>` : ''}
        <tr><th>fixtures</th><td class="mono tiny">${(c.fixtures || []).join(', ')}</td></tr>
      </table>
      ${renderStepsAndCriteria(c)}
      <div class="row" style="margin-top:10px"><button class="btn sm ${state.selection.has(nodeid) ? '' : 'primary'}" id="cd-sel">${state.selection.has(nodeid) ? '取消選取' : '加入選取'}</button><button class="btn sm" id="cd-only">只跑這一條</button></div>`;
    $('#cd-copy', root).onclick = () => { copy(c.nodeid); toast('已複製', 'success'); };
    $('#cd-sel', root).onclick = () => { state.selection.has(nodeid) ? state.selection.delete(nodeid) : state.selection.add(nodeid); draw(); openCase(nodeid); };
    $('#cd-only', root).onclick = () => { state.selection.clear(); state.selection.add(nodeid); if (c.needs_prereq) (idx.flat || []).filter((x) => x.stage === c.requires_stage).forEach((x) => state.selection.add(x.nodeid)); window.__tp_selection = state.selection; navigate('/tool/ui_tests'); };
  }
}
export function unmount() {}
