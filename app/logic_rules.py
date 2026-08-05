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

# Health & safety keywords (LOGIC.md §2) — case-insensitive substring match.
# Polish + English, v1 list. Extend via a dated LOGIC.md changelog entry.
HEALTH_KEYWORDS = (
    "zatrucie",
    "zatrułem",
    "zatrułam",
    "salmonella",
    "sanepid",
    "robak",
    "karaluch",
    "mysz",
    "szczur",
    "włos w",
    "pleśń",
    "niedogotowan",
    "surowe mięso",
    "brudn",
    "food poisoning",
    "poisoned",
    "sick after",
    "cockroach",
    "rat",
    "mouse",
    "mold",
    "hair in",
    "raw chicken",
    "dirty",
)
