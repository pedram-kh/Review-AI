"""Thin wrapper around the Outscraper SDK.

Every method here is routed through app.services.cost_guard.enforce_caps() before any
network call — no other module should call the outscraper SDK directly. Jobs (Sprint 1
tickets 1.2/1.3) call this client; they never construct their own outscraper.ApiClient.
"""

from outscraper import ApiClient

from app.config import settings
from app.services.cost_guard import enforce_caps

DEFAULT_REVIEWS_PER_PLACE = 10


class OutscraperClient:
    def __init__(self, api_key: str | None = None) -> None:
        self._client = ApiClient(api_key or settings.outscraper_api_key)

    def search_places(self, query: str, limit: int) -> list[dict]:
        """Google Maps search for places matching `query`. Enforces the places-per-run
        cap before calling the API."""
        enforce_caps(n_places=limit, n_review_records=0)
        raw = self._client.google_maps_search(query, limit=limit, language="pl")
        return _flatten(raw)

    def fetch_reviews(
        self, place_ids: list[str], reviews_per_place: int = DEFAULT_REVIEWS_PER_PLACE
    ) -> list[dict]:
        """Fetch the newest `reviews_per_place` reviews for each place_id. Enforces the
        review-records-per-run cap (len(place_ids) * reviews_per_place) before calling
        the API. Returns one dict per place, each carrying its reviews under Outscraper's
        'reviews_data' key."""
        enforce_caps(n_places=0, n_review_records=len(place_ids) * reviews_per_place)
        raw = self._client.google_maps_reviews(
            place_ids,
            reviews_limit=reviews_per_place,
            limit=1,
            sort="newest",
            language="pl",
        )
        return _flatten(raw)


def _flatten(result: list | dict) -> list[dict]:
    """Outscraper wraps every request in an outer list keyed by query (we always send a
    single query — a search string, or a list of place_ids counted as one request), so
    the raw response is a single-element list wrapping either a list (search) or dicts
    (reviews). Normalize all shapes to a flat list[dict]."""
    if isinstance(result, dict):
        return [result]
    if not result:
        return []
    if isinstance(result[0], list):
        return [item for sublist in result for item in sublist]
    return result
