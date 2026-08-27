// #/run/<id> 執行監控：phase 時間軸、進度環、指標卡（summary.kind 分派）、參數回顯（人話＋遮罩）、
// console 尾巴（預設關、上限 500 行）、優雅／強制停止、報告 chip、失敗案例 → Bug 草稿 → 開單
import { api } from '../api.js';
import { $, $$, html, raw, esc, fmt } from '../ui/el.js';
import { state, subscribe, set } from '../store.js';
import { ring, timeline, metricCards, dot, phaseLabel, toneOfPhase } from '../ui/hud.js';
import { modal } from '../ui/modal.js';
import { toast } from '../ui/toast.js';
import { kick } from '../poll.js';
import { navigate } from '../router.js';
import { renderTaskBar } from '../ui/tasklauncher.js';
// ⭐ 開單流程抽到 ui/bugfiler.js —— 一套流程、兩個入口
//    （run 結果頁 ＋ #/sessions 的待開單草稿面板）。
import { fileDrafts, prechecksBlock } from '../ui/bugfiler.js';
import { pageLoading } from '../ui/loading.js';

let unsub = null, timer = null, logOffset = 0, logOn = false, logLines = [], runId = null, info = null;

export async function mount(root, { id }) {
  runId = id; logOffset = 0; logLines = []; logOn = false;
  // ⭐ 先畫殼再抓資料（2026-08-24）—— 見 `views/tools.js` 同一段說明
  root.innerHTML = html`<div class="page"><div class="page-body" id="run-root" style="padding-right:6px">${pageLoading('讀取執行紀錄…')}</div></div>`;
  try { info = await api.get(`/api/runs/${id}`); } catch (e) { root.innerHTML = `<div class="alert is-error">${esc(e.message)}</div>`; return; }
  draw(info.status);
  unsub = subscribe((s, patch) => { if (patch.active) { const st = (s.active || []).find((r) => r.run_id === id); if (st) draw(st); } });
  timer = setInterval(async () => {
    const term = ['completed', 'failed', 'stopped'].includes((info.status || {}).phase);
    if (!term || logOn) { try { const d = await api.get(`/api/runs/${id}`); info.status = d.status; info.live = d.live; if (!(state.active || []).some((r) => r.run_id === id)) draw(d.status); } catch (e) { /* ignore */ } }
    if (logOn) pullLog();
  }, 2000);
}
// 參數卡：把 run_meta 的 {key: value} 換成「中文 label ＝ 選項 label」。
// 先前直接 JSON.stringify —— 印出 stop_members_on_close 這種鍵名，看的人得回去翻 registry 才懂。
// 這裡用 run 當下的 spec（/api/runs/<id> 回的 tool）對照；對不上的鍵仍原樣列出，不吞掉。
function paramCard(meta) {
  const params = meta.params || {};
  const cmd = ((info.tool || {}).commands || []).find((c) => c.id === meta.command_id);
  const fields = ((cmd || {}).params || {}).fields || [];
  const rows = [];
  const seen = new Set();
  for (const f of fields) {
    if (!(f.key in params)) continue;
    seen.add(f.key);
    rows.push([f.label || f.key, humanValue(f, params[f.key])]);
  }
  for (const [k, v] of Object.entries(params)) {
    if (seen.has(k) || k.startsWith('_')) continue;
    rows.push([k, typeof v === 'object' ? JSON.stringify(v) : String(v)]);
  }
  if (!rows.length) return '<div class="muted small">（此命令不帶參數）</div>';
  return `<div class="confirm-sum" style="margin-top:0">${rows.map(([k, v]) =>
    `<div class="row between"><span class="muted">${esc(k)}</span><b>${esc(v)}</b></div>`).join('')}</div>`;
}
function humanValue(f, v) {
  if (f.type === 'boolean') return v ? '是' : '否';
  if (f.type === 'select' || f.type === 'file_select') {
    const o = (f.options || []).find((x) => String(x.value) === String(v));
    return o ? o.label : String(v);
  }
  if (f.type === 'multiselect') {
    const m = Object.fromEntries((f.options || []).map((x) => [String(x.value), x.label]));
    return (Array.isArray(v) ? v : [v]).map((x) => m[String(x)] || String(x)).join('、');
  }
  if (f.type === 'case_picker') return `已勾選 ${(Array.isArray(v) ? v : []).length} 條`;
  if (f.type === 'number') return `${v}${f.unit || ''}`;
  const t = String(v);
  return t.length > 80 ? t.slice(0, 80) + '…' : t;
}

// ── 失敗 → Bug 草稿 → 開單 ──────────────────────────────────────────────
// ★ 兩段式（2026-08-21 使用者裁示）：run 結束自動產**草稿**（不佔 ID、不寫檔），
//   人勾選並確認過內容才真的配號開單。理由見 core/bug_draft.py 檔頭 ——
//   走查實測三筆 run 的失敗集合完全相同，自動開正式單會是 42 張永久佔號的垃圾。
let drafts = [];
async function loadDrafts() {
  const root = $('#run-root'); if (!root) return;
  try { drafts = (await api.get(`/api/runs/${runId}/bug-drafts`)).drafts || []; } catch (e) { return; }
  const bySig = {};
  for (const d of drafts) bySig[d.nodeid] = d;
  for (const tr of $$('#fail-tbl tbody tr', root)) {
    const d = bySig[tr.dataset.node]; if (!d) continue;
    const cell = $('.bd-hint', tr);
    const cb = $('.bd-pick', tr);
    if (d.filed_as) {
      cell.innerHTML = `<span class="pill tone-success">已開 ${esc(d.filed_as)}</span>`;
      cb.disabled = true;
    } else if (d.likely_existing) {
      const e = d.likely_existing;
      // ★ 命中一張**已結案**的單 ＝ 回歸，比新缺陷更該優先處理 —— 用 danger 色標出來，
      //   而且**預設勾選**（該開新單承接殘留，見 memory「舊 Bug 單不回填，用新單追蹤」）。
      //   命中的若是活躍單，該做的是回原單補重現紀錄，所以預設不勾。
      cell.innerHTML = `<span class="pill ${e.regressed ? 'tone-danger' : e.confidence === 'high' ? 'tone-warn' : ''}" title="${esc(e.why)}">`
        + (e.regressed ? `⚠ ${esc(e.id)} 回歸` : `疑似 ${esc(e.id)}`) + '</span>';
      cb.checked = Boolean(e.regressed);
    } else {
      cell.innerHTML = d.seen_count > 1 ? `<span class="tiny muted">已出現 ${d.seen_count} 次</span>` : '<span class="muted">—</span>';
    }
  }
  const upd = () => {
    const n = $$('.bd-pick:checked', root).length;
    const b = $('#btn-file-bugs', root);
    b.textContent = `開單（${n}）`; b.disabled = !n;
    b.classList.toggle('primary', n > 0);
  };
  $('#fail-tbl', root).addEventListener('change', (e) => { if (e.target.closest('.bd-pick')) upd(); });
  $('#btn-file-bugs', root).onclick = () => {
    const picked = drafts.filter((d) => $$('.bd-pick:checked', root)
      .map((c) => c.dataset.node).includes(d.nodeid));
    return fileDrafts(picked, runId, loadDrafts);
  };
  upd();
}


export function unmount() { unsub && unsub(); clearInterval(timer); drafts = []; }

// ★ 開單前三問（`bug-report` §3.9）—— 攤在開單頁上，不是只放在草稿檔裡。
//
// 為什麼一定要看得到：平台起的 session 是**無人看管**的（按下按鈕就去做別的事了）。
// 「Claude 說它做過三問」和「**你看過它的判斷**」是兩回事，
// 而 Bug ID 配發後永不回收 —— 燒錯號的代價是永久的，按一下確認的成本是零。
//
// ⚠️ 沒答的也要顯示成「未回答」。看得到「它沒答」比看不到這件事重要。



function draw(st) {
  const root = $('#run-root'); if (!root || !st) return;
  info.status = st;
  const t = info.tool || {}, meta = info.meta || {};
  const term = ['completed', 'failed', 'stopped'].includes(st.phase);
  const pct = st.progress?.percent ?? (term ? 100 : 3);
  const s = st.summary || {};
  const stopCfg = info.stop || {};
  root.innerHTML = html`
    <div class="page-head" style="flex-wrap:wrap">
      <a href="#/reports" class="crumb">← 報告中心</a>
      <h2>${dot(st.phase)}${st.tool_name}<span class="pill ${st.product}">${st.product}</span><span class="pill tone-${toneOfPhase(st.phase)}">${st.tool_phase_label || phaseLabel(st.phase)}</span></h2>
      <span class="crumb mono" style="text-transform:none">${st.run_id}${st.remark ? ' · ' + st.remark : ''} · ${st.started_at}${st.ended_at ? ' → ' + st.ended_at.slice(11) : ''}</span>
      <span style="flex:1"></span>
      <span class="row">${!term ? html`<button class="btn warn" id="btn-stop">■ 停止</button><button class="btn danger" id="btn-force" title="${stopCfg.warning || ''}">強制終止</button>` : html`<a class="btn" href="#/tool/${st.tool_id}">再跑一次 →</a>`}</span>
    </div>
    ${(st.survivors || []).length ? html`<div class="alert is-error" style="margin-top:10px">⚠ 停止複驗未過：仍有殘留程序 <code>${st.survivors.join(', ')}</code>。請手動執行：<code>taskkill /F /T /PID ${st.survivors[0]}</code></div>` : ''}
    ${/* ⭐ 「被平台重啟打斷」與「執行失敗」要分得出來（2026-08-24）——
           前者那一輪可能跑得好好的，只是平台被關掉了。用黃色而不是紅色，
           並直接給下一步（右上角的「再跑一次」）。 */''}
    ${st.interrupted ? html`<div class="alert is-warn" style="margin-top:10px">
        ⏸ ${st.error || '平台重啟時中斷'}${st.progress?.percent ? html`（停在 ${Math.round(st.progress.percent)}%）` : ''}
        —— 下面的數字是**中斷當下**的，不是完整結果。要完整結果請用右上角的「再跑一次」。
      </div>` : st.error ? html`<div class="alert is-error" style="margin-top:10px">${st.error}</div>` : ''}
    <section class="card hud ${term ? '' : 'is-running'}" style="margin-top:12px">${!term ? raw('<div class="scanline"></div>') : ''}
      ${raw(timeline(info.phases || [], st.tool_phase, st.phase))}
      <div class="grid" style="grid-template-columns:96px minmax(0,1fr);gap:16px;align-items:center;margin-top:8px">
        ${raw(ring(pct, { size: 88, stroke: 7, label: term ? (st.phase === 'completed' ? '✓' : st.phase === 'failed' ? '✕' : '■') : null }))}
        <div><div class="small muted">${st.progress?.label || (term ? '已結束' : '進行中')}${st.progress?.total ? ` · ${st.progress.current}/${st.progress.total}` : ''}</div>
          ${raw(metricCards(info.metrics_def || [], { ...(st.metrics || {}), ...(s.kind === 'pytest' ? { passed: s.passed, failed: s.failed, skipped: s.skipped } : {}) }))}</div>
      </div></section>
    ${s.kind === 'pytest' && (s.failed_cases || []).length ? html`<section class="card" style="margin-top:12px"><h3>失敗案例 <span class="cnt">${s.failed_cases.length}</span></h3>
      <table class="tbl small" id="fail-tbl"><thead><tr><th style="width:26px"></th><th>案例</th><th>錯誤</th><th style="width:150px">既有單</th></tr></thead>
        <tbody>${s.failed_cases.map((c) => html`<tr data-node="${c.nodeid}"><td onclick="event.stopPropagation()"><input type="checkbox" class="bd-pick" data-node="${c.nodeid}"></td><td>${c.title || c.nodeid}<div class="mono tiny muted">${c.nodeid}</div></td><td class="mono tiny" style="color:var(--danger)">${c.message || ''}</td><td class="tiny bd-hint">—</td></tr>`)}</tbody></table>
      <div class="row" style="margin-top:8px"><button class="btn sm primary" id="btn-rerun-failed">只重跑這 ${s.failed_cases.length} 條</button>
        <button class="btn sm" id="btn-file-bugs" disabled>開單（0）</button>
        <span class="tiny muted" id="bd-note">草稿由本次執行自動整理 · ⚠ 測試失敗 ≠ 缺陷，請先確認不是測試碼或環境問題</span></div></section>` : ''}
    <div class="grid two" style="margin-top:12px">
      <section class="card" id="run-tasks" style="margin-bottom:12px"></section>
      <section class="card"><h3>報告</h3><div class="row">${(st.artifacts || []).length ? st.artifacts.map((a) => a.exists ? html`<a class="report-link" href="${a.href}" target="_blank" rel="noopener">${a.label}</a>` : html`<span class="report-link missing">${a.label}（尚未產生）</span>`) : raw('<span class="muted small">尚無報告' + (term ? '' : '（結束後產生）') + '</span>')}</div>
        ${(st.artifacts || []).some((a) => a.exists && a.open === 'iframe') ? html`<div class="row" style="margin-top:8px">${st.artifacts.filter((a) => a.exists && a.kind === 'html').map((a) => html`<button class="btn xs" data-iframe="${a.href}">內嵌檢視：${a.label}</button>`)}</div><div id="iframe-wrap"></div>` : ''}</section>
      <section class="card"><h3>參數 <span class="cnt">secret 已遮罩</span></h3>${raw(paramCard(meta))}${meta.selection_count ? html`<div class="small muted" style="margin-top:6px">選取案例 ${meta.selection_count} 條（<a href="/reports/${st.run_id}/selection.txt" target="_blank">selection.txt</a>）</div>` : ''}</section>
    </div>
    <section class="card" style="margin-top:12px"><h3>主控台尾巴 <span class="cnt">最多 500 行 · 完整請開 console.log</span><label class="small row" style="margin-left:auto;font-weight:400"><span class="switch ${logOn ? 'on' : ''}" id="log-sw"></span> 顯示</label></h3>
      <div class="console ${logOn ? '' : 'hidden'}" id="console"></div>
      <div class="tiny muted" style="margin-top:6px">這不是完整日誌，長跑數萬行會卡死畫面 —— <a href="/reports/${st.run_id}/console.log" target="_blank">另開分頁看 console.log</a></div></section>`;
  const sb = $('#btn-stop', root); if (sb) sb.onclick = () => stop(false);
  const fb = $('#btn-force', root); if (fb) fb.onclick = () => stop(true);
  if ($('#fail-tbl', root)) loadDrafts();
  const rf = $('#btn-rerun-failed', root); if (rf) rf.onclick = () => { const sel = new Set(s.failed_cases.map((c) => c.nodeid)); set({ selection: sel }); window.__tp_selection = sel; toast(`已選取 ${sel.size} 條`, 'success'); navigate(`/tool/${st.tool_id}`); };
  $('#log-sw', root).onclick = () => { logOn = !logOn; $('#log-sw', root).classList.toggle('on', logOn); $('#console', root).classList.toggle('hidden', !logOn); if (logOn) pullLog(); };
  root.onclick = (e) => { const b = e.target.closest('[data-iframe]'); if (b) { $('#iframe-wrap', root).innerHTML = `<iframe src="${b.dataset.iframe}" style="width:100%;height:520px;border:1px solid var(--border);border-radius:6px;margin-top:8px;background:#0d1117"></iframe>`; } };
  if (logOn) renderLog();

  // ★ run 結果頁的任務列（計畫 E-3）——「從失敗 run 開單」宣告 entry:["run"]，
  //   但先前這裡從來沒呼叫 renderTaskBar，於是那顆按鈕**根本出不來**。
  //   ⚠️ 只在 run 結束後才顯示：跑到一半就叫人開單沒有意義。
  const tb = $('#run-tasks', root);
  // ⚠️ 只在**有失敗**時才出這一排 —— 這一排目前只有「從失敗 run 開單」，
  //    對一次成功的 run 顯示它等於在問「要不要為這次成功開一張缺陷單」
  //    （2026-08-24 走查：api_load 跑成功，畫面照樣有那顆按鈕）。
  const hasFailure = st.phase === 'failed' || !!(s.failed || (s.failed_cases || []).length);
  if (tb && term && hasFailure) {
    renderTaskBar(tb, {
      entry: 'run',
      product: meta.product || null,
      // 帶給任務模板的上下文。
      // ⚠️ 鍵名必須跟 **任務的 `fields[].key`** 一致（`nodeid`、`message`）——
      //    先前只傳了 `failed_cases` 陣列，於是表單上兩個必填欄位都是空的，
      //    使用者得自己回去拄 nodeid（2026-08-23 範本端到端驗收）。
      //    多條失敗時帶第一條，其餘讓人自己改 —— 一張單一個問題。
      ctx: { run_id: st.run_id, tool_id: st.tool_id, phase: st.phase,
             nodeid: (s.failed_cases || [])[0]?.nodeid || '',
             message: (s.failed_cases || [])[0]?.message || '',
             failed_cases: (s.failed_cases || []).map((c) => c.nodeid),
             analysis_line: s.analysis_line || '' },
    });
  } else if (tb) {
    tb.remove();
  }
}
async function pullLog() {
  try { const d = await api.get(`/api/runs/${runId}/logs?offset=${logOffset}`); logOffset = d.offset; if (d.lines?.length) { logLines.push(...d.lines); if (logLines.length > 500) logLines = logLines.slice(-500); renderLog(); } } catch (e) { /* ignore */ }
}
function renderLog() {
  const el = $('#console'); if (!el) return;
  el.innerHTML = logLines.map((l) => `<div class="ln ${/FAILED|ERROR|失敗/.test(l) ? 'fail' : /PASSED|✓/.test(l) ? 'pass' : /SKIPPED/.test(l) ? 'skip' : ''}">${esc(l)}</div>`).join('');
  el.scrollTop = el.scrollHeight;
}
async function stop(force) {
  const st = info.status;
  const ok = await modal.confirm(force ? '強制終止' : '停止 run', `${force ? `<div class="alert is-warn small">${esc(info.stop?.warning || '強制終止會殺掉整棵程序樹。')}</div>` : '會先嘗試優雅收尾（寫 stop.flag），逾時才強制。'}<div class="mono small" style="margin-top:6px">${st.run_id}</div>`, { danger: true, okLabel: force ? '強制終止' : '停止' });
  if (!ok) return;
  try { const d = await api.post('/api/runs/stop', { run_id: st.run_id, force }); toast(d.message || '已送出停止'); kick(); } catch (e) { toast(e.message, 'danger'); }
}
