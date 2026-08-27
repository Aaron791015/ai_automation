// #/ 總覽（態勢感知，嚴格單屏）：頂部狀態列／左側 HERO（產品基座＋知識雷達）／右側監控卡。
// Dashboard 回答「現在如何」，不回答「我要做什麼」—— 工具清單在 #/tools。
import { api } from '../api.js';
import { $, $$, html, raw, fmt, esc } from '../ui/el.js';
import { state, subscribe, set } from '../store.js';
import { renderHero, updateHeroRuns } from '../ui/hero.js';
import { ring, dot, phaseLabel, toneOfPhase } from '../ui/hud.js';
import { toast } from '../ui/toast.js';
import { navigate } from '../router.js';
import { md, openTodo, keptBlock } from '../ui/todopanel.js';
import { renderTaskBar } from '../ui/tasklauncher.js';
import { renderChatPortal } from '../ui/chatportal.js';
import { spinner } from '../ui/loading.js';

let unsub = null, timer = null, resizeT = null;
// 掛載代號：載入中途被切走時（dispatch 會先 unmount 再清空 root），
// 尚未 resolve 的 fetch 續行段不可再畫 —— 否則 $('#c-sys .body') 已不存在而丟 TypeError。
let token = 0;
let knowledge = null, heat = [], health = null, bugs = null, todos = null, cases = null, usage = null;
// ⚠️ 不可寫死原型的產品 id —— 匯出的範本沒有 'crux'（2026-08-23 階段 B）
let curProd = null;

// ── 空狀態：還沒有任何產品 ──────────────────────────────────
// 同事拿到的範本 config/products.json 是空的 —— 知識雷達、待辦、Bug 全是 0，
// 他看到一片空白卻不知道下一步。這三步就是 README 的上手流程。
function emptyState(root) {
  root.innerHTML = html`<div class="screen"><div class="page" style="max-width:820px;margin:0 auto">
    <div class="page-head"><h2>還沒有接任何產品</h2>
      <span class="crumb">這是一份乾淨的範本 —— 照下面三步接上你的產品，儀表板就會活起來</span></div>
    <div class="page-body">
      <div class="card" style="margin-bottom:12px">
        <div class="name">① 裝通用 memory</div>
        <div class="subtitle">memory 存在 repo 外面、以路徑當 key，clone 帶不過來。
          這一步把範本內建的通用 QA 教訓裝進你的本機。</div>
        <div class="row" style="margin-top:8px">
          <a class="btn xs" href="#/settings/workspace">開啟設定 → 工作區 → 裝通用 memory</a></div>
      </div>
      <div class="card" style="margin-bottom:12px">
        <div class="name">② 接一個產品</div>
        <div class="subtitle">一次建好目錄、產品 skill 骨架、交接檔，並註冊到
          <code>config/products.json</code>（產品定義的單一來源）。
          ⛔ 不要手動建 —— 漏一步就不會被 lint 檢查到。</div>
        <div class="row" style="margin-top:8px">
          <a class="btn xs" href="#/settings/workspace">開啟設定 → 工作區 → 接一個產品</a></div>
      </div>
      <div class="card">
        <div class="name">③ 首次探索</div>
        <div class="subtitle">跟 Claude 說「載入 <code>/testcase-design</code>，我要探索 &lt;某個功能區塊&gt;」——
          寫 charter → 五來源交叉盤點 → 產出覆蓋矩陣。這一步的產物就是你的知識起點。</div>
        <div class="row" style="margin-top:8px">
          <a class="btn xs" href="#/doc?path=README.md">看 README 的完整上手五步</a></div>
      </div>
      <div class="tiny muted" style="margin-top:14px">
        接完產品後重新整理，這個畫面就會換成儀表板。</div>
    </div>
  </div>`;
}


export async function mount(root) {
  // 完全沒有產品 ＝ 剛匯出的範本：給引導而不是空的儀表板
  if (!(state.products || []).some((p) => !p.virtual)) { emptyState(root); return; }
  // 版面：主視覺獨占左側、卡片改右側欄垂直排列（2026-08-19 使用者裁示）
  // 原本的「系統狀態／執行狀態／環境健康」三張卡合併為一張「系統概況」，
  // 省下兩組卡框與標題列 —— 這是騰出主視覺高度的關鍵。
  root.innerHTML = html`<div class="screen dash">
    <!-- ① 頂部狀態列：橫貫全寬，一眼看完就不必再看的東西（數字／執行摘要／環境燈）。
         ⭐ 它原本是右欄第一張卡，把另外四張擠到摺線以下 —— 使用者連標題都看不到。 -->
    <header class="card dash-strip" id="c-sys">
      <div class="strip-seg stats"><div class="body" id="sys-stats">${spinner("統計中…")}</div></div>
      <!-- ⛔ 這裡原本還有一段「進行中／保留中／最近結果」，2026-08-25 移除 ——
           三個數字右欄的「運行中」卡全都有（進行中＝卡裡列的那幾筆、最近結果＝第一筆的通過/失敗/略過），
           而它在 1440 寬會折成兩行、**是整條狀態列最高的一段**（內容 112px，撐出 132px 的總高）。
           判準是使用者的原話：「與右側資訊重疊的話就移除，讓上下高度窄一點」。 -->
      <!-- ⭐ Claude 用量（2026-08-25 使用者要求）：放狀態列而不是右欄 ——
           右欄「四張卡分掉欄高」是版面保證（見 hud.css），插第五張會把每張都壓矮；
           而用量正好是狀態列的定義：**看一眼就不必再看的東西**。 -->
      <div class="strip-seg claude" id="c-claude" title="點開看用量明細"><div class="body" id="c-claude-body">${spinner("統計中…")}</div>
        <span class="strip-score" id="claude-plan"></span>
        <button class="strip-refresh" id="claude-refresh" title="重讀本機快照（額度 % 要先在 Claude Code 打 /usage 才會更新）">↻</button></div>
      <div class="strip-seg env"><div class="body" id="c-env-body"></div>
        <span class="strip-score" id="env-score"></span></div>
    </header>
    <div class="row-hero"><div id="hero"></div><div id="task-bar"></div>
      <!-- ⭐ 主視覺腳下的對話入口（2026-08-24 使用者裁示：把那顆「星塵光點」換成看得懂的入口）。
           這一頁出現它時，右下角那顆浮動鈕自動隱藏 —— 見 body.is-overview。 -->
      <div id="hero-portal"></div></div>
    <!-- ② 右欄**整欄不捲**（見 hud.css）：兩張卡分掉欄高、各自內捲。
         「有幾張卡」因此是版面保證的，不是使用者要捲到才會發現。
         ⭐ 2026-08-25 使用者裁示砍掉「助手提示」與「最近報告」——
            「實際用起來沒有太大用途，主要還是看**什麼在跑**、**還有什麼事要做**」。
            ⚠️ 24 小時執行熱度條原本住在「助手提示」卡裡，一起下架了。 -->
    <aside class="dash-side">
      <section class="card" id="c-active"><h3>運行中 <span class="cnt" id="active-cnt"></span></h3>
        <div class="body" id="active"></div>
        <!-- ⭐ 熱度條放在**捲動區之外** —— 上半（現在在跑什麼）再長，它都還在原地。 -->
        <div class="heat-foot">
          <div class="tiny muted heat-cap"><span>24 小時執行熱度</span><span>24 小時前 → 現在</span></div>
          <div class="heat-strip" id="heat"></div></div></section>
      <section class="card" id="c-todo"><h3>待辦 <span class="cnt" id="tb-jira"></span></h3>
        <div class="tabs" id="tb-tabs" style="margin:0 0 6px"></div><div class="body" id="tb-body"></div></section>
    </aside>
  </div>`;
  const my = ++token;
  const live = () => my === token;
  renderChatPortal($('#hero-portal', root));
  document.body.classList.add('is-overview');
  drawActive();
  // ★ 有快取就**立刻先畫一次**，不要空等四支 API。
  //   knowledge／health／bugs／todos／cases 都是模組層變數，離開總覽時不會被清掉 ——
  //   第二次以後進來其實資料早就在手上，卻還是等 fetch 回來才畫。
  //   那段空窗在主視覺那塊大面積上就是**一片黑**（2026-08-20 使用者：「其他頁面切回總覽，
  //   會先黑畫面才顯示」）。先畫快取、資料回來再重畫一次，是同一份程式碼跑兩趟，
  //   不需要另做骨架屏。
  if (knowledge) { drawHero(); drawTop(); drawTodo(); drawHeat(); }
  unsub = subscribe((s, patch) => {
    if (patch.active) { drawActive(); drawHero(); }
    // ⭐ session 的執行狀態也要即時反映（2026-08-24）
    if (patch.sessionRunning || patch.sessionReview) { drawActive(); drawHero(); }
  });
  await Promise.all([loadKnowledge(), loadSide(), loadHeat(), loadUsage()]);
  if (!live()) return;
  drawHero(); drawTop(); drawTodo();
  startPolling();
  window.addEventListener('resize', onResize);
}
// ★ 這一頁**留在文件裡**（router 用 content-visibility 隱藏），不重建 DOM。
//   主視覺 5,347 個 SVG 節點，重建一次 86ms／恢復只要 8–12ms（實測見 router.js 檔頭）。
export const keepAlive = true;

/** 切走：停掉所有會持續跑的東西，但**不動 DOM**。 */
export function pause() {
  token++;                                    // 讓還沒回來的 fetch 續行段自己作廢
  document.body.classList.remove('is-overview');   // 切走 → 右下角的浮動入口要回來
  unsub && unsub(); unsub = null;
  clearInterval(timer); timer = null;
  clearTimeout(resizeT);
  window.removeEventListener('resize', onResize);
}

/** 切回來：重新訂閱與輪詢，先用手上的資料立刻重畫，再背景刷新。 */
export async function resume() {
  const my = ++token;
  const live = () => my === token;
  document.body.classList.add('is-overview');
  renderChatPortal($('#hero-portal'));
  unsub = subscribe((s, patch) => {
    if (patch.active) { drawActive(); drawHero(); }
    if (patch.sessionRunning || patch.sessionReview) { drawActive(); drawHero(); }
  });
  window.addEventListener('resize', onResize);
  startPolling();
  // 切回來的**第一幀**只畫看得見的主體；待辦排到下一幀，
  // 免得幾個 draw 疊成一個 50ms 以上的長任務、把轉場的頭幾幀吃掉。
  drawActive(); drawHero(); drawTop();
  requestAnimationFrame(() => { if (live()) { drawTodo(); drawHeat(); drawUsage(); } });
  await Promise.all([loadKnowledge(), loadSide(), loadHeat(), loadUsage()]);
  if (!live()) return;
  drawHero(); drawTop(); drawTodo();
}

export function unmount() { pause(); }

function startPolling() {
  clearInterval(timer);
  const my = token;
  const live = () => my === token;
  timer = setInterval(() => {
    loadUsage();
    loadHeat();
    loadSide().then(() => { if (live()) drawTop(); });
  }, 60000);
}
function onResize() { clearTimeout(resizeT); resizeT = setTimeout(() => drawHero(true), 200); }

// ---------------------------------------------------------------- 載入
async function loadKnowledge() { try { knowledge = await api.get('/api/knowledge'); } catch (e) { const el = $('#hero'); if (el) el.innerHTML = `<div class="alert is-error">知識索引載入失敗：${esc(e.message)}</div>`; } }
async function loadHeat() { try { heat = (await api.get('/api/runs/heat')).heat || []; } catch (e) { heat = []; } drawHeat(); }
// Claude 用量：後端**不阻塞** —— 快取過期時只丟給背景執行緒，這裡拿到的可能是上一輪的數字
// （首次啟動會回 ready:false，畫面顯示「首次統計中」，下一輪 60 秒後就有了）。
async function loadUsage(force) {
  // ⚠️ force 只給使用者按 ↻ 時用 —— 平時輪詢一律走節流，別把額度端點打爆
  try { usage = await api.get('/api/claude/usage' + (force ? '?quota=force' : '')); } catch (e) { usage = null; }
  drawUsage();
}
async function loadSide() {
  // ★ bugs 要帶 slim=1：不帶參數時後端會剔掉 bugs[]（只回 counts／cross 的 id 陣列），
  //   側欄就列不出「活躍 Bug 前幾條」。slim=1 每條保留 11 欄白名單，含 path（給「看全文」用）。
  const r = await Promise.allSettled([api.get('/api/health'), api.get('/api/bugs?slim=1'), api.get('/api/todos'), api.get('/api/cases?slim=1')]);
  [health, bugs, todos, cases] = r.map((x) => (x.status === 'fulfilled' ? x.value : null));
}

// ---------------------------------------------------------------- 頂部狀態列
function drawTop() {
  const sysBody = $('#sys-stats'), envBody = $('#c-env-body');
  if (!sysBody || !envBody) return;      // 已被切走（與 mount 的 token 雙保險）
  const totCases = cases?.count ?? 0;
  // 三根柱子只畫「產品」案例，共通（tests/tooling 的工作區工具自測）沒有基座 ——
  // 於是柱上數字加總（491）與這裡的總數（622）對不起來，看的人會以為漏了。標出差額即可。
  // ⚠️ 不可以從知識雷達取 —— 它只掃**非虛擬**產品，`common` 根本不在裡面，
  //    於是 commonCases 恆為 0、那個「產品 N ＋ 共通 M」的子標籤**永遠不顯示**。
  //    結果：中央全息體寫「177 案例」、這裡寫「810」，兩個數字擺在同一畫面卻沒人說得出差別
  //    （2026-08-23 UI 走查）。案例索引自己就有分區數字。
  const commonCases = cases?.by_product?.common?.total ?? 0;
  const activeBugs = Object.values(bugs?.products || {}).reduce((a, p) => a + (p.active || 0), 0);
  const openTodos = Object.values(todos?.products || {}).reduce((a, p) => a + (p.open || 0), 0);
  const blockers = Object.values(todos?.products || {}).reduce((a, p) => a + (p.blockers?.length || 0), 0);
  const avgHealth = knowledge ? Math.round(Object.values(knowledge.products).reduce((a, p) => a + p.rings.health.value, 0) / Object.keys(knowledge.products).length) : null;
  sysBody.innerHTML = html`<div class="stat-row">
    <div class="stat" title="${commonCases ? `含共通 ${commonCases} 條（工作區工具自測，不屬任何產品，故不在三根柱子上）` : ''}"><span class="k">測試案例</span><span class="v accent">${fmt.int(totCases)}</span>${commonCases ? html`<span class="sub tiny muted">產品 ${fmt.int(totCases - commonCases)} ＋ 共通 ${fmt.int(commonCases)}</span>` : ''}</div>
    <div class="stat"><span class="k">活躍 Bug</span><span class="v ${activeBugs ? 'danger' : ''}">${activeBugs}</span></div>
    <div class="stat"><span class="k">未完成待辦</span><span class="v">${openTodos}</span></div>
    <div class="stat"><span class="k">Blocker</span><span class="v ${blockers ? 'danger' : 'success'}">${blockers}</span></div>
    <div class="stat"><span class="k">平均健康</span><span class="v ${avgHealth >= 80 ? 'success' : avgHealth >= 55 ? 'warn' : 'danger'}">${avgHealth ?? '—'}</span></div>
  </div>`;
  const c = Object.fromEntries((health?.checks || []).map((x) => [x.key, x]));
  const lamp = (k, label) => { const x = c[k]; return html`<span class="lamp ${x ? (x.ok ? 'ok' : 'bad') : ''}" title="${x?.detail || ''}">${dot(x ? (x.ok ? 'ok' : 'bad') : 'idle')}${label} <span class="v">${x ? (x.ok ? 'OK' : '缺') : '…'}</span></span>`; };
  const ports = health?.ports || {};
  const sc = $('#env-score'); if (sc) sc.textContent = health ? `${health.score}%` : '';
  envBody.innerHTML = html`<div class="lamp-row">
    ${raw(lamp('venv', '.venv'))}${raw(lamp('modules', '套件'))}${raw(lamp('allure', 'allure'))}${raw(lamp('claude', 'Claude'))}${raw(lamp('cases', '案例索引'))}${raw(lamp('disk', '磁碟'))}
  </div>
  <div class="lamp-row" style="margin-top:6px">
    ${Object.entries(ports).map(([k, v]) => html`<span class="lamp">${dot(v ? 'ok' : 'idle')}${esc(k)} <span class="v">${v ? '運作' : '未啟'}</span></span>`)}
  </div>
  <div class="tiny muted" style="margin-top:5px">${(health?.checks || []).find((x) => !x.ok)?.hint || 'JIRA：' + (bugs?.jira_source || '—') + (bugs?.jira_fetched_at ? ' · ' + bugs.jira_fetched_at : '')}</div>`;
}
// ---------------------------------------------------------------- Claude 用量
// 這一段同時給**兩種**用量，因為兩種各有各的缺點：
//   · 額度百分比：官方回報、有分母，但那是 Claude Code 抓完存在 ~/.claude.json 的**快照**
//   · token 數字：本機 transcript 統計，永遠即時，但**沒有分母**
// 額度百分比有兩個來源，優先用即時的：
//   ① 即時：平台自己打 `/api/oauth/usage`（5 分鐘節流，↻ 可立刻重打）
//   ② 退回：Claude Code 存在 ~/.claude.json 的快照 —— 它**不會自己更新**，要人去打 `/usage`
// ⛔ 不論哪一種都一律標出抓取時間；過期時**不畫進度條**（沒有分母的進度條是假的）。
function drawUsage() {
  const el = $('#c-claude-body'); if (!el) return;
  const seg = $('#c-claude'), badge = $('#claude-plan');
  const u = usage;
  const setBadge = (t, tip) => { if (badge) { badge.textContent = t || ''; badge.title = tip || ''; } };
  if (!u || u.ok === false) { setBadge(''); el.innerHTML = '<div class="muted small">用量無法取得</div>'; return; }
  if (!u.ready) { setBadge(''); el.innerHTML = String(spinner(u.hint || '首次統計中…')); return; }
  if (!u.available) {
    setBadge('');
    el.innerHTML = html`<div class="muted small">找不到 Claude Code 的紀錄目錄</div>
      <div class="tiny muted" style="margin-top:4px">用過 Claude Code 之後就會出現</div>`;
    return;
  }
  const w = u.windows, q = u.quota || {};
  // ⚠️ 角標**只放方案**（加時間會把第三欄的「今日」擠成「今…」，1440 寬實測）。
  //    抓取時間掛在 tooltip；**即時模式不另佔一行**（那 13px 換不到資訊 —— 即時本來就是新的），
  //    退回快照時才畫出來，因為那時候「什麼時候抓的」才是使用者真正要判斷的東西。
  const tier = q.tier_label || u.plan?.short || u.plan?.label || '';
  // ⚠️ 角標**只放方案**：加上時間會把第三欄的「今日」擠成「今…」（1440 寬實測）。
  //    新鮮度不靠這裡表達 —— 新鮮才會走百分比模式，過期會退回 token 模式並明講日期。
  setBadge(tier,
    (q.tier_label ? `方案：${q.tier_label}（Claude Code 回報的額度層級）\n` : '')
    + (q.fetched_at ? `額度 % 快照抓取時間：${q.fetched_at}\n` : '') + (u.plan?.note || ''));
  const tip = (x) => `輸入 ${fmt.int(x.input)}　輸出 ${fmt.int(x.output)}　快取寫 ${fmt.int(x.cache_write)}　快取讀 ${fmt.int(x.cache_read)}　訊息 ${fmt.int(x.messages)}`;
  el.innerHTML = q.usable ? quotaRow(q, w) : tokenRow(u, w, tip);
  bindUsageActions(seg);
}

// 整段可點進明細；右上角那顆 ↻ 只重讀，不要連帶跳頁。
function bindUsageActions(seg) {
  if (!seg || seg.dataset.bound) return;
  seg.dataset.bound = '1';
  seg.onclick = (e) => {
    if (e.target.closest('#claude-refresh')) return;
    navigate('/settings/claude');
  };
  const btn = $('#claude-refresh');
  if (btn) btn.onclick = async (e) => {
    e.stopPropagation();
    btn.classList.add('spinning');
    await loadUsage(true);           // force：繞過 5 分鐘節流，立刻重打一次
    btn.classList.remove('spinning');
  };
}

// ── ① 有官方百分比且還新鮮：百分比才是人要看的東西 ─────────────
// ⭐ 這裡的進度條**有真的分母**（官方回報的 utilization），所以畫得出來；
//    下面 tokenRow() 那條路徑沒有分母，就一條也不畫。
function quotaRow(q, w) {
  const bar = (b) => {
    if (b.expired) return html`<div class="stat" title="這個窗口已經重置，快照裡的百分比講的是上一個窗口"><span class="k">${b.label}</span><span class="v sm muted">已重置</span><span class="d">等下次更新</span></div>`;
    const tone = b.percent >= 90 ? 'danger' : b.percent >= 70 ? 'warn' : '';
    return html`<div class="stat" title="${b.label} ${b.percent}%　${resetText(b, true)}">
      <span class="k">${b.label}</span><span class="v sm ${tone}">${b.percent}%</span>
      <span class="qbar ${tone}"><i style="width:${Math.min(100, b.percent)}%"></i></span>
      <span class="d">${resetText(b)}</span></div>`;
  };
  return html`<div class="stat-row">${q.bars.map(bar)}
    <div class="stat" title="本機 transcript 統計的實際消耗（與左邊的官方百分比是兩回事）">
      <span class="k">今日</span><span class="v sm">${fmt.compact(w.today.total)}</span>
      <span class="d">${fmt.int(w.today.messages)} 則</span></div>
  </div>
  ${q.live ? '' : html`<div class="tiny muted qfoot" title="${q.source}">快照 · ${String(q.fetched_at || '').slice(5)}（Claude Code 存的，打 /usage 才會更新）</div>`}`;
}

// ── ② 沒有百分比、或快照過舊：退回本機統計的 token 數字 ────────
// ⛔ 這條路徑**不畫進度條** —— 沒有分母的進度條是假的。
function tokenRow(u, w, tip) {
  const weekly = !!u.plan?.has_weekly;
  const prev = w.prev_week.total, cur = w.week.total;
  const delta = prev ? Math.round((cur - prev) / prev * 100) : null;
  const third = weekly
    ? { k: '近 7 天', v: w.week, d: delta == null ? '較前 7 天 —' : `較前 7 天 ${delta >= 0 ? '+' : ''}${delta}%` }
    : { k: '近 30 天', v: w.month, d: '無週限額' };          // ⚠️ 這一欄約 90px，寫長了會被截字
  const q = u.quota || {};
  // ⭐ 過期時要給**做得到的下一步**，不是只說壞掉了。
  //    2026-08-25 實測：在 Claude Code 裡打 `/usage` 會當場更新這個快照
  //    （fetchedAtMs 08-23 02:06 → 08-25 09:09、五小時 74%→18%、週 56%→88%，與 /usage 印的一致）。
  //    ⚠️ 反面也測過：`claude -p "/usage"` **不會**更新（slash 指令在 print 模式不執行），
  //       所以平台起 session 去刷是白費額度 —— 別再試。
  const why = q.live_error
    ? `即時查詢失敗：${q.live_error}` : '額度 % 只剩 Claude Code 的本機快照，而它不會自己更新';
  const note = (q.available || q.live_error)
    ? html`<div class="tiny muted qfoot" title="${why}｜即時查詢 5 分鐘節流，右上角 ↻ 可立刻重打；打不通時退回本機快照，那份要在 Claude Code 裡打一次 /usage 才會更新">
        ${q.live_error ? '即時額度取不到' : `額度 % 已過期（${String(q.fetched_at || '').slice(5)}）`} · 打 <code>/usage</code> 或按 ↻</div>`
    : '';
  return html`<div class="stat-row">
    <div class="stat" title="${tip(w.h5)}"><span class="k">近 5 小時</span><span class="v sm">${fmt.compact(w.h5.total)}</span><span class="d">${fmt.int(w.h5.messages)} 則</span></div>
    <div class="stat" title="${tip(w.today)}"><span class="k">今日</span><span class="v sm">${fmt.compact(w.today.total)}</span><span class="d">${fmt.int(w.today.messages)} 則</span></div>
    <div class="stat" title="${tip(third.v)}"><span class="k">${third.k}</span><span class="v sm">${fmt.compact(third.v.total)}</span><span class="d">${third.d}</span></div>
  </div>
  ${note || html`<div class="usage-spark" title="近 14 天每日總 token">${sparkBars(u.spark)}</div>`}`;
}

/** 重置時間：`full` 為 true 時給完整日期，否則給「還有多久」。 */
function resetText(b, full) {
  if (!b.resets_at) return '';
  const t = new Date(b.resets_at);
  if (full) return `${t.toLocaleString()} 重置`;
  const left = (b.resets_in_sec == null ? (t - Date.now()) / 1000 : b.resets_in_sec);
  if (left <= 0) return '已重置';
  if (left < 3600) return `${Math.round(left / 60)} 分後重置`;
  // ⚠️ 這一欄只有約 90px —— 十小時以上就不要小數，否則「23.0 小時後重置」會被截字
  if (left < 86400) return `${left < 36000 ? (left / 3600).toFixed(1) : Math.round(left / 3600)} 小時後重置`;
  return `${t.getMonth() + 1}/${t.getDate()} 重置`;
}

function sparkBars(spark) {
  const arr = spark || [];
  const mx = Math.max(1, ...arr.map((d) => d.total));
  // ⚠️ 後端的日期是**本機時區**切的（見 core/claude_usage.py），這裡不可以用 toISOString()
  //    —— 那是 UTC，台灣早上八點以前會標到前一天，今天那根就永遠不會亮。
  const n = new Date();
  const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`;
  return raw(arr.map((d) => `<i class="b${d.day === today ? ' now' : ''}" style="height:${Math.max(2, Math.round(d.total / mx * 100))}%" title="${d.day} · ${Number(d.total).toLocaleString('en-US')} token"></i>`).join(''));
}

// 註：知識雷達已融進主視覺（星系外圍的五條軌道），側欄不再另設卡片。


// ---------------------------------------------------------------- HERO
function sysState() {
  const runs = state.active || [];
  if (runs.some((r) => (r.survivors || []).length)) return 'fault';
  if (runs.some((r) => !['completed', 'failed', 'stopped'].includes(r.phase))) return 'running';
  if (runs.some((r) => r.phase === 'failed')) return 'warning';
  return 'idle';
}
let heroSig = null;
function drawHero(force = false) {
  const el = $('#hero'); if (!el || !knowledge) return;
  // 重畫一次 hero 要建 ~4,900 個 SVG 節點（約 37ms），而 drawHero 會被 store 訂閱與
  // 60s 輪詢反覆呼叫 —— 內容沒變就別重畫。時鐘不列入簽章（球上已不顯示時間）。
  // ⚠️ **進度百分比不列入簽章** —— 它每幾秒就變一次，列進來等於每幾秒重建 5,347 個節點
  //    （約 60ms 的 long frame），跑測試時整個畫面會週期性地頓。
  //    進度改由 updateHeroRuns() 原地改屬性，見下方 subscribe。
  const sig = JSON.stringify([
    Object.entries(knowledge.products).map(([k2, p]) => [k2, p.rings.cases.value, p.rings.spec.value, p.rings.reports.value, p.rings.bugs.value]),
    (state.active || []).map((r) => [r.run_id, r.phase, r.tool_phase_label]),
    sysState(),
    Object.keys(todos?.products || {}).map((k2) => (todos.products[k2].blockers || []).length),
  ]);
  if (!force && sig === heroSig && el.querySelector('svg')) {
    updateHeroRuns(state.active || [], state.sessionRunning || []);
    return;
  }
  heroSig = sig;
  // hero 已無扇形雷達（改地球），故不再需要 heat／onRing —— 知識五圈在產品頁的線框雷達上
  renderHero(el, knowledge, {
    // force（改視窗大小）時給 null，強制真的重建；平時同一個 sig 就直接把上次的節點搬回來
    sig: force ? null : sig,
    active: state.active || [], todos, state: sysState(),
    clock: new Date().toTimeString().slice(0, 5),
    onSector: (pid) => navigate(`/product/${pid}`),
  });
  // ⚠️ 場景**剛重建**時還不知道有沒有 session 在跑 —— 補一次，
  //    否則重畫（改視窗大小、知識數字變動）會把動畫弄不見。
  updateHeroRuns(state.active || [], state.sessionRunning || []);
}

/** 24 小時執行熱度：一格一小時，有失敗轉紅。
 *
 * ⭐ 住在「運行中」卡的底部（2026-08-25 使用者裁示搬過來的）——
 *    同一張卡回答「現在在跑什麼」與「過去一天跑了多少」。
 */
function drawHeat() {
  const el = $('#heat'); if (!el) return;
  const mx = Math.max(1, ...heat.map((h) => h.runs));
  // ⭐ 最後一格是**現在這個小時** —— 標出來，方向才不必靠 hover 才知道
  el.innerHTML = heat.map((h, i) => `<div class="h ${h.runs ? (h.failed ? 'fail' : 'ok') : ''}${i === heat.length - 1 ? ' now' : ''}" style="opacity:${h.runs ? .45 + .55 * h.runs / mx : 1}" data-tip="${h.hour}:00${i === heat.length - 1 ? '（現在）' : ''} · ${h.runs} run${h.failed ? ' · 失敗 ' + h.failed : ''}"></div>`).join('');
}

// ---------------------------------------------------------------- 運行中卡
/** 任務 session 的一列：它沒有百分比，進度用**最近幾個工具動作**表示。
 *
 * ⭐ 為什麼不做百分比：session 沒有可預估的總量，硬掰一個數字只會騙人。
 *    而「它現在在讀檔／開瀏覽器／載 skill」正是人真正想知道的事。
 */
function sessionRow(x) {
  const tools = (x.tools || []).slice(-4).map(prettyTool);
  return html`<div class="card plain run-card is-running" style="margin-bottom:6px;padding:7px 9px">
    <div class="scanline"></div>
    <div class="sess-orb" title="任務 session 執行中">◐</div>
    <div style="min-width:0">
      <div class="title"><span class="dot running"></span>
        <a href="#/sessions" data-open-sess="${x.id}">${x.task_label || x.title || '對話'}</a>
        ${x.product ? html`<span class="pill ${x.product}">${x.product}</span>` : ''}
        <span class="pill tone-info">session</span></div>
      <div class="sub mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${x.prompt || ''}</div>
      <div class="mini-metrics">${tools.length
        ? tools.map((t) => html`<span>${t}</span>`)
        : raw('<span class="muted">正在啟動…</span>')}</div>
    </div>
    <div class="stack"><span class="tiny muted">${x.started_at ? fmt.ago(x.started_at) : ''}</span></div></div>`;
}

/** 工具名 → 人話。與 `ui/chatpanel.js` 的 `prettyTool` 同一套規則。 */
function prettyTool(t) {
  const zh = { Read: '讀檔', Grep: '搜尋', Glob: '找檔', Skill: '載入 skill',
               WebFetch: '取網頁', WebSearch: '搜網路', ToolSearch: '找工具' };
  if (zh[t]) return zh[t];
  const m = /^mcp__([a-z0-9-]+)__(.+)$/.exec(t || '');
  if (!m) return t;
  const srv = m[1].startsWith('playwright') ? '瀏覽器' : m[1] === 'test-platform' ? '平台' : m[1];
  return srv + '·' + m[2].replace(/^browser_/, '').replace(/_/g, ' ');
}

function drawActive() {
  const el = $('#active'), cnt = $('#active-cnt'); if (!el) return;
  const runs = state.active || [];
  const sess = state.sessionRunning || [];
  const review = state.sessionReview || [];
  const live = runs.filter((r) => !['completed', 'failed', 'stopped'].includes(r.phase));
  const done = runs.length - live.length;
  // 標題已經寫「運行中 N」，右上角就只補剛結束的數量，不要把同一個數字說兩遍
  const parts = [];
  if (done) parts.push(`${done} 剛結束`);
  if (review.length) parts.push(`${review.length} 待確認`);
  if (cnt) cnt.textContent = parts.join(' · ');
  // ★ 有東西在跑時，「運行中」升到側欄最上面並吃掉更多高度（CSS 的 .has-run）。
  //   先前它固定排第二、內容區又鎖 168px，兩個 run 就會被切掉半張 ——
  //   使用者要的是「回到總覽就知道什麼在跑」，被切掉的卡片答不了這件事。
  // 任務按鈕：儀表板回答「現在如何」，這排回答「我要做什麼」
  const tb = $('#task-bar');
  if (tb) renderTaskBar(tb, { entry: 'overview', product: curProd });
  const side = $('.dash-side'), card = $('#c-active');
  const busy = live.length + sess.length;
  if (side) side.classList.toggle('has-run', busy > 0 || review.length > 0);
  if (card) card.classList.toggle('is-running', busy > 0);
  const head = $('#c-active > h3');
  if (head) head.firstChild.nodeValue = busy ? `運行中 ${busy} ` : '運行中 ';
  if (!runs.length && !sess.length && !review.length) {
    api.get('/api/runs?limit=4').then((d) => {
      const rows = d.runs || [];
      el.innerHTML = rows.length
        ? `<div class="tiny muted" style="margin-bottom:4px;letter-spacing:.12em">最近執行</div>` + rows.map((r) => `<div class="todo-row" style="grid-template-columns:auto 1fr auto" onclick="location.hash='#/run/${r.run_id}'"><span>${dotHtml(r.phase)}</span><span class="sum">${esc(r.tool_name || '')} <span class="muted tiny">${esc(r.headline || '')}</span></span><span class="pri">${fmt.ago(r.started_at)}</span></div>`).join('')
        : `<div class="empty">尚無執行。到 <a href="#/tools">工具</a> 啟動，或按 <span class="kbd">Ctrl K</span>。</div>`;
    }).catch(() => { el.innerHTML = '<div class="empty">尚無執行</div>'; });
    return;
  }
  el.innerHTML = sess.map(sessionRow).join('') + reviewBlock(review) + runs.map((r) => {
    const term = ['completed', 'failed', 'stopped'].includes(r.phase);
    const pct = r.progress?.percent ?? (term ? 100 : 3);
    const m = r.metrics || {}, s = r.summary || {};
    const mini = (s.kind === 'pytest' || m.passed != null)
      ? html`<span>通過 <b style="color:var(--success)">${m.passed ?? s.passed ?? 0}</b></span><span>失敗 <b style="color:var(--danger)">${m.failed ?? s.failed ?? 0}</b></span><span>略過 <b>${m.skipped ?? s.skipped ?? 0}</b></span>`
      : html`${m.total_bets != null ? html`<span>注 <b>${fmt.int(m.total_bets)}</b></span>` : ''}${m.rps != null ? html`<span>RPS <b>${fmt.float1(m.rps)}</b></span>` : ''}${m.fail_ratio != null ? html`<span>失敗 <b>${fmt.percent(m.fail_ratio)}</b></span>` : ''}${m.periods_seen != null ? html`<span>期 <b>${m.periods_seen}</b></span>` : ''}`;
    return html`<div class="card plain run-card ${term ? 'recent' : 'is-running'} ${(r.survivors || []).length ? 'is-fault' : ''}" style="margin-bottom:6px;padding:7px 9px">
      ${!term ? raw('<div class="scanline"></div>') : ''}
      ${raw(ring(pct, { size: 44, stroke: 4, label: term ? (r.phase === 'completed' ? '✓' : r.phase === 'failed' ? '✕' : '■') : null }))}
      <div style="min-width:0">
        <div class="title">${dot(r.phase)}<a href="#/run/${r.run_id}">${r.tool_name}</a><span class="pill ${r.product}">${r.product}</span><span class="pill tone-${toneOfPhase(r.phase)}">${r.tool_phase_label || phaseLabel(r.phase)}</span></div>
        <div class="sub mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.progress?.label || r.run_id}</div>
        <div class="mini-metrics">${raw(mini)}</div>
        ${(r.survivors || []).length ? html`<div class="alert is-error tiny" style="margin-top:5px">⚠ 殘留程序 ${r.survivors.join(', ')} —— <code>taskkill /F /T /PID ${r.survivors[0]}</code></div>` : ''}
      </div>
      <div class="stack">${!term ? html`<button class="btn xs warn" data-stop="${r.run_id}">停止</button>` : html`<a class="btn xs" href="#/run/${r.run_id}">查看</a>`}</div></div>`;
  }).join('');
  el.onclick = async (e) => {
    // ⭐ 結果確認：看過了就按「知道了」，這一列消失。
    //    ⚠️ 只清掉**提醒**，不動產出本身 —— 產出在 Bug 單／案例／文件裡，
    //       各有自己的生命週期。
    const ok2 = e.target.closest('[data-reviewed]');
    if (ok2) {
      try { await api.post(`/api/sessions/${ok2.dataset.reviewed}/reviewed`); } catch (err) { /* ignore */ }
      (await import('../poll.js')).kick();
      return;
    }
    const os2 = e.target.closest('[data-open-sess]');
    if (os2) {
      e.preventDefault();
      const { setSession } = await import('../store.js');
      setSession(os2.dataset.openSess);
      (await import('../ui/dock.js')).open();
      return;
    }
    const b = e.target.closest('[data-stop]'); if (!b) return;
    const { modal } = await import('../ui/modal.js');
    if (await modal.confirm('停止 run', `確定停止 <code>${b.dataset.stop}</code>？會先嘗試優雅收尾。`, { danger: true, okLabel: '停止' })) {
      try { await api.post('/api/runs/stop', { run_id: b.dataset.stop }); toast('已送出停止'); (await import('../poll.js')).kick(); } catch (err) { toast(err.message, 'danger'); }
    }
  };
}
/** 「做完了，這是它交出來的東西」—— 結果確認那一段。
 *
 * ⭐ 這是本次設計的核心：先前 session 做完就沒有下文，產出散在 Bug 單／案例／
 *    文件裡，而**沒有任何地方告訴人「有東西可以看了、在哪」**。
 *    對話串流裡其實有講，但那段字關掉視窗就看不到了 —— 這一塊留得住。
 */
function reviewBlock(review) {
  if (!review.length) return '';
  return review.map((x) => html`<div class="card plain run-card recent" style="margin-bottom:6px;padding:7px 9px">
    <div class="sess-orb done" title="已完成，等你確認">✓</div>
    <div style="min-width:0">
      <div class="title"><span class="dot completed"></span>
        <a href="#/sessions" data-open-sess="${x.id}">${x.task_label || x.title || '對話'}</a>
        ${x.product ? html`<span class="pill ${x.product}">${x.product}</span>` : ''}
        <span class="pill tone-success">做完了</span></div>
      <div class="review-items">${(x.review?.items || []).map((it) =>
        html`<a class="review-item ${it.kind}" href="${it.href || '#/sessions'}">${it.text}</a>`)}</div>
    </div>
    <div class="stack"><button class="btn xs" data-reviewed="${x.id}" title="看過了 —— 只清掉這個提醒，不動產出">知道了</button></div></div>`).join('');
}

function dotHtml(p) { return `<span class="dot ${p}"></span>`; }

// ---------------------------------------------------------------- 待辦與 Bug（精簡版；完整在產品頁）
const CROSS = [['revisit', '待重驗'], ['unfiled', '漏開單'], ['to_close', '該關單'], ['no_regr', '缺回歸']];
function drawTodo() {
  const tabs = $('#tb-tabs'), body = $('#tb-body'); if (!tabs) return;
  const prods = state.products || [];
  // `cache`／`live` 是英文實作術語，人要知道的是「這個數字是不是新的」
  $('#tb-jira').textContent = bugs
    ? 'JIRA ' + ({ cache: '快取', live: '即時', off: '未設定' }[bugs.jira_source] || bugs.jira_source)
    : '';
  tabs.innerHTML = prods.map((p) => {
    const n = (todos?.products?.[p.id]?.open || 0) + (bugs?.products?.[p.id]?.active || 0);
    return html`<button class="tab-btn ${p.id === curProd ? 'active' : ''}" data-tab="${p.id}"><span class="pc-${p.id}">${p.short || p.label}</span>${n ? html`<span class="cnt">${n}</span>` : ''}</button>`;
  }).join('');
  tabs.onclick = (e) => { const b = e.target.closest('[data-tab]'); if (!b) return; curProd = b.dataset.tab; $$('#tb-tabs .tab-btn').forEach((x) => x.classList.toggle('active', x.dataset.tab === curProd)); drawTodoBody(); };
  drawTodoBody();
}
function drawTodoBody() {
  const body = $('#tb-body'); if (!body) return;
  if (!curProd) curProd = (state.products || []).filter((p) => !p.virtual)[0]?.id || null;
  const t = todos?.products?.[curProd] || {}, b = bugs?.products?.[curProd] || {};
  const cc = b.cross_counts || {};
  // doc／line 現在由後端 todo_index 直接給（不必再從 d.path 補）；保留 d.path 當舊資料的退路
  const items = (t.docs || []).flatMap((d) => (d.items || []).filter((i) => !i.done).map((i) => ({ doc: d.path, ...i })));
  // 活躍 Bug：未歸檔且非已修／已撤銷。先前這張卡只有四個 cross 數字，看不到「是哪幾條」
  const activeBugs = (b.bugs || []).filter((x) => !x.archived && ['open', 'superseded', 'reopen', '已接續'].includes(x.status));
  // ★ 順序＝重要性，因為這張卡的高度有限、下面的東西要捲才看得到：
  //   ① blocker（一行，擋住整條線的事）
  //   ② **那排動作卡** —— 它是這張卡的導覽入口，先前排在「刻意保留的測試資料」
  //      那個長方塊後面，於是整排被推到摺線下、要捲才看得到（2026-08-24 走查）
  //   ③ 保留中的測試資料（長、但屬於背景說明）→ 自己內捲，不再無限長高
  body.innerHTML = html`
    ${(t.blockers || []).slice(0, 1).map((bl) => html`<div class="blocker"><b>⛔ ${bl.n}</b> ${raw(md(bl.what))}</div>`)}
    ${b.present === false ? html`<div class="alert is-info tiny">尚未建立 bugs/（不版控，clone 後為空屬正常）</div>` : html`<div class="action-cards">${CROSS.map(([k, l]) => html`<div class="action-card ${k} ${cc[k] ? '' : 'zero'}" data-cross="${k}"><div class="n">${cc[k] || 0}</div><div class="l">${l}</div></div>`)}</div>`}
    ${keptBlock(t.data_status, { max: 2 })}
    <div class="row between tiny muted" style="margin:7px 0 3px"><span>待辦 ${t.open || 0} 未完成</span></div>
    ${items.slice(0, 5).map((i) => html`<div class="todo-row" data-todo="${i.id}" data-doc="${i.doc}"><span class="id">${i.starred ? '⭐' : ''}${i.id}</span><span class="sum" title="${i.summary}">${i.summary}</span><span class="pri">${raw(md((i.priority || '').slice(0, 8)))}</span></div>`)}
    ${!items.length ? html`<div class="empty tiny">沒有未完成的待辦</div>` : ''}
    <div class="row between tiny muted" style="margin:9px 0 3px"><span>活躍 Bug ${b.active || 0}</span>${b.archived ? html`<span>歸檔 ${b.archived}</span>` : ''}</div>
    ${activeBugs.slice(0, 5).map((x) => html`<div class="todo-row" data-bug="${x.id}"><span class="id">${x.id.split('-')[1] || x.id}</span><span class="sum" title="${x.title}">${x.title}</span><span class="pri">${x.severity || ''}</span></div>`)}
    ${!activeBugs.length && b.present !== false ? html`<div class="empty tiny">沒有活躍 Bug</div>` : ''}
    <div class="row" style="margin-top:7px"><a class="btn xs" href="#/product/${curProd}?tab=todos">全部待辦 →</a><a class="btn xs" href="#/product/${curProd}?tab=bugs">Bug 清單 →</a></div>`;
  body.onclick = (e) => {
    const c = e.target.closest('[data-cross]'); if (c) { navigate(`/product/${curProd}?tab=bugs&cross=${c.dataset.cross}`); return; }
    const bg = e.target.closest('[data-bug]');
    if (bg) { navigate(`/product/${curProd}?tab=bugs&focus=${encodeURIComponent(bg.dataset.bug)}`); return; }
    const r = e.target.closest('[data-todo]'); if (!r) return;
    const it = items.find((x) => x.id === r.dataset.todo && x.doc === r.dataset.doc);
    if (it) openTodo(it, curProd);
  };
}
