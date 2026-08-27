// 30 行 observable：state / set(patch) / subscribe(fn)。
const listeners = new Set();
export const state = {
  boot: null, tools: [], products: [],
  active: [], serverTime: null, health: null,
  // 任務 session 的執行狀態（2026-08-24）——「在跑的」與「有產出等你看的」
  sessionRunning: [], sessionReview: [],
  selection: new Set(),        // 案例瀏覽器勾選（nodeid）
  motion: localStorage.getItem('tp.motion') !== '0',
  session: localStorage.getItem('tp.session') || null,
};
export function set(patch) {
  Object.assign(state, patch);
  listeners.forEach((fn) => { try { fn(state, patch); } catch (e) { console.error(e); } });
}
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
/** 產品查找 —— **三種寫法都要認得**（2026-08-24）。
 *
 * ⚠️ 平台裡有兩份 id 空間（`core/registry.py` 的合併註解記過）：
 *   · slug（`crux`／`qixing`）—— `#/product/<id>` 網址、tool.json 的鍵
 *   · 權威 id（`CRUX`／`七星`）—— Bug 前綴、`lint_docs --product`、目錄名
 *
 * 而**連結不一定由平台自己產生**：命令的 `next` 會把「這次填的欄位值」
 * 帶進網址，而那些欄位填的往往是**權威 id**（`lint_product` 就是）。
 * 只認 slug 的話，那種連結一律落在「未知產品」——
 * 2026-08-24 走查當場踩到：`#/product/七星` 打不開。
 *
 * ⭐ 順手 `decodeURIComponent` —— 中文 id 過網址一定是編碼過的。
 */
export const productOf = (id) => {
  if (!id) return undefined;
  let want = String(id);
  try { want = decodeURIComponent(want); } catch (e) { /* 已經是明文 */ }
  const lower = want.toLowerCase();
  return state.products.find((p) => p.id === want)
      || state.products.find((p) => [p.id, p.product_id, p.label, p.short, p.wordmark]
           .some((c) => c && String(c).toLowerCase() === lower));
};
export const toolOf = (id) => state.tools.find((t) => t.id === id);
export function toggleMotion() {
  const m = !state.motion;
  localStorage.setItem('tp.motion', m ? '1' : '0');
  document.documentElement.dataset.motion = m ? '1' : '0';
  set({ motion: m });
}
export function setSession(id) { if (id) localStorage.setItem('tp.session', id); else localStorage.removeItem('tp.session'); set({ session: id }); }

// ── 選取案例 → 產品集合（表單的虛擬欄位 _products）─────────────────────────
// 為什麼放這裡而不是各頁自己維護：使用者可能**沒有經過案例瀏覽器**就直接進 #/tool/ui_tests
// （從工具頁點進、載入 profile、或貼網址），那時 __tp_selection 有值但集合沒建 ——
// 環境欄位就會全部消失。所以對照表由「載到案例索引的頁面」填，集合則隨時可重算。
let caseProduct = null;
export function setCaseProductMap(flat) {
  caseProduct = new Map((flat || []).map((c) => [c.nodeid, c.product]));
  return syncSelectionProducts();
}
export function hasCaseProductMap() { return !!caseProduct; }
export function syncSelectionProducts(explicit = null) {
  const out = new Set(explicit || []);
  if (!explicit && caseProduct) {
    for (const n of window.__tp_selection || []) { const p = caseProduct.get(n); if (p) out.add(p); }
  }
  window.__tp_selection_products = out;
  return out;
}


// ⛔ 危險等級要取**工具與它每一個命令**的最高值。
//    只看工具層的話，`setup` 會標成「本機唯讀」，而它底下有「匯出範本」
//    （會 rmtree 目標目錄）、「清空原型產品」、「歸檔」。
//    **騙人的安全感比沒有標籤更糟**（2026-08-23 UI 走查，三個畫面都犯同一個錯）。
const _DANGER_RANK = { low: 0, medium: 1, high: 2 };
export function worstDanger(tool) {
  let lv = tool?.danger?.level || 'low';
  for (const c of tool?.commands || []) {
    const c2 = c.danger?.level || 'low';
    if (_DANGER_RANK[c2] > _DANGER_RANK[lv]) lv = c2;
  }
  return lv;
}
