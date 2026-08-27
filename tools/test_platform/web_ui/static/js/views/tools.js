// #/tools 工具清單：四欄產品看板（欄首＝產品色光棒＋小圖騰）—— Dashboard 的「⚙ 工具」入口
import { api } from '../api.js';
import { $, html, raw, fmt, esc } from '../ui/el.js';
import { state, worstDanger } from '../store.js';
import { dot } from '../ui/hud.js';
import { glyphSvg } from '../ui/hero.js';
import { pageLoading } from '../ui/loading.js';

// 危險等級的判斷抽到 `store.js` 的 `worstDanger()` —— 三個畫面共用一份。


export async function mount(root) {
  const prods = state.products, tools = state.tools;
  const byProd = (pid) => tools.filter((t) => t.scope !== 'workspace' && (t.products || [t.product]).includes(pid)).sort((a, b) => (a.order ?? 99) - (b.order ?? 99));
  // ⭐ `scope: workspace` 的工具（接產品／裝 memory／體檢／匯出範本）**不在這一頁** ——
  //    2026-08-24 使用者裁示「設定相關的操作應放在設定頁面，而非工具頁面出現工作區設定功能」。
  //    它們現在是設定的「工作區」分頁：#/settings/workspace。
  //    （2026-08-23 曾在這裡另立一欄「工作區」，本次移除。）
  const wsTools = tools.filter((t) => t.scope === 'workspace');
  // 虛擬產品（`common`）沒有工具時整欄不畫 —— 先前恆顯示一欄「共通 0 · 此產品尚無工具」，
  // 那是一格永遠不會變的空白（2026-08-24 走查）。
  // ⭐ 先畫殼再抓資料（2026-08-24）—— 這一頁原本是拿到 /api/runs 才第一次 innerHTML，
  //    而 router 早就把上一頁收掉了：中間那段畫面上**什麼都沒有**。
  root.innerHTML = html`<div class="page">
    <div class="page-head"><h2>工具</h2><span class="crumb">${tools.length - wsTools.length} 個產品工具${wsTools.length ? ` · ${wsTools.length} 個工作區工具` : ''}</span></div>
    <div class="page-body" id="tl-body">${pageLoading('讀取最近執行紀錄…')}</div>
  </div>`;

  let recent = [];
  try { recent = (await api.get('/api/runs?limit=60')).runs || []; } catch (e) { /* ignore */ }
  const lastOf = (tid, pid) => recent.find((r) => r.tool_id === tid && (!pid || r.product === pid)) || null;

  // ⚠️ 抓資料期間可能已經被切走（pane 被拆掉）—— 找不到就別寫了
  const body = $('#tl-body', root);
  if (!body) return;
  body.innerHTML = html`<div class="board">${prods.filter((p) => !p.virtual || byProd(p.id).length).map((p) => {
        const isWs = false;
        const ts = byProd(p.id);
        return html`<div class="col">
          <div class="col-head" style="color:${p.color}">
            <span class="bar" style="background:${p.color}"></span>
            <span class="col-glyph">${isWs ? '⚙' : raw(glyphSvg(p.id, 22))}</span>
            <span class="nm">${p.label}</span><span class="sub">${ts.length}</span>
          </div>
          <div class="stack">${ts.length ? ts.map((t) => {
            const last = lastOf(t.id, isWs ? null : p.id);
            const live = (state.active || []).find((r) => r.tool_id === t.id && !['completed', 'failed', 'stopped'].includes(r.phase));
            return html`<div class="card tool-card ${live ? 'is-running' : ''}" data-tool="${t.id}" data-prod="${isWs ? '' : p.id}">
              ${live ? raw('<div class="scanline"></div>') : ''}
              <div class="name">${dot(live ? 'running' : last ? last.phase : 'idle')}${t.name}</div>
              <div class="subtitle">${t.subtitle || ''}</div>
              <div class="row" style="gap:4px">${(t.tags || []).slice(0, 3).map((g) => html`<span class="pill">${g}</span>`)}</div>
              <div class="foot"><span class="danger-lvl ${worstDanger(t)}">${{ high: '高風險', medium: '會寫入', low: '本機唯讀' }[worstDanger(t)]}</span>
                <span>${live ? html`<span style="color:var(--accent)">執行中</span>` : last ? fmt.ago(last.started_at) : '尚未執行'}</span></div>
            </div>`;
          }) : raw('<div class="empty tiny">此產品尚無工具</div>')}</div>
        </div>`;
      })}</div>`;
  root.onclick = (e) => { const c = e.target.closest('[data-tool]'); if (c) location.hash = `#/tool/${c.dataset.tool}` + (c.dataset.prod ? `?product=${c.dataset.prod}` : ''); };
}
export function unmount() {}
