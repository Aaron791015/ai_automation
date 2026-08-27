// #/sessions 對話紀錄總覽：全部 session（未關閉／已關閉）表格
// ⚠️ `state: 'active'` 的意思是**尚未關閉**，不是「程序正在跑」——
//    標成「進行中」會讓人以為背景還在工作（2026-08-23 更正）。、全文搜尋、續接／分叉／改名／刪除／匯出
import { api } from '../api.js';
import { $, html, raw, esc, fmt, debounce } from '../ui/el.js';
import { setSession } from '../store.js';
import { modal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';
import * as dock from '../ui/dock.js';
import { fileDrafts } from '../ui/bugfiler.js';


// ── 任務啟動器導過來時，自動送出它組好的 prompt ─────────────────────
//
// `tasklauncher.js` 會導到 `#/sessions?session=<id>&send=<prompt>`。
// ⛔ 先前**沒有任何人讀 `send`** —— session 建好了、prompt 被丟掉，
//    使用者看到一個只有「帶入上下文」的空對話，得自己重打
//    （2026-08-23 範本端到端驗收）。整個階段 E 的價值就在那段 prompt。
async function autoSend() {
  const q = location.hash.split('?')[1];
  if (!q) return;
  const p = new URLSearchParams(q);
  const sid = p.get('session');
  const text = p.get('send');
  if (!sid || !text) return;

  // ⚠️ **先把 send 從網址移掉再送** —— 留著的話重新整理就再送一次，
  //    而每一次都是真的呼叫 Claude（重複計費）。
  p.delete('send');
  const rest = p.toString();
  history.replaceState(null, '', '#/sessions' + (rest ? '?' + rest : ''));

  setSession(sid);
  await dock.open();
  const inp = document.querySelector('#ch-in');
  const btn = document.querySelector('#ch-send');
  if (!inp || !btn) { toast('對話面板還沒就緒，請手動貼上任務提示', 'warn'); return; }
  inp.value = text;
  btn.click();
}


// ── session 的**產出**：待開單的 Bug 草稿 ─────────────────────────
//
// ⭐ 為什麼要放在這一頁：對話本身在這裡看，產出理應也在這裡 ——
//    先前 `bug_draft.read_all()` 的 docstring 明寫「供 UI 的待開單清單用」，
//    卻沒有任何介面消費它。按「探索新功能」→ Claude 判定該開單 → 整理成草稿，
//    **那份草稿只存在於磁碟上，介面上不存在**
//    （2026-08-23 使用者提問：session 的執行結果要怎麼檢視）。
//
// ⛔ 這裡**只列出與開啟**，開單一律走既有的確認框（配號在寫檔那一刻）。
async function loadDrafts(root) {
  const box = $('#ss-drafts', root);
  if (!box) return;
  let d;
  try { d = await api.get('/api/bug-drafts'); } catch (e) { return; }
  const items = d.drafts || [];
  if (!items.length) { box.style.display = 'none'; return; }
  box.style.display = '';
  box.innerHTML = html`<h3>待開單的 Bug 草稿 <span class="cnt">${items.length}</span></h3>
    <div class="alert is-warn tiny" style="margin:6px 0">
      草稿<b>不佔 Bug ID</b> —— 按「開單」才配號。
      ⚠️ <b>測試失敗 ≠ 缺陷</b>：平台起的 session 是無人看管的，開單前請看過它的判斷。
    </div>
    <table class="tbl small"><thead><tr><th>來源</th><th>出現</th><th>標題</th><th>產品</th><th>嚴重度</th><th></th></tr></thead><tbody>
    ${items.map((x, i) => html`<tr>
      <td class="tiny"><a href="${x.source_href || '#/'}">${x.source_label || '—'}</a></td>
      ${/* ⭐ 同一個失敗（nodeid ＋ 錯誤訊息）跨多次執行只列一筆 —— 這一欄就是
             「它反覆失敗了幾次」。先前是列 N 筆一模一樣的，人要按 N 次
             （2026-08-24 走查實見 6 筆）。反覆失敗本身是判斷材料：
             次數愈多，愈可能是**環境或前置**而不是新缺陷。 */''}
      <td class="tiny num">${x.seen_count > 1 ? html`<span class="pill tone-warn">${x.seen_count} 次</span>` : '1 次'}</td>
      <td><a href="#" class="row-open" data-draft="${i}">${x.title || '（無標題）'}</a></td>
      <td>${x.product ? html`<span class="pill">${x.product}</span>` : ''}</td>
      <td class="tiny">${x.severity || '—'}</td>
      <td style="white-space:nowrap"><button class="btn xs" data-draft="${i}">看草稿</button> <button class="btn xs primary" data-file="${i}">開單</button> <button class="btn xs ghost" data-drop="${i}" title="判定不該開 —— 標記捨棄（要寫理由，不會真的刪掉）">捨棄</button></td>
    </tr>`)}</tbody></table>`;
  box.onclick = async (e) => {
    // 捨棄：⛔ 不刪除，只標記 ＋ 理由 ——
    //   判定「不該開」的草稿若沒有出口，清單會愈長愈髒，久了沒有人願意看
    //   （2026-08-23 UI 走查：`test_必定失敗` 那筆探針殘留就一直躺著）。
    const dp = e.target.closest('[data-drop]');
    if (dp) {
      const x = items[Number(dp.dataset.drop)];
      const why = await modal.prompt('捨棄這筆草稿',
        '⛔ 不會真的刪掉 —— 只標記「已捨棄」＋理由。<br>'
        + '<b>「當初為什麼判定不開」正是下次要看的東西</b>（同一個現象再出現時，不必重走一遍判斷）。',
        { placeholder: '例：這是 verify_platform 的探針檔，不是產品缺陷', okLabel: '捨棄' });
      if (!why) return;
      try {
        await api.post('/api/drafts/discard',
          { source: x.source, signature: x.signature, kind: 'bug', why });
        toast('已捨棄', 'success'); await loadDrafts(root);
      } catch (err) { toast(err.message, 'danger', 6000); }
      return;
    }
    // 開單：走與 run 結果頁**完全相同**的確認流程（預覽也會真的配號）
    const f = e.target.closest('[data-file]');
    if (f) {
      const x = items[Number(f.dataset.file)];
      fileDrafts([x], x.source, () => loadDrafts(root));
      return;
    }
    const b = e.target.closest('[data-draft]');
    if (!b) return;
    e.preventDefault();            // ⛔ 同上：標題是 <a href="#">
    const x = items[Number(b.dataset.draft)];
    const pre = (x.prechecks || []).filter((q) => q.answer);
    modal.open({
      title: `Bug 草稿　${x.title || ''}`.slice(0, 60),
      wide: true,
      body: html`<div class="tiny muted mono">${x.source_label || ''}　${x.nodeid || ''}</div>
        ${pre.length ? html`<div class="alert is-info small" style="margin-top:8px">
          <b>開單前三問（<code>bug-report</code> §3.9）</b>
          ${pre.map((q) => html`<div style="margin-top:3px"><b>${q.label}</b>　${q.answer}</div>`)}
        </div>` : raw('<div class="alert is-warn small" style="margin-top:8px">⚠️ 這份草稿<b>沒有開單前三問的答案</b> —— 開單前請自己確認一次。</div>')}
        <pre style="max-height:46vh;margin-top:8px">${x.message || x.body || JSON.stringify(x, null, 2)}</pre>`,
      actions: [{ label: '關閉' }],
    });
  };
}


/** `#/sessions?focus=<sid>&panel=<bugs|cases|docs>` —— 從「待確認」的產出連結點過來。
 *
 * ⭐ 2026-08-24：這些連結原本全指向 `#/sessions`（列表首頁）——
 *    而**對話列表不是產出物**，人到了還要自己找，等於沒接上。
 *    判準見「已開單」那條：`?focus=` 捲到那一列並高亮，點開就是完整描述。
 *
 * ⚠️ 面板可能是空的（草稿已經被處理掉了）—— 那時要**講出來**，
 *    而不是靜靜地什麼都不做（人會以為連結壞了）。
 */
function focusFromQuery(root) {
  const p = new URLSearchParams(location.hash.split('?')[1] || '');
  const sid = p.get('focus'), panel = p.get('panel');
  if (!sid && !panel) return;
  const box = panel === 'bugs' ? $('#ss-drafts', root)
            : panel === 'docs' ? $('#ss-docs', root) : null;
  if (box && box.style.display !== 'none') {
    box.scrollIntoView({ block: 'start', behavior: 'smooth' });
    box.classList.add('flash-focus');
    setTimeout(() => box.classList.remove('flash-focus'), 2000);
  } else if (panel) {
    toast('那批草稿已經不在了（可能已落單或被捨棄）', 'info', 4000);
  }
  if (sid) {
    const row = $(`[data-sid="${sid}"]`, root);
    if (row) { row.classList.add('selected-leaf'); row.scrollIntoView({ block: 'center' }); }
  }
}

// ── session 的**文件產出**：機制文件、交接檔要補的列 ────────────────
//
// ⭐ 計畫 E-1b 列了五種寫入型產出，先前只做了 Bug 與案例兩種 ——
//    探索寫出來的機制文件、收尾補做的交接檔內容**根本沒有寫檔路徑**：
//    session 產得出來，介面上寫不下去，使用者只能自己複製貼上到編輯器。
//    那正是「草稿／寫檔兩段式」要消滅的手工（2026-08-23）。
async function loadDocDrafts(root) {
  const box = $('#ss-docs', root);
  if (!box) return;
  let d;
  try { d = await api.get('/api/doc-drafts'); } catch (e) { return; }
  const items = d.drafts || [];
  if (!items.length) { box.style.display = 'none'; return; }
  box.style.display = '';
  const KIND = { doc: '機制文件', handover: '交接檔', report: '驗證報告' };
  box.innerHTML = html`<h3>待寫檔的文件產出 <span class="cnt">${items.length}</span></h3>
    <div class="alert is-info tiny" style="margin:6px 0">
      寫檔由平台執行 —— 交接檔的編號在<b>寫入的那一刻</b>才取，不由對話事先推算。
    </div>
    <table class="tbl small"><thead><tr><th>來源</th><th>類型</th><th>標題</th><th>會寫到</th><th></th></tr></thead><tbody>
    ${items.map((x, i) => html`<tr class="${i >= 5 ? 'foldrow' : ''}" ${i >= 5 ? raw('hidden') : ''}>
      <td class="tiny">${x.source_label || '—'}</td>
      <td><span class="pill">${KIND[x.kind] || x.kind}</span></td>
      <td>${x.title || '（無標題）'}${x.why ? html`<div class="tiny muted">${x.why}</div>` : ''}</td>
      <td class="tiny mono">${x.target_rel || '—'}</td>
      <td style="white-space:nowrap"><button class="btn xs primary" data-doc="${i}">寫檔</button> <button class="btn xs ghost" data-dropdoc="${i}" title="不寫了 —— 標記捨棄（要寫理由）">捨棄</button></td>
    </tr>`)}</tbody></table>
    ${items.length > 5 ? html`<button class="btn xs ghost" id="doc-more" style="margin-top:6px">展開其餘 ${items.length - 5} 筆</button>` : ''}`;
  const more = $('#doc-more', box);
  if (more) more.onclick = () => {
    box.querySelectorAll('tr.foldrow').forEach((r) => r.removeAttribute('hidden'));
    more.remove();
  };
  box.onclick = async (e) => {
    const dp = e.target.closest('[data-dropdoc]');
    if (dp) {
      const x = items[Number(dp.dataset.dropdoc)];
      const why = await modal.prompt('捨棄這筆文件草稿',
        '⛔ 不會真的刪掉 —— 只標記「已捨棄」＋理由。',
        { placeholder: '例：這一節已經有人寫進去了', okLabel: '捨棄' });
      if (!why) return;
      try {
        await api.post('/api/drafts/discard',
          { source: x.source, signature: x.signature, kind: 'doc', why });
        toast('已捨棄', 'success'); await loadDocDrafts(root);
      } catch (err) { toast(err.message, 'danger', 6000); }
      return;
    }
    const b = e.target.closest('[data-doc]');
    if (!b) return;
    const x = items[Number(b.dataset.doc)];
    await writeDocDraft(x, () => loadDocDrafts(root));
  };
}

// 預覽 → 人確認 → 才真的寫。與開單同一條紀律。
async function writeDocDraft(x, onDone) {
  let pv;
  try { pv = await api.post('/api/doc-drafts/write', { source: x.source, signature: x.signature, dry_run: true }); }
  catch (e) { toast(e.message, 'danger', 6000); return; }
  const box = document.createElement('div');
  box.innerHTML = `
    <div class="alert is-warn small">${esc(pv.mode || '')} → <code>${esc(pv.path || '')}</code>
      ${pv.id ? `<br>編號：<b>${esc(pv.id)}</b>（${esc(pv.id_source || '')}）` : ''}</div>
    ${pv.index ? `<div class="alert ${pv.index.ok ? 'is-info' : 'is-warn'} tiny" style="margin-bottom:6px">
      ${pv.index.ok
        ? `會一併登記 <code>docs/INDEX.md</code> → §${esc(pv.index.section)}<br><code>${esc(pv.index.row)}</code>`
        : `⚠️ 不會登記 docs/INDEX.md：${esc(pv.index.reason || '')}　—— 沒登記的文件別人搜尋不到`}
    </div>` : ''}
    ${x.why ? `<div class="tiny muted" style="margin-bottom:6px">為什麼要寫：${esc(x.why)}</div>` : ''}
    ${(pv.header && pv.header.length) ? `<div class="tiny muted" style="margin-bottom:6px">
      欄位順序：${pv.header.map(esc).join('｜')}${pv.aligned ? `　<b>⚠️ ${esc(pv.aligned)}</b>` : ''}</div>` : ''}
    <pre style="max-height:46vh">${esc(pv.text || '')}</pre>`;
  const go = await new Promise((res) => modal.open({
    title: `寫入　${x.title || ''}`.slice(0, 60), wide: true, body: box,
    actions: [{ label: '取消', onClick: () => res(false) },
      { label: pv.exists ? '覆寫' : '確認寫入', cls: 'primary', onClick: () => res(true) }],
    onClose: () => res(false),
  }));
  if (!go) return;
  try {
    const r = await api.post('/api/doc-drafts/write', {
      source: x.source, signature: x.signature, dry_run: false, overwrite: !!pv.exists,
    });
    toast(`已寫入 ${r.path}${r.id ? '（' + r.id + '）' : ''}`, 'success', 6000);
    if (r.note) modal.alert('寫好了', `<code>${esc(r.path)}</code><p class="small muted">${esc(r.note)}</p>`);
    if (onDone) await onDone();
  } catch (e) { toast(e.message, 'danger', 8000); }
}

export async function mount(root) {
  root.innerHTML = html`<div class="page">
    <div class="page-head"><h2>對話</h2><span class="crumb" id="ss-cnt"></span><span style="flex:1"></span>
      <button class="btn sm primary" id="ss-new">＋ 新對話</button>
      <input id="ss-q" type="text" placeholder="搜尋標題或對話內容（全文）…" style="min-width:280px;padding:5px 9px;background:var(--code-bg);border:1px solid var(--border-strong);color:var(--text)"></div>
    <div class="page-bar"><div class="alert is-info tiny" style="width:100%">session 是伺服器端物件，關掉分頁不等於關掉 session。<b>關閉</b>＝結束程序但紀錄保留、可續接；<b>刪除</b>才是對話真的沒了。續接會重新載入完整脈絡（正式模式會消耗額度）。</div></div>
    <div class="page-body">
      <section class="card" id="ss-drafts" style="margin-bottom:10px;display:none"></section>
      <section class="card" id="ss-docs" style="margin-bottom:10px;display:none"></section>
      <section class="card"><table class="tbl small" id="ss-tbl"></table></section>
    </div>
  </div>`;
  $('#ss-q', root).oninput = debounce(() => load($('#ss-q', root).value.trim()), 200);
  await autoSend();
  // 新對話與「開啟／續接」都直接把 dock 叫出來 —— 只切 store 而不開面板，畫面上等於沒反應
  $('#ss-new', root).onclick = async () => { const d = await api.post('/api/sessions', { title: '' }); setSession(d.session.id); toast('已建立', 'success'); await dock.open(); load($('#ss-q', root).value.trim()); };
  await load('');
  await loadDrafts(root);
  await loadDocDrafts(root);
  focusFromQuery(root);

  async function load(q) {
    const d = await api.get('/api/sessions' + (q ? '?q=' + encodeURIComponent(q) : ''));
    const rows = d.sessions || [];
    $('#ss-cnt', root).textContent = `${rows.length} 個 · 未關閉 ${rows.filter((s) => s.state === 'active').length}`;
    $('#ss-tbl', root).innerHTML = html`<thead><tr><th></th><th>標題</th><th>模型</th><th class="num">訊息</th><th>最後活動</th><th>關聯</th><th></th></tr></thead><tbody>
      ${rows.length ? rows.map((s) => html`<tr data-sid="${s.id}"><td>${s.state === 'active' ? '●' : '○'}</td>${/* 標題可點 ＝ 這一列的主要動作（進行中→開啟、已關閉→續接）。
            2026-08-24 使用者要求；`data-act` 沿用同一組事件委派，不必另寫處理器。 */''}
        <td><a href="#" class="row-open" data-act="${s.state === 'active' ? 'open' : 'resume'}" data-id="${s.id}" data-n="${s.message_count || 0}">${s.title}</a>${s.hit ? html`<div class="tiny muted">…${s.hit}…</div>` : ''}${s.forked_from ? raw(' <span class="pill">分叉</span>') : ''}</td><td class="mono">${s.model}</td><td class="num">${s.message_count || 0}</td><td class="tiny muted">${fmt.ago(s.last_active)}</td><td class="tiny">${s.product ? html`<span class="pill ${s.product}">${s.product}</span>` : ''}${s.run_id ? html`<a href="#/run/${s.run_id}" class="mono">${s.run_id.slice(0, 15)}</a>` : ''}</td>
        <td class="row">${s.state === 'active' ? html`<button class="btn xs primary" data-act="open" data-id="${s.id}">開啟</button><button class="btn xs" data-act="close" data-id="${s.id}">關閉</button>` : html`<button class="btn xs primary" data-act="resume" data-id="${s.id}" data-n="${s.message_count || 0}">續接</button>`}<button class="btn xs" data-act="fork" data-id="${s.id}">分叉</button><button class="btn xs" data-act="rename" data-id="${s.id}" data-title="${s.title}">改名</button><button class="btn xs" data-act="export" data-id="${s.id}">匯出</button><button class="btn xs danger" data-act="delete" data-id="${s.id}">刪除</button></td></tr>`) : raw('<tr><td colspan="7" class="muted">尚無 session</td></tr>')}</tbody>`;
    $('#ss-tbl', root).onclick = async (e) => {
      const b = e.target.closest('[data-act]'); if (!b) return;
      e.preventDefault();          // ⛔ 標題是 <a href="#">（按鈕不受影響）
      const id = b.dataset.id, act = b.dataset.act;
      if (act === 'open') { setSession(id); await dock.open(); }
      else if (act === 'close') { await api.patch(`/api/sessions/${id}`, { action: 'close' }); toast('已關閉'); load(q); }
      else if (act === 'resume') { if (await modal.confirm('續接 session', `會重新載入 <b>${b.dataset.n}</b> 則對話脈絡（正式模式會消耗額度）。`, { okLabel: '續接' })) { await api.patch(`/api/sessions/${id}`, { action: 'resume' }); setSession(id); await dock.open(); load(q); } }
      else if (act === 'fork') { const d2 = await api.post(`/api/sessions/${id}/fork`); toast('已分叉', 'success'); load(q); }
      else if (act === 'rename') { const t = await modal.prompt('重新命名', '新標題', b.dataset.title); if (t) { await api.patch(`/api/sessions/${id}`, { title: t }); load(q); } }
      else if (act === 'export') { const d2 = await api.get(`/api/sessions/${id}`); const md = `# ${d2.session.title}\n\n模型：${d2.session.model}　建立：${d2.session.created_at}\n\n` + (d2.messages || []).map((m) => `**${m.role}**（${m.at}）\n\n${m.text}\n`).join('\n---\n\n'); const blob = new Blob([md], { type: 'text/markdown' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `session_${id.slice(0, 8)}.md`; a.click(); }
      else if (act === 'delete') { if (await modal.confirm('刪除 session', '刪除後對話紀錄無法復原。', { danger: true, okLabel: '刪除' })) { await api.del(`/api/sessions/${id}`); toast('已刪除'); load(q); } }
    };
  }
}
export function unmount() {}
