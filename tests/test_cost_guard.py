import pytest

from app.services.cost_guard import (
    MAX_PLACES_PER_RUN,
    MAX_REVIEW_RECORDS_PER_RUN,
    CostCapExceeded,
    enforce_caps,
    estimate_cost,
)


def test_estimate_cost_math() -> None:
    estimate = estimate_cost(n_places=1000, n_review_records=12000)
    assert estimate.places_cost_usd == pytest.approx(3.0)
    assert estimate.reviews_cost_usd == pytest.approx(36.0)
    assert estimate.total_usd == pytest.approx(39.0)


def test_estimate_cost_zero() -> None:
    estimate = estimate_cost(n_places=0, n_review_records=0)
    assert estimate.total_usd == 0


def test_enforce_caps_within_limits_returns_estimate() -> None:
    estimate = enforce_caps(n_places=500, n_review_records=6000)
    assert estimate.n_places == 500
    assert estimate.n_review_records == 6000
    assert estimate.total_usd == pytest.approx(1.5 + 18.0)


def test_enforce_caps_at_exact_limit_passes() -> None:
    estimate = enforce_caps(
        n_places=MAX_PLACES_PER_RUN, n_review_records=MAX_REVIEW_RECORDS_PER_RUN
    )
    assert estimate.n_places == MAX_PLACES_PER_RUN


def test_enforce_caps_places_over_limit_raises() -> None:
    with pytest.raises(CostCapExceeded):
        enforce_caps(n_places=MAX_PLACES_PER_RUN + 1, n_review_records=0)


def test_enforce_caps_reviews_over_limit_raises() -> None:
    with pytest.raises(CostCapExceeded):
        enforce_caps(n_places=0, n_review_records=MAX_REVIEW_RECORDS_PER_RUN + 1)
