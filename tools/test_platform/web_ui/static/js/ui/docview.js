// 文件檢視器：讀 /api/doc 的 markdown → 渲染 → modal 全文顯示，並跳到來源那一行。
//
// 為什麼自己寫渲染器：後端 venv 沒有 markdown 套件（只有 flask/psutil/requests），
// 前端也零建置不裝相依。目標是**讀得懂、能定位**，不是完美還原 —— 交接檔重度使用
// 表格與 <br> 多段，複雜巢狀不保證排版完美，但內容不會遺漏（無法解析的行退回段落）。
//
// ★ 行號對應：每個區塊帶 data-line（該區塊在原始檔的起始行，1-based），
//   openDoc({line}) 靠它捲到最接近的區塊並高亮 —— 待辦／Bug 的「看全文」就是這樣定位的。
import { api } from '../api.js';
import { $, $$, esc, h } from './el.js';
import { modal } from './modal.js';
import { toast } from './toast.js';

// ── 行內：粗體／斜體／刪除線／code／連結／<br> ──────────────────────────
// 交接檔儲存格常見的就這些。順序重要：先 esc，再處理 code（避免 code 內的 * 被當粗體）。
export function md(s) {
  if (!s) return '';
  let t = esc(String(s));
  t = t.replace(/&lt;br\s*\/?&gt;/gi, '<br>');
  const codes = [];
  t = t.replace(/`([^`]+)`/g, (_m, c) => `\u0000${codes.push(c) - 1}\u0000`);
  t = t.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  t = t.replace(/~~(.+?)~~/g, '<s>$1</s>');
  t = t.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<i>$2</i>');
  // 站內 markdown 連結一律不外連（可能是相對路徑）；改成可點的「開這份文件」
  t = t.replace(/\[([^\]]*)\]\(([^)]+)\)/g, (_m, label, href) => {
    const h2 = href.trim();
    if (/^https?:\/\//i.test(h2)) return `<a href="${esc(h2)}" target="_blank" rel="noopener">${label || esc(h2)}</a>`;
    if (/\.md(#.*)?$/i.test(h2)) return `<a href="#" data-doclink="${esc(h2)}">${label || esc(h2)}</a>`;
    return `<span class="pc-crux">${label || esc(h2)}</span>`;
  });
  t = t.replace(/\u0000(\d+)\u0000/g, (_m, i) => `<code>${codes[Number(i)]}</code>`);
  return t;
}

const H = /^(#{1,6})\s+(.*)$/;
const HR = /^\s*(?:---+|\*\*\*+|___+)\s*$/;
const LI = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const TABLE_SEP = /^\s*\|?[\s:|-]+\|[\s:|-]*$/;

const cells = (ln) => ln.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

/** markdown → HTML；每個區塊帶 data-line（原始檔 1-based 起始行）。
 *  ⚠️ offset 是給巢狀呼叫（blockquote）用的：少了它，內層會從 1 重新編號，
 *     於是文件後段冒出一堆小行號，破壞 focusLine 賴以提前 break 的「行號遞增」前提。 */
export function renderMarkdown(text, offset = 0) {
  const lines = String(text || '').split(/\r?\n/);
  const out = [];
  let i = 0;
  const at = (n) => ` data-line="${n + 1 + offset}"`;

  while (i < lines.length) {
    const ln = lines[i];

    if (/^\s*```/.test(ln)) {                                   // 圍籬程式碼
      const start = i, lang = ln.trim().slice(3).trim();
      const buf = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i += 1; }
      i += 1;
      out.push(`<pre${at(start)} class="md-code" data-lang="${esc(lang)}"><code>${esc(buf.join('\n'))}</code></pre>`);
      continue;
    }
    if (!ln.trim()) { i += 1; continue; }
    if (HR.test(ln)) { out.push(`<hr${at(i)}>`); i += 1; continue; }

    const hm = ln.match(H);
    if (hm) { out.push(`<h${hm[1].length}${at(i)}>${md(hm[2])}</h${hm[1].length}>`); i += 1; continue; }

    // 表格：一行 | 開頭 ＋ 下一行是分隔列
    if (ln.trim().startsWith('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const start = i;
      const head = cells(ln);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(cells(lines[i])); i += 1; }
      out.push(`<div class="md-table-wrap"${at(start)}><table class="tbl"><thead><tr>${head.map((c) => `<th>${md(c)}</th>`).join('')}</tr></thead>`
        + `<tbody>${rows.map((r, ri) => `<tr data-line="${start + 3 + ri + offset}">${r.map((c) => `<td>${md(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      continue;
    }

    if (QUOTE.test(ln)) {                                        // 引言（可含多行）
      const start = i, buf = [];
      while (i < lines.length && QUOTE.test(lines[i])) { buf.push(lines[i].match(QUOTE)[1]); i += 1; }
      out.push(`<blockquote${at(start)}>${renderMarkdown(buf.join('\n'), start + 1 + offset)}</blockquote>`);
      continue;
    }

    if (LI.test(ln)) {                                           // 清單（依縮排分層，最多兩層）
      const start = i;
      const ordered = /^\s*\d+[.)]/.test(ln);
      const items = [];
      while (i < lines.length && LI.test(lines[i])) {
        const m = lines[i].match(LI);
        items.push({ depth: Math.min(1, Math.floor(m[1].replace(/\t/g, '  ').length / 2)), text: m[3], line: i });
        i += 1;
        // 清單項目的續行（縮排且非新項目）併進同一項
        while (i < lines.length && lines[i].trim() && !LI.test(lines[i]) && /^\s{2,}/.test(lines[i])) {
          items[items.length - 1].text += ' ' + lines[i].trim(); i += 1;
        }
      }
      const tag = ordered ? 'ol' : 'ul';
      let htmlStr = `<${tag}${at(start)}>`, open2 = false;
      for (const it of items) {
        if (it.depth && !open2) { htmlStr += `<${tag}>`; open2 = true; }
        else if (!it.depth && open2) { htmlStr += `</${tag}>`; open2 = false; }
        htmlStr += `<li data-line="${it.line + 1 + offset}">${md(it.text)}</li>`;
      }
      if (open2) htmlStr += `</${tag}>`;
      out.push(htmlStr + `</${tag}>`);
      continue;
    }

    const start = i, buf = [];                                   // 段落
    while (i < lines.length && lines[i].trim() && !H.test(lines[i]) && !HR.test(lines[i])
           && !LI.test(lines[i]) && !QUOTE.test(lines[i]) && !/^\s*```/.test(lines[i])
           && !lines[i].trim().startsWith('|')) { buf.push(lines[i]); i += 1; }
    if (!buf.length) { buf.push(lines[i]); i += 1; }              // 保底：任何情況都不吞行
    out.push(`<p${at(start)}>${md(buf.join('\n')).replace(/\n/g, '<br>')}</p>`);
  }
  return out.join('\n');
}

/** 開一份 markdown 全文；line 給了就捲過去並高亮。 */
export async function openDoc(path, { line = null, title = null } = {}) {
  let d;
  try {
    d = await api.get(`/api/doc?path=${encodeURIComponent(path)}`);
  } catch (e) {
    toast(`讀不到檔案：${e.message}`, 'danger', 5000);
    return null;
  }
  const body = h('div', { class: 'docview' });
  // ⭐ 原始碼／渲染切換（2026-08-24）。偏好記在 localStorage —— 會挑原始碼的人
  //    多半是為了捲得快，每開一份都要再按一次等於沒給。
  const rawKey = 'docview.raw';
  let showRaw = localStorage.getItem(rawKey) === '1';
  const paint = () => {
    const el = $('.docview-body', body);
    const keep = el ? el.scrollTop : 0;
    el.className = showRaw ? 'docview-body raw' : 'md docview-body';
    if (showRaw) { el.textContent = ''; el.appendChild(h('pre', { class: 'doc-raw' }, d.text)); }
    else el.innerHTML = renderMarkdown(d.text);
    el.scrollTop = keep;
    const b = $('[data-raw-toggle]', body);
    if (b) { b.textContent = showRaw ? '渲染' : '原始碼'; b.title = showRaw
      ? '切回渲染 —— 表格、標題階層與可點的站內連結會回來'
      : '看原始碼 —— 只有一個 <pre>，捲動快約 1.8 倍（實測 1,055ms → 578ms）'; }
  };
  body.innerHTML = `<div class="row between tiny muted docview-head"><span class="mono">${esc(d.path)}</span>`
    + `<span class="row" style="gap:8px"><button class="btn xs" data-raw-toggle></button>${d.lines} 行</span></div>`
    + `<div class="md docview-body"></div>`;
  paint();
  body.addEventListener('click', (e) => {
    if (!e.target.closest('[data-raw-toggle]')) return;
    showRaw = !showRaw;
    localStorage.setItem(rawKey, showRaw ? '1' : '0');
    paint();
  });

  const m = modal.open({
    title: title || path.split('/').pop(),
    body,
    // ⭐ `wide` 是 880px —— 那是給確認卡與表單用的寬度。文件不一樣：
    //    交接檔那種 4~5 欄的表格在 880px 下每格都在硬斷行，而 1920 的螢幕
    //    右邊還空著一半（2026-08-24 走查）。`doc` ＝ min(1360px, 94vw)。
    size: 'doc',
    actions: [
      { label: '複製路徑', onClick: () => { navigator.clipboard?.writeText(line ? `${d.path}:${line}` : d.path); toast('已複製', 'success'); return false; } },
      { label: '關閉' },
    ],
  });

  // ⭐ 只留 `.docview-body` 這一個捲動容器。
  //    `.modal .box` 自己也是 `overflow:auto`，兩層疊著就會互搶：內層捲到底之後
  //    事件往外傳，整個對話框跟著滑一截 —— 使用者回報的「畫面跳動」就是它。
  m.box.classList.add('no-scroll');
  // ⚠️ 原始碼模式沒有 `data-line`，`focusLine` 會**靜默**失效（找不到就 return）——
  //    從 Bug 單或知識雷達點過來時是要看那一行的，這種情況一律用渲染版。
  if (line) {
    if (showRaw) { showRaw = false; paint(); }
    requestAnimationFrame(() => focusLine(body, Number(line)));
  }
  // 文件內的 .md 連結：就地換一份，不離開 modal
  body.addEventListener('click', (e) => {
    const a = e.target.closest('[data-doclink]');
    if (!a) return;
    e.preventDefault();
    const [p, frag] = a.dataset.doclink.split('#');
    m.close();
    openDoc(resolveRel(d.path, p), { line: /^L\d+$/.test(frag || '') ? Number(frag.slice(1)) : null });
  });
  return m;
}

/** 捲到 <= line 的最後一個區塊並高亮（區塊起始行未必等於目標行）。 */
function focusLine(root, line) {
  const scroller = $('.docview-body', root) || root;
  let best = null;
  for (const n of $$('[data-line]', scroller)) {
    if (Number(n.dataset.line) <= line) best = n; else break;   // 行號遞增，超過就不必再看
  }
  if (!best) return;
  // ⚠️ 用 rect 差而非 offsetTop：<tr> 的 offsetParent 在各瀏覽器不一致（可能是 table 而非捲動容器）
  const delta = best.getBoundingClientRect().top - scroller.getBoundingClientRect().top;
  scroller.scrollTop = Math.max(0, scroller.scrollTop + delta - 56);
  best.classList.add('line-hit');
}

function resolveRel(from, rel) {
  if (!rel.startsWith('.')) return rel.replace(/^\/+/, '');
  const base = from.split('/').slice(0, -1);
  for (const seg of rel.split('/')) {
    if (seg === '.' || !seg) continue;
    if (seg === '..') base.pop();
    else base.push(seg);
  }
  return base.join('/');
}
