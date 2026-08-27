// 待辦與 Bug 現況面板（四產品分頁）：上方四個交叉狀態行動卡、blocker 置頂、下方待辦列表（只顯示摘要，點開看全文）
import { api } from '../api.js';
import { $, $$, html, raw, esc, copy } from './el.js';
import { state } from '../store.js';
import { modal } from './modal.js';
import { navigate } from '../router.js';
import { md, openDoc } from './docview.js';
import { toast } from './toast.js';
import { spinner } from './loading.js';

// md() 現由 docview.js 提供（同一支渲染器，行內與全文共用）；此處再匯出以維持既有 import 路徑
export { md };

const CROSS = [
  ['revisit', '待重驗', '本地 open × JIRA 已完成'],
  ['unfiled', '漏開單', '本地 open × 未開 JIRA'],
  ['to_close', '該關單', '本地已修 × JIRA 仍 open'],
  ['no_regr', '缺回歸', 'regression 待補'],
];

export async function renderTodoPanel(container, { product = null } = {}) {
  const prods = (state.products || []).filter((p) => p.id !== 'common' || true);
  let cur = product || sessionStorage.getItem('tp.todoTab') || 'crux';
  container.innerHTML = html`<h3>待辦與 Bug 現況 <span class="cnt" id="tb-jira"></span></h3>
    <div class="tabs">${prods.map((p) => html`<button class="tab-btn ${p.id === cur ? 'active' : ''}" data-tab="${p.id}"><span class="pc-${p.id}">${p.label}</span><span class="cnt" data-cnt="${p.id}"></span></button>`)}</div>
    <div id="tb-body">${spinner("讀取待辦…")}</div>`;
  container.querySelector('.tabs').onclick = (e) => { const b = e.target.closest('[data-tab]'); if (!b) return; cur = b.dataset.tab; sessionStorage.setItem('tp.todoTab', cur); $$('.tab-btn', container).forEach((x) => x.classList.toggle('active', x.dataset.tab === cur)); draw(); };
  let bugsAll = null, todosAll = null;
  try { [bugsAll, todosAll] = await Promise.all([api.get('/api/bugs'), api.get('/api/todos')]); } catch (e) { $('#tb-body', container).innerHTML = `<div class="alert is-error">${esc(e.message)}</div>`; return; }
  // 「未設定」是**還沒做的事**，不是錯誤 —— 給一條可以點過去的路
  //（計畫 F-2：顯示「JIRA 未設定」＋一鍵到設定頁。2026-08-23 情境 B 走查）
  const js = bugsAll.jira_source;
  const el = $('#tb-jira', container);
  if (js === '未設定') {
    el.innerHTML = 'JIRA 未設定 · <a href="#/settings/credentials">去設定 →</a>';
  } else {
    el.textContent = `JIRA：${js}${bugsAll.jira_fetched_at ? ' · ' + bugsAll.jira_fetched_at : ''}`;
  }
  prods.forEach((p) => { const t = todosAll.products[p.id], b = bugsAll.products[p.id]; const n = (t?.open || 0) + (b?.active || 0); const el = container.querySelector(`[data-cnt="${p.id}"]`); if (el) el.textContent = n ? n : ''; });
  draw();

  async function draw() {
    const body = $('#tb-body', container);
    const t = todosAll.products[cur] || {}, b = bugsAll.products[cur] || {};
    const cc = b.cross_counts || {};
    body.innerHTML = html`
      ${(t.blockers || []).map((bl) => html`<div class="blocker"><b>⛔ blocker ${bl.n}</b>　${raw(md(bl.what))}<div class="tiny muted">卡在：${raw(md(bl.who))}　·　影響：${raw(md(bl.impact))}</div></div>`)}
      ${keptBlock(t.data_status)}
      ${b.present === false ? html`<div class="alert is-info small">此產品尚未建立 <code>docs/…/bugs/</code>（不版控，clone 後為空屬正常）。</div>` : ''}
      <div class="action-cards">${CROSS.map(([k, l, d]) => html`<div class="action-card ${k} ${cc[k] ? '' : 'zero'}" data-cross="${k}" title="${d}"><div class="n">${cc[k] || 0}</div><div class="l">${l}</div></div>`)}</div>
      <div class="row between small muted" style="margin:6px 0 4px"><span>待辦（未完成 ${t.open || 0} · 已完成 ${t.done || 0}）</span><span>活躍 Bug ${b.active || 0} · 歸檔 ${b.archived || 0}</span></div>
      <div id="tb-list" style="max-height:260px;overflow:auto"></div>
      <div class="row" style="margin-top:8px"><a class="btn xs" href="#/product/${cur}?tab=todos">全部待辦 →</a><a class="btn xs" href="#/product/${cur}?tab=bugs">Bug 清單 →</a><button class="btn xs ghost" id="tb-refresh">↻ 更新 JIRA</button></div>`;
    const list = $('#tb-list', body);
    const items = (t.docs || []).flatMap((d) => (d.items || []).filter((i) => !i.done).map((i) => ({ ...i, doc: d.path })));
    const bySub = {};
    items.forEach((i) => { (bySub[i.sub_label] = bySub[i.sub_label] || []).push(i); });
    list.innerHTML = Object.entries(bySub).map(([sub, arr]) => html`<div class="tiny muted" style="margin:6px 0 2px;letter-spacing:.06em">${sub}（${arr.length}）</div>${arr.map((i) => html`<div class="todo-row" data-todo="${i.id}" data-doc="${i.doc}"><span class="id">${i.starred ? '⭐' : ''}${i.id}</span><span class="sum" title="${i.summary}">${i.summary}</span><span class="pri">${(i.priority || '').slice(0, 12)}</span></div>`)}`).join('') || '<div class="empty small">沒有未完成的待辦</div>';
    list.onclick = (e) => { const r = e.target.closest('[data-todo]'); if (!r) return; const it = items.find((x) => x.id === r.dataset.todo && x.doc === r.dataset.doc); if (it) openTodo(it, cur); };
    body.querySelector('.action-cards').onclick = (e) => { const c = e.target.closest('[data-cross]'); if (c) navigate(`/product/${cur}?tab=bugs&cross=${c.dataset.cross}`); };
    $('#tb-refresh', body).onclick = async () => { $('#tb-refresh', body).classList.add('loading'); try { bugsAll = await api.get('/api/bugs?refresh=1'); draw(); } catch (err) { /* ignore */ } };
  }
}

// ⛔ 交接檔 §5「測試資料現況」裡**刻意保留**的那幾筆 —— 開工必讀。
//
// 為什麼要推到眼前（`handoff` §1.A 自己解釋過）：這一節的觸發時機是
// 「我看到一批看起來像殘留的資料」，而那一刻你的判斷是「這是垃圾，清掉」——
// **不會有任何訊號提醒你先去查交接檔**。而清掉之後那張單就不可重現了
// （RD 照 Reproduce Steps 走會看不到現象），要重新建資料才拍得到佐證。
//
// ⚠️ 只顯示標明「保留／不還原」的那些 —— 已還原的不必佔版面。
/** ⛔ 交接檔 §5 裡**刻意保留**的測試資料。
 *
 * `max` ＝ 最多列幾筆。總覽那張卡只有 ~170px 高、要跟動作卡與待辦分，
 * 列滿 5 筆會把整張卡吃掉（2026-08-24 走查看到動作卡被推到摺線下）；
 * 產品頁空間夠，維持 5 筆。**筆數與「去哪看」兩者一定要留著** ——
 * 這個方塊的作用是攔住「這看起來像殘留，清掉吧」那個念頭，不是列清單。
 */
export function keptBlock(rows, { max = 5 } = {}) {
  const kept = (rows || []).filter((r) => r.kept);
  if (!kept.length) return '';
  return html`<div class="alert is-warn small" style="margin-bottom:8px">
    <b>⛔ 這些測試資料是刻意保留的，不要當殘留清掉（${kept.length} 筆）</b>
    <div class="tiny muted" style="margin:2px 0 4px">
      它們是某張 Bug 單的重現環境。清掉之後那張單就不可重現 —— 交接檔 §5。
    </div>
    ${kept.slice(0, max).map((r) => html`<div class="tiny">· ${raw(md(r.what))}</div>`)}
    ${kept.length > max ? html`<div class="tiny muted">…另有 ${kept.length - max} 筆，見交接檔 §5</div>` : ''}
  </div>`;
}

export function openTodo(it, pid) {
  // 來源位置：後端 todo_index 現在會給 doc（repo 相對路徑）與 line（1-based）
  const src = it.doc ? `${it.doc}${it.line ? ':' + it.line : ''}` : '';
  const actions = [];
  if (it.doc) {
    actions.push({ label: '📄 看全文', cls: 'primary', onClick: () => { openDoc(it.doc, { line: it.line, title: `${it.id}　${it.doc.split('/').pop()}` }); } });
    actions.push({ label: '複製', onClick: () => { copy(todoPlainText(it, src)); toast('已複製項目內容與來源位置', 'success'); return false; } });
  }
  actions.push({ label: '關閉' });
  modal.open({ title: `${pid.toUpperCase()} ${it.id}　${it.sub_label}`, wide: true,
    body: `<div class="tiny muted mono">${esc(src)}</div><div class="md" style="margin-top:8px">${md(it.body)}</div>${it.priority ? `<div class="small muted" style="margin-top:8px">優先：${md(it.priority)}</div>` : ''}${Object.keys(it.cols || {}).length ? `<div class="small" style="margin-top:8px">${Object.entries(it.cols).filter(([k]) => !k.includes('優先')).map(([k, v]) => `<div><span class="muted">${esc(k)}：</span>${md(v)}</div>`).join('')}</div>` : ''}`,
    actions });
}

/** 複製用的純文字：編號＋原文＋來源位置，貼到報告或交接檔都不用再整理 */
function todoPlainText(it, src) {
  const cols = Object.entries(it.cols || {}).map(([k, v]) => `${k}：${v}`).join('\n');
  return [`${it.id}${it.starred ? '（重點）' : ''}　${it.sub_label}`,
    String(it.body || '').replace(/<br\s*\/?>/gi, '\n'),
    cols, src ? `來源：${src}` : ''].filter(Boolean).join('\n');
}
