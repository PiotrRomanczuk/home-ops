import { type DecisionRow, normalizeOptions } from './decisions-store.ts';

// The two tiny HTML pages behind a signed link: confirm (GET) and result
// (POST). Phone-first, no console chrome, no scripts. Same light palette as
// the digest email so the tap feels like a continuation of it.

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function shell(title: string, body: string): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title>
<style>
body{margin:0;background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif;padding:24px 16px}
.card{max-width:520px;margin:0 auto;background:#fff;border-radius:18px;padding:28px 24px}
.eyebrow{font-size:12px;color:#6e6e73;text-transform:uppercase;letter-spacing:.04em}
h1{font-size:22px;line-height:1.25;margin:10px 0 8px;font-weight:600;letter-spacing:-.01em}
p{font-size:15px;color:#6e6e73;margin:0 0 14px;line-height:1.45}
.q{font-size:15px;color:#1d1d1f;white-space:pre-wrap}
a{color:#0066cc;text-decoration:none}
label{display:block;font-size:13px;color:#6e6e73;margin:14px 0 6px}
input{width:100%;box-sizing:border-box;font:inherit;font-size:16px;padding:10px 12px;border:1px solid #d2d2d7;border-radius:10px;background:#fff}
button{margin-top:16px;width:100%;font:inherit;font-size:17px;font-weight:600;padding:14px;border:0;border-radius:12px;background:#1d1d1f;color:#fff}
button.no{background:#ff3b30}
.ok{color:#34c759;font-weight:600}.bad{color:#ff3b30;font-weight:600}
</style></head><body><div class="card">${body}</div></body></html>`;
}

export function confirmPage(d: DecisionRow, option: string): string {
  const opt = normalizeOptions(d.options).find((o) => o.key === option);
  const label = opt?.label ?? option;
  const isNo = /^(no|reject|skip|decline)$/i.test(option);
  const consequence = opt?.consequence ? `<p>${esc(opt.consequence)}</p>` : '';
  const ctx = d.context_url ? `<p><a href="${esc(d.context_url)}">Open the context →</a></p>` : '';
  const detail = d.detail ? `<p class="q">${esc(d.detail)}</p>` : '';
  return shell(
    `Confirm: ${label}`,
    `<div class="eyebrow">${esc(d.routine)} asks</div>
<h1>${esc(d.question)}</h1>${detail}${ctx}${consequence}
<form method="post">
<label for="reason">${isNo ? 'Why not? (one line helps the routine learn)' : 'Note (optional)'}</label>
<input id="reason" name="reason" maxlength="200" ${isNo ? 'required' : ''} autocomplete="off">
<button type="submit" class="${isNo ? 'no' : ''}">Confirm: ${esc(label)}</button>
</form>`,
  );
}

export function resultPage(d: DecisionRow, ok: boolean, message: string): string {
  const when = d.answered_at ? new Date(d.answered_at).toLocaleString('en-GB', { timeZone: 'Europe/Warsaw' }) : '';
  const label = normalizeOptions(d.options).find((o) => o.key === d.answer)?.label ?? d.answer ?? '';
  const why = d.reason ? `<p>Reason: ${esc(d.reason)}</p>` : '';
  const line = ok
    ? `<p class="ok">Recorded: ${esc(label)}${when ? ` · ${esc(when)}` : ''}</p>${why}`
    : `<p class="bad">${esc(message)}</p>`;
  const already = !ok && d.answer ? `<p>Already answered <b>${esc(label)}</b> at ${esc(when)}.</p>${why}` : '';
  return shell(
    ok ? 'Recorded' : 'Not recorded',
    `<div class="eyebrow">${esc(d.routine)}</div><h1>${esc(d.question)}</h1>${line}${already}
<p>The routine picks this up on its next run. You can close this tab.</p>`,
  );
}

export function errorPage(reason: string): string {
  const text =
    reason === 'expired'
      ? 'This link has expired. The decision is still in the console if it is still open.'
      : reason === 'not-found'
        ? 'This decision no longer exists.'
        : 'This link is not valid.';
  return shell('Link not valid', `<h1>Nothing recorded</h1><p>${esc(text)}</p>`);
}
