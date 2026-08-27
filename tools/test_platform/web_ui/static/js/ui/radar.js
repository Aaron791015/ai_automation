// ★ 知識雷達：扇形＝產品（等分）、同心圈＝知識層級（五圈，由內而外）、弧長＝正規化值。
// 最外圈為 24 小時執行熱度；圓心顯示系統狀態；進行中 run 以推進弧疊在核心環上。
// 兩種用法：
//   renderRadarInto(gEl, data, {compact:true, size})  ← 畫進既有 SVG 的 <g>（hero 中央用）
//   renderRadar(divEl, data, {...})                   ← 自成一個 SVG（產品頁／獨立卡用）
// 純 inline SVG，不引圖表庫。點扇區→產品頁；點圈層→對應清單。
import { html, raw, esc } from './el.js';

const RING_KEYS = ['spec', 'cases', 'bugs', 'reports', 'health'];
const RING_LABEL = { spec: '規格', cases: '案例', bugs: '缺陷', reports: '紀錄', health: '健康' };
const SHORT = { crux: 'CRUX', qixing: '七星', wbot: 'WBOT', common: '共通' };
const RING_TARGET = {
  spec: (p) => `#/product/${p}?tab=docs`, cases: (p) => `#/cases?product=${p}`,
  bugs: (p) => `#/product/${p}?tab=bugs`, reports: (p) => `#/product/${p}?tab=docs`,
  health: (p) => `#/product/${p}?tab=health`,
};
const PROD_VAR = { crux: 'var(--p-crux)', qixing: 'var(--p-qixing)', wbot: 'var(--p-wbot)', common: 'var(--p-common)' };

function polar(cx, cy, r, deg) { const a = (deg - 90) * Math.PI / 180; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; }
function arcPath(cx, cy, r, a0, a1) {
  if (a1 - a0 >= 359.9) a1 = a0 + 359.9;
  const [x0, y0] = polar(cx, cy, r, a0), [x1, y1] = polar(cx, cy, r, a1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}
function sectorPath(cx, cy, r0, r1, a0, a1) {
  const [ax, ay] = polar(cx, cy, r1, a0), [bx, by] = polar(cx, cy, r1, a1), [c1x, c1y] = polar(cx, cy, r0, a1), [dx, dy] = polar(cx, cy, r0, a0);
  const lg = a1 - a0 > 180 ? 1 : 0;
  return `M ${ax} ${ay} A ${r1} ${r1} 0 ${lg} 1 ${bx} ${by} L ${c1x} ${c1y} A ${r0} ${r0} 0 ${lg} 0 ${dx} ${dy} Z`;
}
const ringColor = (key, val, prod) => {
  if (key === 'health') return val >= .8 ? 'var(--success)' : val >= .55 ? 'var(--accent-amber)' : 'var(--danger)';
  if (key === 'bugs') return 'var(--danger)';
  return PROD_VAR[prod] || 'var(--accent)';
};

/** 產品顯示順序：與 hero 基座槽位一致（crux → qixing → wbot → common） */
export const PRODUCT_ORDER = ['crux', 'qixing', 'wbot', 'common'];
export function orderedIds(products) {
  const ids = Object.keys(products);
  return [...ids].sort((a, b) => {
    const ia = PRODUCT_ORDER.indexOf(a), ib = PRODUCT_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
}

/** 產生雷達的 SVG 內容字串（以 (0,0) 為圓心，供嵌入 <g>） */
function radarMarkup(data, { active = [], heat = [], state = 'idle', clock = '', compact = false, size = 300 } = {}) {
  const ids = orderedIds(data.products);
  const N = ids.length || 1;
  const scale = size / 300;
  const rCore = 34 * scale, rIn = 46 * scale, ringW = 11 * scale, gap = 4.5 * scale;
  const rOut = rIn + RING_KEYS.length * (ringW + gap);
  const rHeat0 = rOut + 4 * scale, rHeat1 = rHeat0 + 6 * scale;
  const sectorGap = 3;
  const p = [];
  const ringLabels = [];   // 圈層標籤延後畫（要壓在弧之上並帶襯底）

  for (let i = 0; i <= RING_KEYS.length; i++) p.push(`<circle class="ring-bg" cx="0" cy="0" r="${(rIn + i * (ringW + gap) - gap / 2).toFixed(1)}"/>`);
  ids.forEach((_, i) => {
    const a = i * 360 / N;
    const [x0, y0] = polar(0, 0, rCore + 3, a), [x1, y1] = polar(0, 0, rHeat1 + 2, a);
    p.push(`<line class="grid-line" x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}"/>`);
  });

  ids.forEach((pid, i) => {
    const prod = data.products[pid];
    const a0 = i * 360 / N + sectorGap / 2, aSpan = 360 / N - sectorGap;
    RING_KEYS.forEach((key, k) => {
      const ring = prod.rings[key];
      const norm = Math.max(0, Math.min(1, ring?.norm ?? 0));
      const r = rIn + k * (ringW + gap) + ringW / 2;
      const zero = norm === 0 || ring?.present === false;
      const len = zero ? aSpan : Math.max(2, aSpan * norm);
      const tip = `${esc(prod.label)} · ${RING_LABEL[key]}：${esc(ring?.detail || '—')}`;
      // 同一產品的相鄰圈常同色（例：spec 與 reports 都是產品色且都滿格），
      // 因此在透明度上做「由內而外遞增」的階梯，讓五圈在視覺上仍分得開。
      const tierAlpha = [.42, .58, .74, .86, 1][k];
      const op = zero ? .45 : Math.min(1, tierAlpha * (.55 + norm * .4) + .22);
      // 「零／不存在」的圈畫成一條細虛線軌跡就好 —— 早期版本用整條粗虛線，
      // 五圈疊起來像放射狀髒污，把整個雷達的可讀性吃掉了。
      // 線框極座標：弧一律畫細（參考圖 RISK METRICS 的雷達是線，不是色塊）
      const w = zero ? Math.max(1, 1.4 * scale) : Math.max(2.2, ringW * .32);
      p.push(`<path class="arc ${zero ? 'zero' : ''}" data-pid="${pid}" data-ring="${key}" data-tip="${tip}" d="${arcPath(0, 0, r, a0, a0 + len)}" stroke="${ringColor(key, norm, pid)}" stroke-width="${w.toFixed(1)}" opacity="${op.toFixed(2)}"/>`);
      // 圈底槽（未填滿的部分留一道極淡軌跡，讓「這一圈有多滿」看得出來）
      // 整圈的底軌（含已填滿的段）：讓「這一圈到哪裡」有參照，同樣是細線
      p.push(`<path class="arc-track" d="${arcPath(0, 0, r, a0, a0 + aSpan)}" stroke-width="${Math.max(.7, .9 * scale).toFixed(1)}" fill="none"/>`);
      if (i === 0) ringLabels.push({ r, label: RING_LABEL[key] });
    });
    p.push(`<path class="sector-hit" data-pid="${pid}" data-tip="${esc(prod.label)}：點擊進入產品頁" d="${sectorPath(0, 0, rCore + 2, rOut, a0, a0 + aSpan)}"/>`);
    const [tx, ty] = polar(0, 0, rHeat1 + (compact ? 11 : 15), a0 + aSpan / 2);
    const anchor = tx > 8 ? 'start' : tx < -8 ? 'end' : 'middle';
    p.push(`<text class="sector-lbl" x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}" style="fill:${PROD_VAR[pid] || 'var(--accent)'}">${esc(compact ? (SHORT[pid] || prod.label) : prod.label)}</text>`);
  });

  const hn = heat.length || 24;
  heat.forEach((hh, i) => {
    const a0 = i * 360 / hn + .6, a1 = (i + 1) * 360 / hn - .6;
    const col = !hh.runs ? 'rgba(27,68,112,.5)' : hh.failed ? 'var(--danger-dim)' : 'var(--success-dim)';
    p.push(`<path class="heat" data-tip="${hh.hour}:00 · ${hh.runs} run${hh.failed ? ` · 失敗 ${hh.failed}` : ''}" d="${arcPath(0, 0, (rHeat0 + rHeat1) / 2, a0, a1)}" stroke="${col}" stroke-width="${(rHeat1 - rHeat0).toFixed(1)}" fill="none"/>`);
  });

  // 圈層標籤：12 點鐘方向一條「索引條」，五個標籤共用一塊襯底 ——
  // 先前每個標籤各自帶一塊小襯底，看起來像五塊隨機的灰斑而不是刻意的標示。
  if (ringLabels.length) {
    const top = -rOut + 1, bottom = -rIn + 1;
    p.push(`<rect class="ring-lbl-bg" x="-19" y="${top.toFixed(1)}" width="38" height="${(bottom - top + 5).toFixed(1)}" rx="2"/>`);
    ringLabels.forEach(({ r, label }) => {
      p.push(`<text class="ring-lbl" x="0" y="${(-r + 3).toFixed(1)}" text-anchor="middle">${label}</text>`);
    });
  }

  p.push(`<circle class="core-ring ${state === 'idle' ? 'breath' : ''}" cx="0" cy="0" r="${rCore.toFixed(1)}"/>`);
  const running = active.filter((r) => !['completed', 'failed', 'stopped'].includes(r.phase));
  running.forEach((r, i) => {
    const pct = Math.max(2, Math.min(100, r.progress?.percent ?? 5));
    const rr = rCore + (4 + i * 4) * scale, c = 2 * Math.PI * rr;
    p.push(`<circle class="run-arc" data-run="${r.run_id}" data-tip="${esc(r.tool_name || '')}：${Math.round(pct)}%" cx="0" cy="0" r="${rr.toFixed(1)}" stroke="${PROD_VAR[r.product] || 'var(--accent)'}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - pct / 100)).toFixed(1)}" transform="rotate(-90)"/>`);
  });
  const big = state === 'running' ? `執行中 ${running.length}` : state === 'fault' ? '異常' : state === 'warning' ? '注意' : '待命';
  p.push(`<text class="center-txt big state-${state}" x="0" y="${(-1 * scale).toFixed(1)}">${big}</text>`);
  p.push(`<text class="center-txt small" x="0" y="${(13 * scale).toFixed(1)}">${esc(clock)}</text>`);
  return p.join('');
}

/** 畫進既有 SVG 的 <g>（hero 用） */
export function renderRadarInto(gEl, data, opts = {}) {
  gEl.innerHTML = radarMarkup(data, opts);
  gEl.classList.add('radar');
}

/** 自成一個 SVG（產品頁／獨立卡用） */
export function renderRadar(container, data, opts = {}) {
  const size = opts.size || 300;
  const box = size + (opts.compact ? 44 : 76);
  container.innerHTML = `<div class="radar" style="position:relative"><svg viewBox="${-box / 2} ${-box / 2} ${box} ${box}" role="img" aria-label="知識雷達">${radarMarkup(data, opts)}</svg><div class="radar-tip hidden"></div></div>`;
  const svg = container.querySelector('svg'), tipEl = container.querySelector('.radar-tip');
  svg.addEventListener('mousemove', (e) => {
    const t = e.target.closest('[data-tip]');
    if (!t) { tipEl.classList.add('hidden'); return; }
    tipEl.innerHTML = String(t.dataset.tip).replace(/^([^·]+·[^：]+)：/, '<b>$1</b>：');
    tipEl.classList.remove('hidden');
    const rect = container.getBoundingClientRect();
    tipEl.style.left = (e.clientX - rect.left + 12) + 'px';
    tipEl.style.top = (e.clientY - rect.top + 12) + 'px';
  });
  svg.addEventListener('mouseleave', () => tipEl.classList.add('hidden'));
  svg.addEventListener('click', (e) => {
    const arc = e.target.closest('.arc');
    if (arc) { opts.onRing ? opts.onRing(arc.dataset.pid, arc.dataset.ring) : (location.hash = RING_TARGET[arc.dataset.ring](arc.dataset.pid)); return; }
    const sec = e.target.closest('.sector-hit');
    if (sec) { opts.onSector ? opts.onSector(sec.dataset.pid) : (location.hash = `#/product/${sec.dataset.pid}`); return; }
    const ra = e.target.closest('.run-arc');
    if (ra) location.hash = `#/run/${ra.dataset.run}`;
  });
  svg.addEventListener('mouseover', (e) => {
    const pid = e.target.closest('[data-pid]')?.dataset.pid;
    svg.querySelectorAll('.arc').forEach((a) => a.classList.toggle('dim', !!pid && a.dataset.pid !== pid));
  });
  svg.addEventListener('mouseout', () => svg.querySelectorAll('.arc').forEach((a) => a.classList.remove('dim')));
}

export function renderLegend(container, data) {
  const rows = RING_KEYS.map((k) => html`<div class="lg" data-ring="${k}"><span class="sw" style="background:${k === 'health' ? 'var(--success)' : k === 'bugs' ? 'var(--danger)' : 'var(--accent)'}"></span>${{ spec: '規格機制', cases: '測試案例', bugs: '缺陷（活躍）', reports: '驗證紀錄', health: '健康度' }[k]}<span class="n">${raw(Object.entries(data.products).map(([pid, p]) => `<span class="pc-${pid}">${p.rings[k].value}</span>`).join('/'))}</span></div>`);
  container.innerHTML = rows.join('');
}

export { RING_TARGET, RING_LABEL };
