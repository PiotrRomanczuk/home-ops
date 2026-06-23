#!/usr/bin/env python3
"""rhcsa_log — emit ``app:rhcsa`` study events to home-ops.

First real consumer of ``home_ops_log.py``. Run it from the Mac / lab
terminal during RHCSA (EX200) study so sessions, exercise attempts and
timed simulations show up in the home-ops console (source ``app:rhcsa``)
and feed the planned ``rhcsa_progress`` dashboard.

Env (same secret the watchers use):
  INGEST_URL    http://192.168.1.75:64421/api/ingest            (on LAN)
                http://elitedesk.tail266853.ts.net:64421/api/ingest (off-LAN)
  INGEST_TOKEN  shared ingest secret

Best-effort: if home-ops is unreachable the event is dropped (a stderr
note from the client) but the local one-line confirmation still prints,
so this doubles as an offline study log.

Examples:
  rhcsa_log start "shell + pipes drill" --week 1
  rhcsa_log exercise 1 --minutes 4.2 --week 1            # passes unless --fail
  rhcsa_log exercise 8 --fail --note "fcontext vs restorecon"
  rhcsa_log sim --minutes 142 --score 240               # timed 150-min run, /300
  rhcsa_log weak "autofs idle-unmount timeout"
  rhcsa_log done --minutes 95
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run in place: import the sibling client without vendoring.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import home_ops_log as hops  # noqa: E402


def _minutes_to_ms(minutes: float | None) -> int | None:
    """duration_ms is a well-known home-ops data key (integer ms)."""
    return round(minutes * 60_000) if minutes is not None else None


def _emit(message: str, level: str, data: dict[str, object]) -> None:
    clean = {k: v for k, v in data.items() if v is not None}
    hops.event(message, level=level, data=clean or None)
    # Local confirmation — prints even when home-ops is unreachable.
    suffix = f"  {clean}" if clean else ""
    print(f"[app:rhcsa] {level}: {message}{suffix}")


def cmd_start(args: argparse.Namespace) -> None:
    _emit("study_started", "info", {"topic": args.topic, "week": args.week})


def cmd_done(args: argparse.Namespace) -> None:
    _emit("study_ended", "info",
          {"duration_ms": _minutes_to_ms(args.minutes), "week": args.week})


def cmd_exercise(args: argparse.Namespace) -> None:
    passed = not args.fail  # default to a pass; --fail records a miss
    verb = "passed" if passed else "failed"
    _emit(
        f"exercise_{args.n:02d}_{verb}",
        "info" if passed else "warn",
        {"exercise": args.n, "duration_ms": _minutes_to_ms(args.minutes),
         "week": args.week, "note": args.note},
    )


def cmd_sim(args: argparse.Namespace) -> None:
    _emit("timed_sim_done", "info",
          {"duration_ms": _minutes_to_ms(args.minutes),
           "score": args.score, "week": args.week})


def cmd_weak(args: argparse.Namespace) -> None:
    _emit("weak_point", "warn", {"topic": args.text, "week": args.week})


def cmd_note(args: argparse.Namespace) -> None:
    _emit(args.text, args.level, {"week": args.week})


def build_parser() -> argparse.ArgumentParser:
    # --week is shared and may follow the subcommand (argparse parent trick).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--week", type=int, default=None,
                        help="RHCSA study week (1-8) to tag the event")

    p = argparse.ArgumentParser(
        prog="rhcsa_log", description="Emit app:rhcsa study events to home-ops.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", parents=[common], help="session start")
    s.add_argument("topic", help="what you are drilling")
    s.set_defaults(func=cmd_start)

    d = sub.add_parser("done", parents=[common], help="session end")
    d.add_argument("--minutes", type=float, default=None)
    d.set_defaults(func=cmd_done)

    e = sub.add_parser("exercise", parents=[common],
                       help="record an exercise attempt (passes unless --fail)")
    e.add_argument("n", type=int, help="exercise number 1-10")
    e.add_argument("--minutes", type=float, default=None,
                   help="time from clean snapshot to pass")
    e.add_argument("--fail", action="store_true", help="record a failed attempt")
    e.add_argument("--note", default=None)
    e.set_defaults(func=cmd_exercise)

    m = sub.add_parser("sim", parents=[common], help="record a timed simulation")
    m.add_argument("--minutes", type=float, default=None)
    m.add_argument("--score", type=int, default=None, help="points out of 300")
    m.set_defaults(func=cmd_sim)

    w = sub.add_parser("weak", parents=[common], help="log a weak point")
    w.add_argument("text")
    w.set_defaults(func=cmd_weak)

    n = sub.add_parser("note", parents=[common], help="generic event")
    n.add_argument("text")
    n.add_argument("--level", default="info",
                   choices=["debug", "info", "warn", "error"])
    n.set_defaults(func=cmd_note)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hops.init("rhcsa")
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
