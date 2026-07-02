from solution import rle_encode


def test_runs():
    assert rle_encode("aaabccdddd") == "a3bc2d4"


def test_no_runs():
    assert rle_encode("abc") == "abc"


def test_empty():
    assert rle_encode("") == ""


def test_digits_are_chars():
    assert rle_encode("aab11") == "a2b12"


def test_single_long_run():
    assert rle_encode("z" * 12) == "z12"
