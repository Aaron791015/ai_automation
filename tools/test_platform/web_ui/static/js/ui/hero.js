// ★ HERO 場景：各產品的全息基座一字排開，中央前方是線框地球（總覽主視覺）
// 對齊參考圖 JARVIS SOVEREIGN 的「ASSET ALLOCATION」帶：
//   透視地板 → 一排圓柱基座（標籤刻在柱面上）→ 基座上方大型線框物件 → 前方中央線框地球
// ⚠️ 2026-08-19 改版：中央原為彩色扇形雷達，使用者指出參考圖沒有扇形 → 改為地球＋軌道環。
//   知識五圈的細節改由產品頁的線框極座標雷達承載（radar.js）。
// 狀態聯動：有 run → 光管脈動＋基座掃描環；有 blocker → 基座轉紅。點基座 → 產品頁。
import { esc } from './el.js';
import { orderedIds } from './radar.js';
import { pointCloudCaption, baseBloom } from './pointcloud.js';
import { renderProduct, sampleDots, layerK, LAYERS, bodyFrame, modelOf, swayYaw, fontsUsable, resetShapes, badgeMetrics } from './models.js';

const W = 1200;
// 側欄化之後主視覺拿到整個左欄（1920 下約 1440×970），故場景改為「基座列在上、地球在下」的高版面
const FLOOR_Y = 700;          // 地板橢圓中心（＝地球球心，讓地球像放在地板上）
const DRUM_Y = 500;           // 基座頂面橢圓中心
const DRUM_RX = 100, DRUM_RY = 26, DRUM_H = 68;

let bgCache = null, floorCache = null;   // 靜態背景只算一次
const modelCache = new Map();           // 表面取樣與靜態幀只算一次
let swayRaf = 0;                        // hover 擺動的 rAF；重繪主視覺時必須先取消（舊 DOM 已卸載）
let lastDraw = null, fontHooked = false;   // 字型載入完成後要重畫一次，見檔尾
// ★ 場景快取：換頁離開總覽再回來時，**把上次建好的節點搬回去**，不重新 parse。
//   重建一次要 408KB 標記／5,347 節點 ＝ 約 23ms 解析 ＋ 36ms 版面，是一格看得見的 long frame
//   （2026-08-20 使用者：「畫面切換會有不夠滑順的體感」）。
//   移動既有子樹便宜一個數量級，而且事件監聽掛在 <svg> 上、隨節點一起搬，不必重掛。
//   ⚠️ 快取鍵是 opts.sig（由 overview.js 算），**內容一變就必須換鍵**，否則會顯示舊資料。
let scene = null;              // { sig, root, stopSway, updateRuns }

const EMPTY_CLOUD = { base: '', frame: () => null };

/**
 * 產品的全息體 ＝ 3D 線框投影 ＋ 表面取樣點。
 * 點數規則同前：亮點＝案例＋規格＋紀錄＋Bug（上限 340），不足 60 補暗點；Bug 為紅點。
 *
 * 回傳 `{ base, frame(yaw) }`：
 *   `base` ＝ 基準視角的成品字串（靜態呈現直接用，零成本）；
 *   `frame(yaw)` ＝ 擺動時各層的仿射矩陣，由 paint() 寫回既有節點的 transform。
 *
 * ⚠️ **取樣與每點的亂數半徑／透明度只抽一次**，之後永不重算 ——
 *    每幀重抽亂數的話，星點會整片跳動而不是跟著字轉。
 */
function productCloud(pid, counts) {
  const key = `${pid}|${counts.cases}|${counts.spec}|${counts.reports}|${counts.bugs}`;
  if (modelCache.has(key)) return modelCache.get(key);
  if (!modelOf(pid)) { modelCache.set(key, EMPTY_CLOUD); return EMPTY_CLOUD; }

  let seed = seedOf(pid);
  const rnd = () => { seed = (seed + 0x6D2B79F5) >>> 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };

  const bright = Math.min(340, counts.cases + counts.spec + counts.reports + counts.bugs);
  const ghost = Math.max(0, 60 - bright);
  const kinds = [];
  const push = (k, n) => { for (let i = 0; i < n; i++) kinds.push(k); };
  push('case', counts.cases); push('spec', counts.spec); push('report', counts.reports); push('bug', counts.bugs);
  kinds.length = Math.min(kinds.length, bright);
  while (kinds.length < bright) kinds.push('case');
  for (let i = 0; i < ghost; i++) kinds.push('ghost');
  for (let i = kinds.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [kinds[i], kinds[j]] = [kinds[j], kinds[i]]; }

  const STYLE = { case: [0.5, 0.95, 0.5, 0.9], spec: [0.4, 0.7, 0.26, 0.5], report: [0.4, 0.7, 0.26, 0.5], bug: [0.7, 1.1, 0.78, 1], ghost: [0.34, 0.6, 0.1, 0.2] };
  // ★ 取樣一次，並**依深度層分組**：同一層的點吃同一個仿射矩陣，
  //   擺動時整組換一次 transform 就好（見 models.js 的 sampleDots 說明）。
  //   半徑與透明度含深度係數，分層後就是常數，可以直接烘進靜態字串、永不再改。
  const buckets = [...Array(LAYERS)].map(() => []);
  sampleDots(pid, kinds.length, rnd).forEach((d, i) => {
    const [r0, r1, o0, o1] = STYLE[kinds[i]];
    const k = layerK(pid, d.layer);                       // 遠的點小而暗
    buckets[d.layer].push(`<circle class="pc-dot k-${kinds[i]}" cx="${d.lx.toFixed(1)}" cy="${d.ly.toFixed(1)}"`
      + ` r="${((r0 + rnd() * (r1 - r0)) * k).toFixed(2)}" opacity="${((o0 + rnd() * (o1 - o0)) * (0.55 + 0.45 * k)).toFixed(2)}"/>`);
  });
  // 掃描顆粒：純質感，密度固定（不隨深度縮放，維持原本的均勻顆粒感）
  sampleDots(pid, 200, rnd).forEach((d) => {          // 2026-08-20 由 420 減半，降低光柵化成本
    buckets[d.layer].push(`<circle class="pc-grain" cx="${d.lx.toFixed(1)}" cy="${d.ly.toFixed(1)}"`
      + ` r="${(0.22 + rnd() * 0.32).toFixed(2)}" opacity="${(0.08 + rnd() * 0.18).toFixed(2)}"/>`);
  });

  // 靜態幀：字樣本體（由後而前）＋ 分層的點群，都用基準視角的矩陣
  const frame0 = bodyFrame(pid, 0);
  let base = renderProduct(pid, 0);
  // 點群整批畫在字樣之後（疊在最上），順序與 frame 陣列一致，paint() 才對得上索引
  for (const f of frame0) base += `<g class="pc-layer" transform="${f.m}">${buckets[f.i].join('')}</g>`;

  // 擺動幀：只需要各層的矩陣 —— 每幀 17 個字層 ＋ 17 個點群 ＝ 34 次 transform 寫入
  const spec = { base, frame: (yaw) => bodyFrame(pid, yaw) };
  modelCache.set(key, spec);
  return spec;
}

const PROD_VAR = { crux: 'var(--p-crux)', qixing: 'var(--p-qixing)', wbot: 'var(--p-wbot)', common: 'var(--p-common)' };

/** n 個基座的 x 座標：一字排開、等距置中；產品變多時自動縮小並收緊間距。 */
function slotsFor(n) {
  const gap = Math.min(288, (W - 120) / n);
  const s = Math.min(1.28, gap / 225);      // 主視覺變大了，物件跟著放大
  const total = gap * (n - 1);
  return [...Array(n)].map((_, i) => ({ x: W / 2 - total / 2 + i * gap, s }));
}


// ── 投影裝置（讓物件看起來是「投出來的」而不是貼上去的圖示）──────────────
// 三件事：① 從基座往上收束的光錐 ② 全息掃描橫帶 ③ 基座的發射環
function projector(rx, topY) {
  const p = [];
  // ① 光錐：從基座鏡面往上收束，兩側各一片，中間一片較亮
  p.push(`<path class="holo-cone" d="M${(-rx * .86).toFixed(1)} 0 L${(-rx * .30).toFixed(1)} ${topY} L${(rx * .30).toFixed(1)} ${topY} L${(rx * .86).toFixed(1)} 0 Z"/>`);
  p.push(`<path class="holo-cone edge" d="M${(-rx * .86).toFixed(1)} 0 L${(-rx * .30).toFixed(1)} ${topY} M${(rx * .86).toFixed(1)} 0 L${(rx * .30).toFixed(1)} ${topY}"/>`);
  // ② 掃描橫帶：等距細橫線，寬度隨光錐收束
  for (let y = -10; y > topY; y -= 9) {
    const t = y / topY;                       // 0（底）→ 1（頂）
    const w = rx * (.86 - .56 * t);
    p.push(`<line class="holo-band" x1="${(-w).toFixed(1)}" y1="${y}" x2="${w.toFixed(1)}" y2="${y}"/>`);
  }
  // ③ 發射環：基座鏡面上的兩圈細環
  p.push(`<ellipse class="holo-emit" cx="0" cy="-2" rx="${(rx * .58).toFixed(1)}" ry="${(rx * .15).toFixed(1)}"/>`);
  p.push(`<ellipse class="holo-emit" cx="0" cy="-2" rx="${(rx * .34).toFixed(1)}" ry="${(rx * .09).toFixed(1)}"/>`);
  return p.join('');
}

// ⚠️ 2026-08-20 刪除：原本這裡有一整套**手繪 2D 圖騰**（搖球機／北斗七星／機器人／機櫃剪影，約 110 行），
//    供 #/tools 欄首與產品頁頁首的小圖示使用。小圖示改為文字徽章後（見 glyphSvg）整組成為死碼，
//    主視覺的 3D 物件也早在同日換成字樣投影。要找它們請看 git 歷史（449b6c5 之前）。
//    對應的 CSS（.glyph-mini／.obj-*／.pc-silhouette／.gl-node）同時移除。

// ── 執行中標籤 ─────────────────────────────────────────────────────────
// 使用者的原話是「設定測試執行後，回到總覽，就知道是什麼任務正在進行中」——
// 所以標籤必須直接寫出**工具名、階段、進度**，不能只靠光效暗示。
// 位置在投影機頭頂上方（local y −214），那一帶是空的星空，不會壓到字樣或基座。
const RT_W = 230, RT_BAR = 200;
const RT_FS = 15, RT_FS_MIN = 10.5;
/**
 * SVG 的 <text> 沒有 ellipsis，長工具名會直接撞上右邊的百分比
 * （「投注機器人 聊天室壓測」實測就會壓到 —— 2026-08-20 修）。
 * 故自己估寬：CJK 約 1 em、拉丁與空白約 0.55 em，先縮字級，縮到下限還放不下才截斷。
 */
function fitName(t, maxW) {
  const unit = (ch) => (ch.codePointAt(0) > 0x2e80 ? 1 : 0.55);
  const em = [...t].reduce((a2, ch) => a2 + unit(ch), 0);
  if (em * RT_FS <= maxW) return { text: t, fs: RT_FS };
  const fs = Math.max(RT_FS_MIN, maxW / em);
  if (em * fs <= maxW) return { text: t, fs: +fs.toFixed(1) };
  let acc = 0, out = '';
  for (const ch of t) { const cw = unit(ch) * fs; if (acc + cw > maxW - fs) break; acc += cw; out += ch; }
  return { text: out + '…', fs: +fs.toFixed(1) };
}
function runTag(r) {
  const pct = Math.max(0, Math.min(100, r.progress?.percent ?? 0));
  const h = RT_W / 2, x0 = -h + 15;
  const phase = r.tool_phase_label || r.phase || '';
  const nm = fitName(r.tool_name || r.tool_id || '', RT_BAR - 46);   // 46 ＝ 右側百分比與間距
  return `<g class="run-tag" data-pid="${esc(r.product)}" transform="translate(0 -214)">
    <rect class="rt-bg" x="${-h}" y="-22" width="${RT_W}" height="52" rx="9"/>
    <circle class="rt-dot" cx="${x0 + 4}" cy="-10" r="3.6"/>
    <text class="rt-phase" x="${x0 + 13}" y="-6">執行中${phase ? ' · ' + esc(phase) : ''}</text>
    <text class="rt-name" x="${x0}" y="13" font-size="${nm.fs}">${esc(nm.text)}</text>
    <text class="rt-pct" x="${h - 15}" y="13" text-anchor="end">${Math.round(pct)}%</text>
    <rect class="rt-track" x="${x0}" y="21" width="${RT_BAR}" height="3" rx="1.5"/>
    <rect class="rt-fill" x="${x0}" y="21" width="${(RT_BAR * pct / 100).toFixed(1)}" height="3" rx="1.5"/>
    <line class="rt-leader" x1="0" y1="30" x2="0" y2="40"/>
  </g>`;
}

/** 進度弧的點串（updateRuns 要重算，故抽成函式） */
function arcPoints(pct, rr, ry) {
  const p2 = Math.max(3, Math.min(100, pct));
  const pts = [];
  for (let d = 0; d <= 360 * p2 / 100; d += 3) {
    const th = (d - 90) * Math.PI / 180;
    pts.push(`${(Math.cos(th) * rr).toFixed(1)} ${(Math.sin(th) * ry).toFixed(1)}`);
  }
  return pts.join(' ');
}

/** 產品 id → 固定 seed（同一產品每次都得到同一張星圖） */
function seedOf(pid) {
  let h = 2166136261;
  for (let i = 0; i < pid.length; i++) { h ^= pid.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

/** 給其他頁重用的小圖騰（產品頁頁首、#/tools 欄首） */
export function glyphSvg(pid, size = 22) {
  // ★ 2026-08-20 起改為**與主視覺同一組字樣**的文字徽章（使用者裁示）：
  //   各產品顏色不同，顏色本來就足以快速分辨，圖形不必再擔負辨識工作；
  //   字樣一致則主視覺與清單頁講同一種語言。
  //   高度固定、寬度隨字樣長短伸縮（ChatBot 比 CRUX 寬是正常的），
  //   故 viewBox 用量測出的比例，呼叫端只鎖高度、寬度給 auto。
  const m = badgeMetrics(pid);
  if (!m) return '';
  const H = 34, PAD = 7;                       // 徽章內部座標系
  const FS = 19;                               // 字級（相對 H）
  const W = Math.round(m.ratio * FS + PAD * 2);
  return `<svg viewBox="0 0 ${W} ${H}" height="${size}" width="${Math.round(size * W / H)}" aria-hidden="true">`
    + `<rect class="wm-box" x=".8" y=".8" width="${W - 1.6}" height="${H - 1.6}" rx="5"/>`
    + `<text class="wm-text" x="${W / 2}" y="${H / 2}" font-size="${FS}" text-anchor="middle" dominant-baseline="central">${m.text}</text>`
    + `</svg>`;
}

// ── 中央：螺旋星系 ＋ 融入其中的知識雷達軌道 ──────────────────────────
// 2026-08-19 改版：地球移除，改為代表「整個測試宇宙」的螺旋星系；
// 原本在側欄的知識雷達五圈，改成星系外圍的**軌道環**融進主視覺（使用者要求）。
// 軌道用透視壓扁的橢圓，不是正圓餅圖 —— 讀起來是行星系統，不是圓餅。

const RING_ORDER = ['spec', 'cases', 'bugs', 'reports', 'health'];
const RING_NAME = { spec: '規格', cases: '案例', bugs: '缺陷', reports: '紀錄', health: '健康' };

/** 螺旋星系：核球 ＋ 兩條旋臂（每條由密集粒子構成）＋ 星系盤 */
function galaxyMarkup(R, rnd) {
  const p = [];
  const SQUASH = 0.34;                       // 透視壓扁，與地板同一個視角
  p.push(`<ellipse class="gx-halo" cx="0" cy="0" rx="${(R * 1.5).toFixed(0)}" ry="${(R * 1.5 * SQUASH).toFixed(0)}"/>`);
  p.push(`<ellipse class="gx-disc" cx="0" cy="0" rx="${(R * 1.12).toFixed(0)}" ry="${(R * 1.12 * SQUASH).toFixed(0)}"/>`);

  // 旋臂：對數螺線上撒粒子，越外圈越稀疏
  for (let arm = 0; arm < 2; arm++) {
    const phase = arm * Math.PI;
    for (let i = 0; i < 320; i++) {
      const t = i / 320;
      const th = phase + t * Math.PI * 2.05;
      const rad = R * (0.16 + t * 0.98);
      const jitter = (rnd() - .5) * rad * 0.20;
      const x = Math.cos(th) * (rad + jitter);
      const y = Math.sin(th) * (rad + jitter) * SQUASH;
      const rr = 0.35 + rnd() * (1 - t) * 1.15;
      const op = (0.20 + rnd() * 0.65) * (1 - t * 0.55);
      p.push(`<circle class="gx-star" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rr.toFixed(2)}" opacity="${op.toFixed(2)}"/>`);
    }
  }
  // 盤面散星
  for (let i = 0; i < 260; i++) {
    const th = rnd() * Math.PI * 2, rad = R * (0.1 + Math.sqrt(rnd()) * 1.05);
    p.push(`<circle class="gx-star dim" cx="${(Math.cos(th) * rad).toFixed(1)}" cy="${(Math.sin(th) * rad * SQUASH).toFixed(1)}" r="${(0.25 + rnd() * 0.5).toFixed(2)}" opacity="${(0.10 + rnd() * 0.35).toFixed(2)}"/>`);
  }
  // 核球
  p.push(`<ellipse class="gx-core" cx="0" cy="0" rx="${(R * 0.34).toFixed(0)}" ry="${(R * 0.34 * SQUASH * 1.5).toFixed(0)}"/>`);
  p.push(`<circle class="gx-core-hot" cx="0" cy="0" r="${(R * 0.11).toFixed(0)}"/>`);
  return p.join('');
}

/**
 * 知識雷達軌道：五條壓扁橢圓軌道，各代表一個知識層級；
 * 每個產品在軌道上佔一段弧，弧長＝該產品在該層級的正規化值。
 */
function knowledgeOrbits(R, products, ids) {
  const SQUASH = 0.34;
  const p = [];
  const N = ids.length || 1;
  RING_ORDER.forEach((key, k) => {
    const rx = R * (1.30 + k * 0.24), ry = rx * SQUASH;
    p.push(`<ellipse class="ko-track" cx="0" cy="0" rx="${rx.toFixed(1)}" ry="${ry.toFixed(1)}"/>`);
    ids.forEach((pid, i) => {
      const ring = products[pid].rings[key];
      const norm = Math.max(0, Math.min(1, ring?.norm ?? 0));
      const a0 = i * 360 / N + 4, span = (360 / N - 8) * norm;
      if (span < 1.5) return;
      const pts = [];
      for (let d = 0; d <= span; d += 2) {
        const th = (a0 + d - 90) * Math.PI / 180;
        pts.push(`${(Math.cos(th) * rx).toFixed(1)} ${(Math.sin(th) * ry).toFixed(1)}`);
      }
      const col = key === 'bugs' ? 'var(--danger)' : PROD_VAR[pid] || 'var(--accent)';
      p.push(`<polyline class="ko-arc" data-pid="${pid}" data-ring="${key}" data-tip="${esc(products[pid].label)} · ${RING_NAME[key]}：${esc(ring?.detail || '—')}" points="${pts.join(' ')}" stroke="${col}"/>`);
      // 弧末端的節點
      const last = pts[pts.length - 1].split(' ');
      p.push(`<circle class="ko-node" cx="${last[0]}" cy="${last[1]}" r="1.8" fill="${col}"/>`);
    });
    // 軌道標籤放 9 點鐘方向：壓扁橢圓在 12 點鐘的 ry 幾乎重疊，標籤會疊成一團；
    // 放在左側則各軌道以 rx 分開，天然不打架。
    p.push(`<text class="ko-lbl" x="${(-rx - 6).toFixed(1)}" y="3" text-anchor="end">${RING_NAME[key]}</text>`);
  });
  return p.join('');
}

// ── 主繪製 ────────────────────────────────────────────────────────────────
export function renderHero(container, knowledge, opts = {}) {
  const { active = [], todos = null, state = 'idle', clock = '', onSector } = opts;
  if (!knowledge || !knowledge.products) return;
  if (opts.sig && scene && scene.sig === opts.sig && scene.root) {
    scene.stopSway();                       // 上次可能停在 hover 擺動中途，先收乾淨再接回去
    container.replaceChildren(scene.root);
    lastDraw = [container, knowledge, opts];
    return;
  }
  if (swayRaf) { cancelAnimationFrame(swayRaf); swayRaf = 0; }   // 舊場景要被換掉，先停掉它的擺動
  scene = null;
  lastDraw = [container, knowledge, opts];
  // 共通貫穿所有產品，刻意不給它基座 —— 它的知識量改為散佈成整個場景的星塵（見下方 dustField）
  const ids = orderedIds(knowledge.products).filter((pid) => modelOf(pid));
  const ambient = orderedIds(knowledge.products).filter((pid) => !modelOf(pid));
  const slots = slotsFor(ids.length);
  const cx = W / 2;
  const parts = [];

  // ── 深空背景：星雲 → 銀河帶 → 星空 → 地板資料點 ──
  // 這些與資料無關，算一次就好；drawHero() 會被 store 訂閱與輪詢反覆呼叫，
  // 每次重算約 2,000 個節點的字串是白花的（實測佔 renderHero 的大半時間）。
  // 先前只有 132 顆星塵，畫面空洞、沒有宇宙感（2026-08-19 使用者指出）。
  // 這一層純屬氛圍，資料語意仍只在「共通星塵」那一組（較亮、青色、可 hover）。
  let seed = 0x9e3779b9;
  const rnd = () => { seed = (seed + 0x6D2B79F5) >>> 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const Y0 = 214, YH = 606;
  if (!bgCache) {
    const bg = [];

  // ① 星雲：幾團極淡的色暈，給深空一點層次
    bg.push(`<g class="nebula">
    <ellipse cx="210" cy="320" rx="360" ry="230" fill="url(#neb-a)"/>
    <ellipse cx="1000" cy="400" rx="400" ry="250" fill="url(#neb-b)"/>
    <ellipse cx="600" cy="730" rx="520" ry="210" fill="url(#neb-c)"/>
    <ellipse cx="560" cy="300" rx="300" ry="160" fill="url(#neb-b)" opacity=".7"/>
  </g>`);

  // ② 銀河帶：一條斜過畫面的密集星帶
  const band = [];
  for (let i = 0; i < 620; i++) {
    const t = rnd();
    const bx = -60 + t * (W + 120);
    const spread = 46 + 60 * Math.sin(t * Math.PI);
    const by = Y0 + 120 + t * 300 + (rnd() - .5) * spread * 2;
    band.push(`<circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="${(0.25 + rnd() * 0.6).toFixed(2)}" opacity="${(0.12 + rnd() * 0.45).toFixed(2)}"/>`);
  }
    bg.push(`<g class="milky">${band.join('')}</g>`);

  // ③ 星空：三級亮度，亮星帶十字星芒
  const sky = [], bright = [];
  for (let i = 0; i < 1000; i++) {
    const x = rnd() * W, y = Y0 + rnd() * YH;
    const t = rnd();
    if (t > 0.972) {
      bright.push(`<g class="bstar" style="animation-delay:${(rnd() * 6).toFixed(1)}s"><circle class="halo" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(2.6 + rnd() * 1.6).toFixed(2)}"/><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(0.9 + rnd() * 0.7).toFixed(2)}"/><path d="M${(x - 5).toFixed(1)} ${y.toFixed(1)} h10 M${x.toFixed(1)} ${(y - 5).toFixed(1)} v10"/></g>`);
    } else {
      sky.push(`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(0.25 + t * 0.85).toFixed(2)}" opacity="${(0.18 + t * 0.62).toFixed(2)}"/>`);
    }
  }
    bg.push(`<g class="starfield">${sky.join('')}</g><g class="starfield bright">${bright.join('')}</g>`);

    bgCache = bg.join('');
  }
  parts.push(bgCache);

  // ④ 共通的知識星塵（有資料語意：較亮、青色、可 hover）
  const dustN = ambient.reduce((a, pid) => {
    const r = knowledge.products[pid].rings;
    return a + (r.cases?.value || 0) + (r.spec?.value || 0) + (r.reports?.value || 0);
  }, 0);
  if (dustN) {
    const dust = [];
    for (let i = 0; i < Math.min(320, dustN); i++) {
      const x = 20 + rnd() * (W - 40), y = Y0 + 20 + rnd() * (YH - 60);
      dust.push(`<circle class="scene-dust" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(0.55 + rnd() * 0.8).toFixed(2)}" opacity="${(0.25 + rnd() * 0.5).toFixed(2)}"/>`);
    }
    parts.push(`<g class="dust-field" data-tip="共通（跨產品基礎設施）：${dustN} 項知識，散佈於全景">${dust.join('')}</g>`);
  }

  // ── 地板：透視同心橢圓 ＋ 放射刻度 ──
  [[566, 105], [452, 84], [338, 62], [224, 41]].forEach(([rx, ry], i) => {
    parts.push(`<ellipse class="floor-ring ${i ? 'faint' : ''}" cx="${cx}" cy="${FLOOR_Y}" rx="${rx}" ry="${ry}"/>`);
  });
  for (let a = 0; a < 360; a += 6) {
    const rad = a * Math.PI / 180, k = a % 30 === 0 ? 26 : 12;
    const x1 = cx + 566 * Math.cos(rad), y1 = FLOOR_Y + 105 * Math.sin(rad);
    const x2 = cx + (566 - k) * Math.cos(rad), y2 = FLOOR_Y + (105 - k * .186) * Math.sin(rad);
    parts.push(`<line class="floor-tick" x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" opacity="${a % 30 === 0 ? .34 : .13}"/>`);
  }

  // ── 地板：密集電路板 ──
  // 參考圖的平台地面是一整片發光的電路紋理，不是零星幾個點。
  // 四種元素疊起來才有那個密度：① 放射走線 ② 環段 ③ 節點 ④ 資料流亮點。
  // 與資料無關 → 只算一次（floorCache）。
  if (!floorCache) {
    const ell = (rx, ry, ang) => [cx + rx * Math.cos(ang), FLOOR_Y + ry * Math.sin(ang)];
    const RINGS = [[566, 105], [488, 91], [410, 76], [332, 62], [254, 47], [176, 33]];
    const fdots = [];

    // ① 放射走線：內外環之間的直角折線（電路板走線的樣子）
    for (let i = 0; i < 72; i++) {
      const ang = (i / 72) * Math.PI * 2 + rnd() * .02;
      const k0 = 1 + Math.floor(rnd() * 3);
      const k1 = Math.min(RINGS.length - 1, k0 + 1 + Math.floor(rnd() * 3));
      const [x0, y0] = ell(RINGS[k1][0], RINGS[k1][1], ang);
      const [xm, ym] = ell(RINGS[k0][0], RINGS[k0][1], ang);
      const [x1, y1] = ell(RINGS[k0][0], RINGS[k0][1], ang + (rnd() - .5) * .16);
      fdots.push(`<path class="ftrace" d="M${x0.toFixed(1)} ${y0.toFixed(1)} L${xm.toFixed(1)} ${ym.toFixed(1)} L${x1.toFixed(1)} ${y1.toFixed(1)}" opacity="${(0.12 + rnd() * 0.3).toFixed(2)}"/>`);
    }

    // ② 環段：沿環的短弧，密集鋪滿
    RINGS.forEach(([rx, ry], ri) => {
      const segs = 26 - ri * 2;
      for (let i = 0; i < segs; i++) {
        const a0 = rnd() * Math.PI * 2, len = .06 + rnd() * .18;
        const pts = [];
        for (let t = 0; t <= len; t += .02) { const [x, y] = ell(rx, ry, a0 + t); pts.push(`${x.toFixed(1)} ${y.toFixed(1)}`); }
        fdots.push(`<polyline class="fseg ${rnd() > .78 ? 'warm' : ''}" points="${pts.join(' ')}" opacity="${(0.18 + rnd() * 0.45).toFixed(2)}"/>`);
      }
    });

    // ③ 節點：走線交會處的小方塊與圓點
    for (let i = 0; i < 150; i++) {
      const ang = rnd() * Math.PI * 2;
      const [rx, ry] = RINGS[Math.floor(rnd() * RINGS.length)];
      const [x, y] = ell(rx * (1 + (rnd() - .5) * .04), ry * (1 + (rnd() - .5) * .04), ang);
      const warm = rnd() > .74 ? 'warm' : '';
      if (rnd() > .6) fdots.push(`<rect class="fnode ${warm}" x="${(x - 1.6).toFixed(1)}" y="${(y - 1).toFixed(1)}" width="3.2" height="2" opacity="${(0.3 + rnd() * 0.55).toFixed(2)}"/>`);
      else fdots.push(`<circle class="fnode ${warm}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(0.6 + rnd() * 1).toFixed(2)}" opacity="${(0.3 + rnd() * 0.6).toFixed(2)}"/>`);
    }

    // ④ 資料流亮點：密度最高的一層
    RINGS.forEach(([rx, ry]) => {
      for (let i = 0; i < 90; i++) {
        const ang = rnd() * Math.PI * 2;
        const [x, y] = ell(rx * (1 + (rnd() - .5) * .03), ry * (1 + (rnd() - .5) * .03), ang);
        fdots.push(`<circle class="floor-dot ${rnd() > .8 ? 'warm' : ''}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(0.3 + rnd() * 0.7).toFixed(2)}" opacity="${(0.2 + rnd() * 0.6).toFixed(2)}"/>`);
      }
    });
    floorCache = `<g class="floor-dots">${fdots.join('')}</g>`;
  }
  parts.push(floorCache);

  const liveByProduct = {};
  const clouds = new Map();          // pid → { base, render(yaw) }，給 hover 擺動用
  active.filter((r) => !['completed', 'failed', 'stopped'].includes(r.phase)).forEach((r) => { liveByProduct[r.product] = r; });

  // ── 各產品基座 ──
  ids.forEach((pid, i) => {
    const slot = slots[i];
    const p = knowledge.products[pid];
    const col = PROD_VAR[pid] || 'var(--accent)';
    const cases = p.rings.cases.value, bugs = p.rings.bugs.value, health = p.rings.health.value;
    const hot = !!liveByProduct[pid];
    const blocked = !!(todos?.products?.[pid]?.blockers || []).length;
    const rx = DRUM_RX, ry = DRUM_RY, hh = DRUM_H;
    // ★ 3D 線框投影 ＋ 表面取樣點（點數＝該產品的真實知識量）
    const counts = {
      cases, bugs,
      spec: p.rings.spec?.value || 0,
      reports: p.rings.reports?.value || 0,
    };
    const cloud = productCloud(pid, counts);
    clouds.set(pid, cloud);
    const cloudMarkup = cloud.base + baseBloom();
    const bright = Math.min(340, counts.cases + counts.spec + counts.reports + counts.bugs);
    const tip = `${p.label}：${pointCloudCaption(counts, { ghost: Math.max(0, 60 - bright) })}・健康 ${health}${hot ? '・執行中' : ''}${blocked ? '・有 blocker' : ''}`;
    const ribs = [...Array(21)].map((_, k) => {
      const a = Math.PI * (0.03 + k * 0.047);
      const x = -Math.cos(a) * rx, y = Math.sin(a) * ry;
      return `<line class="drum-rib" x1="${x.toFixed(1)}" y1="${y.toFixed(1)}" x2="${x.toFixed(1)}" y2="${(y + hh).toFixed(1)}"/>`;
    }).join('');

    parts.push(`<g class="pedestal ${hot ? 'hot' : ''} ${blocked ? 'fault' : ''}" data-pid="${pid}" data-tip="${esc(tip)}" transform="translate(${slot.x.toFixed(1)} ${DRUM_Y}) scale(${slot.s.toFixed(3)})" style="color:${col}">
      <path class="holo-tube" d="M${(-rx * .84).toFixed(1)} 0 V-164 a${(rx * .84).toFixed(1)} 24 0 0 1 ${(rx * 1.68).toFixed(1)} 0 V0 Z" fill="url(#beam-${pid})"/>
      <ellipse class="holo-cap" cx="0" cy="-164" rx="${(rx * .84).toFixed(1)}" ry="22" stroke="${col}"/>
      <g class="projector" style="color:${col}" stroke="${col}" fill="${col}">${projector(rx, -172)}</g>
      <g class="glyph-wrap" style="color:${col}">${cloudMarkup}</g>
      <!-- 閒置動畫：投影每隔約 4 秒「重建」一次，一條亮線由下往上掃過字樣（CSS: .idle-scan）。
           三座**同步**（2026-08-20 使用者裁示「不用輪流」）。執行中的那座不播（見 hud.css）。 -->
      <rect class="idle-scan halo" x="${(-rx * .82).toFixed(0)}" y="-12" width="${(rx * 1.64).toFixed(0)}" height="15"/>
      <rect class="idle-scan" x="${(-rx * .74).toFixed(0)}" y="-6" width="${(rx * 1.48).toFixed(0)}" height="2.4"/>
      <!-- 寫實基座：上緣光環 → 三段金屬柱身（各有分模線）→ 底盤外沿 -->
      <path class="drum-body" d="M${-rx} 0 V${hh} a${rx} ${ry} 0 0 0 ${rx * 2} 0 V0 Z"/>
      ${ribs}
      <ellipse class="drum-seam" cx="0" cy="${(hh * .34).toFixed(0)}" rx="${rx}" ry="${ry}"/>
      <ellipse class="drum-seam" cx="0" cy="${(hh * .70).toFixed(0)}" rx="${rx}" ry="${ry}"/>
      <ellipse class="drum-bottom" cx="0" cy="${hh}" rx="${rx}" ry="${ry}"/>
      <!-- 底盤外沿（比柱身寬，做出台座感） -->
      <path class="drum-flange" d="M${(-rx * 1.14).toFixed(0)} ${hh + 4} a${(rx * 1.14).toFixed(0)} ${(ry * 1.1).toFixed(0)} 0 0 0 ${(rx * 2.28).toFixed(0)} 0 Z"/>
      <ellipse class="drum-flange-ring" cx="0" cy="${hh + 4}" rx="${(rx * 1.14).toFixed(0)}" ry="${(ry * 1.1).toFixed(0)}"/>
      <ellipse class="drum-top-fill" cx="0" cy="0" rx="${rx}" ry="${ry}"/>
      <ellipse class="drum-top" cx="0" cy="0" rx="${rx}" ry="${ry}" stroke="${col}"/>
      <ellipse class="drum-top inner" cx="0" cy="1" rx="${(rx * .8).toFixed(0)}" ry="${(ry * .8).toFixed(0)}" stroke="${col}"/>
      <ellipse class="drum-top inner2" cx="0" cy="2" rx="${(rx * .58).toFixed(0)}" ry="${(ry * .58).toFixed(0)}" stroke="${col}"/>
      ${hot ? `<ellipse class="scan-ring" cx="0" cy="0" rx="${rx}" ry="${ry}" stroke="${col}"/>` : ''}
      ${hot ? [...Array(5)].map((_, k) => `<circle class="beam-mote" cx="${(-rx * .46 + k * rx * .23).toFixed(0)}" cy="-6" r="2.2" style="--d:${(k * .62).toFixed(2)}s"/>`).join('') : ''}
      ${hot ? runTag(liveByProduct[pid]) : ''}
      <g class="fault-mark" transform="translate(${(rx - 20).toFixed(0)} ${(hh * .76).toFixed(0)})">
        <circle class="bg" cx="0" cy="-4" r="9"/><circle class="ring" cx="0" cy="-4" r="9"/>
        <path class="ex" d="M0 -9 v6 M0 0.5 v.5"/>
      </g>
      <!-- ⚠️ 柱面**不再刻產品名**（2026-08-20 使用者裁示）——
           上方的投影字樣就是這座基座的標籤，刻在柱面上等於同一件事說兩遍。
           產品名仍保留在 tooltip 與其他頁面。 -->
      <text class="p-num" y="${(hh * .76).toFixed(0)}">${cases}<tspan class="p-unit"> 案例</tspan></text>
      <text class="p-sub" y="${(hh * .99).toFixed(0)}">BUG ${bugs} · HP ${health}</text>
    </g>`);
  });

  // ── 中央：螺旋星系 ＋ 知識雷達軌道（最後畫＝疊在最前）──
  const gr = 104;
  const running = active.filter((r) => !['completed', 'failed', 'stopped'].includes(r.phase));
  const runArcs = running.map((r, i) => {
    const pct = Math.max(3, Math.min(100, r.progress?.percent ?? 5));
    const rr = gr * (2.42 + i * 0.14), ry = rr * 0.34;
    return `<polyline class="run-arc" data-run="${r.run_id}" data-rr="${rr.toFixed(1)}" data-ry="${ry.toFixed(1)}" data-tip="${esc(r.tool_name || '')}：${Math.round(pct)}%" points="${arcPoints(pct, rr, ry)}" stroke="${PROD_VAR[r.product] || 'var(--accent)'}"/>`;
  }).join('');
  const big = state === 'running' ? `執行中 ${running.length}` : state === 'fault' ? '異常' : state === 'warning' ? '注意' : '待命';
  parts.push(`<g class="galaxy state-${state}" transform="translate(${cx} ${FLOOR_Y})">
    <ellipse class="gx-hit" cx="0" cy="0" rx="${(gr * 1.4).toFixed(0)}" ry="${(gr * 1.4 * 0.34).toFixed(0)}" data-tip="測試宇宙：${esc(big)}・613 條案例・4 條產品線${clock ? `（${esc(clock)}）` : ''}"/>
    ${knowledgeOrbits(gr, knowledge.products, ids)}
    ${runArcs}
    ${galaxyMarkup(gr, rnd)}
  </g>`);

  const nebDefs = `
    <radialGradient id="neb-a"><stop offset="0%" stop-color="#1d59a8" stop-opacity=".34"/><stop offset="100%" stop-color="#1d59a8" stop-opacity="0"/></radialGradient>
    <radialGradient id="neb-b"><stop offset="0%" stop-color="#5b4fd8" stop-opacity=".28"/><stop offset="100%" stop-color="#5b4fd8" stop-opacity="0"/></radialGradient>
    <radialGradient id="gx-glow"><stop offset="0%" stop-color="#5fa4ff" stop-opacity=".22"/><stop offset="55%" stop-color="#3a6fd8" stop-opacity=".10"/><stop offset="100%" stop-color="#3a6fd8" stop-opacity="0"/></radialGradient>
    <radialGradient id="gx-disc"><stop offset="0%" stop-color="#9fc9ff" stop-opacity=".30"/><stop offset="60%" stop-color="#4f8fd8" stop-opacity=".12"/><stop offset="100%" stop-color="#4f8fd8" stop-opacity="0"/></radialGradient>
    <radialGradient id="gx-core"><stop offset="0%" stop-color="#ffffff" stop-opacity=".95"/><stop offset="45%" stop-color="#cfe9ff" stop-opacity=".55"/><stop offset="100%" stop-color="#7fbbf0" stop-opacity="0"/></radialGradient>
    <radialGradient id="neb-c"><stop offset="0%" stop-color="#0f6aa8" stop-opacity=".26"/><stop offset="100%" stop-color="#0f6aa8" stop-opacity="0"/></radialGradient>`;
  const defs = ids.map((pid) => {
    const col = PROD_VAR[pid] || 'var(--accent)';
    return `<linearGradient id="beam-${pid}" x1="0" y1="1" x2="0" y2="0"><stop offset="0%" stop-color="${col}" stop-opacity=".16"/><stop offset="100%" stop-color="${col}" stop-opacity="0"/></linearGradient>`;
  }).join('');

  container.innerHTML = `<div class="hero">
    <svg viewBox="0 214 1200 606" preserveAspectRatio="xMidYMid meet" role="img" aria-label="產品全息基座與系統球">
      <defs>${nebDefs}${defs}</defs>
      ${parts.join('')}
    </svg>
    <div class="hero-tip hidden"></div>
  </div>`;

  const heroRoot = container.firstElementChild;      // .hero —— 場景快取搬動的就是這個節點
  const svg = heroRoot.querySelector('svg');
  const tipEl = heroRoot.querySelector('.hero-tip');
  // tooltip 走 rAF 節流：主視覺節點多，每個 mousemove 都動 DOM 會讓游標拖行時明顯頓
  let tipRaf = 0, lastTip = null;
  svg.addEventListener('mousemove', (e) => {
    const t = e.target.closest('[data-tip]');
    const mx = e.clientX, my = e.clientY;
    if (tipRaf) return;
    tipRaf = requestAnimationFrame(() => {
      tipRaf = 0;
      if (!t) { tipEl.classList.add('hidden'); lastTip = null; return; }
      if (t.dataset.tip !== lastTip) {
        lastTip = t.dataset.tip;
        tipEl.innerHTML = String(t.dataset.tip).replace(/^([^：]+)：/, '<b>$1</b>：');
      }
      tipEl.classList.remove('hidden');
      // ⚠️ 用 heroRoot 而不是 container —— 場景被搬到新的 #hero 之後，
      //    閉包裡的 container 會指向已卸載的舊節點，tooltip 位置會整個偏掉。
      const rect = heroRoot.getBoundingClientRect();
      tipEl.style.transform = `translate(${Math.min(mx - rect.left + 14, rect.width - 270)}px, ${my - rect.top + 14}px)`;
    });
  });
  svg.addEventListener('mouseleave', () => tipEl.classList.add('hidden'));
  const peds = [...svg.querySelectorAll('.pedestal')];

  // ── hover 擺動 ────────────────────────────────────────────────────────
  // 游標停在某座基座上時，那一個全息體繞 Y 軸來回擺 ±20°，露出前後面的立體關係。
  // ⚠️ 擺動**以正對觀者為中心**、不是以靜止姿態為中心（見 models.js 的 swayYaw），否則左右轉幅不一致；
  // 移開後緩降回基準視角，並還原快取的靜態幀 —— 不留任何常駐運算。
  // 三道成本控制：① 一次只有一個產品在動 ② 每幀只改 34 個 transform ③「降低動態」下完全不啟動。
  // ⚠️ 用**逐屬性更新**，不要每幀重寫 innerHTML（實測 8.6ms/幀 → 3.2ms/幀）。
  //    2026-08-20 再進一步：知識點改為**依深度分層、整組共用 transform**，
  //    每幀寫入量從約 2,000 次 setAttribute 降到 34 次 —— 這才有本錢跑滿 60fps。
  //    先前為了壓成本鎖 30fps，擺動加快加大之後就看得出一格一格（使用者指出「卡卡的」）。
  const FRAME_MS = 0;    // 不節流：每個 rAF 都畫，交給瀏覽器的垂直同步決定節奏
  const wraps = new Map(peds.map((p) => [p.dataset.pid, p.querySelector('.glyph-wrap')]));
  const nodeCache = new Map();
  let swayPid = null, hoverPid = null;
  let amp = 0, phase = 0, prevTs = 0, lastPaint = 0;
  const reducedMotion = () => document.documentElement.dataset.motion === '0';

  function nodesOf(pid) {
    let n = nodeCache.get(pid);
    if (!n) {
      const w = wraps.get(pid);
      if (!w) return null;
      // 兩組節點的順序都與 bodyFrame() 回傳的陣列一致（由後而前），索引直接對得上
      n = { words: w.querySelectorAll('.m3-word'), layers: w.querySelectorAll('.pc-layer') };
      nodeCache.set(pid, n);
    }
    return n;
  }

  function paint(pid, yaw) {
    const c = clouds.get(pid), n = nodesOf(pid);
    if (!c || !n) return;
    const f = c.frame(yaw);
    if (!f) return;
    // 明暗、半徑、透明度都與視角無關（已烘在靜態字串裡），每幀只改 transform
    for (let i = 0; i < f.length; i++) {
      const m = f[i].m;
      if (n.words[i]) n.words[i].setAttribute('transform', m);
      if (n.layers[i]) n.layers[i].setAttribute('transform', m);
    }
  }

  function swayStep(ts) {
    swayRaf = 0;
    const dt = prevTs ? Math.min(100, ts - prevTs) : 16;
    prevTs = ts;
    const reduced = reducedMotion();
    const target = (!reduced && hoverPid && hoverPid === swayPid) ? 1 : 0;
    amp += (target - amp) * Math.min(1, dt / (target ? 300 : 220));   // 進場慢、收回快
    phase += dt / 4160 * Math.PI * 2;                                  // 4.16s 一個來回（2026-08-20 加快 25%）
    if (!target && amp < 0.01) {                                       // 收乾淨，換回靜態幀
      const done = swayPid, next = reduced ? null : hoverPid;
      swayPid = null; amp = 0; phase = 0; prevTs = 0; lastPaint = 0;
      paint(done, 0);
      if (next) startSway(next);
      return;
    }
    if (ts - lastPaint >= FRAME_MS) {
      lastPaint = ts;
      paint(swayPid, swayYaw(phase, amp));   // ⚠️ 不要 toFixed —— 那會把角度量化成 1 mrad 而抖
    }
    swayRaf = requestAnimationFrame(swayStep);
  }

  function startSway(pid) {
    if (swayPid || !clouds.has(pid) || reducedMotion()) return;
    swayPid = pid; amp = 0; phase = 0; prevTs = 0; lastPaint = 0;
    swayRaf = requestAnimationFrame(swayStep);
  }

  let hoverPed = null;
  svg.addEventListener('mouseover', (e) => {
    const ped = e.target.closest('.pedestal');
    if (ped === hoverPed) return;                 // 目標沒變就不要動 class（會觸發重繪）
    hoverPed = ped;
    peds.forEach((x) => x.classList.toggle('dim', !!ped && x !== ped));
    hoverPid = ped ? ped.dataset.pid : null;
    if (hoverPid) startSway(hoverPid);
  });
  svg.addEventListener('mouseout', (e) => {
    if (!e.relatedTarget || !svg.contains(e.relatedTarget)) {
      hoverPed = null; hoverPid = null;
      peds.forEach((x) => x.classList.remove('dim'));
    }
  });
  svg.addEventListener('click', (e) => {
    const ra = e.target.closest('.run-arc');
    if (ra) { location.hash = `#/run/${ra.dataset.run}`; return; }
    const ped = e.target.closest('.pedestal');
    if (ped) { const pid = ped.dataset.pid; onSector ? onSector(pid) : (location.hash = `#/product/${pid}`); }
  });

  // ── 場景註冊：讓換頁回來時可以整組搬回去（見檔頭 scene 說明）──────────
  function stopSway() {
    if (swayRaf) { cancelAnimationFrame(swayRaf); swayRaf = 0; }
    if (swayPid) paint(swayPid, 0);                  // 停在中途的話先還原成靜態幀
    swayPid = null; hoverPid = null; hoverPed = null;
    amp = 0; phase = 0; prevTs = 0; lastPaint = 0;
    peds.forEach((x) => x.classList.remove('dim'));
  }

  // 進度變動**不重建場景**，只改標籤與弧的幾個屬性。
  // 重建一次要 60ms，而一個 run 的進度每隔幾秒就更新一次 —— 那會變成週期性的卡頓。
  function updateRuns(list, sessions) {
    // ⭐ 任務 session 執行中 → 該產品的投影做動畫（2026-08-24 使用者要求）。
    //    ⚠️ **只切 class，不重建場景** —— 重建一次 60ms，而 session 的狀態每兩秒
    //       輪詢一次，重建會變成週期性卡頓（與進度弧同一條理由，見下方註解）。
    const busy = new Set((sessions || []).map((x) => x.product).filter(Boolean));
    svg.querySelectorAll('.pedestal').forEach((g) => {
      g.classList.toggle('sess', busy.has(g.dataset.pid));
    });
    const live = (list || []).filter((r) => !['completed', 'failed', 'stopped'].includes(r.phase));
    const byProd = {}; live.forEach((r) => { byProd[r.product] = r; });
    svg.querySelectorAll('.run-tag').forEach((g) => {
      const r = byProd[g.dataset.pid]; if (!r) return;
      const pct = Math.max(0, Math.min(100, r.progress?.percent ?? 0));
      g.querySelector('.rt-fill')?.setAttribute('width', (RT_BAR * pct / 100).toFixed(1));
      const t = g.querySelector('.rt-pct'); if (t) t.textContent = `${Math.round(pct)}%`;
      const ph = g.querySelector('.rt-phase');
      if (ph) ph.textContent = `執行中${r.tool_phase_label ? ' · ' + r.tool_phase_label : ''}`;
    });
    svg.querySelectorAll('.run-arc').forEach((pl) => {
      const r = live.find((x) => x.run_id === pl.dataset.run); if (!r) return;
      const pct = Math.max(3, Math.min(100, r.progress?.percent ?? 5));
      pl.setAttribute('points', arcPoints(pct, +pl.dataset.rr, +pl.dataset.ry));
      pl.dataset.tip = `${r.tool_name || ''}：${Math.round(pct)}%`;
    });
  }
  scene = { sig: opts.sig || null, root: heroRoot, stopSway, updateRuns };

  // ⚠️ 字樣的形狀是用離屏 canvas 量出來的（見 models.js）。首屏時自帶字型可能還沒載完，
  //    量到的會是 fallback 字的寬度與筆畫 —— 字寬、點陣都會偏掉，而且會被快取下來。
  //    故：偵測到字型尚未可用時掛一次性鉤子，載完後清掉形狀與模型快取重畫。
  if (!fontHooked && document.fonts && !fontsUsable()) {
    fontHooked = true;
    document.fonts.ready.then(() => {
      resetShapes(); modelCache.clear();
      if (lastDraw && lastDraw[0].isConnected) renderHero(...lastDraw);
    });
  }
}

/** 進度更新：只改既有節點的幾個屬性，不重建場景。場景不存在時是 no-op。 */
export function updateHeroRuns(active, sessions) { scene?.updateRuns(active, sessions); }
