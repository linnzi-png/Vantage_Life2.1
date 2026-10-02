"""Close Rate math: Sales / Sits.

N1 is a medical disqualification and is already left out of the Sits count at
entry, so it must NOT be subtracted again — doing so excluded those people
twice and inflated every agent's score. Corrected 2026-08-08 per owner; see
CLAUDE.md for the evidence.
"""
import metrics


def test_close_rate_is_sales_over_sits():
    assert metrics.close_rate(sales=5, sits=10) == 50.0


def test_n1_is_not_subtracted():
    """Regression: the old rule computed 5/(10-2) = 62.5%. N1 is not part of
    Sits, so the denominator stays 10 and the answer is 50%."""
    assert metrics.close_rate(sales=5, sits=10) == 50.0


def test_zero_sits_returns_zero():
    assert metrics.close_rate(sales=0, sits=0) == 0
    assert metrics.close_rate(sales=3, sits=0) == 0


def test_every_sit_closed_is_one_hundred_percent():
    assert metrics.close_rate(sales=4, sits=4) == 100.0


def test_more_sales_than_sits_exceeds_one_hundred():
    """Legitimate: one appointment can produce more than one policy."""
    assert metrics.close_rate(sales=3, sits=2) == 150.0


def test_eligible_sits_helper_is_gone():
    """It only existed to subtract N1; keeping it invites the old rule back."""
    assert not hasattr(metrics, "eligible_sits")


# ---------------- Team views: Refs per Sit and Average ALP ----------------

def test_refs_per_sit_is_referrals_over_sits():
    assert metrics.refs_per_sit(refs_obtained=6, sits=4) == 1.5
    assert metrics.refs_per_sit(refs_obtained=0, sits=10) == 0


def test_refs_per_sit_is_a_ratio_not_a_percentage():
    assert metrics.refs_per_sit(refs_obtained=5, sits=5) == 1.0


def test_refs_per_sit_with_zero_sits_returns_zero():
    assert metrics.refs_per_sit(refs_obtained=0, sits=0) == 0
    assert metrics.refs_per_sit(refs_obtained=7, sits=0) == 0   # referrals with no appointment kept: no ratio


def test_alp_per_sale_is_gross_alp_over_sales():
    assert metrics.alp_per_sale(gross_alp=1800.0, sales=3) == 600.0


def test_alp_per_sale_with_zero_sales_returns_zero():
    assert metrics.alp_per_sale(gross_alp=0.0, sales=0) == 0
    assert metrics.alp_per_sale(gross_alp=950.0, sales=0) == 0
