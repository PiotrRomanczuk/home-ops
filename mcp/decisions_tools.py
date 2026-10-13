"""MCP tools for the routine contract: digest cards + the decisions inbox.

Registered from server.py. These let a headless Claude run inside a routine
(seo-analyse, seo-improve, a social-post drafter …) report its result and
ask before doing anything public, with no curl plumbing in the prompt.
"""
from __future__ import annotations

import json
from typing import Any, Callable

Request = Callable[..., tuple[int, Any]]


def register(mcp: Any, request: Request) -> None:
    def out(code: int, body: Any, ok: int = 200) -> str:
        if code != ok:
            return json.dumps({'error': f'HTTP {code}', 'body': body})
        return json.dumps(body)

    @mcp.tool()
    def post_digest_card(routine: str, headline: str, status: str = 'ok', slug: str | None = None,
                         items: list[dict] | None = None, metric: dict | None = None) -> str:
        """Report this routine's run to tomorrow's digest email. Call once, at the end.

        Args:
          routine:  slug of the routine, e.g. 'seo-analyse'
          headline: ONE plain sentence, what changed (≤200 chars). Not a log.
          status:   ok | warn | fail | skipped
          items:    up to 5 of {"text": "...", "url": "https://..."} worth a tap
          metric:   {"label": "clicks 7d", "value": 12, "delta": 3, "lower_is_better": false}
        """
        body = {'routine': routine, 'headline': headline, 'status': status, 'slug': slug,
                'items': items or [], 'metric': metric}
        code, res = request('POST', '/api/cards', body=body)
        return out(code, res, 201)

    @mcp.tool()
    def create_decision(routine: str, question: str, options: list[dict] | None = None,
                        ref: str | None = None, slug: str | None = None, context_url: str | None = None,
                        detail: str | None = None, expires_hours: int = 72) -> str:
        """Ask Piotr before anything irreversible or public (publish, merge, send).

        File the question and STOP; do not perform the action in this run. The
        digest email shows it with one-tap buttons; read the answer next run
        with list_decisions(state='answered').

        Args:
          question: one sentence ending in '?', e.g. 'Merge the weekly SEO PR #52?'
          options:  2-4 of {"key": "yes", "label": "Merge", "consequence": "..."}; default yes/no
          ref:      your own handle (PR number, post id) to match the answer back
          context_url: where to look before answering (PR, draft preview)
        """
        body = {'routine': routine, 'question': question, 'ref': ref, 'slug': slug,
                'context_url': context_url, 'detail': detail, 'expires_hours': expires_hours}
        if options:
            body['options'] = options
        code, res = request('POST', '/api/decisions', body={k: v for k, v in body.items() if v is not None})
        return out(code, res, 201)

    @mcp.tool()
    def list_decisions(state: str = 'open', routine: str | None = None) -> str:
        """List decisions. state: open | answered | expired | all.

        A routine acting on answers should take answered ones whose
        consumed_at is null, act, then call consume_decision(id).
        """
        code, res = request('GET', '/api/decisions', params={'state': state, 'routine': routine})
        return out(code, res)

    @mcp.tool()
    def consume_decision(decision_id: int) -> str:
        """Mark an answered decision as acted on, so it is not handled twice."""
        code, res = request('POST', f'/api/decisions/{int(decision_id)}/consume', body={})
        return out(code, res)
