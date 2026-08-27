// Ctrl+K 指令列：全域模糊搜尋（案例／工具／產品／Bug／run／待辦）＋ `>` 命令模式
import { api } from '../api.js';
import { $, $$, debounce, esc, h, overlayOpened, overlayClosed } from './el.js';
import { navigate } from '../router.js';
import { state, set } from '../store.js';
import { toast } from './toast.js';

let wrap = null, activeIdx = 0, results = [];
const TYPE_LABEL = { case: '案例', tool: '工具', product: '產品', bug: 'Bug', run: 'run', todo: '待辦', doc: '文件', command: '命令', more: '…' };

export function openCmdbar(initial = '') {
  if (wrap) return;
  wrap = h('div', { class: 'cmdbar' });
  wrap.innerHTML = `<div class="box"><input type="text" placeholder="搜尋案例／工具／Bug 單號／run_id／T21… 或輸入 > 執行命令" value="${esc(initial)}"><div class="results"></div><div class="foot"><span><span class="kbd">↑↓</span> 選擇</span><span><span class="kbd">Enter</span> 開啟／加入選取</span><span><span class="kbd">Esc</span> 關閉</span></div></div>`;
  document.body.append(wrap);
  overlayOpened();
  const inp = $('input', wrap), res = $('.results', wrap);
  const run = debounce(async () => {
    const q = inp.value.trim();
    if (!q) { res.innerHTML = hint(); results = []; return; }
    try {
      const d = await api.get('/api/search?q=' + encodeURIComponent(q));
      results = d.results || [];
      activeIdx = 0;
      render();
    } catch (e) { res.innerHTML = `<div class="res muted">搜尋失敗：${esc(e.message)}</div>`; }
  }, 150);
  function render() {
    res.innerHTML = results.length ? results.map((r, i) => `<div class="res ${i === activeIdx ? 'active' : ''}" data-i="${i}"><span class="t">${TYPE_LABEL[r.type] || r.type}</span><span class="l">${esc(r.label)}</span>${r.sub ? `<span class="s">${esc(r.sub)}</span>` : ''}${r.product ? `<span class="pill ${r.product}">${r.product}</span>` : ''}</div>`).join('') : `<div class="res muted">沒有結果</div>`;
  }
  function hint() { return `<div class="res muted">試試：「變動賠率」找案例、「CRUX-874」看 Bug、「T21」看待辦、「>」進命令模式</div>`; }
  res.innerHTML = hint();
  inp.addEventListener('input', run);
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { activeIdx = Math.min(results.length - 1, activeIdx + 1); render(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { activeIdx = Math.max(0, activeIdx - 1); render(); e.preventDefault(); }
    else if (e.key === 'Enter') { const r = results[activeIdx]; if (r) act(r); }
    else if (e.key === 'Escape') close();
  });
  res.addEventListener('click', (e) => { const el = e.target.closest('.res'); if (el && el.dataset.i != null) act(results[+el.dataset.i]); });
  wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
  setTimeout(() => { inp.focus(); if (initial) run(); }, 20);
}
export function closeCmdbar() { close(); }
function close() { if (wrap) { wrap.remove(); wrap = null; overlayClosed(); } }

async function act(r) {
  switch (r.type) {
    case 'tool': navigate(`/tool/${r.id}`); break;
    case 'product': navigate(`/product/${r.id}`); break;
    case 'run': navigate(`/run/${r.id}`); break;
    case 'bug': navigate(`/product/${r.product}?tab=bugs&focus=${encodeURIComponent(r.id)}`); break;
    case 'todo': navigate(`/product/${r.product}?tab=todos&focus=${encodeURIComponent(r.id)}`); break;
    // 知識文件：直接開文件檢視 —— 使用者要的是「內容」，不是「哪一頁列著它」
    case 'doc': import('./docview.js').then((m) => m.openDoc(r.path, { title: r.label })); break;
    case 'case': {
      const s = new Set(state.selection); s.add(r.id); set({ selection: s }); window.__tp_selection = s;
      toast(`已加入選取：${r.label}（共 ${s.size} 條）`, 'success'); return;   // 不關閉，可連續加
    }
    case 'more': navigate(`/cases?q=${encodeURIComponent(r.id)}`); break;
    case 'command': await command(r.id); break;
  }
  close();
}
async function command(id) {
  const { modal } = await import('./modal.js');
  if (id === 'stop_all') {
    const live = state.active.filter((x) => !['completed', 'failed', 'stopped'].includes(x.phase));
    if (!live.length) { toast('沒有進行中的 run'); return; }
    if (await modal.confirm('停止全部', `將停止 ${live.length} 個進行中的 run。`, { danger: true, okLabel: '停止全部' })) {
      for (const r of live) { try { await api.post('/api/runs/stop', { run_id: r.run_id, reason: 'cmdbar stop_all' }); } catch (e) { /* ignore */ } }
      toast('已送出停止');
    }
  } else if (id === 'rebuild_index') { toast('重建案例索引中…'); const d = await api.post('/api/cases/rebuild'); toast(`索引已重建：${d.count} 條`, 'success'); }
  else if (id === 'refresh_jira') { toast('更新 JIRA…'); await api.get('/api/bugs?refresh=1'); toast('JIRA 已更新', 'success'); }
  else if (id === 'health') navigate('/settings/claude');
  else if (id === 'tools') navigate('/tools');
}

export function installHotkey() {
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); wrap ? close() : openCmdbar(); }
  });
}
