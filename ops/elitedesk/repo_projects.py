"""repo_projects — which GitHub repo each project lives in, for github-repo-sync.

The vault is the source of truth (frontmatter `repo:`, synced into the
projects table); github-repo-sync.projects.json only overrides: deploy_url,
manifest, a local bare repo, or "unsupported". Pure functions, no network.
"""
from __future__ import annotations

from typing import Any

SKIP_VERDICTS = {'usunięty'}


def vault_entries(projects: list[dict[str, Any]], owner: str) -> dict[str, dict[str, Any]]:
    """GET /api/projects rows → slug → {owner_repo} for notes with a `repo:`."""
    out: dict[str, dict[str, Any]] = {}
    for p in projects:
        fm = p.get('raw_frontmatter') or {}
        repo = str(fm.get('repo') or '').strip().strip('"\'')
        if not repo or repo == '-' or fm.get('verdict') in SKIP_VERDICTS:
            continue
        out[p['slug']] = {'owner_repo': repo if '/' in repo else f'{owner}/{repo}'}
    return out


def merged_mapping(json_map: dict[str, dict[str, Any]], vault: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Vault entries + JSON overrides. A JSON entry that points somewhere else
    (local_git_dir, unsupported) replaces the vault repo instead of mixing."""
    out = {slug: dict(cfg) for slug, cfg in vault.items()}
    for slug, cfg in json_map.items():
        elsewhere = 'owner_repo' not in cfg and bool(cfg.keys() & {'local_git_dir', 'unsupported'})
        out[slug] = {**({} if elsewhere else out.get(slug, {})), **cfg}
    return out
