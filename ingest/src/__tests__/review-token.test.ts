import { describe, expect, it } from 'vitest';
import { checkReviewToken, issueReviewToken } from '../review-token.ts';

const SECRET = 'test-secret';
const NOW = 1_760_000_000;
const SHA = 'a'.repeat(40);

describe('review token', () => {
  it('accepts the token for the decision and commit it was issued for', () => {
    const t = issueReviewToken(SECRET, 7, SHA, NOW);
    expect(checkReviewToken(SECRET, t, 7, SHA, NOW + 60)).toEqual({ ok: true });
  });

  it('rejects it for another commit — a push after the page was opened', () => {
    const t = issueReviewToken(SECRET, 7, SHA, NOW);
    expect(checkReviewToken(SECRET, t, 7, 'b'.repeat(40), NOW)).toEqual({
      ok: false,
      reason: 'bad-signature',
    });
  });

  it('rejects it for another decision', () => {
    const t = issueReviewToken(SECRET, 7, SHA, NOW);
    expect(checkReviewToken(SECRET, t, 8, SHA, NOW)).toEqual({
      ok: false,
      reason: 'bad-signature',
    });
  });

  it('expires after twelve hours', () => {
    const t = issueReviewToken(SECRET, 7, SHA, NOW);
    expect(checkReviewToken(SECRET, t, 7, SHA, NOW + 12 * 3600 + 1)).toEqual({
      ok: false,
      reason: 'expired',
    });
  });

  it('rejects a missing or malformed token', () => {
    expect(checkReviewToken(SECRET, '', 7, SHA, NOW)).toEqual({
      ok: false,
      reason: 'malformed',
    });
    expect(checkReviewToken(SECRET, 'soon.abc', 7, SHA, NOW)).toEqual({
      ok: false,
      reason: 'malformed',
    });
  });
});
