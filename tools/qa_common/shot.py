# -*- coding: utf-8 -*-
"""Bug 截圖標注：在畫面上加紅框、編號徽章與說明條，再擷取。

用途：只有畫面的截圖，讀者得自己找問題在哪；標注後**一眼就知道錯在哪、錯在哪個數字**。
      （規範見 `bug-report` skill「截圖規範」節。）

使用方式（pytest / Playwright Python）：
    from qa_common.shot import capture_annotated

    capture_annotated(
        page, "reports/shots/CRUX-050_01_大類卡最大損失錯值.png",
        marks=[
            {"selector": ".card[data-number='123'] [title='最大损失']",
             "label": "實際 +550.24，應為 −129.76"},
            {"selector": ".card[data-number='123'] [title='总吃货-总出货']",
             "label": "貨量 ¥20 正確，可對照"},
        ],
        note="CRUX-050 虛盤组六多码大類卡：最大損失取到 K=700 而非涵蓋實貨")

使用方式（Playwright MCP）：把 `ANNOTATE_JS` 的內容用 `browser_evaluate` 注入，
    再 `browser_take_screenshot`，最後用 `CLEAR_JS` 清除。見 `browser-ops` skill。

前置條件：Playwright（已在 requirements.txt）。不需要 Pillow —— 標注在瀏覽器內完成。

⚠️ 標注是**疊加在頁面上的 DOM**，截圖後務必清除，否則後續操作與截圖都會帶著紅框。
   `capture_annotated()` 已自動清除；手動注入時記得呼叫 `CLEAR_JS`。
"""
import os

_MARK_ATTR = "data-qa-annotation"

# 同一份 JS 同時供 pytest 與 MCP 使用，避免兩邊行為漂移。
# 參數 marks: [{selector, label}]；note: 整張圖的說明條（可省略）
ANNOTATE_JS = r"""
async (payload) => {
  const {marks = [], note = ''} = payload || {};
  const ATTR = 'data-qa-annotation';
  document.querySelectorAll('[' + ATTR + ']').forEach(n => n.remove());

  const px = v => v + 'px';
  const raf = () => new Promise(r => requestAnimationFrame(() => r()));
  const mk = (tag, css) => {
    const el = document.createElement(tag);
    el.setAttribute(ATTR, '1');
    Object.assign(el.style, css);
    return el;
  };

  // ⚠️ 說明文字**絕不浮在畫面上** —— 早期版本把標籤貼在框旁邊，結果直接蓋住
  //    它要說明的那個數值（+550.24 被自己的說明遮掉），比沒標注更糟。
  //    現在改成：原地只放「框 ＋ 編號」，文字一律收進頁首說明條與頁尾圖例，
  //    兩者都插進正常文檔流，結構上不可能重疊。

  // 1) 頁首說明條
  if (note) {
    const bar = mk('div', {
      padding: '10px 14px', background: '#1f2937', color: '#fff',
      font: '600 15px/1.5 system-ui,sans-serif', whiteSpace: 'pre-wrap',
    });
    bar.textContent = note;
    document.body.insertBefore(bar, document.body.firstChild);
  }

  // ⛔ **插入說明條之後一定要等版面重排，量座標才準。**
  //    教訓（2026-08-20）：舊版在插入的同一個 tick 就 getBoundingClientRect()，
  //    六張 bug 截圖的紅框全部整體下移一個說明條的高度，框到空白處 ——
  //    圖看起來有標注、實際上標錯地方，比沒標更誤導。
  //    說明條愈多行偏移愈大（2 行偏 ~30px、4 行偏 ~50px），所以小樣本不一定看得出來。
  await raf(); await raf();

  // 2) 原地畫框與編號
  const missing = [], drawn = [];
  marks.forEach((m, i) => {
    const target = document.querySelector(m.selector);
    if (!target) { missing.push(m.selector); return; }
    const r = target.getBoundingClientRect();
    const top = r.top + window.scrollY, left = r.left + window.scrollX;

    const box = mk('div', {
      position: 'absolute', top: px(top - 3), left: px(left - 3),
      width: px(r.width + 6), height: px(r.height + 6),
      border: '3px solid #e02424', borderRadius: '3px',
      boxShadow: '0 0 0 2px rgba(255,255,255,.9)',
      pointerEvents: 'none', zIndex: 2147483000,
    });
    document.body.appendChild(box);

    // 徽章擺左上角外側；只有兩位數字，遮蔽面積極小
    const badge = mk('div', {
      position: 'absolute', top: px(top - 14), left: px(left - 14),
      minWidth: '22px', height: '22px',
      background: '#e02424', color: '#fff', borderRadius: '11px',
      font: '700 13px/22px system-ui,sans-serif', textAlign: 'center',
      pointerEvents: 'none', zIndex: 2147483001,
    });
    badge.textContent = String(i + 1);
    document.body.appendChild(badge);
    drawn.push({target, box, badge});
  });

  // 3) 頁尾圖例：編號 → 說明
  const labelled = marks.filter(m => m.label && document.querySelector(m.selector));
  if (labelled.length) {
    const legend = mk('div', {
      marginTop: '16px', padding: '12px 14px', background: '#1f2937', color: '#fff',
      font: '500 14px/1.7 system-ui,sans-serif',
    });
    // 內部元素刻意不帶 ATTR：標記只掛在頂層容器，
    // 移除容器即整批消失，數量也才等於「標注件數」而非 DOM 節點數。
    const plain = (tag, css) => {
      const el = document.createElement(tag);
      Object.assign(el.style, css);
      return el;
    };
    marks.forEach((m, i) => {
      if (!m.label || !document.querySelector(m.selector)) return;
      const row = plain('div', {display: 'flex', alignItems: 'flex-start', gap: '8px'});
      const n = plain('span', {
        flex: '0 0 auto', minWidth: '20px', height: '20px', marginTop: '2px',
        background: '#e02424', borderRadius: '10px',
        font: '700 12px/20px system-ui,sans-serif', textAlign: 'center',
      });
      n.textContent = String(i + 1);
      const t = plain('span', {whiteSpace: 'pre-wrap'});
      t.textContent = m.label;
      row.appendChild(n); row.appendChild(t);
      legend.appendChild(row);
    });
    document.body.appendChild(legend);
  }

  // 4) ★自我校正：頁尾圖例也可能改變版面（例如撐出捲軸），再對一次位置。
  //    這一步讓「框對不準」在結構上不可能發生 —— 不必去推理是哪個元素推移了誰。
  await raf(); await raf();
  let drift = 0;
  drawn.forEach(({target, box, badge}) => {
    const r = target.getBoundingClientRect();
    const top = r.top + window.scrollY, left = r.left + window.scrollX;
    drift = Math.max(drift, Math.abs(parseFloat(box.style.top) - (top - 3)),
                            Math.abs(parseFloat(box.style.left) - (left - 3)));
    Object.assign(box.style, {top: px(top - 3), left: px(left - 3),
                              width: px(r.width + 6), height: px(r.height + 6)});
    Object.assign(badge.style, {top: px(top - 14), left: px(left - 14)});
  });

  // ⚠️ 「有沒有東西擋住要框的元素」機器判不了語意，但**開著的下拉／彈窗**判得了 ——
  //    它們是遮住目標最常見的原因（2026-08-20 兩張圖就是玩法下拉沒關）。
  const overlays = [...document.querySelectorAll(
      '.el-select-dropdown, .el-overlay, .el-overlay-message-box, .el-popper')]
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => e.className);

  return {marked: marks.length - missing.length, missing, drift: Math.round(drift), overlays};
}
"""

CLEAR_JS = r"""
() => {
  const n = document.querySelectorAll('[data-qa-annotation]');
  n.forEach(e => e.remove());
  return n.length;
}
"""


def annotate(page, marks=None, note=""):
    """在頁面疊上標注；回傳 {'marked': N, 'missing': [selector…]}。

    ⚠️ `missing` 非空代表 selector 沒對到元素 —— **那張圖等於沒標到重點**，
       呼叫端應視為失敗，不要當成「有截到就好」。
    """
    return page.evaluate(ANNOTATE_JS, {"marks": marks or [], "note": note})


def clear(page):
    """清除所有標注（截圖後必做，否則後續畫面都會帶紅框）"""
    return page.evaluate(CLEAR_JS)


# ── PNG 標記 ────────────────────────────────────────────────────
# 在 PNG 寫入一個 tEXt 區塊，讓 lint 分得出「已標注」與「原始畫面」——
# 否則「截圖要有框選與說明」這條規範無法機檢，只能靠人自律（本工作區的教訓：
# 靠人自律的規範必然漂移）。用純 Python 寫入，不需要 Pillow。
PNG_MARK_KEY = b"qa-annotated"


def _png_text_chunk(key, value):
    import struct
    import zlib
    data = key + b"\x00" + value.encode("utf-8")
    return (struct.pack(">I", len(data)) + b"tEXt" + data
            + struct.pack(">I", zlib.crc32(b"tEXt" + data) & 0xFFFFFFFF))


def stamp_png(path, value):
    """把標記寫進 PNG（插在 IHDR 之後）。非 PNG 則靜默略過。"""
    with open(path, "rb") as f:
        raw = f.read()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    ihdr_end = 8 + 8 + 13 + 4          # 簽章 ＋ (長度+型別) ＋ IHDR 資料 ＋ CRC
    with open(path, "wb") as f:
        f.write(raw[:ihdr_end] + _png_text_chunk(PNG_MARK_KEY, value) + raw[ihdr_end:])
    return True


def read_png_mark(path):
    """回傳標記字串；未標注或非 PNG 回 None。只讀前 4KB，不解碼影像。

    ⚠️ 必須用 chunk 的**長度欄位**界定文字，不能 split(NUL) ——
       tEXt 的 text 後面沒有終止符，緊接著是 4 bytes CRC，
       split 會把 CRC 的位元組一起讀進來（實測拿到 `marks=1\\xefRd\\xfe`）。
    """
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    i = head.find(PNG_MARK_KEY + b"\x00")
    if i < 8:
        return None
    length = struct.unpack(">I", head[i - 8:i - 4])[0]
    data = head[i:i + length]
    return data[len(PNG_MARK_KEY) + 1:].decode("utf-8", "replace")


def capture_annotated(page, path, marks=None, note="", full_page=True, strict=True):
    """標注 → 截圖 → 蓋標記 → 清除。回傳 annotate() 的結果。

    strict=True 時，下列兩種情況都丟 AssertionError ——
    寧可讓案例失敗，也不要產出一張**看起來有標注、實際上標錯地方或被遮住**的截圖：

    1. `missing` 非空：selector 對不到元素。
    2. `overlays` 非空：畫面上有展開中的下拉／彈窗（`.el-select-dropdown`／`.el-overlay`…）。
       它們幾乎必定蓋住表格中段，正好是要框的欄位（2026-08-20 實際踩過兩張）。
       關掉它（`page.keyboard.press("Escape")` 或點空白處）再截，或明確傳 `strict=False`。
    """
    result = annotate(page, marks, note)
    try:
        if result.get("missing") and strict:
            raise AssertionError(
                "標注 selector 對不到元素，截圖會失去意義：%s" % result["missing"])
        if result.get("overlays") and strict:
            raise AssertionError(
                "畫面上有展開中的下拉／彈窗，會遮住要框的欄位：%s"
                "（先關閉再截圖；確定不影響時才傳 strict=False）" % result["overlays"])
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        page.screenshot(path=path, full_page=full_page)
        stamp_png(path, "marks=%d" % result.get("marked", 0))
    finally:
        clear(page)
    return result
