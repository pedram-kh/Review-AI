"""Lead qualification constants (LOGIC.md §1, §2).

MUST match docs/LOGIC.md — change only together, with a dated changelog entry there.
"""

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

# Tier 2 — substring match. Stems/phrases where we deliberately want to catch inflections
# (e.g. "zatru" catches zatrucie/zatrułem/zatrułam/zatruta...).
HEALTH_KEYWORDS_SUBSTRING = (
    "zatru",
    "salmonell",
    "sanepid",
    "włos w",
    "niedogotowan",
    "surowe mięso",
    "brudn",
    "food poisoning",
    "sick after",
    "cockroach",
    "hair in",
    "raw chicken",
)
