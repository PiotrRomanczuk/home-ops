"""pr_review_llm.py — the reviewer itself: two headless `claude -p` passes on
the subscription, cwd = the PR checkout, tools limited to Read/Grep/Glob.

Pass 1 (pr_review/review.md) finds problems; pass 2 (pr_review/verify.md)
re-checks every finding against the code and drops the ones it cannot
confirm. The reviewer never sees the session that wrote the code — only what
a human reviewer would: PR text, diff, repo rules and Piotr's global rules."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent / 'pr_review'
RULES = Path(os.environ.get('PR_REVIEW_RULES', '~/code/planner-mirror/_system/ai-config/global/rules')).expanduser()
RULE_FILES = ('code-quality.md', 'documentation.md', 'git-commits.md')
LOCAL_RULES = ('CLAUDE.md', 'AGENTS.md', 'web/AGENTS.md', 'web/CLAUDE.md')
MODEL = os.environ.get('PR_REVIEW_MODEL', 'opus')
TIMEOUT_S = 1800
RANK = {'bloker': 0, 'ważne': 1, 'drobne': 2}

Runner = Callable[..., subprocess.CompletedProcess]


class ReviewError(RuntimeError):
    """The CLI failed or returned no structured output — the PR is retried next run."""


def message(pr: dict[str, Any], body: str, skipped: str, checkout: Path) -> str:
    rules = '\n\n'.join(f'## {f}\n{(RULES / f).read_text(encoding="utf-8")}' for f in RULE_FILES if (RULES / f).is_file())
    local = [p for p in LOCAL_RULES if (checkout / p).is_file()]
    return (f'# PR {pr["repo"]}#{pr["number"]}: {pr["title"]}\n\n## Opis\n{pr.get("body") or "(brak)"}\n\n'
            f'## Stan CI\n{pr.get("ci") or "nieznany"}\n\n'
            f'# Reguły projektu\nPrzeczytaj w repo: {", ".join(local) or "brak plików z regułami"}\n\n'
            f'# Reguły globalne właściciela\n{rules or "(niedostępne)"}\n\n'
            f'# Poprzednia recenzja tego PR\n{pr.get("previous") or "brak"}\n\n'
            f'# Pominięte w diffie\n{skipped or "nic"}\n\n# Diff (baza origin/{pr["base"]})\n{body}')


def call(prompt: str, schema: str, stdin: str, cwd: Path, runner: Runner = subprocess.run) -> dict[str, Any]:
    cmd = ['claude', '-p', '--model', MODEL, '--system-prompt', (HERE / prompt).read_text(encoding='utf-8'),
           '--json-schema', (HERE / schema).read_text(encoding='utf-8'), '--tools', 'Read,Grep,Glob',
           '--strict-mcp-config', '--no-session-persistence', '--output-format', 'json', '--max-budget-usd', '6']
    proc = runner(cmd, input=stdin, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S)
    try:
        res = json.loads(proc.stdout or '{}')
    except json.JSONDecodeError as exc:
        raise ReviewError(f'non-JSON from claude: {proc.stdout[:200]!r}') from exc
    if res.get('is_error') or not isinstance(res.get('structured_output'), dict):
        raise ReviewError(f'claude failed: {res.get("subtype")} {str(res.get("errors") or "")[:200]}')
    return res


def merge_checks(findings: list[dict[str, Any]], checks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep confirmed findings (with the verifier's severity); count the dropped ones."""
    by_index = {c['index']: c for c in checks}
    kept = [{**f, 'severity': by_index[i]['severity']} for i, f in enumerate(findings)
            if by_index.get(i, {}).get('confirmed')]
    return sorted(kept, key=lambda f: RANK.get(f['severity'], 3)), len(findings) - len(kept)


def verdict_of(findings: list[dict[str, Any]]) -> str:
    severities = {f['severity'] for f in findings}
    return 'bloker' if 'bloker' in severities else 'zmiany' if 'ważne' in severities else 'ok'


def review(pr: dict[str, Any], body: str, skipped: str, checkout: Path, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Two passes → {verdict, summary, findings, dropped, model, cost_usd}."""
    first = call('review.md', 'review.json', message(pr, body, skipped, checkout), checkout, runner)
    out = first['structured_output']
    findings, dropped, cost = out.get('findings') or [], 0, float(first.get('total_cost_usd') or 0)
    if findings:
        second = call('verify.md', 'verify.json', f'# PR {pr["repo"]}#{pr["number"]}\n\n# Uwagi do weryfikacji\n'
                      + json.dumps(findings, ensure_ascii=False, indent=1), checkout, runner)
        findings, dropped = merge_checks(findings, second['structured_output'].get('checks') or [])
        cost += float(second.get('total_cost_usd') or 0)
    model = next(iter(first.get('modelUsage') or {}), MODEL)
    return {'verdict': verdict_of(findings), 'summary': str(out.get('summary') or '').strip()[:600],
            'findings': findings, 'dropped': dropped, 'model': model, 'cost_usd': round(cost, 4)}
