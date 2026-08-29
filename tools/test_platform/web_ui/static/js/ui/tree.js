// 可勾選樹（半選態）：案例瀏覽器用。節點徽章顯示 total／smoke／write／prereq。
import { $, $$, esc, html, raw } from './el.js';

export function renderTree(container, tree, { selection, onToggle, onOpenCase, filter = null, expandAll = false } = {}) {
  const sel = selection;
  // ★ 有篩選時，分支勾選只作用於「可見」的案例（否則搜「變動賠率」再勾整個 crux 會選到 152 條）
  function leafIds(n) { if (n.type === 'case') return (!filter || filter(n.case)) ? [n.id] : []; return (n.children || []).flatMap(leafIds); }
  function visible(n) {
    if (!filter) return true;
    if (n.type === 'case') return filter(n.case);
    return (n.children || []).some(visible);
  }
  function node(n, depth) {
    if (!visible(n)) return '';
    if (n.type === 'case') {
      const c = n.case, on = sel.has(n.id);
      return html`<div class="node type-case ${on ? 'selected-leaf' : ''}" data-id="${n.id}">
        <span class="tw"></span><input type="checkbox" data-leaf="${n.id}" ${on ? raw('checked') : ''}>
        <span class="lbl case" data-open="${n.id}" title="${c.nodeid}">${c.title}</span>
        <span class="badges">${raw((c.markers.includes('write_action') ? '<span class="b w">write</span>' : '') + (c.markers.includes('smoke') ? '<span class="b s">smoke</span>' : '') + (c.needs_prereq ? '<span class="b p" title="需先跑前置階段">🔗</span>' : '') + (c.param_id ? `<span class="b">[${esc(c.param_id)}]</span>` : ''))}</span></div>`;
    }
    const ids = leafIds(n), on = ids.filter((i) => sel.has(i)).length;
    const st = on === 0 ? 'none' : on === ids.length ? 'all' : 'some';
    // ⚠️ 2026-08-28 修正：原本 `depth < 1` 會讓所有產品層（如「新綜合」）永遠強制展開，
    // 點收合箭頭雖然有把狀態寫進 openState，但這裡完全沒讀它就被短路成 true——等於
    // 產品層的收合鈕形同虛設。改成只用「預設值」決定初次展開與否（產品層預設展開，
    // 除非設了 collapsed；其餘層預設收合），一旦 openState 有記錄一律以它為準。
    const defaultOpen = n.type === 'product' && !n.collapsed;
    const open = expandAll ? true : (openState.get(n.id) ?? defaultOpen);
    const c = n.counts || {};
    return html`<div class="branch" data-id="${n.id}">
      <div class="node type-${n.type}"><span class="tw" data-tog="${n.id}">${open ? '▾' : '▸'}</span>
        <input type="checkbox" data-branch="${n.id}" ${st === 'all' ? raw('checked') : ''} ${st === 'some' ? raw('data-ind="1"') : ''}>
        <span class="lbl" data-tog="${n.id}">${n.label}${n.sublabel ? html`<span class="muted small"> ${n.sublabel}</span>` : ''}</span>
        <span class="badges"><span class="b">${c.total}</span>${raw((c.smoke ? `<span class="b s">smoke ${c.smoke}</span>` : '') + (c.write_action ? `<span class="b w">write ${c.write_action}</span>` : '') + (c.needs_prereq ? `<span class="b p">🔗 ${c.needs_prereq}</span>` : ''))}</span></div>
      <div class="children ${open ? '' : 'hidden'}">${open ? (n.children || []).map((ch) => node(ch, depth + 1)) : ''}</div></div>`;
  }
  const openState = container.__open || (container.__open = new Map());
  container.innerHTML = `<div class="tree">${tree.map((n) => node(n, 0)).join('')}</div>`;
  $$('input[data-ind]', container).forEach((cb) => (cb.indeterminate = true));

  container.onclick = (e) => {
    const tog = e.target.closest('[data-tog]');
    if (tog) { const id = tog.dataset.tog; openState.set(id, !(openState.get(id) ?? (tog.textContent === '▾'))); rerender(); return; }
    const opn = e.target.closest('[data-open]');
    if (opn) { onOpenCase && onOpenCase(opn.dataset.open); return; }
  };
  container.onchange = (e) => {
    const leaf = e.target.dataset.leaf, br = e.target.dataset.branch;
    if (leaf) { e.target.checked ? sel.add(leaf) : sel.delete(leaf); }
    else if (br) {
      const n = find(tree, br); const ids = leafIds(n);
      e.target.checked ? ids.forEach((i) => sel.add(i)) : ids.forEach((i) => sel.delete(i));
    }
    onToggle && onToggle(sel);
    rerender();
  };
  function rerender() { renderTree(container, tree, { selection: sel, onToggle, onOpenCase, filter, expandAll }); }
  function find(nodes, id) { for (const n of nodes) { if (n.id === id) return n; const f = n.children ? find(n.children, id) : null; if (f) return f; } return null; }
}
