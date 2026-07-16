/* ============================================================
   eval-scores.js — Scores tab: strummy_eval reconstruction
   scoreboard. One card per model × task (pass-rate, tok/s, iters,
   last result), a summary strip, and a recent-runs list. Read-only
   — the Evals board is where tasks are managed; this just shows how
   the 7700 XT local models are doing against the real tasks.
   ============================================================ */

function scoreRateClass(rate) {
  return rate >= 70 ? 'good' : rate >= 40 ? 'warn' : 'bad';
}

function scoreShortModel(m) {
  return m || '?';
}

/* ---------- one model × task card ---------- */
function scoreCard(row) {
  const rate = row.pass_rate;
  const tokS = row.avg_tok_per_s;
  return h('div', { class: 'scard', title: `${row.model} · ${row.task}` },
    h('div', { class: 'scard-top' },
      h('span', { class: 'smodel' }, scoreShortModel(row.model)),
      h('span', { class: 'grow' }),
      row.last_passed != null
        ? h('span', { class: 'elast ' + (row.last_passed ? 'good' : 'bad') }, row.last_passed ? '✓ last' : '✕ last')
        : null,
    ),
    h('div', { class: 'scard-task' }, row.task),
    h('div', { class: 'scard-rate' },
      h('span', { class: 'erate num ' + scoreRateClass(rate) }, (rate ?? 0) + '%'),
      h('span', { class: 'faint num' }, row.n_passed + '/' + row.n + ' green'),
    ),
    h('div', { class: 'scard-metrics num' },
      h('span', { title: 'avg tokens/sec on passing runs' }, (tokS != null ? tokS : '—') + ' tok/s'),
      h('span', { class: 'dotsep' }, '·'),
      h('span', { title: 'avg edit→test iterations to green' }, (row.avg_iterations != null ? row.avg_iterations : '—') + ' it'),
      h('span', { class: 'grow' }),
      h('span', { class: 'faint', title: 'last run' }, row.last_scored_at ? relShort(row.last_scored_at) : ''),
    ),
  );
}

/* ---------- recent runs strip ---------- */
function scoreRecentRow(s) {
  return h('div', { class: 'mini-row' },
    h('span', { class: 't num' }, window.__abs ? abs(s.scored_at) : relShort(s.scored_at)),
    h('span', { class: 'elast ' + (s.passed ? 'good' : 'bad') }, s.passed ? '✓' : '✕'),
    h('span', { class: 'num', style: { minWidth: '78px' } }, s.model),
    h('span', { class: 'num', style: { minWidth: '110px' } }, s.task),
    h('span', { class: 'num faint' }, (s.iterations ?? '—') + ' it'),
    h('span', { class: 'num faint' }, (s.tok_per_s != null ? Math.round(s.tok_per_s) : '—') + ' t/s'),
    h('span', { class: 'num faint' }, s.latency_ms ? Math.round(s.latency_ms / 1000) + 's' : '—'),
  );
}

/* ---------- view ---------- */
VIEWS.scores = function (st, main) {
  if (!EvalScores.loaded && !EvalScores.loading) EvalScores.load();
  EvalScores.startPoll();

  const S = EvalScores;
  const wrap = h('div', { class: 'scores-view' });

  // header bar
  const cfg = S.config;
  wrap.append(h('div', { class: 'sec-bar' },
    h('span', { class: 'lbl' }, 'strummy eval ',
      h('span', { class: 'faint', style: { fontWeight: 400, fontSize: '11px' } }, '· 7700 XT reconstruction scoreboard')),
    cfg ? h('span', { class: 'spill ' + (cfg.paused ? 'paused' : 'live') },
      cfg.paused ? '⏸ paused' : '● live') : null,
    S.err ? h('span', { class: 'lv error', style: { fontSize: '11px' } }, '✕ ' + S.err) : null,
    h('span', { class: 'grow' }),
    h('button', { class: 'toolbtn', onclick: () => S.load(), title: 'refresh' }, '↻'),
  ));

  if (!S.available) {
    wrap.append(h('div', { class: 'empty' }, 'strummy_eval tables not present in this database'));
    main.append(wrap);
    return;
  }

  if (!S.loaded && S.loading) {
    wrap.append(h('div', { class: 'empty' }, 'loading…'));
    main.append(wrap);
    return;
  }

  // summary strip
  const o = S.overall;
  if (o && o.n) {
    const overallRate = Math.round((o.n_passed / o.n) * 100);
    wrap.append(h('div', { class: 'sstrip' },
      h('div', { class: 'sstat' },
        h('span', { class: 'sv num ' + scoreRateClass(overallRate) }, overallRate + '%'),
        h('span', { class: 'sl' }, 'overall pass')),
      h('div', { class: 'sstat' },
        h('span', { class: 'sv num' }, o.n_passed + '/' + o.n),
        h('span', { class: 'sl' }, 'green runs')),
      h('div', { class: 'sstat' },
        h('span', { class: 'sv num' }, String(o.n_models)),
        h('span', { class: 'sl' }, 'models')),
      h('div', { class: 'sstat' },
        h('span', { class: 'sv num' }, String(o.n_tasks)),
        h('span', { class: 'sl' }, 'tasks')),
      h('div', { class: 'sstat' },
        h('span', { class: 'sv num' }, o.last_scored_at ? relShort(o.last_scored_at) : '—'),
        h('span', { class: 'sl' }, 'last run')),
    ));
  }

  // model × task cards
  if (!S.matrix.length) {
    wrap.append(h('div', { class: 'empty' }, 'no eval runs recorded yet'));
  } else {
    const grid = h('div', { class: 'sgrid' }, ...S.matrix.map(scoreCard));
    wrap.append(grid);
  }

  // recent runs
  if (S.recent.length) {
    wrap.append(h('div', { class: 'sec-bar sub' },
      h('span', { class: 'lbl' }, 'recent runs ',
        h('span', { class: 'faint num', style: { fontWeight: 400 } }, S.recent.length))));
    wrap.append(h('div', { class: 'mini' }, ...S.recent.map(scoreRecentRow)));
  }

  main.append(wrap);
};
