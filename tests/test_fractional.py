import random

import pytest

from notesman.api.fractional import key_between


def test_basic_ordering():
    a = key_between(None, None)
    b = key_between(a, None)
    c = key_between(None, a)
    m = key_between(c, a)
    assert c < m < a < b


def test_repeated_insert_between_stays_ordered():
    lo, hi = key_between(None, None), None
    hi = key_between(lo, None)
    for _ in range(200):
        mid = key_between(lo, hi)
        assert lo < mid < hi
        hi = mid  # keep squeezing toward lo


def test_random_inserts_keep_sorted_and_unique():
    keys = [key_between(None, None)]
    for _ in range(500):
        i = random.randint(0, len(keys))
        lo = keys[i - 1] if i > 0 else None
        hi = keys[i] if i < len(keys) else None
        keys.insert(i, key_between(lo, hi))
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert not any(k.endswith("0") for k in keys)


def test_rejects_bad_bounds():
    with pytest.raises(ValueError):
        key_between("b", "a")
