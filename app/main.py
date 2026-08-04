from fastapi import FastAPI

from app.routers import health

app = FastAPI(title="ReviewPilot Backend")

app.include_router(health.router)
