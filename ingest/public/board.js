/* ============================================================
   board.js — Board tab: interactive kanban for home-ops tasks.
   Columns = Now / Next / Later (mirror the vault sections).
   Drag between columns + reorder via SortableJS; ‹ › buttons are
   the keyboard-accessible fallback. A card can be marked done and
   one card pinned as the morning-digest "Today's focus". Edits are
   optimistic (board-api.js); planner-sync renders rows to the vault.
   ============================================================ */

const BOARD_LABELS = { now: 'Now', next: 'Next', later: 'Later' };
const _boardSortables = [];
const boardReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function boardTeardown() {
  while (_boardSortables.length) {
    const s = _boardSortables.pop();
    try { s.destroy(); } catch { /* detached */ }
  }
}

/* ids currently in a column's DOM list, in order */
function boardOrderOf(listEl) {
  return [...listEl.querySelectorAll('.bcard')].map((el) => Number(el.dataset.id));
}

/* ---------- card ---------- */
function boardCard(t) {
  const colIdx = BOARD_COLUMNS.indexOf(t.column_key);

  const moveTo = (col) => {
    if (!col || col === t.column_key) return;
    const toOrder = Board.column(col).map((x) => x.id).concat(t.id);
    const fromOrder = Board.column(t.column_key).map((x) => x.id).filter((id) => id !== t.id);
    Board.move(t, col, toOrder, t.column_key, fromOrder);
  };

  const star = h('button', {
    class: 'bstar no-drag' + (t.is_focus ? ' on' : ''),
    title: t.is_focus ? 'today’s focus (click to unpin)' : 'pin as today’s focus',
    onclick: (e) => { e.stopPropagation(); Board.update(t, { is_focus: !t.is_focus }); },
  }, t.is_focus ? '★' : '☆');

  const check = h('button', {
    class: 'bcheck no-drag' + (t.done ? ' on' : ''),
    title: t.done ? 'done' : 'mark done',
    onclick: (e) => { e.stopPropagation(); Board.update(t, { done: !t.done }); },
  }, t.done ? '✓' : '');

  let body;
  if (t._editing) {
    const ta = h('textarea', {
      class: 'bedit no-drag', rows: 2, value: t.text,
      onkeydown: (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { delete t._editing; render(); }
      },
      onblur: commit,
    });
    function commit() {
      const v = ta.value.trim();
      delete t._editing;
      if (v && v !== t.text) Board.update(t, { text: v }); else render();
    }
    body = ta;
    requestAnimationFrame(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); });
  } else {
    body = h('div', {
      class: 'btext' + (t.done ? ' done' : ''),
      title: 'click to edit',
      onclick: () => { t._editing = true; render(); },
    }, t.text);
  }

  return h('div', {
    class: 'bcard' + (t._pending ? ' pending' : '') + (t._error ? ' err' : '') + (t.is_focus ? ' focus' : ''),
    dataset: { id: String(t.id) },
    title: t._error || undefined,
  },
    h('div', { class: 'bcard-top' }, star, check, h('span', { class: 'grow' }),
      h('button', { class: 'bdel no-drag', title: 'delete', onclick: (e) => { e.stopPropagation(); Board.remove(t); } }, '×')),
    body,
    h('div', { class: 'bcard-foot no-drag' },
      h('button', { class: 'bmove', disabled: colIdx === 0, title: 'move left', onclick: () => moveTo(BOARD_COLUMNS[colIdx - 1]) }, '‹'),
      h('span', { class: 'grow' }),
      h('button', { class: 'bmove', disabled: colIdx === BOARD_COLUMNS.length - 1, title: 'move right', onclick: () => moveTo(BOARD_COLUMNS[colIdx + 1]) }, '›')),
  );
}

/* ---------- add-card form ---------- */
function boardAddForm(col, listEl) {
  if (listEl.querySelector('.bnew')) return;
  const input = h('input', { class: 'bnew-in', placeholder: 'new task…', maxLength: 2000 });
  const form = h('form', {
    class: 'bnew',
    onsubmit: async (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) { form.remove(); return; }
      try { await Board.create(col, v); } catch (err) { input.classList.add('err'); input.title = err.message; }
    },
  }, input);
  listEl.prepend(form);
  requestAnimationFrame(() => input.focus());
}

/* ---------- board view ---------- */
VIEWS.board = function (st, main) {
  boardTeardown();
  if (!Board.loaded && !Board.loading) Board.loadAll();
  Board.startPoll();

  const focus = Board.items.find((t) => t.is_focus);
  const wrap = h('div', { class: 'board-view' });
  wrap.append(h('div', { class: 'sec-bar' },
    h('span', { class: 'lbl' }, 'home-ops board ',
      h('span', { class: 'faint num', style: { fontWeight: 400 } }, Board.items.length)),
    focus ? h('span', { class: 'bfocus-chip', title: 'morning digest Today’s focus' }, '★ ' + focus.text) : null,
    Board.err ? h('span', { class: 'lv error', style: { fontSize: '11px' } }, '✕ ' + Board.err) : null,
    h('span', { class: 'grow' }),
    h('button', { class: 'toolbtn', title: 'refresh', onclick: () => Board.loadAll() }, '↻'),
  ));

  const board = h('div', { class: 'bboard' });
  const lists = [];
  for (const col of BOARD_COLUMNS) {
    const items = Board.column(col);
    const listEl = h('div', { class: 'bcol-list', dataset: { column: col } }, ...items.map(boardCard));
    if (!items.length) listEl.append(h('div', { class: 'bcol-empty' }, 'drop here'));
    const colEl = h('div', { class: 'bcol bcol-' + col },
      h('div', { class: 'bcol-hd' },
        h('span', { class: 'lbl' }, BOARD_LABELS[col]),
        h('span', { class: 'faint num' }, String(items.length)),
        h('span', { class: 'grow' }),
        h('button', { class: 'toolbtn', title: 'add task', onclick: () => boardAddForm(col, listEl) }, '+')),
      listEl);
    board.append(colEl);
    lists.push(listEl);
  }
  wrap.append(board);
  main.append(wrap);

  // Init drag-and-drop after the lists are in the document.
  if (window.Sortable) {
    for (const listEl of lists) {
      _boardSortables.push(window.Sortable.create(listEl, {
        group: 'board',
        animation: boardReducedMotion ? 0 : 150,
        draggable: '.bcard',
        filter: '.no-drag',
        preventOnFilter: false,
        // Pointer-based dragging (not native HTML5 DnD): reliable on touch
        // for morning phone use, and consistent across browsers.
        forceFallback: true,
        fallbackTolerance: 4,
        ghostClass: 'bcard-ghost',
        chosenClass: 'bcard-chosen',
        emptyInsertThreshold: 10,
        onEnd: (evt) => {
          const toCol = evt.to.dataset.column;
          const fromCol = evt.from.dataset.column;
          const id = Number(evt.item.dataset.id);
          const item = Board.byId(id);
          if (!item) { render(); return; }
          const order = boardOrderOf(evt.to);
          const fromOrder = fromCol !== toCol ? boardOrderOf(evt.from) : null;
          Board.move(item, toCol, order, fromCol, fromOrder);
        },
      }));
    }
  }
};

window.VIEW_KEYS = window.VIEW_KEYS || {};
