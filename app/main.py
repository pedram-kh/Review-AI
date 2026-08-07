from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, auth, billing, health

app = FastAPI(title="ReviewPilot Backend")

# Restricted to the dashboard's own origin (SPRINT_03.md ticket 3.1) — no wildcard. In practice
# the Next.js app calls /api/admin/* only from its server (SPRINT_03.md rule 3: the admin key
# never ships to a browser), so this is defense-in-depth rather than the primary access control.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin],
    allow_methods=["GET", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)

app.include_router(health.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(billing.router)
