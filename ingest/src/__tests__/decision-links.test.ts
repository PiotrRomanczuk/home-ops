import { describe, expect, it } from 'vitest';
import { buildLink, verifyLink } from '../decision-links.ts';

const SECRET = 'test-secret';
const NOW = 1_760_000_000;

function partsOf(url: string) {
  const [, , id = '', option = '', exp = '', sig = ''] = new URL(url).pathname.split('/');
  return { id, option, exp, sig };
}

describe('decision links', () => {
  it('round-trips a signed link', () => {
    const url = buildLink(SECRET, 'http://elitedesk:64421/', { id: 7, option: 'yes', exp: NOW + 60 });
    expect(url).toBe(`http://elitedesk:64421/d/7/yes/${NOW + 60}/${partsOf(url).sig}`);
    const v = verifyLink(SECRET, partsOf(url), NOW);
    expect(v).toEqual({ ok: true, parts: { id: 7, option: 'yes', exp: NOW + 60 } });
  });

  it('rejects a tampered option', () => {
    const url = buildLink(SECRET, 'http://x', { id: 7, option: 'no', exp: NOW + 60 });
    const p = partsOf(url);
    expect(verifyLink(SECRET, { ...p, option: 'yes' }, NOW)).toEqual({ ok: false, reason: 'bad-signature' });
  });

  it('rejects a different secret', () => {
    const url = buildLink(SECRET, 'http://x', { id: 7, option: 'yes', exp: NOW + 60 });
    expect(verifyLink('other', partsOf(url), NOW)).toEqual({ ok: false, reason: 'bad-signature' });
  });

  it('rejects an expired link, even when correctly signed', () => {
    const url = buildLink(SECRET, 'http://x', { id: 7, option: 'yes', exp: NOW - 1 });
    expect(verifyLink(SECRET, partsOf(url), NOW)).toEqual({ ok: false, reason: 'expired' });
  });

  it('rejects malformed parts before touching the signature', () => {
    expect(verifyLink(SECRET, { id: 'x', option: 'yes', exp: '1', sig: '' }, NOW)).toEqual({
      ok: false,
      reason: 'malformed',
    });
    expect(verifyLink(SECRET, { id: '1', option: 'Yes!', exp: '1', sig: '' }, NOW)).toEqual({
      ok: false,
      reason: 'malformed',
    });
  });

  it('refuses to build a link with an unsafe option', () => {
    expect(() => buildLink(SECRET, 'http://x', { id: 1, option: 'a b', exp: NOW })).toThrow();
  });
});
