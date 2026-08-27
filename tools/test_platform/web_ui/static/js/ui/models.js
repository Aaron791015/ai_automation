// ★ 三個產品的主視覺全息投影 —— **立體擠出的字樣**（wordmark）
//
// 題材沿革（都是使用者裁示）：
//   2026-08-19  手繪 2D 剪影 → 真 3D 低多邊形物件（搖球機／渾天儀／聊天室）
//   2026-08-20  改為**投影專案文字**：CRUX ／ Seven ／ ChatBot
//               同時**移除基座柱面的產品名** —— 投影文字本身就是標籤，否則同一件事說兩遍。
//               ⚠️ 只有投影文字用這三個字串，**系統內部命名不動**
//               （registry 仍是 crux／qixing／wbot，UI 其餘地方仍顯示中文名）。
//
// 為什麼字樣能解掉「不夠寫實」：字沒有「像不像實物」的問題 —— 字形就是它自己，
// 只要透視、厚度、明暗對，它就是對的。
//
// 作法：字樣是一片**立在 3D 空間裡的面板**，沿面板法線方向排 N 層，由後而前畫，
//   後層暗、前層亮 → 讀起來就是有厚度的擠出字。每一層用 affine matrix 把
//   「字樣自身的座標系」貼到該層投影後的四邊形上，所以字**跟著全域視角與擺動一起轉**。
//   ⚠️ 透視投影後的矩形嚴格說是一般四邊形、不是仿射像；這裡用三個角算 affine 近似，
//      在本場景的小角度下誤差看不出來，換來的是可以直接用瀏覽器的字型排版。
//
// 座標：y 越小越上面（SVG 慣例），原點在基座頂面中心。

import { state } from '../store.js';

import { panel, makeProjector, projectPoint } from './model3d.js';

// 基準的 3/4 視角。日常靜態呈現一律用它，投影結果整份快取。
const VIEW = { ry: 0.62, rx: 0.30, dist: 900, scale: 1 };
const project = makeProjector(VIEW);

/**
 * ★ 擺動幅度（弧度）：hover 該產品時繞 Y 軸來回擺 ±SWAY。
 *
 * 為什麼是「擺動」而不是「整圈旋轉」：字樣轉到 90° 會變成一條線、整個看不見，
 * 那是壞掉不是效果。
 * 2026-08-20 使用者要求「幅度加大且加快 25%」→ 0.28 → 0.35 rad（±20°）；
 * 週期同步由 5.2s 縮到 4.16s（見 hero.js 的 swayStep）。
 * ⚠️ 再往上加要注意：基準斜角是 -0.28，幅度 0.35 時會擺過 0（正對觀者、厚度暫時消失），
 *    那是自然的轉動；但若幅度大到讓斜角接近 ±90°，字會壓成一條線。
 */
export const SWAY = 0.35;

/**
 * 取得某擺動角度的投影器。
 * ⚠️ **刻意不快取**：先前以「毫弧度」為鍵做快取，等於把角度量化到 1 mrad ——
 *    擺動轉折處角速度趨近 0，連續好幾幀會落在同一格而完全不動，再跳一下，
 *    看起來就是抖（2026-08-20 使用者指出）。makeProjector 只是 4 次三角函數，
 *    一幀算一次的成本可以忽略，不值得為它引入量化。
 */
function projectorFor(yaw) {
  return yaw ? makeProjector({ ...VIEW, ry: VIEW.ry + yaw }) : project;
}

// ── 字樣定義 ──────────────────────────────────────────────────────────
// ⚠️ 只有投影文字用這些字串；系統其餘地方一律沿用 registry 的 id 與中文名。
// ★ 字樣本身宣告在 registry/products.json 的 `wordmark` —— 接新產品時不必改這支檔。
//   下面的 fallback 只在 registry 尚未載入（模組先於 /api/bootstrap 被 import）時作用。
const WORDMARK_FALLBACK = { crux: 'CRUX', qixing: 'Seven', wbot: 'ChatBot', common: '共通' };
const WORDMARK = new Proxy({}, {
  get: (_t, pid) => (state.products || []).find((p) => p.id === pid)?.wordmark || WORDMARK_FALLBACK[pid],
  has: (_t, pid) => Boolean((state.products || []).find((p) => p.id === pid)?.wordmark || WORDMARK_FALLBACK[pid]),
});

const CY = -86;           // 字樣中心高度（基座頂面為 0）—— 太高會讓光錐下半空一大段、整體重心偏上
const MAX_W = 156;        // 字樣最大寬度：基座間距最窄約 288×scale，超過會撞在一起
const MAX_FS = 48;        // 字級上限：短字（CRUX）不要被撐到誇張
const BASE_FS = 100;      // 量測用的基準字級
const DEPTH = 36;         // 擠出厚度（薄了會看不出是立體的，只像有陰影的平面字）
const LAYERS = 12;        // 擠出的層數：層少會看到一片片殘影（＝糊、不寫實），層多才連成實心的側面
                          // 2026-08-20 由 17 降為 12 以減少光柵化成本；單層透明度同步上調補回實心感
// 面板自身的 yaw。字樣的**視角斜角 ＝ VIEW.ry + FACE_YAW**，
// 斜角的絕對值決定看得到多少厚度（16° 讀得清楚又有體積），正負號決定臉朝左還朝右。
//
// ⚠️ **朝向是由「厚度往哪邊退」決定的，不是只看這個角度的正負** ——
//    正面的外法線指向 -sin(斜角)，斜角 +0.28 → 法線朝左 ＝ **臉朝左**，厚度往右上退。
//    2026-08-20 曾誤改為 -0.90（斜角 -0.28）以為那才是朝左，其實那是建立在
//    「擠出層序反了」的錯誤深度上（見 layerZ 的說明）；層序修正後就露餡變回朝右。
//    兩者是連動的，日後只要動了 layerZ 的正負，這裡也要跟著重新判斷。
const FACE_YAW = -0.34;      // 斜角 0.62-0.34 = +0.28 rad（≈16°）＝ 臉朝左
/**
 * ★ 面板俯仰（負值＝臉朝下）。
 * 面板原本是完全垂直（pitch = 0），配上由上往下的視角，字的臉是朝上的
 * —— 讀起來像從下往上打的光（2026-08-20 使用者指出「向上翹」）。
 * 給一點負俯仰讓上緣往後、下緣往前，臉就微微朝下，才像從上方投下來。
 */
const FACE_PITCH = -0.20;      // ≈-11.5°
/** 靜止姿態的視角斜角（臉朝左 16°）—— 擺動要用它把中心搬到正面，見 swayYaw */
const REST_ANGLE = VIEW.ry + FACE_YAW;

/**
 * ★ 擺動時要餵給投影器的 yaw 偏移量。
 *
 * ⚠️ 擺動**以「正對觀者」為中心**，不是以靜止姿態為中心。
 *    靜止姿態是臉朝左 16°；若以它為中心擺 ±20°，有效角度會落在 -4°～+36° ——
 *    往一邊會轉過正面（cos 在 0 附近很平，形狀幾乎不變、厚度趨近消失），
 *    往另一邊卻愈轉愈側（厚度大幅拉開），看起來就是「一邊轉得多、一邊轉得少」
 *    （2026-08-20 使用者指出）。以正面為中心後範圍是對稱的 -20°～+20°，
 *    厚度會對稱地往左右擺過去，才讀得出是左右轉動。
 *
 * amp 由 0→1 的過程中，中心會從靜止姿態平滑移到正面，所以**靜止外觀不變**。
 */
export function swayYaw(phase, amp) {
  return amp * (SWAY * Math.sin(phase) - REST_ANGLE);
}

/**
 * ★ 基線傾角（弧度，正值＝往右下）。
 *
 * 為什麼需要這個修正：字樣是一片**垂直的面板**，只繞 Y 軸轉；而全域視角是**從上往下看**
 * （VIEW.rx = 0.30）。兩件事一疊加，面板的水平邊在螢幕上就會斜掉，
 * 且斜的方向跟著 yaw 的正負走：面向右時往右下斜，面向左時**往右上斜**。
 * 2026-08-20 改成面向左之後就變成向上翹，讀起來像從下往上打的光（使用者指出）。
 *
 * ⚠️ 不能靠調 FACE_YAW 解決：讓基線水平的 FACE_YAW 剛好是 -VIEW.ry，
 *    那正是「正對觀者」的角度，厚度會完全消失。傾角與朝向在幾何上是綁死的。
 * 解法：投影後在**螢幕平面上把整組轉正**（等同把物件沿視線軸滾一個角度），
 *    朝向與厚度都保留，只把基線擺平。字樣本體與知識點必須用同一組旋轉，否則會分家。
 */
const TILT = 0.03;        // ≈1.7°，水平再微微向下 —— 讀起來就是從上方投下來的

const FONT_STACK = '"Sora", "Inter", "Noto Sans TC", "Microsoft JhengHei", system-ui, sans-serif';

// ⚠️ 有字樣 ≠ 有基座：共通有字樣（小徽章要用），但**刻意不給它基座**
//    —— 它貫穿所有產品，改以星塵呈現（ui/hero.js）。由 registry 的 hero_pillar 決定。
export function modelOf(pid) {
  const p = (state.products || []).find((x) => x.id === pid);
  if (p && p.hero_pillar === false) return null;
  if (!p && pid === 'common') return null;
  return WORDMARK[pid] || null;
}

/**
 * 小徽章用的字樣與長寬比（#/tools 欄首、產品頁頁首）。
 * 2026-08-20 使用者裁示「小圖示改為一致使用文字」——理由是各產品顏色不同，
 * 顏色本來就足以快速分辨，字只要與主視覺一致即可。
 * 共通沒有主視覺投影，這裡仍給它一個字樣，否則它的欄首會沒有圖示。
 */
export function wordmarkOf(pid) { return WORDMARK[pid] || null; }

/** 徽章的字樣尺寸（以真實字型量測，避免各產品寬度比例失真） */
export function badgeMetrics(pid) {
  const text = wordmarkOf(pid);
  if (!text) return null;
  const g = ctx2d();
  g.font = `600 ${BASE_FS}px ${FONT_STACK}`;
  const w = (g.measureText(text).width || BASE_FS * text.length * 0.6) / BASE_FS;   // 相對字級的寬度倍率
  return { text, ratio: w };
}

// ── 字形量測與點陣取樣（離屏 canvas）────────────────────────────────
// 亮點要**長在字裡面**，所以必須知道「哪些位置是字」。用離屏 canvas 把字畫一次、
// 讀 alpha 通道，就得到字形的填滿區域；之後只是從中抽樣。
//
// ⚠️ 字型還沒載完時量到的是 fallback 字的形狀 —— 故 fontsReady() 供上層在
//    document.fonts.ready 後清快取重畫（見 hero.js）。

let _ctx = null;
function ctx2d() {
  if (!_ctx) {
    const c = document.createElement('canvas');
    c.width = 512; c.height = 160;
    _ctx = c.getContext('2d', { willReadFrequently: true });
  }
  return _ctx;
}

export function fontsUsable() {
  try { return document.fonts && document.fonts.check(`600 ${BASE_FS}px "Sora"`); } catch { return false; }
}

const shapeCache = new Map();

/**
 * 字樣的幾何與填滿點：
 *   { text, fs, w, h, fill: [[u,v], …] }   u/v 為 0–1 的字樣內相對座標
 */
function wordShape(pid) {
  let s = shapeCache.get(pid);
  if (s) return s;
  const text = WORDMARK[pid];
  if (!text) return null;

  const g = ctx2d();
  g.font = `600 ${BASE_FS}px ${FONT_STACK}`;
  const measured = g.measureText(text).width || BASE_FS * text.length * 0.6;
  const fs = Math.min(MAX_FS, MAX_W / (measured / BASE_FS));   // 先照最大寬度算，再套字級上限
  const w = (measured / BASE_FS) * fs;
  const h = fs * 1.02;                                          // 大寫高＋少量餘裕

  // 以較高解析度描一次字，取出填滿的像素當抽樣池
  const SS = 3;                                                 // 超取樣倍率
  const cw = Math.max(8, Math.ceil(w * SS)), ch = Math.max(8, Math.ceil(h * SS));
  const c = g.canvas;
  if (c.width < cw || c.height < ch) { c.width = cw; c.height = ch; }
  g.clearRect(0, 0, c.width, c.height);
  g.font = `600 ${fs * SS}px ${FONT_STACK}`;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillStyle = '#fff';
  g.fillText(text, cw / 2, ch / 2);

  const data = g.getImageData(0, 0, cw, ch).data;
  const fill = [];
  const step = 2;                                               // 每 2px 取一格就夠密
  for (let y = 0; y < ch; y += step) {
    for (let x = 0; x < cw; x += step) {
      if (data[(y * cw + x) * 4 + 3] > 128) fill.push([x / cw, y / ch]);
    }
  }
  s = { text, fs, w, h, fill };
  shapeCache.set(pid, s);
  return s;
}

/** 字型載入後呼叫：丟掉以 fallback 字量到的形狀 */
export function resetShapes() { shapeCache.clear(); }

// ── 幾何：把字樣座標 (u,v,層深) 換算成模型空間 3D ────────────────────

/**
 * 第 i 層的深度（i = 0 是**最靠近鏡頭**的那一面）。
 * ⚠️ 這裡必須是**正值**。投影器的 Z 越大越遠（p = dist/(dist+Z)），
 *    而 FACE_YAW 之下沿面板法線推正 z 才會讓層往鏡頭外走。
 *    先前寫成負值 → 「前緣」其實是最遠的一面、暗的厚度堆疊全擋在它前面，
 *    深度線索整個相反（2026-08-20 查出）。
 */
const layerZ = (i) => (i / (LAYERS - 1)) * DEPTH;

/** 字樣內相對座標 → 模型空間 3D（含面板自身的 yaw／pitch，與 panel() 同一套算式） */
function wordPoint(shape, u, v, z) {
  const x0 = (u - 0.5) * shape.w, y0 = (v - 0.5) * shape.h;
  const cy2 = Math.cos(FACE_YAW), sy2 = Math.sin(FACE_YAW);
  const cp = Math.cos(FACE_PITCH), sp = Math.sin(FACE_PITCH);
  const off = y0 * sp + z;                       // 俯仰造成的深度 ＋ 擠出深度
  return [x0 * cy2 + off * sy2, CY + y0 * cp, -x0 * sy2 + off * cy2];
}

/**
 * 螢幕平面的轉正參數（見 TILT 的說明）。只跟 yaw 有關、與是哪個產品無關
 * —— 旋轉中心固定取模型原點 (0, CY, 0) 的投影，各層與知識點才會用同一組旋轉。
 */
function rollFor(yaw) {                                  // 同樣不快取，理由見 projectorFor
  const project = projectorFor(yaw);
  const c = project([0, CY, 0]);
  const cy2 = Math.cos(FACE_YAW), sy2 = Math.sin(FACE_YAW);
  const p1 = project([100 * cy2, CY, -100 * sy2]);      // 字樣的 u 軸（往右）
  const r = TILT - Math.atan2(p1[1] - c[1], p1[0] - c[0]);
  return { cx: c[0], cy: c[1], cs: Math.cos(r), sn: Math.sin(r) };
}
function applyRoll(x, y, R) {
  const dx = x - R.cx, dy = y - R.cy;
  return [R.cx + dx * R.cs - dy * R.sn, R.cy + dx * R.sn + dy * R.cs];
}

/** 某一層的四角（模型空間）→ 投影並轉正後的四點 */
function layerQuad(shape, z, project, R) {
  const cy2 = Math.cos(FACE_YAW), sy2 = Math.sin(FACE_YAW);
  return panel([0, CY, 0], shape.w, shape.h, FACE_YAW, FACE_PITCH).verts
    .map(([x, y, zz]) => {
      // panel 建在 z=0 的平面上，往法線方向推 z
      const p = projectPoint([x + z * sy2, y, zz + z * cy2], project);
      const [rx, ry] = applyRoll(p.x, p.y, R);
      return { x: rx, y: ry, z: p.z, k: p.k };
    });
}

/**
 * 由投影後的四角算 affine matrix：把「字樣自身座標系（0..w, 0..h）」貼到該四邊形上。
 * q[0]=左上 q[1]=右上 q[2]=右下 q[3]=左下（panel 的頂點順序）。
 */
function quadMatrix(q, w, h) {
  const a = (q[1].x - q[0].x) / w, b = (q[1].y - q[0].y) / w;
  const c = (q[3].x - q[0].x) / h, d = (q[3].y - q[0].y) / h;
  // 精度刻意給足：位移捨到 0.1 單位（≈0.15 螢幕像素）就會看得見整組跳動
  return `matrix(${a.toFixed(6)} ${b.toFixed(6)} ${c.toFixed(6)} ${d.toFixed(6)} ${q[0].x.toFixed(3)} ${q[0].y.toFixed(3)})`;
}

// ── 對外：字樣本體 ────────────────────────────────────────────────────

/** 各層的 transform 與明暗（擺動時每幀只需改 transform） */
export function bodyFrame(pid, yaw = 0) {
  const shape = wordShape(pid);
  if (!shape) return [];
  const project = projectorFor(yaw), R = rollFor(yaw);
  const out = [];
  for (let i = LAYERS - 1; i >= 0; i--) {          // 由後而前
    const q = layerQuad(shape, layerZ(i), project, R);
    out.push({ m: quadMatrix(q, shape.w, shape.h), front: i === 0, i });
  }
  return out;
}

/** 字樣的 SVG（由後而前的 N 層文字） */
export function renderProduct(pid, yaw = 0) {
  const shape = wordShape(pid);
  if (!shape) return '';
  const frame = bodyFrame(pid, yaw);
  return frame.map((f) => {
    const t = 1 - f.i / (LAYERS - 1);              // 0（最後）→ 1（最前）
    const rear = f.i === LAYERS - 1;
    const cls = 'm3-word' + (f.front ? ' front' : rear ? ' rear' : '');
    // 厚度層要夠淡，否則會蓋掉裡面的知識點；層數加倍後單層還要再減半
    const op = f.front ? 1 : rear ? 0.5 : (0.035 + t * 0.12).toFixed(3);   // 層數減少 → 單層加濃，整體厚度感不變
    const txt = (extra) => `<text${extra} x="${(shape.w / 2).toFixed(1)}" y="${(shape.h / 2).toFixed(1)}"`
      + ` font-size="${shape.fs.toFixed(1)}" text-anchor="middle" dominant-baseline="central">${shape.text}</text>`;
    // 前緣多描一層寬而淡的邊當光暈 —— 用幾何而非 filter，見 CSS 的說明
    return `<g class="${cls}" transform="${f.m}" opacity="${op}">`
      + (f.front ? txt(' class="halo"') : '') + txt('') + `</g>`;
  }).join('');
}

// ── 對外：表面取樣點（點數＝知識量）──────────────────────────────────

export { LAYERS };

/**
 * ★ 在字形填滿區域內取樣 n 個點，回傳**字樣自身座標系**的位置＋所屬深度層。
 *
 * 為什麼不回傳投影後的座標（2026-08-20 為了擺動的流暢度改寫）：
 *   同一個深度層的所有點吃**同一個仿射矩陣**，所以只要把它們裝進同一個 `<g>`，
 *   每幀改一次群組的 transform 就好 —— 不必逐點搬 cx/cy/r/opacity。
 *   實測差距：原本每幀約 2,000 次 setAttribute（只能跑 30fps、看得出一格一格），
 *   改成分層後每幀 34 次，可以放到 60fps 跑滿。
 *   代價是點的深度被量化到 17 階（層距 ~2.1 單位），肉眼看不出來。
 */
export function sampleDots(pid, n, rnd) {
  const shape = wordShape(pid);
  if (!shape || !n || !shape.fill.length) return [];
  const out = [];
  for (let i = 0; i < n; i++) {
    const [u, v] = shape.fill[Math.floor(rnd() * shape.fill.length) % shape.fill.length];
    // 大部分點貼在最前面那一面（看得到），少部分埋進厚度裡製造景深
    const t = rnd() < 0.62 ? rnd() * 0.25 : rnd();
    out.push({ lx: u * shape.w, ly: v * shape.h, layer: Math.min(LAYERS - 1, Math.round(t * (LAYERS - 1))) });
  }
  return out;
}

/** 各層的深度係數（近大遠小），供烘焙點的半徑與透明度用 —— 以基準視角算一次 */
const layerKCache = new Map();
export function layerK(pid, i) {
  let arr = layerKCache.get(pid);
  if (!arr) {
    const shape = wordShape(pid);
    const cy2 = Math.cos(FACE_YAW), sy2 = Math.sin(FACE_YAW);
    arr = [];
    for (let j = 0; j < LAYERS; j++) {
      const z = layerZ(j);
      arr.push(projectPoint([z * sy2, CY, z * cy2], project).k);
    }
    layerKCache.set(pid, arr);
  }
  return arr[i];
}
