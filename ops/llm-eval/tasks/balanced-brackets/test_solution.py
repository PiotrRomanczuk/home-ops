from solution import is_balanced


def test_nested_mixed():
    assert is_balanced("(a[b]{c})") is True


def test_interleaved():
    assert is_balanced("([)]") is False


def test_unclosed():
    assert is_balanced("((") is False


def test_close_without_open():
    assert is_balanced(")(") is False


def test_ignores_other_chars():
    assert is_balanced("no brackets") is True


def test_empty():
    assert is_balanced("") is True
