"""Metric calculation utilities.

Project convention: all business-rule metric math lives in this module,
never inline in route handlers.
"""


def close_rate(sales: int, sits: int) -> float:
    """Close Rate percentage: Sales / Sits.

    N1 is a person who cannot be insured for medical reasons. An agent has no
    control over whether someone qualifies, so an N1 must never count against
    them — and it doesn't, because the SITS column already excludes them. The
    N1 field is a separate tally of those visits, not a subset of Sits.

    This is why N1 is NOT subtracted here. Subtracting it would exclude the
    same people twice and inflate every agent's score: verified against the
    Feb-Aug 2026 WAR spreadsheets, whose own Close Rate column matched
    Sales/Sits in all 54 rows where the two formulas differ, and
    Sales/(Sits - N1) in none. Office-wide that gap was 57.2% vs 68.0%.

    Returns 0 when there are no sits.
    """
    return (sales / sits * 100) if sits > 0 else 0
