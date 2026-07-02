import pytest

from solution import parse_duration


def test_hours_minutes():
    assert parse_duration("1h30m") == 5400


def test_seconds_only():
    assert parse_duration("90s") == 90


def test_mixed_order():
    assert parse_duration("5s2m") == 125


def test_all_units():
    assert parse_duration("1h1m1s") == 3661


def test_zero():
    assert parse_duration("0s") == 0


@pytest.mark.parametrize("bad", ["", "m5", "1h1h", "3x", "5", "1h 30m"])
def test_malformed(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
