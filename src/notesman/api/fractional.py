"""Fractional indexing: order keys are strings that sort lexicographically, so moving a
question only rewrites that one row. Keys use base-62 digits in ASCII order (the column
uses the "C" collation) and never end in the lowest digit."""

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ZERO = DIGITS[0]


def _midpoint(a: str, b: str | None) -> str:
    if b is not None:
        n = 0
        while n < len(b) and (a[n] if n < len(a) else ZERO) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    da = DIGITS.index(a[0]) if a else 0
    db = DIGITS.index(b[0]) if b else len(DIGITS)
    if db - da > 1:
        return DIGITS[round(0.5 * (da + db))]
    if b and len(b) > 1:
        return b[:1]
    return DIGITS[da] + _midpoint(a[1:], None)


def key_between(a: str | None, b: str | None) -> str:
    """A key strictly between a and b (either may be None for 'no bound')."""
    if a is not None and b is not None and a >= b:
        raise ValueError("a must sort before b")
    return _midpoint(a or "", b)
