"""Metric calculation utilities.

Project convention: all business-rule metric math lives in this module,
never inline in route handlers.
"""


def eligible_sits(sits: int, n1: int) -> int:
    """Sits that count toward Close Rate. N1 excluded per business rule."""
    return sits - n1


def close_rate(sales: int, sits: int, n1: int) -> float:
    """Close Rate percentage.

    N1 excluded per business rule: Close Rate = Sales / (Sits - N1)
    Returns 0 when there are no eligible sits.
    """
    es = eligible_sits(sits, n1)
    return (sales / es * 100) if es > 0 else 0
