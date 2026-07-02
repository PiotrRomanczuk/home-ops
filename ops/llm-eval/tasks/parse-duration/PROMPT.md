Implement `parse_duration(s: str) -> int` in `solution.py`.

Parse a compact duration string into total seconds. Units: `h` (hours),
`m` (minutes), `s` (seconds). Units may appear in any order, at most once
each, and every number is a non-negative integer. Raise `ValueError` for
anything malformed (unknown unit, repeated unit, empty string, missing
number, trailing garbage).

Examples:
    parse_duration("1h30m")   -> 5400
    parse_duration("90s")     -> 90
    parse_duration("2m5s")    -> 125
    parse_duration("m5")      -> ValueError
    parse_duration("1h1h")    -> ValueError

Only edit `solution.py`. Make every test in `test_solution.py` pass.
