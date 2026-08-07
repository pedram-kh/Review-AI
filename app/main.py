from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, auth, billing, customer, health

app = FastAPI(title="ReviewPilot Backend")

# Restricted to the dashboard's own origin(s) (SPRINT_03.md ticket 3.1) — no wildcard. In practice
# the Next.js app calls /api/admin/* only from its server (SPRINT_03.md rule 3: the admin key
# never ships to a browser), so this is defense-in-depth rather than the primary access control.
#
# LEGACY_APP_ORIGINS: the pre-app.reviewguide.eu-cutover Netlify default domain, kept allowed
# alongside the current settings.app_origin so any still-open tab or bookmarked link on the old
# origin (found live during ticket 4.5's Stakeholder walkthrough — the two origins can otherwise
# diverge silently, as they briefly did here) doesn't get a CORS rejection on top of whatever
# else is wrong with it. Remove once confident nothing legitimate still calls from it.
LEGACY_APP_ORIGINS = ["https://dynamic-puppy-631956.netlify.app"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin, *LEGACY_APP_ORIGINS],
    allow_methods=["GET", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)

app.include_router(health.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(customer.router)
