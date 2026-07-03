"""Close Rate math. N1 excluded per business rule: Close Rate = Sales / (Sits - N1)."""
import metrics


def test_n1_is_excluded_from_denominator():
    # 5 sales / (10 sits - 2 n1) = 62.5%, NOT 5/10 = 50%
    assert metrics.close_rate(sales=5, sits=10, n1=2) == 62.5


def test_zero_n1_is_plain_ratio():
    assert metrics.close_rate(sales=5, sits=10, n1=0) == 50.0


def test_no_eligible_sits_returns_zero():
    assert metrics.close_rate(sales=3, sits=3, n1=3) == 0
    assert metrics.close_rate(sales=0, sits=0, n1=0) == 0


def test_n1_exceeding_sits_returns_zero_not_negative():
    assert metrics.close_rate(sales=1, sits=2, n1=5) == 0


def test_eligible_sits():
    assert metrics.eligible_sits(sits=10, n1=3) == 7
    assert metrics.eligible_sits(sits=0, n1=0) == 0
