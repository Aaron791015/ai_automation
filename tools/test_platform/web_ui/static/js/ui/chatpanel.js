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
import { newSessionDialog } from './newsession.js';

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
  // ⏳ 「這一輪還在跑」的狀態（見下方 `runningBar`）。
  //    ⚠️ **必須宣告在第一次 `draw()` 之前** —— `let` 不會提升，而 `draw()` 會讀它，
  //       放在下面就是 TDZ：`Cannot access 'running' before initialization`，
  //       症狀是**對話面板整個開不起來**（2026-08-28 實測；同一個坑本檔已記過兩次）。
  let running = null;      // { t0, tool, got }
  let runTick = 0;
  // ⛔ 程式自己捲動時的閘（見 `markProgrammatic`）。**同樣必須在第一次 `draw()` 之前** ——
  //    這是本檔第三次踩到同一個 TDZ（`_TOOL_ZH`／`running`／`programmatic`）。
  //    ⭐ 所以現在有一條測試在守：`test_chatpanel的let都要宣告在第一次draw之前`。
  let programmatic = false;
  // 最後一次**人的**捲動手勢（見 `box.onscroll`）。⚠️ 同樣必須在第一次 `draw()` 之前。
  let userScrollAt = 0;
  // 使用者是不是還貼在訊息底部（決定串流時要不要自動捲）。預設 true ＝ 剛開啟。
  let atBottom = true;
  // ⭐ 旁觀用的訂閱（`/api/chat/<id>/events`）—— 這一輪不是本分頁送出的時候用。
  //    ⛔ 它與 `streamReply()` 的 fetch 串流**不可以同時開**，否則同一段文字畫兩次。
  let feed = null;
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
    switchFeed();          // ⛔ 換了 session 就要重接訂閱（見 `switchFeed`）
  }
  await ensureSession();
  draw();
  openFeed();

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
    // ⚠️ 這一輪是**本面板送出**的（`send()` 走 SSE，畫面上有 `running` 指示列）——
    //    不要插手，否則會多出第二個指示器，而且輪詢的 `scheduleDraw()`
    //    會跟串流搶著重畫。
    // ⛔ 判準原本是「pending 那一則帶不帶 `t0`」，而 2026-08-28 `send()` 已改用
    //    `running` 狀態、不再推 pending —— 那個判準當場失效卻沒有人發現。
    if (running) return;
    const p0 = msgs.find((m) => m.role === 'pending');
    if (!p0) {
      msgs.push({ role: 'pending', ...watchInfo(cur) });
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
        if (p) { Object.assign(p, watchInfo(cur)); scheduleDraw(); }
        watchRunning();
        return;
      }
      msgs = d.messages || [];                              // 跑完了：換成落檔後的完整內容
      scheduleDraw();
    }, 3000);
  }

  /**
   * 旁觀一輪「別的地方送出的」session 時，畫面上該有什麼。
   *
   * ⚠️ 2026-08-28 使用者回報「有動畫了，但是處理過程消失了」——
   *    旁觀模式**拿不到串流**，所以沒有累積中的文字與工具 chip，只有一行字。
   * ⭐ 但平台其實一直有存 `activity_tools`（`note_tool()` 每個工具事件寫一次）——
   *    把它畫成 chip，旁觀者就看得到「它走到哪了」，而不是只有一句「處理中」。
   * ⛔ 走到一半的**文字**確實還拿不到（要等 `_persist()` 落檔），所以不假裝有 ——
   *    講明「跑完才會出現在這裡」，比讓人等一個不會來的東西好。
   */
  function watchInfo(m) {
    const t0 = Date.parse((m.activity_started_at || '').replace(' ', 'T'));
    const min = t0 ? Math.max(0, Math.round((Date.now() - t0) / 60000)) : 0;
    return {
      text: `正在處理…（已 ${min} 分鐘）　這一輪是在別處送出的，`
        + `完整回覆會在跑完後出現在這裡`,
      tools: (m.activity_tools || []).slice(),
      at: '',
    };
  }

  /**
   * ★ 捲動位置要在重建之後**還原**，不是只有「原本在底部就回底部」。
   *
   * ⚠️ 2026-08-28 使用者回報：「訊息較長時，開啟會自動跳到最上面，或者滾動時直接跳到最上面」。
   *    成因是一條會自我維持的迴圈：
   *      ① `draw()` 整段重建 `#ch-msgs` → `scrollTop` 歸 0
   *      ② 歸 0 觸發 `onscroll` → `atBottom` 被算成 false
   *      ③ 之後每次重建都不再回底部，於是**永遠停在最上面**
   *    而重建的來源不只串流：`watchRunning()` 每 3 秒輪詢一次也會重畫 ——
   *    所以「人往上滑到一半，三秒後被彈回頂端」。
   *
   * ⛔ 關鍵是 `programmatic` 這道閘：程式自己捲的那一下**不可以**去更新 `atBottom`，
   *    否則第 ② 步的誤判會原封不動地回來。
   */
  function markProgrammatic() {
    programmatic = true;
    // scroll 事件是非同步派送的 —— 下一幀才放行，才擋得住自己造成的那一次
    requestAnimationFrame(() => requestAnimationFrame(() => { programmatic = false; }));
  }

  function toBottom(box) {
    markProgrammatic();
    box.scrollTop = box.scrollHeight;
    const again = () => {
      if (!atBottom || !box.isConnected) return;
      markProgrammatic();
      box.scrollTop = box.scrollHeight;
    };
    // 面板是動畫開啟的：第一次 `draw()` 時容器高度還沒定案，`scrollHeight` 量到舊值
    // （甚至是 0），設了等於沒設 —— 症狀是**每次開啟都停在最上面**（2026-08-25 使用者回報）。
    requestAnimationFrame(again);
    setTimeout(again, 140);
    setTimeout(again, 420);       // 長訊息的 markdown 渲染完才會再長高一次
  }

  /**
   * ⤒ ⤓ 一鍵到頂／到底。
   *
   * 使用者 2026-08-28 問「是否需要」。評估後**做，但只在用得到的時候出現**：
   *   · 探索 session 實際到過 44 則，翻回開頭要拖很久 —— 拖桿在這裡是很差的介面
   *   · 串流中往上翻讀前面的判定表之後，「回到最新」是每一輪都會用到的動作
   * ⛔ 但**不能常駐**：多數對話只有兩三則，兩顆永遠亮著的按鈕就是純粹的雜物。
   *   所以已經在頂／底時，該側那一顆就隱藏（`hidden`）。
   */
  function paintJump() {
    const box = $('#ch-msgs', chat); if (!box) return;
    let wrap = $('#ch-jump', chat);
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'ch-jump'; wrap.className = 'chat-jump';
      wrap.innerHTML = '<button class="jb" data-to="top" title="到最上面">⤒</button>'
        + '<button class="jb" data-to="bottom" title="到最新">⤓</button>';
      wrap.onclick = (e) => {
        const to = e.target.closest('[data-to]')?.dataset.to; if (!to) return;
        atBottom = to === 'bottom';          // ⭐ 按了「到最新」就重新黏底
        markProgrammatic();
        box.scrollTop = to === 'top' ? 0 : box.scrollHeight;
        paintJump();
      };
      box.parentElement.appendChild(wrap);
    }
    const room = box.scrollHeight - box.clientHeight;
    // 內容還沒長到需要捲動就整組收起來
    wrap.hidden = room < 80;
    wrap.querySelector('[data-to="top"]').hidden = box.scrollTop < 40;
    wrap.querySelector('[data-to="bottom"]').hidden = room - box.scrollTop < 40;
  }

  /** 還原重建前的捲動位置（人不在底部時）。 */
  function restoreScroll(box, top) {
    markProgrammatic();
    box.scrollTop = top;
  }

  /**
   * ⏳ 「這一輪還在跑」的常駐指示。
   *
   * ⚠️ 2026-08-28 使用者回報「不曉得是不是還在處理任務」。成因是**指示只活到第一個事件**：
   *    `pending` 那一則在 `onFirst` 就被拿掉，之後畫面上只剩一段不會動的文字 ——
   *    而 session 往往才剛開始（載 skill、開瀏覽器、跑腳本，一輪十幾分鐘）。
   *    工具 chip 雖然會更新，但它是靜態的，看起來跟講完了沒兩樣。
   *
   * ⭐ 所以改成**從送出到 done 全程都在**，並且講得出「現在在做什麼、已經多久」——
   *    靜止的東西看起來像卡死，這個結論本檔已經下過兩次（2026-08-23、08-24）。
   */

  function startRunning() {
    running = { t0: Date.now(), tool: '', note: '', got: false };
    clearInterval(runTick);
    // ⛔ **不可以每秒 `draw()`** —— 那會把 `#ch-msgs` 整段 innerHTML 重建：
    //    ① 點點的動畫是 `chat-dot 1.1s infinite`，元素每秒被重建就永遠停在第 0 幀
    //       —— 看起來完全沒有動畫（2026-08-28 使用者回報）
    //    ② 串流中的文字與工具 chip 每秒被沖掉重建，過程內容看起來會消失
    //    所以計時器只改**那一行字**，不碰 DOM 結構。
    runTick = setInterval(paintRunning, 1000);
  }

  function stopRunning() {
    running = null; clearInterval(runTick); runTick = 0;
  }

  /** 指示列現在該寫什麼。
   *
   * ⛔ **不可以叫 `runningLabel`** —— 上面早就有一個同名的（吃 session 物件，
   *    給 `watchRunning()` 用）。函式宣告後者覆蓋前者，於是
   *    `watchRunning` 的 `runningLabel(cur)` 會跑進這一支、讀到 `running` 是 null
   *    直接 throw（2026-08-28 自我 review 抓到，尚未被使用者踩到）。
   */
  function runLabel() {
    const s = Math.round((Date.now() - running.t0) / 1000);
    const el = s < 60 ? s + ' 秒' : Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒';
    // ⚠️ `note` 是平台自己的短標籤（換工作記憶、接著跑下一則）——
    //    ⛔ 不可以把整句告知塞進 `tool`，那會讓同一句話在畫面上出現兩次。
    const what = running.tool ? '正在使用 ' + prettyTool(running.tool)
      : running.note ? running.note
      : running.got ? '正在整理回覆' : '正在啟動 session';
    return what + ' · 已 ' + el;
  }

  /**
   * 就地更新指示列（**不重建 DOM**，見 `startRunning` 的說明）。
   * 找不到那個元素才退回整段重畫 —— 例如剛送出、還沒畫過。
   */
  function paintRunning() {
    if (!running) return;
    const bar = chat.querySelector('#ch-run');
    if (!bar) { scheduleDraw(); return; }
    const lb = bar.querySelector('.lb');
    if (lb) lb.textContent = runLabel();
    // ⚠️ 前 20 秒不要講「通常要等一下」—— 那時候還沒有等待感，講了只是噪音。
    const s = Math.round((Date.now() - running.t0) / 1000);
    const want = s > 20 && !running.got;
    let hint = bar.querySelector('.rb-hint');
    if (want && !hint) {
      hint = document.createElement('span');
      hint.className = 'rb-hint';
      hint.textContent = '它會先載入 skill、查索引，第一段文字通常要等一下';
      bar.append(hint);
    } else if (!want && hint) {
      hint.remove();
    }
  }

  function runningBar() {
    // ⭐ 中止鈕就放在指示列上 —— 要停的時候人正在看著這一行
    return html`<div class="msg running" id="ch-run">${raw(spinner(runLabel()))}
      <button class="btn tiny" id="ch-stop" title="中止這一輪（已產出的內容會留下）">中止</button></div>`;
  }

  function scheduleDraw() {
    if (drawRaf) return;
    drawRaf = requestAnimationFrame(() => { drawRaf = 0; draw(); });
  }

  function draw() {
    // ⚠️ 重建**之前**先量 —— innerHTML 一換，scrollTop 就沒了
    const keepTop = $('#ch-msgs', chat)?.scrollTop || 0;
    chat.innerHTML = html`
      <div class="head">
        <!-- ⚠️ 標籤的數量用 active_count／closed_count，不要用清單長度 ——
             清單可能被截斷，先前 API 的 [:10] 就讓這裡顯示「進行中（10）」
             而實際有 14 條，且第 11 條之後**根本選不到**（2026-08-27 修）。
             ⛔ 這段註解裡不可以出現反引號 —— 它在 template literal 內，
                反引號會直接終止字串，整頁變空白。 -->
        <select id="ch-sel" title="切換 session（● 進行中／○ 已關閉）">
          ${sessions.active.length ? html`<optgroup label="進行中（${sessions.active_count ?? sessions.active.length}）">${sessions.active.map((s) => html`<option value="${s.id}" ${s.id === cur.id ? raw('selected') : ''}>● ${s.title} · ${s.model} · ${s.message_count} 則</option>`)}</optgroup>` : ''}
          ${sessions.closed.length ? html`<optgroup label="已關閉（${sessions.closed_count ?? sessions.closed.length}）">${sessions.closed.map((s) => html`<option value="${s.id}">○ ${s.title} · ${s.model} · ${fmt.ago(s.last_active)}</option>`)}</optgroup>` : ''}
        </select>
        <button class="btn sm" id="ch-new">＋ 新對話</button>
        <button class="btn sm ghost" id="ch-more">⋯</button>
        <a class="btn sm ghost" href="#/sessions" title="全部 session（含全文搜尋）">全部</a>
      </div>
      <div class="msgs" id="ch-msgs">${msgs.length ? msgs.map(msgHtml) : html`<div class="msg system">新對話（${cur.model}）。試試：「幫我找變動賠率的案例」「CRUX-874 現況」「上次失敗的重跑一次」</div>`}${running ? runningBar() : ''}</div>
      <div class="input"><textarea id="ch-in" placeholder="輸入訊息… Enter 送出，Shift+Enter 換行"></textarea><button class="btn primary" id="ch-send">送出</button></div>`;
    const box = $('#ch-msgs', chat);
    // ⭐ **只有原本就貼在底部時才捲到底**。先前是無條件 `scrollTop = scrollHeight`，
    //    串流中一秒搶好幾次 —— 人想往上翻看前面的判定表，手一放開就被拉回去。
    // ⭐ 不在底部時**還原到重建前的位置**（2026-08-28）—— 先前是什麼都不做，
    //    而重建會讓 `scrollTop` 歸 0，等於「往上滑到一半就被彈回頂端」。
    if (atBottom) toBottom(box); else restoreScroll(box, keepTop);
    // ⭐ 「要不要黏在底部」**只由人的手勢決定**。
    //    ⛔ 先前是每個 scroll 事件都重算，於是程式自己捲出來的事件（版面在
    //       140/420ms 重試之間長高、事件延後派送）會把 atBottom 誤設成 false，
    //       而它只有「人捲回底部」或「按 ⤓」能變回 true —— 錯一次就永久不再自動跟。
    //       實測：串流中距底 287 → 361 → 385 一路長（2026-08-28 使用者回報）。
    ['wheel', 'touchmove', 'mousedown', 'keydown'].forEach((ev) =>
      box.addEventListener(ev, () => { userScrollAt = Date.now(); }, { passive: true }));
    box.onscroll = () => {
      paintJump();                       // 按鈕的顯示狀態一律更新
      if (programmatic) return;
      // ⚠️ 700ms：一次滾輪動作會連續派送好幾個 scroll 事件，要都算在同一個手勢裡
      if (Date.now() - userScrollAt > 700) return;
      atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
    };
    paintJump();
    $('#ch-sel', chat).onchange = async (e) => { const sid = e.target.value; const s = sessions.sessions.find((x) => x.id === sid); if (s.state === 'closed') { if (!(await modal.confirm('續接 session', `「${esc(s.title)}」已關閉。續接會重新載入 <b>${s.message_count}</b> 則對話脈絡（正式模式會消耗額度）。`, { okLabel: '續接' }))) { draw(); return; } await api.patch(`/api/sessions/${sid}`, { action: 'resume' }); } setSession(sid); await ensureSession(); draw(); };
    $('#ch-new', chat).onclick = newSession;
    $('#ch-more', chat).onclick = moreMenu;
    $('#ch-send', chat).onclick = send;
    const stopBtn = chat.querySelector('#ch-stop');
    if (stopBtn) stopBtn.onclick = interrupt;
    $('#ch-in', chat).onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };
    box.onclick = async (e) => {
      const b = e.target.closest('[data-propose]'); if (!b) return;
      const p = JSON.parse(decodeURIComponent(b.dataset.propose));
      await confirmProposal(p, b);
    };
  }
  function msgHtml(m) {
    // ⏳ `watchRunning()` 用的佔位（**別的地方**讓這個 session 跑起來，這個面板只是在旁邊看）。
    //    ⚠️ 2026-08-28 一度被誤刪：當時以為 `pending` 只有 `send()` 在用，
    //       而 `send()` 已改用 `running` 狀態 —— 但 `watchRunning()` 仍然在推這個 role，
    //       刪掉之後它會退回純文字、沒有載入動畫。
    if (m.role === 'pending') {
      // ⭐ 旁觀模式也要看得到「它走到哪了」—— chip 來自 meta 的 `activity_tools`
      //    （見 `watchInfo`）。先前只有一行字，使用者回報「處理過程消失了」。
      const seenT = [];
      for (const t of (m.tools || [])) if (!seenT.includes(t)) seenT.push(t);
      const row = seenT.length
        ? html`<div class="toolrow">${seenT.slice(-8).map((t) => html`<span class="toolchip">${prettyTool(t)}</span>`)}${seenT.length > 8 ? html`<span class="toolchip more">＋${seenT.length - 8}</span>` : ''}</div>`
        : '';
      return html`<div class="msg pending">${raw(spinner(m.text || '正在處理…'))}${row}</div>`;
    }
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
    // ⛔ 進行中的指示要**放進 draw() 畫的東西裡**，不能 append 到 DOM ——
    //    任何一次 draw() 都會重建 `#ch-msgs`，臨時元素當場被沖掉，
    //    於是按下去畫面還是不動（2026-08-23 UI 走查：只剩一個空方框）。
    // ⭐ 2026-08-28 從「一則 pending 訊息」改成 `running` 狀態：
    //    先前它在第一個事件就被拿掉，之後整輪都沒有任何「還在跑」的跡象。
    // ⚠️ 已經在跑就**不要重開指示列** —— 排隊的那一則會把計時歸零，
    //    畫面看起來像是重新開始（2026-08-28 瀏覽器走查：跑了 12 秒卻顯示「已 4 秒」）。
    if (!running) startRunning();
    draw();
    // ⭐ 一條訂閱看到底 —— **不要每次送出都開一條新串流**：同一個面板掛兩條訂閱，
    //    之後每個事件都會被畫兩次（2026-08-28 瀏覽器走查：「已排隊」出現兩次）。
    if (!feed) openFeed();
    if (feed) {
      try { await api.post(`/api/chat/${cur.id}/send`, { text }); }
      catch (e) { msgs.push({ role: 'system', text: '送出失敗：' + e.message, at: '' }); stopRunning(); draw(); }
      return;                       // 之後的畫面由 `openFeed()` 的訂閱接手
    }
    // 退路：EventSource 開不起來（舊環境／代理）—— 用單次串流自己畫
    try { await streamReply(cur.id, text); }
    catch (e) { msgs.push({ role: 'system', text: '送出失敗：' + e.message, at: '' }); }
    finally { stopRunning(); }
    await loadSessions(); cur = sessions.sessions.find((s) => s.id === cur.id) || cur; draw();
  }

  // SSE 串流：一邊產生一邊顯示。
  // 為什麼要串流：正式模式下它會先查好幾個 MCP 工具再回答，非串流要等十幾秒，
  // 這段時間畫面完全沒有反應（2026-08-23 階段 D-3）。
  // ⚠️ 必須定義在這個閉包內 —— `msgs` 與 `draw()` 是閉包變數。
  /** 一輪串流的累積狀態（正在長出來的那一則、文字、工具）。 */
  function newFeed() { return { acc: '', live: null, tools: [] }; }

  /**
   * 把一個事件套進畫面。**送出與旁觀共用這一支。**
   *
   * ⛔ 兩邊各寫一份的話，旁觀模式會永遠少掉最新加的那種事件 ——
   *    2026-08-28 之前旁觀根本沒有事件可用（只能輪詢工具名），就是這麼來的。
   */
  function applyEvent(ev, S) {
    if (ev.type === 'text') {
      if (running) { running.got = true; running.tool = ''; }
      S.acc += ev.text;
      if (!S.live) { S.live = { role: 'assistant', text: S.acc, at: '' }; msgs.push(S.live); }
      else S.live.text = S.acc;
      scheduleDraw();
    } else if (ev.type === 'tool' && ev.name !== '_init') {
      // ⭐ 指示列要講得出「現在在做什麼」—— 只寫「處理中」等於沒講
      if (running) { running.tool = ev.name; running.got = false; }
      S.tools.push(ev.name);
      if (!S.live) { S.live = { role: 'assistant', text: '', at: '' }; msgs.push(S.live); }
      S.live.tools = S.tools.slice(); scheduleDraw();
    } else if (ev.type === 'notice') {
      // ⭐ 平台自己要講的話 —— **只畫一次**（一行字），指示列另外用短標籤。
      //    ⛔ 先前是借用 `tool` 事件，於是同一句話同時變成 chip 與「正在使用 …」
      //       （2026-08-28 使用者截圖：壓縮提示整句出現兩次）。
      if (running) { running.tool = ''; running.note = ev.label || ''; running.got = false; }
      msgs.push({ role: 'system', text: ev.text, at: '' });
      scheduleDraw();
    } else if (ev.type === 'turn_start') {
      // ⛔ 新的一輪開始 —— 累積狀態一定要歸零。被中止的那一輪**沒有 `done`**，
      //    不歸零的話 `S.live` 會留著一個已經被 `reloadMsgs()` 換掉的物件，
      //    下一輪的文字全部寫進那個孤兒，畫面上一個字都不會出現。
      S.acc = ''; S.live = null; S.tools.length = 0;
    } else if (ev.type === 'queued') {
      msgs.push({ role: 'system', at: '',
        text: `⏳ 已排隊（前面還有 ${ev.n} 則）—— 目前這一輪跑完會自動接著跑。` });
      scheduleDraw();
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
      if (!S.live) { S.live = { role: 'assistant', text: S.acc || '（沒有輸出）', at: '' }; msgs.push(S.live); }
      S.live.tools = S.tools.slice(); S.live.proposal = ev.proposal; scheduleDraw();
      // ⭐ 一輪結束 —— 排隊中的下一則要**另外長成一則**，不可以接在這一則後面
      S.acc = ''; S.live = null; S.tools.length = 0;
    }
  }

  async function streamReply(sid, text) {
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
      // 退回非串流：**會等到整段跑完**（可能好幾十分鐘），所以先講清楚
      msgs.push({ role: 'system', at: '',
        text: '⚠️ 串流不可用，改用一次性回覆 —— 這會等到它整段做完才顯示，中間畫面不會動。' });
      scheduleDraw();
      const d = await api.post(`/api/chat/${sid}`, { text });
      msgs.push(d.message); scheduleDraw(); return;
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    const SEP = String.fromCharCode(10, 10);       // 事件分隔＝兩個換行
    const NL = String.fromCharCode(10);
    let buf = ''; const S = newFeed();
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      const chunks = buf.split(SEP); buf = chunks.pop() || '';
      for (const c of chunks) {
        const line = c.split(NL).find((x) => x.startsWith('data:'));
        if (!line) continue;
        let ev; try { ev = JSON.parse(line.slice(5).trim()); } catch (err) { continue; }
        applyEvent(ev, S);
      }
    }
  }

  /**
   * 旁觀：這一輪不是本分頁送出的（重整過、任務啟動器起的、或另一個分頁）。
   *
   * ⭐ 訂閱 `/api/chat/<id>/events` —— **看得到完整的過程**，
   *    而不是 2026-08-28 之前那種「輪詢出來的一行字 ＋ 幾個工具名」。
   */
  function openFeed() {
    if (feed) return;                     // ⭐ 冪等：面板開著就只有一條訂閱
    clearTimeout(watchTimer);
    if (!cur) return;
    // ⭐ 這一輪不是本面板送出的（重整過／任務啟動器起的／另一個分頁）——
    //    也要有指示列與動畫，而且看得到過程。
    if (cur.activity === 'running' && !running) startRunning();
    const S = newFeed();
    let opened = false;
    try { feed = new EventSource(`/api/chat/${cur.id}/events`); } catch (e) { feed = null; }
    if (!feed) { watchRunning(); return; }   // 環境不支援 SSE → 退回輪詢
    feed.onopen = () => { opened = true; };
    feed.onmessage = (e) => {
      let ev; try { ev = JSON.parse(e.data); } catch (err) { return; }
      if (ev.type === 'idle') {
        // ⭐ **不關掉訂閱** —— 關了就看不到「別處送出的下一輪」，
        //    而重開一條又要付一次建立連線的成本。伺服器每 20 秒 ping 一次維持著。
        stopRunning(); reloadMsgs(); return;
      }
      applyEvent(ev, S);
    };
    feed.onerror = () => {
      // ⚠️ 連上過就交給 EventSource 自己重連（它會帶 `Last-Event-ID` 補播）；
      //    **從來沒連上**才退回輪詢 —— 否則一次抖動就永久降級。
      if (!opened) { closeFeed(); stopRunning(); watchRunning(); }
    };
  }

  /** ⛔ 換 session 一定要重接 —— 否則會一直聽著**上一個** session。 */
  function switchFeed() { closeFeed(); openFeed(); }

  function closeFeed() { if (feed) { try { feed.close(); } catch (e) { /* ignore */ } feed = null; } }

  async function reloadMsgs() {
    if (!chat.isConnected || !cur) return;
    try { const d = await api.get(`/api/sessions/${cur.id}`); msgs = d.messages || []; cur = d.session; }
    catch (e) { /* 下一次輪詢會補 */ }
    draw();
  }

  /** ⛔ 中止這一輪（終端機的 Esc）—— 已產出的內容會留下。 */
  async function interrupt() {
    if (!cur) return;
    try {
      const d = await api.post(`/api/chat/${cur.id}/interrupt`, {});
      toast(d.dropped ? `已中止，並丟掉排隊中的 ${d.dropped} 則` : '已中止這一輪');
    } catch (e) { toast(e.message, 'danger'); }
  }

  async function newSession() {
    // ⭐ 對話框與 `#/sessions` 頁共用一份（`ui/newsession.js`）——
    //    先前兩邊各寫一份，那一頁的版本沒有模型下拉。
    const sess = await newSessionDialog();
    if (!sess) return;
    setSession(sess.id); await ensureSession(); draw();
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
