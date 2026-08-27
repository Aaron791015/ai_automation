// 設定 → Claude 分頁：上線檢查（真的：auth status／doctor 唯讀零額度）—— 同事照著做就能上線
import { api } from '../api.js';
import { $, html, raw, esc, fmt, copy, revealable, bindReveal, redactPII } from '../ui/el.js';
import { toast } from '../ui/toast.js';
import { pageLoading } from '../ui/loading.js';

export async function mount(root) {
  // ⚠️ 這一支**只畫內容**，頁殼（標題與分頁列）由 `views/settings.js` 的分頁中樞提供
  //    —— 設定分成四個分頁之後，四份內容各自再畫一次 `.page-head` 會疊出兩層標題。
  root.innerHTML = `<div id="st-body">${pageLoading("檢查 Claude 連線中（claude --version / auth status / doctor，唯讀、零額度）…")}</div>`;
  await load();
  async function load(refresh = false) {
    let d;
    // ⚠️ router 換頁時會清空同一個 root，await 期間被切走的話這些選取器就會是 null
    const body = () => $('#st-body', root);
    try { d = await api.get('/api/settings/claude' + (refresh ? '?refresh=1' : '')); }
    catch (e) { const b = body(); if (b) b.innerHTML = `<div class="alert is-error">${esc(e.message)}</div>`; return; }
    if (!body()) return;
    const a = d.auth || {};
    body().innerHTML = html`
      <div class="grid two">
        <section class="card hud ${d.ok ? '' : 'is-fault'}"><h3>${d.ok ? '✅' : '❌'} 狀態 <span class="cnt">${d.checked_at}</span></h3>
          <table class="tbl small">
            <tr><th>執行檔</th><td class="mono tiny">${raw(revealable(d.executable || '找不到'))}<div class="tiny muted">來源：${{ config: 'platform_config.local.json', PATH: 'PATH', local_bin: '~/.local/bin', vscode: 'VSCode 擴充目錄（自動取版本號最大者）', none: '—' }[d.source] || d.source}</div></td></tr>
            <tr><th>版本</th><td class="mono">${d.version || '—'}</td></tr>
            <tr><th>登入</th><td>${d.logged_in ? html`✅ <b>${raw(revealable(a.email || ''))}</b> · ${a.authMethod || ''} / ${a.apiProvider || ''} · ${a.subscriptionType || ''}<div class="tiny muted">${a.orgName || ''}</div>` : raw('❌ 未登入')}</td></tr>
          </table>
          ${(d.hints || []).length ? html`<div class="alert ${d.ok ? 'is-info' : 'is-warn'} small" style="margin-top:8px">${d.hints.map((h) => html`<div>${h}</div>`)}</div>` : ''}
          <div class="row" style="margin-top:8px"><button class="btn sm" id="st-re">↻ 重新檢查</button></div></section>
        <section class="card"><h3>怎麼上線</h3><div class="md small">
          <p><b>前提</b>：登入憑證存 <code>~/.claude/.credentials.json</code>（使用者層級），<b>與 VSCode 無關</b> —— 不需要「在 VSCode 登入」，需要的是「這台機器的這個使用者已登入」。</p>
          <p><b>A. 用 VSCode 擴充</b>：安裝「Claude Code」擴充（附帶 claude.exe，本平台會自動找到）→ 在 VSCode 內登入<b>或</b>終端機 <code>claude auth login</code>（共用同一份憑證）。</p>
          <p><b>B. 完全不用 VSCode</b>：終端機 <code>claude install</code>（native build，裝到 ~\\.local\\bin）→ <code>claude auth login</code>。</p>
          <p><b>企業／API key</b>：可設環境變數 <code>ANTHROPIC_API_KEY</code>，或 <code>claude setup-token</code> 產長效 token。（這幾條未在本機逐一實測，以下方 auth status 回報為準）</p>
          <p><b>架構前提</b>：每個人跑自己的平台實例（<code>run_server.bat</code>），用自己的帳號。平台綁 127.0.0.1 —— 別人連進來會用你的額度與 OS 身分執行 run。</p>
          <p><b>模型</b>：新建對話時選；預設 <b>${d.default_model}</b>（fallback ${d.fallback_model || '無'}），可在 <code>config/platform_config.local.json</code> 改。⚠ 模型在 session 建立時決定，中途不能切。</p>
        </div></section>
      </div>
      <section class="card" style="margin-top:12px" id="st-usage"><h3>用量 <span class="cnt">統計中…</span></h3></section>
      <section class="card" style="margin-top:12px"><h3>claude doctor <span class="cnt">${(d.doctor?.warnings || []).length} 個警告 · 修復指令原樣顯示</span></h3>
        ${(d.doctor?.warnings || []).length ? html`<div class="checklist">${d.doctor.warnings.map((w) => html`<div class="it"><span>⚠️</span><div>${raw(revealable(w.warning))}${w.fix ? html`<div class="d">修復：<code>${raw(revealable(w.fix))}</code> <button class="btn xs ghost" data-copy="${w.fix}">複製</button></div>` : ''}</div></div>`)}</div>` : raw('<div class="muted small">無警告</div>')}
        <details style="margin-top:8px"><summary class="small muted" style="cursor:pointer">原始輸出</summary><pre class="tiny">${redactPII(d.doctor?.raw || '')}</pre></details></section>`;
    // 個資（登入 email、C:\Users\<帳號>\… 路徑）預設遮罩：這頁常被投影／截圖給同事看。
    // 值本身沒動，複製鈕仍複製完整內容；要看就點一下。
    bindReveal(body());
    loadUsage();
    $('#st-re', root).onclick = () => { $('#st-body', root).innerHTML = String(pageLoading('重新檢查中…')); load(true); };
    root.onclick = (e) => { const b = e.target.closest('[data-copy]'); if (b) { copy(b.dataset.copy); toast('已複製', 'success'); } };
  }

  // ── 用量明細（本機 transcript 統計）─────────────────────────────
  // ⛔ 這裡是**實際消耗**，不是額度餘額 —— 額度百分比只在互動式 /usage 裡，CLI 取不到。
  //    所以不畫百分比、不畫進度條，只給數字與趨勢。
  async function loadUsage(refresh = false, quotaForce = false) {
    const card = $('#st-usage', root); if (!card) return;
    let u;
    const qs = refresh ? '?refresh=1' : (quotaForce ? '?quota=force' : '');
    try { u = await api.get('/api/claude/usage' + qs); }
    catch (e) { card.innerHTML = html`<h3>用量</h3><div class="alert is-error">${e.message}</div>`; return; }
    if (!$('#st-usage', root)) return;
    if (!u.ready || !u.available) {
      card.innerHTML = html`<h3>用量 <span class="cnt">${u.ready ? '沒有紀錄' : '首次統計中'}</span></h3>
        <div class="muted small">${u.ready ? html`找不到 Claude Code 的紀錄目錄（${raw(revealable(u.root || ''))}）—— 用過 Claude Code 之後就會出現。` : (u.hint || '統計中…')}</div>`;
      if (!u.ready) setTimeout(() => loadUsage(), 4000);         // 首建約十秒，等它一下
      return;
    }
    const W = [['h5', '近 5 小時'], ['today', '今日'], ['week', '近 7 天'], ['prev_week', '前 7 天'], ['month', '近 30 天']];
    const weekly = !!u.plan?.has_weekly;
    const mx = Math.max(1, ...(u.spark || []).map((d) => d.total));
    const bar = (v, m) => `<span class="mini-bar"><i style="width:${Math.round(v / m * 100)}%"></i></span>`;
    const q = u.quota || {};
    card.innerHTML = html`<h3>用量 <span class="cnt">${q.tier_label || u.plan?.label || '—'} · ${u.files} 份紀錄 · ${u.scanned_at || ''}</span></h3>
      ${raw(quotaBlock(q))}
      <div class="alert is-info small" style="margin-bottom:10px">
        <b>${u.plan?.label}</b> —— ${u.plan?.note}。
        下面這張表是<b>本機 transcript 記到的實際消耗</b>（有模型與工作區的分佈，但沒有分母）；
        上面的百分比才是<b>額度水位</b>（有分母）。兩者互補，<b>不要互相換算</b> ——
        額度的計費權重不是 token 的簡單相加。</div>
      <div class="alert is-warn small" style="margin-bottom:10px">
        ⛔ <b>額度 % 走的是未公開端點</b>（<code>/api/oauth/usage</code>，從 Claude Code 執行檔撈到的）。
        平台會讀 <code>~/.claude/.credentials.json</code> 的 OAuth token 去查<b>你自己的</b>用量 ——
        token <b>只在記憶體流動：不回傳瀏覽器、不落檔、不進 log</b>。
        端點改版就可能失效，屆時會自動退回本機快照。
        不想要這條的話：<code>platform_config.local.json</code> 設 <code>claude.live_quota: false</code>。</div>
      <div class="scroll-x"><table class="tbl small">
        <thead><tr><th>窗口</th><th class="num">總 token</th><th class="num">輸入</th><th class="num">輸出</th><th class="num">快取寫</th><th class="num">快取讀</th><th class="num">訊息</th></tr></thead>
        <tbody>${W.map(([k, label]) => { const x = u.windows[k]; return html`<tr${!weekly && k === 'week' ? raw(' class="muted"') : ''}>
          <th>${label}</th><td class="num"><b>${fmt.int(x.total)}</b></td><td class="num">${fmt.int(x.input)}</td>
          <td class="num">${fmt.int(x.output)}</td><td class="num">${fmt.int(x.cache_write)}</td>
          <td class="num">${fmt.int(x.cache_read)}</td><td class="num">${fmt.int(x.messages)}</td></tr>`; })}</tbody>
      </table></div>
      <div class="tiny muted" style="margin-top:6px">總 token ＝ 輸入＋輸出＋快取寫＋快取讀。快取讀通常占九成以上（同一份上下文被反覆讀），
        想看「做了多少事」看<b>輸出</b>那一欄比較準。</div>
      <div class="grid two" style="margin-top:12px">
        <div><div class="tiny muted" style="letter-spacing:.12em;margin-bottom:5px">近 14 天每日總量</div>
          <div class="usage-spark tall">${raw((u.spark || []).map((d) => `<i class="b" style="height:${Math.max(2, Math.round(d.total / mx * 100))}%" title="${d.day} · ${Number(d.total).toLocaleString('en-US')}"></i>`).join(''))}</div>
          <div class="tiny muted" style="margin-top:4px">${(u.spark || [])[0]?.day} → ${(u.spark || [])[(u.spark || []).length - 1]?.day}</div></div>
        <div>
          <div class="tiny muted" style="letter-spacing:.12em;margin-bottom:5px">近 7 天 · 依模型</div>
          <table class="tbl small"><tbody>
            ${(u.by_model || []).map((m) => html`<tr><th>${m.name}</th><td class="num">${fmt.compact(m.total)}</td><td style="width:38%">${raw(bar(m.total, u.by_model[0].total))}</td></tr>`)}
          </tbody></table>
          <div class="tiny muted" style="letter-spacing:.12em;margin:10px 0 5px">近 7 天 · 依工作區<span class="tiny muted" style="letter-spacing:0"> —— ★ 是這一份</span></div>
          <table class="tbl small"><tbody>
            ${(u.by_project || []).slice(0, 5).map((x) => html`<tr><th${x.here ? raw(' class="accent"') : ''}>${x.here ? '★ ' : ''}${x.name}</th><td class="num">${fmt.compact(x.total)}</td><td style="width:38%">${raw(bar(x.total, u.by_project[0].total))}</td></tr>`)}
          </tbody></table>
          <div class="tiny muted" style="margin-top:5px">額度是<b>帳號</b>層級的 —— 所以這裡列的是這台機器上<b>所有</b>工作區，不只這一份。</div>
        </div>
      </div>
      <div class="row" style="margin-top:8px"><button class="btn sm" id="st-usage-re">↻ 重新統計</button>
        <button class="btn sm" id="st-quota-re">⚡ 立刻重打額度</button>
        <span class="tiny muted">來源：${u.source}</span></div>`;
    bindReveal(card);
    const b = $('#st-usage-re', root);
    if (b) b.onclick = () => { toast('重新統計中（整份重建約十秒）…'); loadUsage(true); };
    const qb = $('#st-quota-re', root);
    if (qb) qb.onclick = async () => { toast('重打額度…'); await loadUsage(false, true); };
  }

  // ── 官方額度百分比 ────────────────────────────────────────
  // 兩個來源：① 平台自己打 `/api/oauth/usage`（5 分鐘節流）② 退回 Claude Code 的本機快照。
  // ⛔ 不論哪一種，「什麼時候抓的」都跟數字一樣重要 ——
  //    過期的百分比會被當成現在的水位，比沒有百分比更糟。
  function quotaBlock(q) {
    if (!q || !q.available) {
      return String(html`<div class="alert is-warn small" style="margin-bottom:10px">
        <b>本機還沒有額度百分比的快照。</b>
        它由 Claude Code 自己抓（<code>~/.claude.json</code> 的 <code>cachedUsageUtilization</code>），
        平台只讀不抓 —— <b>在 Claude Code 裡打一次 <code>/usage</code></b> 就會產生。</div>`);
    }
    const age = q.age_sec == null ? '' : (q.age_sec < 3600
      ? `${Math.round(q.age_sec / 60)} 分鐘前抓的`
      : `${(q.age_sec / 3600).toFixed(1)} 小時前抓的`);
    const rows = (q.bars || []).map((b) => {
      const tone = b.expired ? '' : b.percent >= 90 ? 'danger' : b.percent >= 70 ? 'warn' : '';
      const reset = b.resets_at ? new Date(b.resets_at).toLocaleString() : '—';
      return html`<tr><th>${b.label}</th>
        <td class="num"><b class="${tone}">${b.expired ? '已重置' : b.percent + '%'}</b></td>
        <td style="width:46%">${b.expired ? '' : raw(`<span class="qbar ${tone}"><i style="width:${Math.min(100, b.percent)}%"></i></span>`)}</td>
        <td class="tiny muted">${reset} 重置</td></tr>`;
    });
    const scoped = (q.scoped || []).map((x) => html`<tr><th class="muted">└ ${x.label}（逐模型）</th>
      <td class="num">${x.percent}%</td>
      <td>${raw(`<span class="qbar"><i style="width:${Math.min(100, x.percent)}%"></i></span>`)}</td>
      <td class="tiny muted">${x.resets_at ? new Date(x.resets_at).toLocaleString() + ' 重置' : ''}</td></tr>`);
    return String(html`<div class="alert ${q.usable ? 'is-info' : 'is-warn'} small" style="margin-bottom:8px">
        ${q.usable
          ? html`<b>額度水位</b>（${q.live ? html`<b>即時</b>，${age}` : html`Claude Code 的快照，${age}`}）`
          : html`<b>⚠️ 這份快照不能當現況看</b> —— ${age || '抓取時間不明'}，
                 ${q.stale ? '已超過 30 分鐘' : ''}${q.stale && (q.bars || []).some((b) => b.expired) ? '，且' : ''}
                 ${(q.bars || []).some((b) => b.expired) ? '有窗口已經重置' : ''}。
                 ${q.live_error ? html`<br>即時查詢失敗：<code>${q.live_error}</code>` : ''}
                 <br>⚡ <b>在 Claude Code 裡打一次 <code>/usage</code> 就會更新</b> ——
                 本機指令、不消耗額度（2026-08-25 實測有效）。`}
      </div>
      <table class="tbl small" style="margin-bottom:12px"><tbody>${rows}${scoped}</tbody></table>`);
  }
}
export function unmount() {}
