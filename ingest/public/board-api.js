/* ============================================================
   board-api.js — wires the Board tab to /api/board.

   board_tasks is server-authoritative (like eval_tasks). Every
   mutation is optimistic with rollback, same pattern as the Evals
   board and the Projects task toggle. Columns mirror the vault
   Now/Next/Later; planner-sync renders rows back to the vault.
   ============================================================ */

const BOARD_SLUG = 'home-ops';
const BOARD_COLUMNS = ['now', 'next', 'later'];
const BOARD_POLL_MS = 30_000;

const Board = {
  slug: BOARD_SLUG,
  items: [],
  loaded: false,
  loading: false,
  err: null,
  _poll: null,

  async loadAll() {
    if (this.loading) return;
    this.loading = true; this.err = null;
    try {
      const j = await window.api('GET', `/api/board?slug=${encodeURIComponent(this.slug)}`);
      this.items = j.tasks || [];
      this.loaded = true;
    } catch (e) { this.err = e.message; }
    finally { this.loading = false; }
    if (window.render) window.render();
  },

  byId(id) { return this.items.find((t) => t.id === Number(id)) || null; },

  // Items in one column, sorted by position (server order of truth).
  column(col) {
    return this.items
      .filter((t) => t.column_key === col)
      .sort((a, b) => a.position - b.position);
  },

  async create(column, text) {
    const j = await window.api('POST', '/api/board', { slug: this.slug, column, text });
    if (j.task) this.items.push(j.task);
    if (window.render) window.render();
    return j.task;
  },

  // order / fromOrder are arrays of ids (from SortableJS toArray) describing
  // the resulting column contents after the drag.
  async move(item, toColumn, order, fromColumn, fromOrder) {
    const snapshot = this.items.map((t) => ({ ...t }));
    const apply = (col, ids) => ids.forEach((id, i) => {
      const t = this.byId(id);
      if (t) { t.column_key = col; t.position = i; }
    });
    apply(toColumn, order.map(Number));            // optimistic
    if (fromColumn && fromColumn !== toColumn && fromOrder) apply(fromColumn, fromOrder.map(Number));
    item._pending = true;
    if (window.render) window.render();
    try {
      await window.api('POST', `/api/board/${item.id}/move`, {
        column: toColumn, order: order.map(Number),
        fromColumn: fromColumn || null, fromOrder: fromOrder ? fromOrder.map(Number) : null,
      });
      item._pending = false;
    } catch (e) {
      this.items = snapshot;                        // rollback
      this._flash(this.byId(item.id), e.message || 'move failed');
    }
    if (window.render) window.render();
  },

  async update(item, patch) {
    const prev = { text: item.text, done: item.done, is_focus: item.is_focus };
    Object.assign(item, patch);                     // optimistic
    if ('is_focus' in patch && patch.is_focus) {
      this.items.forEach((t) => { if (t !== item) t.is_focus = false; });
    }
    item._pending = true;
    if (window.render) window.render();
    try {
      const j = await window.api('POST', `/api/board/${item.id}/update`, patch);
      Object.assign(item, j.task, { _pending: false });
    } catch (e) {
      Object.assign(item, prev);                    // rollback
      this._flash(item, e.message || 'update failed');
    }
    if (window.render) window.render();
  },

  setFocus(item) { return this.update(item, { is_focus: true }); },

  async remove(item) {
    const snapshot = this.items.slice();
    this.items = this.items.filter((t) => t.id !== item.id);   // optimistic
    if (window.render) window.render();
    try {
      await window.api('POST', `/api/board/${item.id}/delete`, {});
    } catch (e) {
      this.items = snapshot;
      this._flash(item, e.message || 'delete failed');
      if (window.render) window.render();
    }
  },

  _flash(item, msg) {
    if (!item) return;
    item._pending = false;
    item._error = msg;
    setTimeout(() => { delete item._error; if (window.render) window.render(); }, 3500);
  },

  startPoll() {
    if (this._poll) return;
    this._poll = setInterval(() => {
      if ((window.getState?.() || {}).tab !== 'board') { this.stopPoll(); return; }
      // Don't refresh mid-edit — a re-render would discard the open editor.
      if (document.querySelector('.bedit, .bnew')) return;
      this.loadAll();
    }, BOARD_POLL_MS);
  },
  stopPoll() { if (this._poll) { clearInterval(this._poll); this._poll = null; } },
};

window.Board = Board;
window.BOARD_COLUMNS = BOARD_COLUMNS;
