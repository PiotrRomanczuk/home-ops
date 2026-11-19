"""Fake git/gh for the flow tests: answers by command prefix (not a test module itself)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flow_ops import Flow, Res  # noqa: E402

OK = Res(0, '', '')
REFUSED = Res(1, '', "! [remote rejected] HEAD -> test (refusing to allow a GitHub App to create or update "
                     "workflow `.github/workflows/check.yml` without `workflows` permission)")
NON_FF = Res(1, '', '! [rejected] HEAD -> test (fetch first)')
NO_PR = Res(1, '', 'pull request create failed: GraphQL: GitHub Actions is not permitted to create or approve '
                   'pull requests (createPullRequest)')


class FakeRun:
    """Answers by command prefix; a list of answers is used in order, the last one repeats."""

    def __init__(self, answers: dict[tuple[str, ...], Res | list[Res]] | None = None) -> None:
        self.answers = {k: v if isinstance(v, list) else [v] for k, v in (answers or {}).items()}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> Res:
        self.calls.append(args)
        for prefix in sorted(self.answers, key=len, reverse=True):
            if tuple(args[:len(prefix)]) == prefix:
                seq = self.answers[prefix]
                return seq.pop(0) if len(seq) > 1 else seq[0]
        return OK

    def ran(self, *prefix: str) -> list[list[str]]:
        return [c for c in self.calls if tuple(c[:len(prefix)]) == prefix]


def issues(*titles: str) -> Res:
    return Res(0, json.dumps([{'number': i + 1, 'title': t} for i, t in enumerate(titles)]), '')


def flow(run: FakeRun, has_token: bool = False) -> Flow:
    return Flow(run, has_token, 'https://run/1', 'o/r')


def moved_head(*shas: str) -> Res | list[Res]:
    return [Res(0, s + '\n', '') for s in shas]
