import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import reconcile
from app.database import engine, Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s"
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Reconcile.dev",
    description="A W3C-Compliant Reconciliation Service API for GeoNames geographic data",
    version="0.1.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Include the reconciliation router — all endpoints live there
app.include_router(reconcile.router)


@app.get("/health")
def health_check():
    """Simple health check so you can confirm the server is running."""
    return {"status": "ok", "service": "Reconcile.dev"}
