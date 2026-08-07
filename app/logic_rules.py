"""Lead qualification constants (LOGIC.md §1, §2).

MUST match docs/LOGIC.md — change only together, with a dated changelog entry there.
"""

import re

# Q1 — star rating cap (LOGIC.md §1)
MAX_RATING_FOR_LEAD = 3

# Q3 — review must be this fresh at detection time (LOGIC.md §1)
MAX_REVIEW_AGE_DAYS = 30

# Q4 — minimum review text length (LOGIC.md §1)
MIN_TEXT_LENGTH = 80

# Q5 — allowed review languages, ISO 639-1 codes (LOGIC.md §1)
ALLOWED_LANGUAGES = frozenset({"pl", "en"})

# Health & safety keywords (LOGIC.md §2, v1.1) — case-insensitive, two tiers.
# Polish + English. Extend/modify only via a dated LOGIC.md changelog entry.

# Tier 1 — whole-word match (regex \b boundaries). Short standalone words that would produce
# false positives as plain substrings (e.g. "rat" inside the Polish word "akurat").
HEALTH_KEYWORDS_WHOLE_WORD = (
    "robak",
    "robaki",
    "karaluch",
    "mysz",
    "myszy",
    "szczur",
    "szczury",
    "pleśń",
    "rat",
    "rats",
    "mouse",
    "mice",
    "mold",
    "dirty",
    "poisoned",
)

# Tier 2 — substring match (label, regex pattern). Stems/phrases where we deliberately want
# to catch inflections (e.g. "zatru" catches zatrucie/zatrułem/zatrułam/zatruta...).
#
# LOGIC.md v1.2: "zatru" gets a negative lookahead excluding "zatru" + "dni" — a second live
# false positive found in ticket 1.5's milestone run ("zatrudnieniu"/"zatrudnić", the unrelated
# Polish employment/hiring word family). Genuine hits (zatrucie, zatrułem, zatrułam) are unaffected.
HEALTH_KEYWORDS_SUBSTRING = (
    ("zatru", r"zatru(?!dni)"),
    ("salmonell", re.escape("salmonell")),
    ("sanepid", re.escape("sanepid")),
    ("włos w", re.escape("włos w")),
    ("niedogotowan", re.escape("niedogotowan")),
    ("surowe mięso", re.escape("surowe mięso")),
    ("brudn", re.escape("brudn")),
    ("food poisoning", re.escape("food poisoning")),
    ("sick after", re.escape("sick after")),
    ("cockroach", re.escape("cockroach")),
    ("hair in", re.escape("hair in")),
    ("raw chicken", re.escape("raw chicken")),
)

_WHOLE_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in HEALTH_KEYWORDS_WHOLE_WORD) + r")\b",
    re.IGNORECASE,
)


def detect_health_keyword(text: str) -> str | None:
    """LOGIC.md §2 keyword match (both tiers). Shared by app/jobs/qualify.py (System A leads)
    and app/jobs/day_one.py (System B customer product, SPRINT_05.md ticket 5.1) — moved here
    from qualify.py so the one regex-matching implementation can't drift between the two call
    sites (qualify.py re-exports it as `_detect_health_keyword` for its existing tests)."""
    whole_word_match = _WHOLE_WORD_PATTERN.search(text)
    if whole_word_match:
        return whole_word_match.group(1).lower()

    for label, pattern in HEALTH_KEYWORDS_SUBSTRING:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return None
