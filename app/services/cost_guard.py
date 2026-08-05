"""Cost guard for all Outscraper spending — implements LOGIC.md §4 exactly.

Every code path that calls Outscraper MUST go through enforce_caps() before making a
request (see app/services/outscraper_client.py). No other module should call the
Outscraper SDK directly.
"""

from dataclasses import dataclass

MAX_PLACES_PER_RUN = 1_000
MAX_REVIEW_RECORDS_PER_RUN = 12_000

PRICE_PER_1000_PLACES_USD = 3.0
PRICE_PER_1000_REVIEW_RECORDS_USD = 3.0


class CostCapExceeded(Exception):
    """Raised when a requested run would exceed a LOGIC.md §4 cap. No API call is made."""


@dataclass(frozen=True)
class CostEstimate:
    n_places: int
    n_review_records: int
    places_cost_usd: float
    reviews_cost_usd: float

    @property
    def total_usd(self) -> float:
        return self.places_cost_usd + self.reviews_cost_usd


def estimate_cost(n_places: int, n_review_records: int) -> CostEstimate:
    """Pure cost math, no cap checks — used both by enforce_caps and for printing
    pre-flight estimates (e.g. when a job is run without --yes)."""
    return CostEstimate(
        n_places=n_places,
        n_review_records=n_review_records,
        places_cost_usd=(n_places / 1000) * PRICE_PER_1000_PLACES_USD,
        reviews_cost_usd=(n_review_records / 1000) * PRICE_PER_1000_REVIEW_RECORDS_USD,
    )


def enforce_caps(n_places: int, n_review_records: int) -> CostEstimate:
    """Raises CostCapExceeded (before any API call) if either LOGIC.md §4 cap would be
    breached. Otherwise returns the cost estimate for the requested run."""
    if n_places > MAX_PLACES_PER_RUN:
        raise CostCapExceeded(
            f"places per run capped at {MAX_PLACES_PER_RUN}, requested {n_places}"
        )
    if n_review_records > MAX_REVIEW_RECORDS_PER_RUN:
        raise CostCapExceeded(
            f"review records per run capped at {MAX_REVIEW_RECORDS_PER_RUN}, "
            f"requested {n_review_records}"
        )
    return estimate_cost(n_places, n_review_records)
