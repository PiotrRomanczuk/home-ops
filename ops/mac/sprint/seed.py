#!/usr/bin/env python3
"""seed.py — write the sprint's starting queue (run once, before the runner).

  1. vault pilot (one note) → Opus review of the pilot → the other notes
  2. one independent review per open PR (read-only, verdict in results/)
Everything after that is the planner's choice (planner.md).

Usage: seed.py [--pilot lesson-notes]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import lifecycle
import sprint_tasks as q

STATE = Path('~/.local/state/home-ops/sprint').expanduser()
VAULT = Path('~/Obsidian/MainCV-Planner').expanduser()
CODE = Path('~/code').expanduser()
METHOD = STATE / 'vault-method.md'
PILOT = sys.argv[sys.argv.index('--pilot') + 1] if '--pilot' in sys.argv else 'lesson-notes'


def task(tid: str, body: str, **meta: object) -> None:
    q.write(STATE / 'queue' / f'{tid}.md', {'id': tid, **meta, 'attempts': 0, 'body': body})


def active_notes() -> list[Path]:
    notes = []
    for path in sorted([*VAULT.glob('1-Projekty/**/*.md'), *VAULT.glob('2-Obszary/**/*.md')]):
        head = path.read_text(errors='replace')[:1500]
        if re.search(r'^status:\s*(hot|warm)\s*$', head, re.M) and re.search(r'^type:\s*project', head, re.M):
            notes.append(path)
    return notes


def vault_body(note: Path, extra: str = '') -> str:
    rel = note.relative_to(VAULT)
    return (f'Uporządkuj notatkę projektu `{rel}` w vaulcie według metody z pliku `{METHOD}` (przeczytaj go w całości).\n'
            f'{extra}Edytujesz tylko tę jedną notatkę. Kryterium ukończenia: Now ≤ 3 zadań z klasą, rozmiarem i '
            f'akceptacją; sekcje „Czeka na Piotra” i „Dziennik” istnieją; kontrola z metody przeszła; jeden commit.')


def repo_dirs() -> dict[str, Path]:
    out = {}
    for git in CODE.glob('*/*/.git'):
        url = subprocess.run(['git', '-C', str(git.parent), 'config', '--get', 'remote.origin.url'],
                             capture_output=True, text=True).stdout.strip()
        m = re.search(r'[:/]([^/:]+/[^/]+?)(?:\.git)?$', url)
        if m:
            out[m.group(1).lower()] = git.parent
    for git in CODE.glob('*/*/*/.git'):
        url = subprocess.run(['git', '-C', str(git.parent), 'config', '--get', 'remote.origin.url'],
                             capture_output=True, text=True).stdout.strip()
        m = re.search(r'[:/]([^/:]+/[^/]+?)(?:\.git)?$', url)
        if m:
            out[m.group(1).lower()] = git.parent
    return out


def main() -> None:
    instance = lifecycle.single_instance(STATE)  # setup() below would take the running tasks from a live runner
    if instance is None:
        sys.exit(f'the runner is running ({STATE}/runner.lock); stop it (touch STOP) before seeding')
    q.setup(STATE)
    notes = active_notes()
    pilot = next((n for n in notes if n.stem == PILOT), notes[0])
    task(f'vault-pilot-{pilot.stem}', vault_body(pilot, 'To pilotaż: w wyniku opisz też, co w metodzie było niejasne.\n'),
         project=pilot.stem, cwd=str(VAULT), model='sonnet', effort='high', kind='vault', priority=10,
         max_minutes=60, lock='vault')
    task('vault-pilot-review', (
        f'Sprawdź pilotaż porządku w notatce `{pilot.relative_to(VAULT)}`: porównaj ostatni commit tej notatki z wersją '
        f'z taga `sprint-start-2026-11-14` (`git diff sprint-start-2026-11-14 -- <ścieżka>`), z metodą `{METHOD}` i z '
        f'wynikiem `{STATE}/results/vault-pilot-{pilot.stem}.md`.\n'
        '1. Czy nic nie zginęło (każde zdanie ze starej wersji jest w nowej)? Czy zadania w Now są wykonalne bez Piotra, '
        'krótkie i mają sensowną klasę? Czy „Czeka na Piotra” zawiera wszystko, co na niego czeka?\n'
        '2. Popraw notatkę, jeśli trzeba (osobny commit).\n'
        f'3. Popraw plik metody `{METHOD}` tak, żeby kolejne notatki wyszły lepiej (doprecyzuj to, co pilotaż zrobił źle; '
        'nie wydłużaj bez potrzeby).\n'
        'W wyniku: ocena pilotażu i lista zmian w metodzie.'),
         project='sprint', cwd=str(VAULT), model='opus', effort='high', kind='vault-review', priority=10,
         max_minutes=45, lock='vault', after=f'vault-pilot-{pilot.stem}')
    for note in notes:
        if note != pilot:
            task(f'vault-{note.stem.lower()}', vault_body(note), project=note.stem, cwd=str(VAULT), model='sonnet',
                 effort='medium', kind='vault', priority=20, max_minutes=45, lock='vault', after='vault-pilot-review')

    dirs = repo_dirs()
    prs = json.loads(subprocess.run(
        ['gh', 'search', 'prs', '--owner', 'PiotrRomanczuk', '--state', 'open', '--limit', '100',
         '--json', 'repository,number,title,url'], capture_output=True, text=True, check=True).stdout)
    for pr in prs:
        repo = pr['repository']['nameWithOwner']
        name = repo.split('/')[1]
        cwd = dirs.get(repo.lower(), CODE)
        task(f'review-{name.lower()}-{pr["number"]}', (
            f'Zrób niezależną recenzję PR-a {pr["url"]} („{pr["title"]}”). Tylko odczyt: `gh pr view {pr["number"]} '
            f'--repo {repo} --json title,body,headRefName,baseRefName,mergeable,statusCheckRollup,updatedAt,labels,files` '
            f'oraz `gh pr diff {pr["number"]} --repo {repo}`; kod bazowy czytaj w `{cwd}` (bez checkoutu, `git show origin/<branch>:<plik>`'
            ' po `git fetch`). Nie komentuj na GitHubie, niczego nie zmieniaj.\n'
            'W wyniku podaj: werdykt **scal / popraw / zamknij**, uzasadnienie w 3–6 punktach, znalezione błędy '
            '(plik:linia, scenariusz awarii), stan CI i konfliktów, zależność od innych PR-ów (stos), oraz dokładną listę '
            'poprawek, jeśli werdykt to „popraw” (tak, żeby inny worker mógł je wykonać).'),
             project=name, cwd=str(cwd), model='opus', effort='high', kind='pr-review', priority=30, max_minutes=30)
    print(f'{len(notes)} notatek (pilot: {pilot.stem}), {len(prs)} PR-ów → {len(list((STATE / "queue").glob("*.md")))} zadań w kolejce')


if __name__ == '__main__':
    main()
