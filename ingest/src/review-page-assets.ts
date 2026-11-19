// Style and behaviour of the review page (review-page.ts), kept apart so the
// renderer stays readable. Same light palette as the decision pages.

export const REVIEW_CSS = `
body{margin:0;background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif;padding:24px 16px}
.wrap{max-width:920px;margin:0 auto}
.card{background:#fff;border-radius:18px;padding:24px;margin-bottom:14px}
.eyebrow{font-size:12px;color:#6e6e73;text-transform:uppercase;letter-spacing:.04em}
h1{font-size:22px;line-height:1.25;margin:10px 0 8px;font-weight:600}
p,li{font-size:15px;color:#3a3a3c;line-height:1.45}
pre{white-space:pre-wrap;font:13px/1.45 ui-monospace,Menlo,monospace;background:#f5f5f7;border-radius:10px;padding:12px;overflow-x:auto}
a{color:#0066cc;text-decoration:none}
details.sec{border-top:1px solid #e5e5ea;padding:12px 0}
details.sec>summary{cursor:pointer;font-weight:600;font-size:16px;list-style:none}
details.sec>summary::before{content:"○ ";color:#8e8e93}
details.sec[open]>summary::before,details.sec.seen>summary::before{content:"● ";color:#34c759}
.src{font-weight:400;font-size:12px;color:#8e8e93}
.finding{border-left:3px solid #ff9500;padding:4px 0 4px 12px;margin:10px 0}
.finding.bloker{border-color:#ff3b30}
.verdict{display:inline-block;border-radius:8px;padding:2px 8px;font-size:13px;font-weight:600;background:#e8f8ec;color:#1e7d34}
.verdict.zmiany{background:#fff4e5;color:#a35c00}.verdict.bloker,.verdict.none{background:#ffeceb;color:#c4271c}
.answer{position:sticky;bottom:0;box-shadow:0 -4px 16px rgba(0,0,0,.06)}
.answer input{width:100%;box-sizing:border-box;font:inherit;font-size:16px;padding:10px 12px;border:1px solid #d2d2d7;border-radius:10px}
.btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.btns button{flex:1 1 140px;font:inherit;font-size:16px;font-weight:600;padding:12px;border:0;border-radius:12px;background:#1d1d1f;color:#fff}
.btns button.no{background:#ff3b30}
.btns button:disabled{background:#d2d2d7;color:#8e8e93}
.err{color:#c4271c;font-weight:600}
`;

// Buttons unlock only after every section was expanded at least once. The
// server checks the same list (the "opened" field) against the sections that
// exist for the commit, so a section filed after the page loaded forces a
// reload instead of being skipped.
export const REVIEW_JS = `(() => {
  const form = document.getElementById('answer');
  const secs = [...document.querySelectorAll('details.sec')];
  const seen = new Set();
  const opened = form.querySelector('[name=opened]');
  const count = document.getElementById('seen');
  const btns = [...form.querySelectorAll('button[name=option]')];
  const update = () => {
    opened.value = [...seen].join(',');
    count.textContent = seen.size + '/' + secs.length;
    for (const b of btns) b.disabled = seen.size < secs.length;
  };
  for (const s of secs) s.addEventListener('toggle', () => {
    if (s.open) { seen.add(s.dataset.key); s.classList.add('seen'); update(); }
  });
  for (const p of document.querySelectorAll('pre.md-src')) {
    if (!window.MdLite) break;
    const div = document.createElement('div');
    div.innerHTML = window.MdLite.render(p.textContent);
    p.replaceWith(div);
  }
  form.addEventListener('submit', (e) => {
    const b = e.submitter;
    if (b && /^(no|reject|skip|decline)$/i.test(b.value) && !form.reason.value.trim()) {
      e.preventDefault();
      form.reason.focus();
    }
  });
  update();
})();`;
