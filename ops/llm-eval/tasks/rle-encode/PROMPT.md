Implement `rle_encode(s: str) -> str` in `solution.py`.

Run-length encode a string: each maximal run of the same character becomes
`<char><count>`, with the count omitted when it is 1.

Examples:
    rle_encode("aaabccdddd") -> "a3bc2d4"
    rle_encode("abc")        -> "abc"
    rle_encode("")           -> ""
    rle_encode("aab11")      -> "a2b12"   (digits are ordinary characters)

Only edit `solution.py`. Make every test in `test_solution.py` pass.
