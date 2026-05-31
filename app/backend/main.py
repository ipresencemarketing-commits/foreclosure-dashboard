from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import listings, users, billing
from config import settings

app = FastAPI(
    title="Foreclosure Finder API",
    version="1.0.0",
    docs_url="/docs" if settings.environment == "development" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(listings.router)
app.include_router(users.router)
app.include_router(billing.router)

@app.get("/health")
async def health():
    return {"status": "ok"}
