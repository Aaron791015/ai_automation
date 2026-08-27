// ★ 主視覺的透視投影小工具
//
// 沿革（2026-08-19 ～ 08-20）：
//   這個檔原本是一套**低多邊形 3D 引擎**（uvSphere／tube／ringBand／merge／面排序／
//   法線明暗／表面取樣），供主視覺的三個立體物件用 —— 搖球機、渾天儀、聊天室。
//   2026-08-20 使用者裁示改為**投影專案文字**（見 models.js），物件整組退場，
//   那些幾何產生器與面繪製也就沒人呼叫了，故一併移除，只留下字樣仍在用的三支。
//   要找舊引擎請看 git 歷史（`19ce86a` 之前的版本）。
//
// 座標採 SVG 慣例：y 越小越上面。

/**
 * 以 Y 軸、X 軸旋轉後做透視投影。
 * 回傳 [X, Y, Z]，其中 **Z 越大越遠**（p = dist/(dist+Z)，Z 為負代表比原點更靠近鏡頭）。
 * ⚠️ Z 的正負是判斷「哪一面在前」的唯一依據 —— models.js 的擠出方向曾因為看錯這個符號
 *    而把最遠的一面當成正面（見 models.js 的 layerZ 說明）。
 */
export function makeProjector({ ry = 0.55, rx = 0.34, dist = 900, scale = 1 } = {}) {
  const cy = Math.cos(ry), sy = Math.sin(ry);
  const cx = Math.cos(rx), sx = Math.sin(rx);
  return ([x, y, z]) => {
    const X = x * cy + z * sy;
    const Z1 = -x * sy + z * cy;
    const Y = y * cx - Z1 * sx;
    const Z = y * sx + Z1 * cx;
    const p = dist / (dist + Z);
    return [X * p * scale, Y * p * scale, Z];
  };
}

/**
 * 四邊形面板：以中心、寬高定義，法線朝 +z，再套 yaw／pitch。
 * 頂點順序為 左上 → 右上 → 右下 → 左下（models.js 的 quadMatrix 依賴這個順序）。
 */
export function panel(c, w, h, yaw = 0, pitch = 0) {
  const cy2 = Math.cos(yaw), sy2 = Math.sin(yaw);
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  const local = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]];
  const verts = local.map(([x, y]) => {
    const y2 = y * cp, z2 = y * sp;
    return [c[0] + x * cy2 + z2 * sy2, c[1] + y2, c[2] - x * sy2 + z2 * cy2];
  });
  return { verts, faces: [[0, 1, 2, 3]] };
}

/**
 * 投影一個 3D 點，回傳含深度與近大遠小係數 k。
 * ⚠️ **不做捨入**：這個結果會拿去算仿射矩陣，捨到 0.1 單位（約 0.15 螢幕像素）
 *    會讓整組字樣在轉動時一跳一跳 —— 剛體移動下，捨入誤差是全體同步的，
 *    不會互相抵銷成模糊，而是看得見的抖動（2026-08-20 使用者指出「微微抖動」）。
 *    要縮短輸出字串請在最終組字串時才捨入，不要在幾何中途。
 */
export function projectPoint(p, project) {
  const [x, y, z] = project(p);
  return { x, y, z, k: 900 / (900 + z) };
}
