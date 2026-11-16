"""Which GitHub repo and which generated block belong to a vault project note.
Pure helpers shared by planner-sync's render tick and its Dziś toggle path."""
from __future__ import annotations

import re
from typing import Any, Mapping


def note_repo(fm: Mapping[str, Any], owner: str) -> str | None:
    """`owner/name` of an opted-in note (`zadania: github` + `repo:`), else None
    (not opted in, or the value is not a plain repo name)."""
    if fm.get('zadania') != 'github' or not fm.get('repo'):
        return None
    repo = str(fm['repo']) if '/' in str(fm['repo']) else f"{owner}/{fm['repo']}"
    return repo if re.fullmatch(r'[\w.-]+/[\w.-]+', repo) else None


def has_issue_block(md: str) -> bool:
    return any(line.startswith('<!-- github-issues:start') for line in md.split('\n'))


def ref_in_note_repo(ref: tuple[str, int], fm: Mapping[str, Any], owner: str) -> bool:
    """A link in a manual line may point anywhere; only the note's own repo is ours to close."""
    repo = note_repo(fm, owner)
    return repo is not None and ref[0].lower() == repo.lower()
