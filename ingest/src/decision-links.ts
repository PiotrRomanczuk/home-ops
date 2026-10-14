import { createHmac, timingSafeEqual } from 'node:crypto';

// Signed one-tap links for the digest email: /d/:id/:option/:exp/:sig
//
// The email is read on a phone with no console session, and the console may
// be AUTH_PUBLIC anyway, so the link itself must prove it came from us. The
// signature covers (id, option, exp) with an HMAC keyed from DECISION_SECRET
// (falls back to INGEST_TOKEN so no new secret is required). GET on the link
// renders a confirmation page; only the POST records the answer, so a mail
// client prefetching the URL can never answer on Piotr's behalf.

const OPTION_RE = /^[a-z0-9_-]{1,32}$/;

export interface LinkParts {
  id: number;
  option: string;
  exp: number; // unix seconds
}

function sign(secret: string, p: LinkParts): string {
  return createHmac('sha256', secret).update(`${p.id}:${p.option}:${p.exp}`).digest('base64url').slice(0, 32);
}

export function isValidOption(option: string): boolean {
  return OPTION_RE.test(option);
}

export function buildLink(secret: string, base: string, p: LinkParts): string {
  if (!isValidOption(p.option)) throw new Error(`bad option: ${p.option}`);
  return `${base.replace(/\/$/, '')}/d/${p.id}/${p.option}/${p.exp}/${sign(secret, p)}`;
}

export type VerifyResult =
  | { ok: true; parts: LinkParts }
  | { ok: false; reason: 'malformed' | 'expired' | 'bad-signature' };

export function verifyLink(
  secret: string,
  raw: { id: string; option: string; exp: string; sig: string },
  nowSec = Math.floor(Date.now() / 1000),
): VerifyResult {
  const id = Number(raw.id);
  const exp = Number(raw.exp);
  if (!Number.isInteger(id) || id <= 0 || !Number.isInteger(exp) || !isValidOption(raw.option)) {
    return { ok: false, reason: 'malformed' };
  }
  const parts = { id, option: raw.option, exp };
  const expected = Buffer.from(sign(secret, parts));
  const given = Buffer.from(raw.sig);
  if (expected.length !== given.length || !timingSafeEqual(expected, given)) {
    return { ok: false, reason: 'bad-signature' };
  }
  if (exp < nowSec) return { ok: false, reason: 'expired' };
  return { ok: true, parts };
}
