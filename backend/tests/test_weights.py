from copy import deepcopy
import random

import pytest

from app.weights import RuleError, merge_remote, redistribute


def row(oid, pin=None, removed=False):
    return dict(offer_id=oid, name=str(oid), share=0, pinned_share=pin, removed=removed)


def test_integer_remainders_and_input_immutability():
    original = [row(1), row(2), row(3)]
    assert [r['share'] for r in redistribute(original)] == [34, 33, 33]
    assert original[0]['share'] == 0


def test_pinned_and_archive():
    result = redistribute([row(1, 25), row(2), row(3), row(4, 50, removed=True)])
    assert [r['share'] for r in result] == [25, 38, 37, 0]


@pytest.mark.parametrize('rows', [[row(1, 80), row(2, 30)], [row(1, 25)], [row(1, removed=True)]])
def test_invalid_distributions(rows):
    with pytest.raises(RuleError):
        redistribute(rows)


def test_all_pinned_exactly_100():
    assert [r['share'] for r in redistribute([row(1, 30), row(2, 70)])] == [30, 70]


def test_many_distributions_have_exact_total_and_equal_free_shares():
    rng = random.Random(17)
    for _ in range(300):
        pinned = rng.randrange(101)
        count = rng.randrange(1, 30)
        rows = redistribute([row(0, pinned)] + [row(i + 1) for i in range(count)])
        free = [r['share'] for r in rows[1:]]
        assert sum(r['share'] for r in rows) == 100
        assert rows[0]['share'] == pinned
        assert max(free) - min(free) <= 1


def test_external_removal_keeps_archive_and_pin():
    previous = redistribute([row(1, 25), row(2)])
    result = merge_remote(previous, [dict(offer_id=2, share=100)], {2: 'Updated'})
    assert result[0]['removed'] and result[0]['share'] == 0
    assert result[0]['pinned_share'] == 25
    assert result[1]['name'] == 'Updated'
    assert not previous[0]['removed']
