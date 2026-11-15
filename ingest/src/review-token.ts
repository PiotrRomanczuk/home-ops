import { createHmac, timingSafeEqual } from 'node:crypto';

// The review page hands out this token; the answer is accepted only with it.
// It is bound to the decision and to the commit the page showed, so a page
// left open across a push cannot answer for code it never displayed. It is
// not a defence against someone who can open the page — it makes "accept"
// impossible without opening it first.

const TTL_SEC = 12 * 60 * 60;

export interface ReviewTokenParts {
  id: number;
  sha: string;
  exp: number; // unix seconds
}

function mac(secret: string, p: ReviewTokenParts): string {
  return createHmac('sha256', secret).update(`review:${p.id}:${p.sha}:${p.exp}`).digest('base64url').slice(0, 32);
}

export function issueReviewToken(
  secret: string,
  id: number,
  sha: string,
  nowSec = Math.floor(Date.now() / 1000),
): string {
  const exp = nowSec + TTL_SEC;
  return `${exp}.${mac(secret, { id, sha, exp })}`;
}

export type ReviewTokenCheck = { ok: true } | { ok: false; reason: 'malformed' | 'expired' | 'bad-signature' };

export function checkReviewToken(
  secret: string,
  token: string,
  id: number,
  sha: string,
  nowSec = Math.floor(Date.now() / 1000),
): ReviewTokenCheck {
  const [expRaw, sig] = token.split('.');
  const exp = Number(expRaw);
  if (!Number.isInteger(exp) || !sig) return { ok: false, reason: 'malformed' };
  const expected = Buffer.from(mac(secret, { id, sha, exp }));
  const given = Buffer.from(sig);
  if (expected.length !== given.length || !timingSafeEqual(expected, given)) {
    return { ok: false, reason: 'bad-signature' };
  }
  if (exp < nowSec) return { ok: false, reason: 'expired' };
  return { ok: true };
}
