// Claude 對話面板：session 下拉（進行中／已關閉）、＋新對話（選模型）、⋯（重新命名／分叉／關閉／刪除）、propose_run 確認卡
// Demo：回覆為規則式模擬（標「DEMO 模擬回覆」）；session 管理與確認卡流程是真的。
import { api } from '../api.js';
import { $, $$, html, raw, esc, fmt } from './el.js';
import { renderMarkdown } from './docview.js';
import { state, setSession } from '../store.js';
import { modal } from './modal.js';
import { toast } from './toast.js';
import { navigate } from '../router.js';
import { spinner } from './loading.js';

// 工具名對人講得通的字。`mcp__playwright__browser_click` → 瀏覽器·點擊
//
// ⛔ **必須放在模組層，不可放在 renderChatPanel 裡面** ——
//    `renderChatPanel` 一開頭就呼叫 `draw()`，而 `draw()` 會經 msgHtml → prettyTool
//    讀到這個 const。放在函式內、宣告又排在 draw() 之後，就落進 TDZ：
//    `ReferenceError: Cannot access '_TOOL_ZH' before initialization`。
//    症狀是**對話面板永遠停在「載入中…」**（2026-08-24 使用者回報、實測重現）——
//    而且只有「session 有工具紀錄」時才會炸，空對話看起來完全正常。
const _TOOL_ZH = {
  Read: '讀檔', Grep: '搜尋', Glob: '找檔', Skill: '載入 skill',
  WebFetch: '取網頁', WebSearch: '搜網路', ToolSearch: '找工具',
};
function prettyTool(t) {
  if (_TOOL_ZH[t]) return _TOOL_ZH[t];
  const m2 = /^mcp__([a-z0-9-]+)__(.+)$/.exec(t || '');
  if (!m2) return t;
  const srv = m2[1].startsWith('playwright') ? '瀏覽器'
    : m2[1] === 'test-platform' ? '平台' : m2[1];
  const act = m2[2].replace(/^browser_/, '').replace(/_/g, ' ');
  return `${srv}·${act}`;
}

export async function renderChatPanel(container, { context = null } = {}) {
  container.innerHTML = html`<h3>Claude 對話 <span class="cnt" id="ch-tag"></span></h3><div class="chat" id="chat">${raw(spinner('載入對話…'))}</div>`;
  const chat = $('#chat', container);
  let sessions = { active: [], closed: [], sessions: [] }, cur = null, msgs = [];
  // ⚠️ 這一行必須在 `watchRunning()` 的呼叫點**之前** —— 函式宣告會提升，`let` 不會，
  //    放在下面會是 TDZ ReferenceError，而症狀是**整個對話面板開不起來**（2026-08-25 實測抓到）。
  let watchTimer = 0, drawRaf = 0;
  // 使用者是不是還貼在訊息底部（決定串流時要不要自動捲）。預設 true ＝ 剛開啟。
  let atBottom = true;
  let claude = null;
  try { claude = await api.get('/api/settings/claude'); } catch (e) { /* ignore */ }
  $('#ch-tag', container).innerHTML = claude?.ok ? `<span class="pc-common">${esc(claude.auth?.email || '')}</span>` : `<a href="#/settings/claude" style="color:var(--accent-amber)">未連線 → 設定</a>`;

  async function loadSessions() { sessions = await api.get('/api/sessions'); }
  async function ensureSession() {
    await loadSessions();
    let sid = state.session;
    let m = sessions.sessions.find((s) => s.id === sid && s.state === 'active');
    if (!m) m = sessions.active[0];
    if (!m) { const d = await api.post('/api/sessions', { title: '', context }); m = d.session; }
    cur = m; setSession(m.id);
    const d = await api.get(`/api/sessions/${m.id}`); msgs = d.messages || []; cur = d.session;
  }
  await ensureSession();
  draw();
  watchRunning();

  // ⭐ 串流時 `draw()` 會被每個 SSE 片段呼叫（每秒數十次），而它是**整個訊息區重建**
  //    ＋ 每則重跑一次 markdown 渲染 —— 捲動與輸入都在同一條主執行緒上，於是卡。
  //    用 rAF 合併成「一幀最多畫一次」。
  //    ⛔ 不可改用節流計時器：最後一次更新會落在計時器上，`done` 之後畫面會停在
  //       倒數第二個片段。rAF 天生對齊繪製，不會有這個尾巴。
  // ⭐ 重新開啟一個**正在跑**的 session：串流是上一次送出時建立的，這一次進來沒有它，
  //    所以要自己補「它還在做事」的跡象，並在它跑完時把訊息重新載進來。
  //    ⛔ 少了這段，畫面與「session 死掉了」長得一模一樣（2026-08-25 使用者回報）。
  function watchRunning() {
    clearTimeout(watchTimer);
    if (!cur || cur.activity !== 'running') return;
    const p0 = msgs.find((m) => m.role === 'pending');
    // ⚠️ `send()` 自己的 pending 帶 `t0`（它有計時器在管）—— 那一輪走串流，不要插手。
    if (p0 && p0.t0) return;
    if (!p0) {
      msgs.push({ role: 'pending', text: runningLabel(cur), at: '' });
      scheduleDraw();
    }
    watchTimer = setTimeout(async () => {
      if (!chat.isConnected) return;                        // 面板關掉就別再輪詢
      let d;
      try { d = await api.get(`/api/sessions/${cur.id}`); } catch (e) { d = null; }
      if (!d) { watchRunning(); return; }
      cur = d.session;
      if (cur.activity === 'running') {
        const p = msgs.find((m) => m.role === 'pending');
        if (p) { p.text = runningLabel(cur); scheduleDraw(); }
        watchRunning();
        return;
      }
      msgs = d.messages || [];                              // 跑完了：換成落檔後的完整內容
      scheduleDraw();
    }, 3000);
  }

  /** 「它在做什麼、跑多久了」—— 只寫「處理中」等於沒說。 */
  function runningLabel(m) {
    const t0 = Date.parse((m.activity_started_at || '').replace(' ', 'T'));
    const min = t0 ? Math.max(0, Math.round((Date.now() - t0) / 60000)) : 0;
    const tools = (m.activity_tools || []).slice(-3).map(prettyTool).join('、');
    return `正在處理…（已 ${min} 分鐘${tools ? '，最近用了 ' + tools : ''}）`;
  }

  /** 捲到底 —— 要捲**三次**，因為版面不是一次定案的。
   *
   * ⚠️ 面板是動畫開啟的：第一次 `draw()` 時容器高度還沒定案，`scrollHeight` 量到舊值
   *    （甚至是 0），`scrollTop` 設了等於沒設 —— 症狀是**每次開啟都停在最上面**，
   *    而人要看的是最新那一則（2026-08-25 使用者回報）。
   * ⛔ 補的兩次都要重新確認 `atBottom`：人若已經往上翻，就不可以把他拉回來。
   */
  function toBottom(box) {
    box.scrollTop = box.scrollHeight;
    requestAnimationFrame(() => { if (atBottom && box.isConnected) box.scrollTop = box.scrollHeight; });
    setTimeout(() => { if (atBottom && box.isConnected) box.scrollTop = box.scrollHeight; }, 140);
  }

  function scheduleDraw() {
    if (drawRaf) return;
    drawRaf = requestAnimationFrame(() => { drawRaf = 0; draw(); });
  }

  function draw() {
    chat.innerHTML = html`
      <div class="head">
        <select id="ch-sel" title="切換 session（● 進行中／○ 已關閉）">
          ${sessions.active.length ? html`<optgroup label="進行中（${sessions.active.length}）">${sessions.active.map((s) => html`<option value="${s.id}" ${s.id === cur.id ? raw('selected') : ''}>● ${s.title} · ${s.model} · ${s.message_count} 則</option>`)}</optgroup>` : ''}
          ${sessions.closed.length ? html`<optgroup label="已關閉（${sessions.closed.length}）">${sessions.closed.map((s) => html`<option value="${s.id}">○ ${s.title} · ${s.model} · ${fmt.ago(s.last_active)}</option>`)}</optgroup>` : ''}
        </select>
        <button class="btn sm" id="ch-new">＋ 新對話</button>
        <button class="btn sm ghost" id="ch-more">⋯</button>
        <a class="btn sm ghost" href="#/sessions" title="全部 session（含全文搜尋）">全部</a>
      </div>
      <div class="msgs" id="ch-msgs">${msgs.length ? msgs.map(msgHtml) : html`<div class="msg system">新對話（${cur.model}）。試試：「幫我找變動賠率的案例」「CRUX-874 現況」「上次失敗的重跑一次」</div>`}</div>
      <div class="input"><textarea id="ch-in" placeholder="輸入訊息… Enter 送出，Shift+Enter 換行"></textarea><button class="btn primary" id="ch-send">送出</button></div>`;
    const box = $('#ch-msgs', chat);
    // ⭐ **只有原本就貼在底部時才捲到底**。先前是無條件 `scrollTop = scrollHeight`，
    //    串流中一秒搶好幾次 —— 人想往上翻看前面的判定表，手一放開就被拉回去。
    if (atBottom) toBottom(box);
    box.onscroll = () => { atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 48; };
    $('#ch-sel', chat).onchange = async (e) => { const sid = e.target.value; const s = sessions.sessions.find((x) => x.id === sid); if (s.state === 'closed') { if (!(await modal.confirm('續接 session', `「${esc(s.title)}」已關閉。續接會重新載入 <b>${s.message_count}</b> 則對話脈絡（正式模式會消耗額度）。`, { okLabel: '續接' }))) { draw(); return; } await api.patch(`/api/sessions/${sid}`, { action: 'resume' }); } setSession(sid); await ensureSession(); draw(); };
    $('#ch-new', chat).onclick = newSession;
    $('#ch-more', chat).onclick = moreMenu;
    $('#ch-send', chat).onclick = send;
    $('#ch-in', chat).onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
    box.onclick = async (e) => {
      const b = e.target.closest('[data-propose]'); if (!b) return;
      const p = JSON.parse(decodeURIComponent(b.dataset.propose));
      await confirmProposal(p, b);
    };
  }
  function msgHtml(m) {
    // ⏳ 「送出了、第一個片段還沒到」的佔位 —— 用會動的載入指示，不是一行死字。
    //    提早 return：下面那些 markdown 渲染對它一項都用不上。
    if (m.role === 'pending') return html`<div class="msg pending">${raw(spinner(m.text || '正在處理…'))}</div>`;
    const prop = m.proposal ? html`<div class="proposal"><h5>⚡ 提議執行（需你確認）</h5><div class="kv">${m.proposal.tool_id} · ${m.proposal.command_id}${m.proposal.selection?.length ? ` · ${m.proposal.selection.length} 條案例` : ''}${Object.keys(m.proposal.params || {}).length ? ' · ' + Object.entries(m.proposal.params).slice(0, 4).map(([k, v]) => `${k}=${v}`).join(' ') : ''}</div><div class="small muted">${m.proposal.reason || ''}</div><div class="row" style="margin-top:6px"><button class="btn sm primary" data-propose="${encodeURIComponent(JSON.stringify(m.proposal))}">檢視並執行</button></div></div>` : '';
    // ⚠️ 任務的提示有兩千多字（實測 1289px 高）—— 整段攤開會把回覆擠到看不見。
    //    超過門檻就收起來，讓人想看再展開。
    const LONG = 420;
    const long = (m.text || '').length > LONG && m.role === 'user';
    // ⭐ session 交出來的幾乎都是 markdown（判定表、結論、程式碼區塊）——
    //    直接塞字串的話表格會變成一行行的 `| A | B |`、`**粗體**` 星號原樣印出來。
    //    `ui/docview.js` 早就有渲染器，兩邊顯示的是同一種東西。
    const rich = m.role === 'assistant' || m.role === 'system';
    const body = long
      ? html`<details class="fold"><summary>任務提示（${(m.text || '').length} 字，點開看）</summary><div class="foldbody">${m.text}</div></details>`
      : (rich ? raw(`<div class="md">${renderMarkdown(m.text || '')}</div>`) : m.text);
    // ⭐ 工具呼叫要看得見 —— session 在查索引／開瀏覽器／載 skill 的那幾分鐘，
    //    這是**唯一**能讓人知道「它還在做事」的東西（先前完全沒畫，畫面是空框）。
    const tl = (m.tools || []);
    const seen = [];
    for (const t of tl) if (!seen.includes(t)) seen.push(t);
    const tools = seen.length
      ? html`<div class="toolrow">${seen.slice(-6).map((t) => html`<span class="toolchip">${prettyTool(t)}</span>`)}${seen.length > 6 ? html`<span class="toolchip more">＋${seen.length - 6}</span>` : ''}</div>`
      : '';
    const empty = !((m.text || '').trim()) && m.role === 'assistant'
      ? raw(spinner(seen.length ? '正在使用工具…' : '正在思考…')) : '';
    return html`<div class="msg ${m.role}">${body}${raw(tools)}${empty}${raw(prop)}<div class="meta">${m.at?.slice(11)}</div></div>`;
  }

  async function send() {
    const inp = $('#ch-in', chat); const text = inp.value.trim(); if (!text) return;
    inp.value = ''; msgs.push({ role: 'user', text, at: new Date().toLocaleString('sv-SE') });
    // ⛔ 進行中的提示要**放進 msgs**，不能 append 到 DOM ——
    //    任何一次 draw() 都會重建 `#ch-msgs`，臨時元素當場被沖掉，
    //    於是按下去畫面還是不動（2026-08-23 UI 走查：只剩一個空方框）。
    const pending = { role: 'pending', text: '正在處理…', at: '', t0: Date.now() };
    msgs.push(pending); draw();
    const tick = setInterval(() => {
      if (!msgs.includes(pending)) return;
      const s = Math.round((Date.now() - pending.t0) / 1000);
      pending.text = `正在處理…（已 ${s < 60 ? s + ' 秒' : Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒'}）`
        + (s > 20 ? ' —— 它會先載入 skill、查索引，第一段文字通常要等一下' : '');
      scheduleDraw();
    }, 1000);
    const drop = () => { const i = msgs.indexOf(pending); if (i >= 0) msgs.splice(i, 1); };
    try { await streamReply(cur.id, text, drop); }
    catch (e) { msgs.push({ role: 'system', text: '送出失敗：' + e.message, at: '' }); }
    finally { clearInterval(tick); drop(); }
    await loadSessions(); cur = sessions.sessions.find((s) => s.id === cur.id) || cur; draw();
  }

  // SSE 串流：一邊產生一邊顯示。
  // 為什麼要串流：正式模式下它會先查好幾個 MCP 工具再回答，非串流要等十幾秒，
  // 這段時間畫面完全沒有反應（2026-08-23 階段 D-3）。
  // ⚠️ 必須定義在這個閉包內 —— `msgs` 與 `draw()` 是閉包變數。
  async function streamReply(sid, text, onFirst) {
    // ⛔ **POST，不要 GET** —— 任務的提示有兩千多字，塞進 query string
    //    URL 會破四千字元然後 500（2026-08-23 UI 走查：按下「開始」等於什麼都沒發生）。
    const url = `/api/chat/${sid}/stream`;
    let res;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
    } catch (e) { res = null; }
    if (!res || !res.ok || !res.body) {
      // 退回非串流 —— 有些環境（代理／舊瀏覽器）吃不了 SSE
      // 退回非串流：**會等到整段跑完**（可能好幾十分鐘），所以先講清楚
      msgs.push({ role: 'system', at: '',
        text: '⚠️ 串流不可用，改用一次性回覆 —— 這會等到它整段做完才顯示，中間畫面不會動。' });
      scheduleDraw();
      const d = await api.post(`/api/chat/${sid}`, { text });
      if (onFirst) onFirst();
      msgs.push(d.message); scheduleDraw(); return;
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    const SEP = String.fromCharCode(10, 10);       // 事件分隔＝兩個換行
    const NL = String.fromCharCode(10);
    let buf = '', acc = '', live = null; const tools = [];
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      const chunks = buf.split(SEP); buf = chunks.pop() || '';
      for (const c of chunks) {
        const line = c.split(NL).find((x) => x.startsWith('data:'));
        if (!line) continue;
        if (onFirst) { onFirst(); onFirst = null; }   // 第一個事件到了才收掉「處理中」
        let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch (err) { continue; }
        if (ev.type === 'text') {
          acc += ev.text;
          if (!live) { live = { role: 'assistant', text: acc, at: '' }; msgs.push(live); }
          else live.text = acc;
          scheduleDraw();
        } else if (ev.type === 'tool' && ev.name !== '_init') {
          tools.push(ev.name);
          if (!live) { live = { role: 'assistant', text: '', at: '' }; msgs.push(live); }
          live.tools = tools.slice(); scheduleDraw();
        } else if (ev.type === 'drafts') {
          // ⭐ 平台收到什麼、自動寫了什麼、哪一筆要你按 —— 這一段先前被整個丟掉。
          const L = [];
          if (ev.bugs && !(ev.filed || []).length) L.push(`🐞 Bug 草稿 ${ev.bugs} 筆`);
          if (ev.cases_written?.ok) {
            L.push(`✅ 已寫入 ${ev.cases_written.collected} 條案例 → \`${ev.cases_written.path}\`　（已跑 --collect-only 驗證，到「案例」頁看）`);
          } else if (ev.cases_written) {
            L.push(`❌ 案例寫檔失敗：${(ev.cases_written.errors || []).join('；')}`);
          } else if (ev.cases) {
            L.push(`✍️ 案例草稿 ${ev.cases} 條`);
          }
          for (const b of ev.filed || []) L.push(`🐞 **已開單 ${b.bug_id}** → \`${b.path}\`　（到產品頁的 Bug 分頁看，確認後轉 JIRA 並回填單號）`);
          for (const bp of ev.bugs_pending || []) L.push(`⏸️ 「${bp.title || ''}」沒有自動開單 —— ${bp.why}`);
          for (const w of ev.written || []) L.push(`✅ 已自動寫入 \`${w.path}\`${w.id ? `（編號 ${w.id}）` : ''}`);
          for (const r of ev.needs_review || []) L.push(`⚠️ 「${r.title || ''}」沒有自動寫 —— ${r.why}`);
          for (const f of ev.write_failed || []) L.push(`❌ 「${f.title || ''}」寫入失敗：${(f.errors || []).join('；')}`);
          if (L.length) { msgs.push({ role: 'system', text: L.join('\n\n'), at: '' }); scheduleDraw(); }
        } else if (ev.type === 'error') {
          msgs.push({ role: 'system', text: '⚠️ ' + ev.message, at: '' }); scheduleDraw();
        } else if (ev.type === 'done') {
          if (!live) { live = { role: 'assistant', text: acc || '（沒有輸出）', at: '' }; msgs.push(live); }
          live.tools = tools.slice(); live.proposal = ev.proposal; scheduleDraw();
        }
      }
    }
  }
  async function newSession() {
    const models = claude?.models || [{ value: 'sonnet', label: 'Sonnet' }, { value: 'opus', label: 'Opus' }];
    const body = document.createElement('div');
    body.innerHTML = html`<div class="field"><label>標題（可留空自動取）</label><input id="ns-title" type="text" placeholder="例：ZS 階段失敗分析"></div>
      <div class="field" style="margin-top:8px"><label>模型</label><select id="ns-model">${models.map((m) => html`<option value="${m.value}" ${m.value === (claude?.default_model || 'sonnet') ? raw('selected') : ''}>${m.label}</option>`)}</select><span class="tiny muted">⚠ 模型在 session 建立時決定，中途不能切；要換模型＝開新 session 或分叉。</span></div>
      <div class="field boolean" style="margin-top:8px"><label><input type="checkbox" id="ns-ctx" checked> 帶入目前上下文（選取的案例、正在看的 run）</label></div>`;
    modal.open({ title: '新對話', body, actions: [{ label: '取消' }, { label: '建立', cls: 'primary', onClick: async (b) => {
      const ctx = $('#ns-ctx', b).checked ? { selection_count: state.selection.size, hash: location.hash, active_runs: (state.active || []).map((r) => r.run_id) } : null;
      const d = await api.post('/api/sessions', { title: $('#ns-title', b).value.trim(), model: $('#ns-model', b).value, context: ctx });
      setSession(d.session.id); await ensureSession(); draw();
    } }] });
  }
  async function moreMenu() {
    const body = document.createElement('div');
    body.innerHTML = `<div class="stack">
      <button class="btn block" data-act="rename">重新命名</button>
      <button class="btn block" data-act="fork">分叉（保留原 session 另開一條）</button>
      <button class="btn block" data-act="close">關閉（結束程序，紀錄保留、可續接）</button>
      <button class="btn block danger" data-act="delete">刪除（對話就沒了）</button></div>`;
    const m = modal.open({ title: `session：${esc(cur.title)}`, body, actions: [{ label: '取消' }] });
    body.onclick = async (e) => {
      const a = e.target.closest('[data-act]')?.dataset.act; if (!a) return; m.close();
      if (a === 'rename') { const t = await modal.prompt('重新命名', '新標題', cur.title); if (t) { await api.patch(`/api/sessions/${cur.id}`, { title: t }); } }
      else if (a === 'fork') { const d = await api.post(`/api/sessions/${cur.id}/fork`); setSession(d.session.id); toast('已分叉', 'success'); }
      else if (a === 'close') { await api.patch(`/api/sessions/${cur.id}`, { action: 'close' }); setSession(null); toast('已關閉（可在下拉「已關閉」區續接）'); }
      else if (a === 'delete') { if (await modal.confirm('刪除 session', '刪除後對話紀錄無法復原。', { danger: true, okLabel: '刪除' })) { await api.del(`/api/sessions/${cur.id}`); setSession(null); toast('已刪除'); } }
      await ensureSession(); draw();
    };
  }
  async function confirmProposal(p, btn) {
    const tool = state.tools.find((t) => t.id === p.tool_id);
    const danger = tool?.danger?.level === 'high';
    const ok = await modal.confirm('確認執行提議', `<div><b>${esc(tool?.name || p.tool_id)}</b> · ${esc(p.command_id)}</div><div class="small muted">${esc(p.reason || '')}</div>
      <pre>${esc(JSON.stringify({ params: p.params, selection: p.selection?.length ? `${p.selection.length} 條` : undefined }, null, 1))}</pre>
      ${danger ? `<div class="alert is-warn small">${esc(tool.danger.confirm_text || '此工具會寫入測試站。')}</div>` : ''}
      <div class="tiny muted">這是 Claude 的提議；<b>只有你按下「執行」才會真的跑</b>。</div>`, { danger, okLabel: '執行' });
    if (!ok) return;
    try { const d = await api.post('/api/runs/start', { tool_id: p.tool_id, command_id: p.command_id, params: p.params || {}, selection: p.selection || [], remark: '由對話提議' }); toast('已啟動 ' + d.run_id, 'success'); (await import('../poll.js')).kick(); navigate(`/run/${d.run_id}`); }
    catch (e) { toast(e.message, 'danger', 6000); }
  }
}
