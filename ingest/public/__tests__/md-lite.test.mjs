/* Tests for md-lite.js — the brief renderer feeds innerHTML, so the
 * escaping guarantees matter more than the formatting.
 *
 * Run: cd ingest && npm test -- --run public/__tests__/md-lite.test.mjs
 */
import { describe, expect, it } from 'vitest';
import '../md-lite.js';

const { render } = globalThis.MdLite;

describe('md-lite safety', () => {
  it('escapes raw HTML everywhere', () => {
    const html = render('<script>alert(1)</script>\n## <img src=x onerror=alert(1)>\n- <b>x</b>');
    expect(html).not.toMatch(/<script|<img|<b>/);
    expect(html).toContain('&lt;script&gt;');
  });

  it('only links http(s) URLs', () => {
    expect(render('[x](javascript:alert)')).toBe('<p>x</p>');
    expect(render('[x](data:text/html,hi)')).toBe('<p>x</p>');
    expect(render('[site](https://example.com/a?b=1&c=2)')).toBe(
      '<p><a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">site</a></p>',
    );
  });

  it('cannot break out of the href attribute', () => {
    const html = render('[x](https://a.pl/"onmouseover="alert(1))');
    expect(html).not.toContain('"onmouseover');
    expect(html).toContain('&quot;');
  });
});

describe('md-lite formatting', () => {
  it('renders headings one level down, bold and code', () => {
    expect(render('## Top 3')).toBe('<h4>Top 3</h4>');
    expect(render('# Plan')).toBe('<h3>Plan</h3>');
    expect(render('**ważne** i `kod`')).toBe('<p><strong>ważne</strong> i <code>kod</code></p>');
  });

  it('turns wikilinks into plain text (alias wins)', () => {
    expect(render('Zob. [[home-ops]] i [[projects/Strummy|Strummy]]')).toBe('<p>Zob. home-ops i Strummy</p>');
  });

  it('groups list items, tasks and nesting', () => {
    const html = render('- jeden\n  - pod\n- [ ] do zrobienia\n- [x] zrobione\n\n1. pierwszy\n2. drugi');
    expect(html).toBe(
      [
        '<ul>',
        '<li>jeden</li>',
        '<li class="sub">pod</li>',
        '<li class="task"><span class="box">☐</span> do zrobienia</li>',
        '<li class="task done"><span class="box">☑</span> zrobione</li>',
        '</ul>',
        '<ol>',
        '<li>pierwszy</li>',
        '<li>drugi</li>',
        '</ol>',
      ].join('\n'),
    );
  });

  it('joins paragraph lines, handles rules and empty input', () => {
    expect(render('a\nb\n\n---\nc')).toBe('<p>a b</p>\n<hr>\n<p>c</p>');
    expect(render('')).toBe('');
    expect(render(null)).toBe('');
  });
});
