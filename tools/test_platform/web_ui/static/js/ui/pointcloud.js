// ★ 全息投影的共用小工具（底部 bloom 與點陣組成說明）
//
// 沿革（2026-08-19）：這個檔原本是「2D 剪影 path → 輪廓取樣 ＋ isPointInFill 灑內部點」的
// 點陣引擎。後來使用者要求物件要真的寫實，改為 **真 3D 低多邊形模型 ＋ 表面取樣**
// （見 ui/model3d.js 與 ui/models.js），2D 那套整個被取代，故僅保留仍在用的兩個函式。
//
// 點數規則仍然成立，只是取樣的載體換成 3D 表面（實作在 hero.js 的 productCloud）：
//    亮點數 = min(340, 案例 + 規格檔 + 驗證紀錄 + 活躍 Bug)
//    暗點數 = max(0, 60 - 亮點數)   ← 補到最低密度，明顯較暗，代表「尚未取樣」
//    亮點依種類分亮度，活躍 Bug 畫成紅點 —— 有問題的產品線一眼看得出來。

/** 物件底部與基座交界的 bloom（參考圖每個物件底下都有一團光） */
export function baseBloom() {
  return `<ellipse class="pc-bloom" cx="0" cy="-4" rx="34" ry="9"/><circle class="pc-bloom core" cx="0" cy="-6" r="5"/>`;
}

/** 給 tooltip 用的組成說明 */
export function pointCloudCaption(counts, meta) {
  const bits = [];
  if (counts.cases) bits.push(`案例 ${counts.cases}`);
  if (counts.spec) bits.push(`規格 ${counts.spec}`);
  if (counts.reports) bits.push(`紀錄 ${counts.reports}`);
  if (counts.bugs) bits.push(`Bug ${counts.bugs}`);
  const base = bits.length ? bits.join('・') : '尚無資料';
  return meta.ghost ? `${base}（另補 ${meta.ghost} 個暗點表示尚未取樣）` : base;
}
