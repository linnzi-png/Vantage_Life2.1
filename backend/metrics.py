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


def show_rate(sits: int, n1: int, sets: int) -> float:
    """Show Rate percentage: (Sits + N1) / Sets.

    How many booked appointments actually turned into a face-to-face. It is the
    mirror image of close_rate on the N1 question, and for the opposite reason:
    an N1 person DID show up — they sat down and went through the presentation —
    they simply could not be insured afterwards. So they belong in the numerator
    here, while close_rate leaves them out because they were never sellable.

    Since the SITS column already excludes N1 visits (see close_rate), N1 has to
    be added back to recover the true number of appointments kept. Read off the
    WAR reports themselves, which compute this column as
    `=IFERROR(SUM(H+L)/G,0)` per agent — H=SITS, L=N1, G=SETS — and the same
    shape again in the leadership summary block, `=IFERROR((G2+R2)/F2,0)`.

    Returns 0 when no appointments were set.
    """
    return ((sits + n1) / sets * 100) if sets > 0 else 0
