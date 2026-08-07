"""Google Maps share-link parsing (SPRINT_05.md ticket 5.1's connect-place endpoint).

We only hold an Outscraper key, not a Google Places API key — a Maps URL's embedded ID is only
useful to us when the URL happens to spell out a literal Places API `place_id` (the "ChIJ..."
format). Most share-link variants instead embed Google's internal Feature ID/CID (a different,
undocumented format we cannot convert to a place_id without a Places API key), so those fall
back to extracting the business name for a search rather than failing outright.

Deliberately never auto-picks a place from a name alone — silently guessing wrong here would
connect a customer to someone else's restaurant, a real product-correctness risk, not just an
inconvenience. A name-only match comes back as `suggested_query` so the caller (connect-place)
can hand it to search-place and let the customer confirm the right result, i.e. "on failure ask
for search" per the ticket.
"""

import re
import urllib.parse
from dataclasses import dataclass

import httpx

# maps.app.goo.gl / goo.gl/maps / app.goo.gl are redirect-only shorteners with no parseable path
# of their own — they must be resolved to a canonical long URL first.
SHORT_LINK_HOSTS = {"goo.gl", "maps.app.goo.gl", "app.goo.gl"}

# Some Maps URLs spell the place_id out directly, e.g. "...?q=place_id:ChIJ...".
_PLACE_ID_QUERY_PARAM = re.compile(r"place_id[:=]([A-Za-z0-9_-]{10,})")
# Opportunistic fallback: a literal ChIJ-prefixed token anywhere in the URL (place_ids are
# consistently long enough that a 10+ char cutoff after the prefix avoids matching noise).
_RAW_CHIJ = re.compile(r"(ChIJ[A-Za-z0-9_-]{10,})")
# .../maps/place/<url-encoded name>/@lat,lng,zoom... — every "share this place" link has this
# segment regardless of whether it also carries a resolvable ID.
_PLACE_NAME_SEGMENT = re.compile(r"/maps/place/([^/@?]+)")


@dataclass(frozen=True)
class ParsedMapsUrl:
    place_id: str | None
    suggested_query: str | None


def _resolve_short_link(url: str) -> str:
    """Follows a shortener redirect to its canonical long URL. Any network failure returns the
    original URL unchanged — the parsers below then simply find nothing, which collapses to the
    same 'ask for search' outcome as a URL that was never parseable in the first place."""
    try:
        response = httpx.get(url, follow_redirects=True, timeout=5.0)
        return str(response.url)
    except httpx.HTTPError:
        return url


def _extract_place_id(url: str) -> str | None:
    for pattern in (_PLACE_ID_QUERY_PARAM, _RAW_CHIJ):
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _extract_name(url: str) -> str | None:
    match = _PLACE_NAME_SEGMENT.search(url)
    if not match:
        return None
    name = urllib.parse.unquote_plus(match.group(1)).strip()
    return name or None


def parse_maps_url(url: str) -> ParsedMapsUrl:
    """Best-effort parse of a Google Maps share link. `place_id` is set only when the URL
    itself spells one out (safe to connect directly); `suggested_query` is set whenever a
    business name could be read out of the URL, regardless of whether a place_id was also
    found, so the caller always has something to prefill a search box with on failure."""
    url = url.strip()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in SHORT_LINK_HOSTS:
        url = _resolve_short_link(url)

    return ParsedMapsUrl(place_id=_extract_place_id(url), suggested_query=_extract_name(url))
