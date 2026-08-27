// 開單流程（草稿 → 預覽配號 → 人確認 → 寫檔）—— **一套流程、兩個入口**。
//
// ⭐ 為什麼抽出來：這段先前只長在 `views/run.js` 裡，綁著它的模組狀態
//    （`runId`、`drafts`）。於是 **session 來源的草稿看得到、落不了檔** ——
//    而「草稿／寫檔兩段式」正是靠寫檔那一步才成立
//    （2026-08-23 走查「測試工程師的一天」時發現）。
//
// ⛔ 三條不能動的紀律：
//    ① **預覽也會真的配號**（`dry_run: true` 走同一支 `gen_bug_index --next-id`）
//       —— 所以預覽看到的號碼與開單後的號碼一致，不會有「說 003 結果寫成 005」。
//    ② **測試失敗 ≠ 缺陷**：確認框一律把開單前三問攤開給人看。
//    ③ **一張一張確認**，不提供「全部開單」的捷徑 —— Bug ID 永不回收。
import { api } from '../api.js';
import { esc } from './el.js';
import { modal } from './modal.js';
import { toast } from './toast.js';

/** 開單前三問的答案 —— 沒有就明講「沒有」，不要靜靜地不顯示。 */
export function prechecksBlock(pre) {
  const answered = (pre || []).filter((q) => (q.answer || '').trim());
  if (!answered.length) {
    return '<div class="alert is-warn tiny" style="margin:6px 0">⚠️ 這份草稿<b>沒有開單前三問的答案</b>'
      + ' —— 多半是 run 自動整理的。開單前請自己確認一次：是規格還是缺陷／是否已被查證過／樣本有沒有鑑別力。</div>';
  }
  return '<div class="alert is-info tiny" style="margin:6px 0"><b>開單前三問</b>'
    + answered.map((q) => `<div style="margin-top:2px"><b>${esc(q.label)}</b>　${esc(q.answer)}</div>`).join('')
    + '</div>';
}

/**
 * @param {Array}  picked  要開單的草稿
 * @param {Object} source  `{kind:'run'|'session', id}`；run 來源也可直接傳 run_id 字串
 * @param {Function} [onDone] 開單後的重新載入
 */
export async function fileDrafts(picked, source, onDone) {
  if (!picked || !picked.length) return;
  const body = (d, extra = {}) => (typeof source === 'string'
    ? { run_id: source, signature: d.signature, ...extra }
    : { source, signature: d.signature, ...extra });

  const previews = [];
  for (const d of picked) {
    try { previews.push({ d, pv: await api.post('/api/bugs/file', body(d, { dry_run: true })) }); }
    catch (e) { toast(`${d.title}：${e.message}`, 'warn', 6000); }
  }
  if (!previews.length) return;

  const box = document.createElement('div');
  box.innerHTML = `
    <div class="alert is-warn small">將寫入 <b>${previews.length}</b> 張單到
      <code>${esc(previews[0].pv.path.replace(/\/[^/]*$/, '/'))}</code>
      <br>
      配號來源：${esc(previews[0].pv.id_source)}</div>
    ${previews.map(({ d, pv }, i) => `
      <details class="bd-prev" ${i ? '' : 'open'}>
        <summary><b>${esc(pv.bug_id)}</b>　${esc(d.title)}
          ${d.likely_existing ? `<span class="pill ${d.likely_existing.regressed ? 'tone-danger' : 'tone-warn'}">${
            d.likely_existing.regressed ? '⚠ ' + esc(d.likely_existing.id) + ' 回歸' : '疑似 ' + esc(d.likely_existing.id)}</span>` : ''}</summary>
        ${d.likely_existing ? `<div class="tiny" style="color:var(--accent-amber)">${esc(d.likely_existing.why)}</div>` : ''}
        ${prechecksBlock(d.prechecks)}
        <label class="small">標題<input class="bd-title" data-sig="${esc(d.signature)}" value="${esc(d.title || '')}"></label>
        <div class="row" style="gap:8px;margin:6px 0">
          <label class="small">嚴重度<select class="bd-sev" data-sig="${esc(d.signature)}">${['高', '中', '低'].map((x) => `<option ${x === d.severity ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
          <label class="small" style="flex:1">模組<input class="bd-mod" data-sig="${esc(d.signature)}" value="${esc(d.module || '')}"></label>
        </div>
        <pre class="tiny bd-text">${esc(pv.text)}</pre>
      </details>`).join('')}`;

  const go = await new Promise((res) => modal.open({
    title: `開立 ${previews.length} 張 Bug 單`, wide: true, body: box,
    actions: [{ label: '取消', onClick: () => res(false) },
      { label: '確認開單', cls: 'primary', onClick: () => res(true) }],
    onClose: () => res(false),
  }));
  if (!go) return;

  const done = [];
  for (const { d } of previews) {
    const g = (sel) => box.querySelector(`${sel}[data-sig="${CSS.escape(d.signature)}"]`)?.value;
    try {
      done.push(await api.post('/api/bugs/file', body(d, {
        dry_run: false, title: g('.bd-title'), severity: g('.bd-sev'), module: g('.bd-mod'),
      })));
    } catch (e) { toast(`${d.title}：${e.message}`, 'danger', 6000); }
  }
  if (done.length) {
    toast(`已開立 ${done.length} 張：${done.map((r) => r.bug_id).join('、')}`, 'success', 6000);
    modal.alert('已開單',
      `<ul>${done.map((r) => `<li><b>${esc(r.bug_id)}</b> → <code>${esc(r.path)}</code></li>`).join('')}</ul>`
      + '<p class="small muted">已寫進產品的 <code>bugs/</code>。記得跑一次 <code>gen_bug_index.py &lt;產品&gt;</code> 重建索引與分組檢視。</p>');
    if (onDone) await onDone();
  }
}
