/* ============================================================
   md-lite.js — tiny safe markdown → HTML for day briefs.

   Safety model: every line is HTML-escaped FIRST, then a fixed set
   of patterns is turned into tags. Nothing from the input reaches
   the output unescaped, links accept http(s) only, so the result
   is safe for innerHTML.

   Supported: # … #### headings, - / * / 1. lists (one nesting
   level), - [ ] / - [x] task items, **bold**, `code`, [text](url),
   [[wikilink]] / [[target|alias]] → plain text, --- rules,
   paragraphs. Everything else renders as text.

   Browser: <script src="/static/md-lite.js"> → window.MdLite.
   Tests:   import '../md-lite.js' → globalThis.MdLite.
   ============================================================ */

(() => {
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);

  /* Inline patterns run on already-escaped text. */
  function inline(escaped) {
    return escaped
      .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, target, alias) => (alias || target).trim())
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, text, url) =>
        /^https?:\/\//i.test(url) ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>` : text)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  }

  const LIST_RE = /^(\s*)([-*]|\d+[.)])\s+(.*)$/;
  const TASK_RE = /^\[([ xX])\]\s+(.*)$/;

  function listItem(indent, body) {
    const t = TASK_RE.exec(body);
    const sub = indent.replace(/\t/g, '  ').length >= 2 ? ' class="sub"' : '';
    if (!t) return `<li${sub}>${inline(escapeHtml(body))}</li>`;
    const done = t[1] !== ' ';
    const cls = `task${done ? ' done' : ''}${sub ? ' sub' : ''}`;
    return `<li class="${cls}"><span class="box">${done ? '☑' : '☐'}</span> ${inline(escapeHtml(t[2]))}</li>`;
  }

  function render(md) {
    const out = [];
    let list = null; // 'ul' | 'ol' | null
    let para = [];
    const flushPara = () => { if (para.length) out.push(`<p>${para.join(' ')}</p>`); para = []; };
    const closeList = () => { if (list) out.push(`</${list}>`); list = null; };
    for (const raw of String(md || '').replace(/\r\n?/g, '\n').split('\n')) {
      const line = raw.replace(/\s+$/, '');
      const head = /^(#{1,4})\s+(.*)$/.exec(line);
      const item = LIST_RE.exec(line);
      if (!line.trim()) { flushPara(); closeList(); continue; }
      if (head) {
        flushPara(); closeList();
        const lvl = Math.min(head[1].length + 2, 6); // # → h3: the brief sits inside a page section
        out.push(`<h${lvl}>${inline(escapeHtml(head[2]))}</h${lvl}>`);
      } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
        flushPara(); closeList(); out.push('<hr>');
      } else if (item) {
        flushPara();
        const kind = /\d/.test(item[2]) ? 'ol' : 'ul';
        if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
        out.push(listItem(item[1], item[3]));
      } else {
        closeList(); para.push(inline(escapeHtml(line.trim())));
      }
    }
    flushPara(); closeList();
    return out.join('\n');
  }

  globalThis.MdLite = { render, escapeHtml, inline };
})();
