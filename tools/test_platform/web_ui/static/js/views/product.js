// #/product/<id> 產品頁：工具、案例子樹入口、Bug 清單（可依交叉狀態篩）、待辦全表、文件索引、健康度、環境
import { api } from '../api.js';
import { $, $$, html, raw, esc, fmt, copy } from '../ui/el.js';
import { state, productOf } from '../store.js';
import { openTodo, md } from '../ui/todopanel.js';
import { openDoc } from '../ui/docview.js';
import { toast } from '../ui/toast.js';
import { modal } from '../ui/modal.js';
import { glyphSvg } from '../ui/hero.js';
import { renderRadar } from '../ui/radar.js';
import { renderTaskBar, openTaskWith } from '../ui/tasklauncher.js';
import { pageLoading } from '../ui/loading.js';

const DANGER_LABEL = { high: '高風險', medium: '會寫入', low: '本機唯讀' };

/** Bug 明細：frontmatter 摘要 ＋「看全文」「複製開單資訊」。
 *  先前這裡只印一行「完整內容請開 <path>」，等於叫人自己去開檔案 —— 動線就斷在這。 */
function openBug(b, productId = '', onChanged = null) {
  const HIDE = ['title', 'id', 'cross', 'jira'];
  const rows = Object.entries(b).filter(([k]) => !HIDE.includes(k))
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</td></tr>`).join('');
  const jira = (b.jira || []).map((j) => `${esc(j.key)} · ${esc(j.status || '?')} · ${esc(j.assignee || '')}`).join('<br>') || '—';
  const actions = [];
  if (b.path) actions.push({ label: '📄 看全文', cls: 'primary', onClick: () => { openDoc(b.path, { title: `${b.id} ${b.title}` }); } });
  actions.push({ label: '複製開單資訊', onClick: () => { copy(bugPlainText(b)); toast('已複製，可直接貼進 JIRA', 'success'); return false; } });
  // ⭐ 開完 JIRA 之後單號要有回來的路 —— 先前只能自己去編 frontmatter
  //    （2026-08-23 使用者的動線：Bug 列表 → 轉 JIRA → **回填單號**）。
  //    ⛔ 平台不寫 JIRA（jira-verify §0 唯讀邊界），只把單號記回本地單。
  if (!(b.jira || []).length) {
    actions.push({ label: '回填 JIRA 單號', onClick: async () => {
      const key = await modal.prompt('回填 JIRA 單號',
        `把 <b>${esc(b.id)}</b> 在 JIRA 上的單號記回本地單的 <code>reported</code> 欄。<br>`
        + '⛔ 平台不會替你開 JIRA —— 開單請在 JIRA 網頁上做。',
        { placeholder: '例：CRUX-1042', okLabel: '回填' });
      if (!key) return false;
      try {
        const r = await api.post(`/api/bugs/${b.id}/jira`,
          { jira_key: key.trim(), product: b.product || productId });
        toast(`已回填 ${r.jira_key} → ${r.path}`, 'success', 6000);
        // ⛔ **寫完要把畫面刷新** —— 後端已經把單號寫進檔案、也清了索引快取，
        //    但前端不重抓的話「漏開單」那個數字**不會變**，看起來就像沒生效
        //    （2026-08-24 拍手冊截圖時實測：檔案已是 reported: CRUX-1099、
        //     後端算出 20，畫面卻還停在 21）。
        //    這與同一天修掉的「落檔後索引快取沒清」是同一個症狀的另一半：
        //    伺服器端清乾淨了，客戶端還捧著舊資料。
        if (typeof onChanged === 'function') await onChanged();
        // ⭐ 成功就把視窗關掉 —— 讓人直接看到更新後的清單。
        //    留著的話，視窗裡的 `reported` 與 `JIRA` 還是舊的（它不會自己重畫），
        //    看起來像沒生效（2026-08-24 拍截圖時看到）。
        return true;
      } catch (e) { toast(e.message, 'danger', 8000); }
      return false;
    } });
  }
  actions.push({ label: '關閉' });
  modal.open({ title: `${b.id} ${b.title}`, wide: true,
    body: `<table class="tbl small">${rows}<tr><th>JIRA</th><td>${jira}</td></tr></table>`, actions });
}

/** 貼進 JIRA 就能用的純文字（欄位順序照 bug-report skill 的回報格式） */
function bugPlainText(b) {
  return [`${b.id}　${b.title}`,
    `嚴重度：${b.severity || '—'}　狀態：${b.status_label || b.status || '—'}`,
    `模組：${b.module || '—'}　介面：${b.surface || '—'}`,
    `發現：${b.found || '—'}　回報：${b.reported || '—'}`,
    `回歸案例：${b.regression || '—'}`,
    (b.jira || []).length ? `JIRA：${(b.jira || []).map((j) => `${j.key}（${j.status || '?'}／${j.assignee || '未指派'}）`).join('、')}` : 'JIRA：尚未開立',
    `本地單：${b.path || '—'}`].join('\n');
}

export async function mount(root, { id }) {
  const p = productOf(id);
  if (!p) { root.innerHTML = `<div class="alert is-error">未知產品：${esc(id)}</div>`; return; }
  const qs = new URLSearchParams(location.hash.split('?')[1] || '');
  let tab = qs.get('tab') || 'overview';
  const focus = qs.get('focus'), cross = qs.get('cross');
  const tools = state.tools.filter((t) => (t.products || [t.product]).includes(id));
  root.innerHTML = html`<div class="page">
    <div class="page-head">
      <a href="#/" class="crumb">← 總覽</a>
      <span style="height:24px;color:${p.color};display:inline-flex;align-items:center">${raw(glyphSvg(id, 24))}</span>
      <h2 style="color:${p.color}">${p.label}</h2>
      <span class="crumb" style="text-transform:none;letter-spacing:0">${p.subtitle}</span>
      <span style="flex:1"></span>
      ${/* ⛔ 這裡原本再畫一次 `env-badge` —— 而全站 header 右上角**已經有一個**
             一模一樣的（同樣文字、只差 46px）。同一畫面把同一件事說兩遍是雜訊，
             而且會稀釋真正該被看到的警示（2026-08-24 走查）。
             環境是全站狀態，屬於 header，不屬於單一產品頁。 */''}
    </div>
    <div class="tabs" id="p-tabs">${[['overview', '總覽'], ['tools', '工具'], ['bugs', 'Bug'], ['todos', '待辦'], ['docs', '文件'], ['health', '健康度']].map(([k, l]) => html`<button class="tab-btn ${k === tab ? 'active' : ''}" data-tab="${k}">${l}</button>`)}</div>
    <div id="p-tasks"></div>
    <div class="page-body" id="p-body">${pageLoading("讀取產品資料…")}</div>
  </div>`;
  $('#p-tabs', root).onclick = (e) => { const b = e.target.closest('[data-tab]'); if (!b) return; tab = b.dataset.tab; $$('.tab-btn', root).forEach((x) => x.classList.toggle('active', x.dataset.tab === tab)); draw(); };
  let k = null, bugs = null, todos = null;
  // 任務按鈕：帶著這個產品的上下文開 session（2026-08-23 階段 E-3）
  const tb = $('#p-tasks', root);
  if (tb) renderTaskBar(tb, { entry: 'product', product: id });
  try { [k, bugs, todos] = await Promise.all([api.get('/api/knowledge'), api.get(`/api/bugs?product=${id}&slim=1`), api.get(`/api/todos?product=${id}`)]); } catch (e) { const bd = $('#p-body', root); if (bd) bd.innerHTML = `<div class="alert is-error">${esc(e.message)}</div>`; return; }
  const kp = k.products[id];
  draw();

  function draw() {
    // ⚠️ await 之後 root 可能已被 router 的 dispatch 清空（快速切頁）—— 沒有這道守衛會丟
    //    「Cannot set properties of null」。同一族的守衛見 cases.js／settings.js／overview.js。
    const body = $('#p-body', root);
    if (!body) return;
    if (tab === 'overview') {
      const r = kp.rings;
      body.innerHTML = html`<div class="metric-cards">${['spec', 'cases', 'bugs', 'reports', 'health'].map((key) => html`<div class="metric ${key === 'health' ? (r[key].value >= 80 ? 'success' : r[key].value >= 55 ? 'warn' : 'danger') : ''}" style="cursor:pointer" data-go="${{ spec: 'docs', cases: 'cases', bugs: 'bugs', reports: 'docs', health: 'health' }[key]}"><div class="k">${r[key].label}</div><div class="v">${r[key].value}${key === 'health' ? raw('<span class="small">/100</span>') : ''}</div><div class="tiny muted">${r[key].detail}</div></div>`)}</div>
        <div class="grid" style="margin-top:12px;grid-template-columns:300px 1fr 1.2fr;gap:12px">
          <section class="card"><h3>知識雷達 <span class="cnt">單產品</span></h3><div id="p-radar"></div>
            <div class="tiny muted" style="margin-top:4px">五圈由內而外：規格／案例／缺陷／紀錄／健康 —— 點圈進對應清單</div></section>
          <section class="card"><h3>工具 <span class="cnt">${tools.length}</span></h3>${tools.length ? tools.map((t) => html`<div class="row between" style="padding:4px 0;border-bottom:1px dashed var(--border)"><a href="#/tool/${t.id}">${t.name}</a><span class="danger-lvl ${t.danger?.level || 'low'}">${DANGER_LABEL[t.danger?.level || 'low']}</span></div>`) : raw('<div class="muted small">無</div>')}</section>
          <section class="card"><h3>待辦摘要</h3><div class="small">未完成 <b class="mono">${todos.open || 0}</b> · blocker <b class="mono" style="color:${(todos.blockers || []).length ? 'var(--danger)' : 'inherit'}">${(todos.blockers || []).length}</b> · 交接檔更新 ${todos.latest_update || '—'}</div>${(todos.blockers || []).map((b) => html`<div class="blocker" style="margin-top:6px"><b>⛔ ${b.n}</b> ${raw(md(b.what))}</div>`)}</section>
        </div>`;
      // 單產品雷達：只餵這個產品 → 扇區佔滿 360°，五圈看得最清楚
      renderRadar($('#p-radar', body), { products: { [id]: kp } }, { size: 236, compact: true, heat: [], state: 'idle', clock: '' });
      body.onclick = (e) => { const g = e.target.closest('[data-go]'); if (!g) return; if (g.dataset.go === 'cases') location.hash = `#/cases?product=${id}`; else { tab = g.dataset.go; $$('.tab-btn', root).forEach((x) => x.classList.toggle('active', x.dataset.tab === tab)); draw(); } };
    } else if (tab === 'tools') {
      // ⚠️ 不可在 html`` 內用 .join('') —— 會把 SafeString 陣列壓成一般字串而被跳脫（整片印出原始 HTML）。
      body.innerHTML = html`<div class="grid auto">${tools.length ? tools.map((t) => html`<div class="card hud tool-card" onclick="location.hash='#/tool/${t.id}'"><div class="name">${t.name}</div><div class="subtitle">${t.subtitle || ''}</div><div class="foot"><span>${t.commands.length} 命令</span><span class="danger-lvl ${t.danger?.level || 'low'}">${DANGER_LABEL[t.danger?.level || 'low']}</span></div></div>`) : raw('<div class="empty">此產品尚無工具</div>')}</div>`;
    } else if (tab === 'bugs') {
      if (bugs.present === false) { body.innerHTML = `<div class="alert is-info">此產品尚未建立 <code>docs/…/bugs/</code>（不版控，clone 後為空屬正常）。</div>`; return; }
      // ⭐ 新到舊（2026-08-24 使用者要求）。原本是後端 `sorted(glob(...))` 的**檔名升冪**，
      //    所以最舊的 CRUX-008 在最上面，要看剛開的單得捲到底。
      //    主鍵用 frontmatter 的 `found`（發現日期，實查 116 張全部有填），
      //    同日再用編號遞減 —— 編號永不回收且單調遞增，同一天內編號大的就是後開的。
      //    ⚠️ 編號要**取數字**再比：字串排序會把 CRUX-99 排到 CRUX-110 前面。
      //    ⚠️ 改善建議是**另一條序列**（CRUX-S01），數字與 bug 序列不可互比 ——
      //       靠 `found` 當主鍵才不會把 S06 排到 CRUX-006 旁邊。
      const bugNo = (x) => { const m = /-S?(\d+)/.exec(String(x || '')); return m ? Number(m[1]) : 0; };
      const newestFirst = (arr) => (arr || []).slice().sort((a, b) =>
        String(b.found || '').localeCompare(String(a.found || '')) || bugNo(b.id) - bugNo(a.id));
      let list = newestFirst(bugs.bugs);
      let f = cross || '';
      const CR = { revisit: '待重驗', unfiled: '漏開單', to_close: '該關單', no_regr: '缺回歸' };
      const render = () => {
        const rows = list.filter((b) => !f || (b.cross || []).includes(f) || (f === 'active' && ['open', 'superseded'].includes(b.status)));
        body.innerHTML = html`<div class="row" style="margin-bottom:8px"><span class="small muted">JIRA：${bugs.jira_source}${bugs.jira_fetched_at ? ' · ' + bugs.jira_fetched_at : ''}</span>
          <div class="row" style="margin-left:auto">${[['', '全部'], ['active', '活躍'], ...Object.entries(CR)].map(([k2, l]) => html`<button class="btn xs ${f === k2 ? 'primary' : ''}" data-f="${k2}">${l}${k2 && k2 !== 'active' ? ` ${bugs.cross_counts?.[k2] ?? ''}` : ''}</button>`)}</div></div>
          <div class="table-scroll" style="max-height:65vh"><table class="tbl small"><thead><tr><th>ID</th><th>標題</th><th>嚴重</th><th>狀態</th><th>JIRA</th><th>回歸</th><th>交叉</th></tr></thead><tbody>
          ${rows.map((b) => html`<tr class="clickable ${focus === b.id ? 'selected-leaf' : ''}" data-bug="${b.id}" id="bug-${b.id}"><td class="mono">${b.id}${b.archived ? raw(' <span class="tiny muted">📦</span>') : ''}</td><td>${b.title}<div class="tiny muted">${b.module}</div></td><td class="nowrap">${b.severity}</td><td class="nowrap">${b.status_label}</td><td class="tiny">${(b.jira || []).map((j) => html`<span class="pill ${/done|resolved|closed/i.test(j.status || '') ? 'tone-success' : 'tone-info'}" title="${j.summary || ''}">${j.key} ${j.status || '?'}</span>`)}${!(b.jira || []).length ? raw('<span class="muted">—</span>') : ''}</td><td class="tiny">${b.regression?.includes('待補') ? raw('<span style="color:var(--accent-amber)">⚠ 待補</span>') : (b.regression || '—').slice(0, 30)}</td><td>${(b.cross || []).map((c) => html`<span class="pill tone-warn">${CR[c]}</span>`)}</td></tr>`)}</tbody></table></div>
          ${f === 'no_regr' && rows.length ? html`<div class="row" style="margin-top:8px">
            <button class="btn xs primary" data-fix-regr>✍️ 補這 ${rows.length} 張的回歸案例</button>
            <span class="tiny muted">單號會帶進「撰寫案例」的表單，送出前可以自己刪減</span></div>` : ''}
          <div class="tiny muted" style="margin-top:6px">${rows.length} 張 · 點列看 frontmatter 摘要 · 📦＝已歸檔（old/）</div>`;
        body.querySelectorAll('[data-f]').forEach((b) => (b.onclick = () => { f = b.dataset.f; render(); }));
        // ⭐ 一鍵補回歸：把當前篩出來的單號帶進「撰寫案例」的 bug_ids。
        //    ⛔ 只在「缺回歸」篩選下出現 —— 其他篩選對應的動作完全不同，
        //       擺一顆「補回歸」在那裡只會讓人按錯。
        //    ⚠️ 是**帶進表單**不是直接發動：補回歸會真的下注、改設定、跑幾小時，
        //       單號預填好之後人還能刪減。一鍵省掉的是抄單號，不是省掉決定補哪幾張。
        const fixBtn = body.querySelector('[data-fix-regr]');
        if (fixBtn) fixBtn.onclick = () => {
          const ids = rows.map((b) => b.id);
          openTaskWith('write_cases', {
            product: id,
            // ⚠️ `points` 是必填 —— 不預填的話一鍵進來會被表單驗證擋在門口。
            //    補回歸時「功能點」就是這些單本身，寫明白比留空好。
            ctx: { bug_ids: ids.join(' '),
                   points: `補上列 ${ids.length} 張 Bug 的回歸案例（判準以各單的 Expect result 為準）` },
          });
        };
        // 第三個參數：回填單號之後要做什麼 —— 重抓 Bug 索引並重畫，
        // 否則「漏開單」的數字不會變（見 openBug 內的說明）。
        const refresh = async () => {
          // ⚠️ 帶 `product=` 時，那個產品的區塊在**頂層**（不是 `products.<id>` 底下）——
          //    寫成 `.products?.[id]` 會永遠拿到 undefined，於是靜靜地什麼都沒刷新
          //    （2026-08-24 第一版就是這樣寫的，數字照樣不動）。
          try {
            const d = await api.get(`/api/bugs?slim=1&product=${encodeURIComponent(id)}`);
            // ⚠️ `list` 也要跟著換 —— 先前只換 `bugs`（那是給 cross_counts 用的），
            //    於是回填 JIRA 之後數字變了、**那一列的 JIRA 欄還是舊的**。
            if (d && d.cross_counts) { bugs = d; list = newestFirst(d.bugs); }
          } catch (e) { /* 抓不到就維持原狀，至少不要炸掉 */ }
          render();
        };
        body.querySelectorAll('[data-bug]').forEach((r) => (r.onclick = () => { const b = list.find((x) => x.id === r.dataset.bug); openBug(b, id, refresh); }));
        if (focus) { const el = document.getElementById('bug-' + focus); el && el.scrollIntoView({ block: 'center' }); }
      };
      render();
    } else if (tab === 'todos') {
      const docs = todos.docs || [];
      body.innerHTML = html`${docs.map((d) => d.present === false ? html`<div class="alert is-info small">${d.path} 不存在</div>` : html`<section class="card" style="margin-bottom:10px"><h3>${d.path.split('/').pop()} <span class="cnt">更新 ${d.updated || '—'} · 未完成 ${d.open} · 已完成 ${d.done}</span></h3>
        ${(d.blockers || []).map((b) => html`<div class="blocker"><b>⛔ ${b.n}</b> ${raw(md(b.what))}<div class="tiny muted">卡在：${raw(md(b.who))}</div></div>`)}
        <div>${(d.items || []).map((i) => html`<div class="todo-row ${i.done ? 'done' : ''} ${focus === i.id ? 'selected-leaf' : ''}" data-todo="${i.id}" data-doc="${d.path}"><span class="id">${i.starred ? '⭐' : ''}${i.id}</span><span class="sum" title="${i.summary}">[${i.sub_label}] ${i.summary}</span><span class="pri">${(i.priority || '').slice(0, 14)}</span></div>`)}</div></section>`)}`; if (!docs.length) body.innerHTML = '<div class="empty">無交接檔</div>';
      body.onclick = (e) => { const r = e.target.closest('[data-todo]'); if (!r) return; const d = docs.find((x) => x.path === r.dataset.doc); const it = (d.items || []).find((x) => x.id === r.dataset.todo); if (it) openTodo({ ...it, doc: d.path }, id); };
    } else if (tab === 'docs') {
      // ⭐ 列得出來就要點得開 —— 先前只印檔名與行數，人得自己去開檔案（2026-08-23）
      setTimeout(() => {
        body.querySelectorAll('[data-doc]').forEach((a) => (a.onclick = (ev) => {
          ev.preventDefault();
          openDoc(a.dataset.doc, { title: a.textContent });
        }));
      }, 0);
      // ⭐ 產品 skill 也要列出來、也要點得開 —— 2026-08-24 起平台會自動往它的
      //    意圖對照表補列（`kind: skill` 的草稿）。**寫得進去卻看不到，等於沒寫**
      //    （27 份驗證報告沒有入口那次的教訓）。
      const skillFiles = (kp.skill_files || []).filter(Boolean);
      body.innerHTML = html`${skillFiles.length ? html`<section class="card" style="margin-bottom:10px">
          <h3>產品 skill <span class="cnt">每次對話開場都會讀它</span></h3>
          <table class="tbl small"><thead><tr><th>檔案</th><th class="num">行數</th><th>更新</th></tr></thead><tbody>${skillFiles.map((d) => html`<tr><td class="mono"><a href="#" data-doc="${d.path}">${d.name}</a></td><td class="num">${fmt.int(d.lines)}</td><td class="tiny muted">${fmt.ago(new Date(d.mtime * 1000).toISOString().replace('T', ' '))}</td></tr>`)}</tbody></table>
          <div class="tiny muted" style="margin-top:6px">§1 必記的不變量（要人確認才寫）· §2 意圖對照表（平台會自動補列）</div>
        </section>` : ''}
        <section class="card"><h3>docs/ <span class="cnt">${kp.docs.length} 檔 · ${kp.rings.spec.detail}</span></h3><table class="tbl small"><thead><tr><th>檔案</th><th class="num">行數</th><th>更新</th></tr></thead><tbody>${kp.docs.map((d) => html`<tr><td class="mono"><a href="#" data-doc="${d.path || (kp.docs_dir ? kp.docs_dir + '/' + d.name : d.name)}">${d.name}</a></td><td class="num">${fmt.int(d.lines)}</td><td class="tiny muted">${fmt.ago(new Date(d.mtime * 1000).toISOString().replace('T', ' '))}</td></tr>`)}</tbody></table>
        <div class="tiny muted" style="margin-top:8px">以意圖為鍵的對照表在 <code>.claude/skills/${p.knowledge?.skill || '—'}/SKILL.md</code>（${kp.rings.spec.skill_rows} 列）；以檔案為鍵的在 <code>docs/INDEX.md</code>。</div></section>`;
    } else if (tab === 'health') {
      const h = kp.rings.health;
      body.innerHTML = html`<section class="card"><h3>健康度 <span class="cnt">${h.value}/100</span></h3>
        <div class="small">${h.reasons?.length ? html`扣分項：${h.reasons.map((r) => html`<span class="pill tone-warn">${r}</span>`)}` : '無扣分項'}</div>
        <div class="sep"></div><div class="small muted">lint_docs（快取 10 分鐘）：</div>
        <div class="row" style="margin-top:6px">${Object.entries(h.lint || {}).map(([k2, v]) => html`<span class="pill ${v ? (['D1', 'D5', 'D6', 'D7'].includes(k2) ? 'tone-danger' : 'tone-warn') : ''}">${k2} ${v}</span>`)}</div>
        <div class="tiny muted" style="margin-top:8px">D1 斷連結／D2 未登記／D3 描述失真／D4 檔案偏大／D5 skill 指向不存在／D6 交接檔過期／D7 規格被改動。D1／D5 必修；D3／D4 技術債。<br>計分：D1/D5 −15、D6 −20、D7 −10、D2 −5、D3/D4 −2；交接檔 &gt;3 天 −N；blocker −10；缺回歸案例比例 ×20；待重驗 ×3。</div></section>`;
    }
  }
}
export function unmount() {}