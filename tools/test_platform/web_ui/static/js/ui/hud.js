// HUD 小元件：進度環、sparkline、狀態燈、phase 時間軸、指標卡
import { html, raw, fmt } from './el.js';

export function ring(percent, { size = 56, stroke = 5, label = null, tone = '' } = {}) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  return html`<span class="ring ${tone}" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}"><circle class="track" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}"/>
    <circle class="bar" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - p / 100)).toFixed(1)}"/></svg>
    <span class="val">${label ?? Math.round(p) + '%'}</span></span>`;
}

export function sparkline(values, { w = 120, h = 28, max = null } = {}) {
  if (!values || !values.length) return '';
  const mx = max ?? Math.max(...values, 1), n = values.length;
  const xy = values.map((v, i) => [i / Math.max(n - 1, 1) * w, h - (v / mx) * (h - 2) - 1]);
  // 平滑曲線（Catmull-Rom → 三次貝茲），對齊參考圖那種柔和的走勢線
  const smooth = (() => {
    if (xy.length < 2) return '';
    let d = `M${xy[0][0].toFixed(1)} ${xy[0][1].toFixed(1)}`;
    for (let i = 0; i < xy.length - 1; i++) {
      const p0 = xy[i - 1] || xy[i], p1 = xy[i], p2 = xy[i + 1], p3 = xy[i + 2] || p2;
      const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    return d;
  })();
  // 橫向拉滿容器（preserveAspectRatio=none）；線寬用 non-scaling-stroke 才不會被拉粗
  return html`<svg class="spark" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="area" d="${smooth} L${w} ${h} L0 ${h} Z"/><path class="line" d="${smooth}" vector-effect="non-scaling-stroke"/></svg>`;
}

export const dot = (state) => html`<span class="dot ${state || ''}"></span>`;

export function timeline(phases, current, platformPhase) {
  if (!phases || !phases.length) return '';
  const idx = phases.findIndex((p) => p.value === current);
  const nonTerm = phases.filter((p) => !p.terminal);
  const term = phases.find((p) => p.value === current && p.terminal);
  const list = term ? [...nonTerm, term] : nonTerm;
  return html`<div class="timeline">${list.map((p, i) => {
    const pi = phases.findIndex((x) => x.value === p.value);
    let cls = '';
    if (term && p.terminal) cls = 'term-' + (p.tone || 'success');
    else if (idx >= 0 && (pi < idx || (term && !p.terminal))) cls = 'done';
    else if (p.value === current) cls = 'cur';
    return html`<div class="ph ${cls}"><span class="d"></span><span>${p.label}</span></div>`;
  })}</div>`;
}

export function metricCards(defs, metrics) {
  if (!defs || !defs.length) return '';
  return html`<div class="metric-cards">${defs.map((d) => {
    const v = metrics?.[d.key];
    let tone = d.tone || '';
    if (d.warn_above != null && v != null && v > d.warn_above) tone = 'warn';
    return html`<div class="metric ${tone}"><div class="k">${d.label}</div><div class="v">${fmt.by(d.format || 'int', v)}</div></div>`;
  })}</div>`;
}

export const toneOfPhase = (p) => ({ completed: 'success', failed: 'danger', stopped: 'warn', running: 'info', starting: 'info', stopping: 'warn', queued: 'info' }[p] || '');
export const phaseLabel = (p) => ({ queued: '排隊中', starting: '啟動中', running: '執行中', stopping: '停止中', completed: '完成', failed: '失敗', stopped: '已停止' }[p] || p);
