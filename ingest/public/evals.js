/* ============================================================
   evals.js — Evals board: eval-task lifecycle cards.
   Columns = stages (idea → building → testing → active → paused
   → retired). testing/active are what eval-tick actually runs —
   the board is authoritative. Card click → drill panel with stage
   controls, notes, and recent per-run results.
   ============================================================ */

const EVAL_STAGE_LABELS = {
  idea: 'idea', building: 'building', testing: 'testing',
  active: 'active', paused: 'paused', retired: 'retired',
};
const EVAL_RUNNABLE = new Set(['testing', 'active']);

function evalPassRate(t) {
  if (!t.n_runs) return null;
  return Math.round((t.n_passed / t.n_runs) * 100);
}

function evalNeedsFiles(t) {
  return EVAL_RUNNABLE.has(t.stage) && !t.has_files;
}

/* ---------- card ---------- */
function evalCard(t) {
  const rate = evalPassRate(t);
  const stageIdx = EVAL_STAGES.indexOf(t.stage);
  const move = (delta) => (e) => {
    e.stopPropagation();
    const next = EVAL_STAGES[stageIdx + delta];
    if (next) Evals.setStage(t, next);
  };
  return h('div', {
    class: 'ecard' + (t._pending ? ' pending' : '') + (t._error ? ' err' : ''),
    onclick: () => setState({ eval: String(t.id) }),
    title: t._error || t.notes || t.name,
  },
    h('div', { class: 'ecard-top' },
      h('span', { class: 'ekind ' + t.kind }, t.kind === 'strummy' ? 'strummy' : 'py'),
      h('span', { class: 'grow' }),
      evalNeedsFiles(t) ? h('span', { class: 'echip warn', title: 'in rotation but eval-tick has not seen task files' }, '⚠ no files') : null,
      t.timeout_s ? h('span', { class: 'echip', title: 'timeout override' }, t.timeout_s + 's') : null,
    ),
    h('div', { class: 'ecard-name' }, t.name),
    rate != null ? h('div', { class: 'ecard-stats num' },
      h('span', { class: 'erate ' + (rate >= 70 ? 'good' : rate >= 40 ? 'warn' : 'bad') }, rate + '%'),
      h('span', { class: 'faint' }, t.n_passed + '/' + t.n_runs + ' green'),
      t.last_passed != null ? h('span', { class: 'elast ' + (t.last_passed ? 'good' : 'bad') },
        (t.last_passed ? '✓' : '✕') + ' ' + (t.last_model || '')) : null,
    ) : h('div', { class: 'ecard-stats faint' }, t.stage === 'idea' || t.stage === 'building' ? 'not run yet' : 'no results yet'),
    h('div', { class: 'ecard-foot' },
      h('button', { class: 'emove', disabled: stageIdx === 0, onclick: move(-1), title: 'move to ' + (EVAL_STAGES[stageIdx - 1] || '—') }, '‹'),
      h('span', { class: 'faint num', style: { fontSize: '10.5px' } }, t.last_scored_at ? relShort(t.last_scored_at) : ''),
      h('button', { class: 'emove', disabled: stageIdx === EVAL_STAGES.length - 1, onclick: move(1), title: 'move to ' + (EVAL_STAGES[stageIdx + 1] || '—') }, '›'),
    ),
  );
}

/* ---------- new-card form ---------- */
function evalNewForm(col) {
  const name = h('input', { class: 'enew-in', placeholder: 'task-name (dir-safe)', maxLength: 64 });
  const kind = h('select', { class: 'enew-kind' },
    h('option', { value: 'python' }, 'python'),
    h('option', { value: 'strummy' }, 'strummy'));
  const notes = h('textarea', { class: 'enew-notes', placeholder: 'what should this task prove? (notes)', rows: 3 });
  const errEl = h('div', { class: 'enew-err' });
  const form = h('form', {
    class: 'enew',
    onsubmit: async (e) => {
      e.preventDefault();
      errEl.textContent = '';
      try {
        await Evals.create(name.value.trim(), kind.value, notes.value.trim());
        form.remove();
      } catch (err) { errEl.textContent = '✕ ' + (err.message || 'create failed'); }
    },
  },
    name, kind, notes, errEl,
    h('div', { class: 'enew-btns' },
      h('button', { class: 'toolbtn', type: 'submit' }, '+ add idea'),
      h('button', { class: 'toolbtn', type: 'button', onclick: () => form.remove() }, 'cancel')),
  );
  col.append(form);
  requestAnimationFrame(() => name.focus());
}

/* ---------- drill panel ---------- */
function evalDrill(t, main) {
  if (t._scores === undefined && !t._scoresLoading) Evals.loadScores(t);
  const scores = t._scores || [];
  const notesTa = h('textarea', { class: 'edrill-notes', rows: 5, value: t.notes || '', placeholder: 'notes — intent, edge cases to cover, model observations…' });
  const timeoutIn = h('input', { class: 'edrill-timeout num', type: 'number', min: 1, max: 3600, placeholder: 'default', value: t.timeout_s ?? '' });

  const stageBtns = EVAL_STAGES.map((s) => h('button', {
    class: 'estage' + (t.stage === s ? ' on' : '') + (EVAL_RUNNABLE.has(s) ? ' runnable' : ''),
    onclick: () => Evals.setStage(t, s),
  }, EVAL_STAGE_LABELS[s]));

  const scoreRows = scores.map((s) => h('div', { class: 'mini-row' },
    h('span', { class: 't num' }, window.__abs ? abs(s.scored_at) : relShort(s.scored_at)),
    h('span', { class: 'elast ' + (s.passed ? 'good' : 'bad') }, s.passed ? '✓ pass' : '✕ fail'),
    h('span', { class: 'num' }, s.model),
    h('span', { class: 'num faint' }, (s.iterations ?? '—') + ' runs'),
    h('span', { class: 'num faint' }, s.latency_ms ? Math.round(s.latency_ms / 1000) + 's' : '—'),
  ));

  main.append(h('div', { class: 'drill' },
    h('div', { class: 'drill-hd' },
      h('button', { class: 'drill-back', onclick: () => setState({ eval: null }) }, '← board'),
      h('div', { class: 'drill-title' },
        h('span', { class: 'ekind ' + t.kind }, t.kind),
        h('span', { class: 'slug' }, t.name),
        h('span', { class: 'grow' }),
        evalNeedsFiles(t) ? h('span', { class: 'echip warn' }, '⚠ eval-tick has not seen files for this task') : null,
      ),
    ),
    h('div', { class: 'edrill-body' },
      h('div', { class: 'block' },
        h('div', { class: 'block-hd' }, h('span', { class: 'lbl' }, 'stage'),
          h('span', { class: 'faint', style: { fontSize: '11px' } }, 'testing + active run every 6h tick')),
        h('div', { class: 'estages' }, ...stageBtns)),
      h('div', { class: 'block' },
        h('div', { class: 'block-hd' }, h('span', { class: 'lbl' }, 'notes & timeout')),
        notesTa,
        h('div', { class: 'edrill-row' },
          h('label', { class: 'faint', style: { fontSize: '11px' } }, 'timeout_s override '),
          timeoutIn,
          h('span', { class: 'grow' }),
          h('button', {
            class: 'toolbtn',
            onclick: () => Evals.update(t, {
              notes: notesTa.value,
              timeout_s: timeoutIn.value === '' ? null : Number(timeoutIn.value),
            }).catch((e) => { notesTa.classList.add('err'); notesTa.title = e.message; }),
          }, 'save'))),
      h('div', { class: 'block' },
        h('div', { class: 'block-hd' }, h('span', { class: 'lbl' }, 'recent results'),
          h('span', { class: 'faint num', style: { fontSize: '11px' } }, String(scores.length))),
        scores.length ? h('div', { class: 'mini' }, ...scoreRows)
          : h('div', { class: 'empty', style: { height: 'auto', padding: '18px' } },
              t._scoresLoading ? 'loading…' : 'no eval_scores rows for this task yet')),
    ),
  ));
}

/* ---------- board view ---------- */
VIEWS.evals = function (st, main) {
  if (!Evals.loaded && !Evals.loading) Evals.loadAll();
  Evals.startPoll();

  if (st.eval) {
    const t = Evals.byId(st.eval);
    if (t) return evalDrill(t, main);
  }

  const wrap = h('div', { class: 'evals-view' });
  wrap.append(h('div', { class: 'sec-bar' },
    h('span', { class: 'lbl' }, 'eval tasks ',
      h('span', { class: 'faint num', style: { fontWeight: 400 } }, Evals.items.length)),
    h('span', { class: 'faint', style: { fontSize: '11px' } }, '· board gates the 6h tick'),
    Evals.err ? h('span', { class: 'lv error', style: { fontSize: '11px' } }, '✕ ' + Evals.err) : null,
    h('span', { class: 'grow' }),
    h('button', { class: 'toolbtn', onclick: () => Evals.loadAll(), title: 'refresh' }, '↻'),
  ));

  const board = h('div', { class: 'eboard' });
  for (const stage of EVAL_STAGES) {
    const items = Evals.items.filter((t) => t.stage === stage);
    const col = h('div', { class: 'ecol' + (EVAL_RUNNABLE.has(stage) ? ' runnable' : '') },
      h('div', { class: 'ecol-hd' },
        h('span', { class: 'lbl' }, EVAL_STAGE_LABELS[stage]),
        h('span', { class: 'faint num' }, String(items.length)),
        h('span', { class: 'grow' }),
        stage === 'idea' ? h('button', {
          class: 'toolbtn', title: 'new task idea',
          onclick: (e) => { if (!col.querySelector('.enew')) evalNewForm(col, e); },
        }, '+') : null),
      ...items.map(evalCard),
    );
    if (!items.length && stage !== 'idea') col.append(h('div', { class: 'ecol-empty' }, '—'));
    board.append(col);
  }
  wrap.append(board);
  main.append(wrap);
};
