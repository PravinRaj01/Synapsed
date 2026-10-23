import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.ingestion import router as ingestion_router
from app.api.report import router as report_router
from app.api.runs import router as runs_router
from app.api.workspaces import router as workspaces_router
from app.core import database, name_models
from app.core.config import get_settings

logger = logging.getLogger("synapsed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().pii_warmup:  # load the name models in the background
        threading.Thread(target=name_models.warm_up, daemon=True).start()
    if get_settings().database_url:
        database.init_pool()
    else:
        logger.warning("DATABASE_URL is not set; database features are disabled")
    yield
    database.close_pool()


app = FastAPI(title="Synapsed", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(ingestion_router)
app.include_router(report_router)
app.include_router(runs_router)
app.include_router(workspaces_router)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> JSONResponse:
    """Liveness check. Pinging the database also wakes a suspended Neon compute."""
    try:
        database_ok = database.ping()
    except Exception:
        database_ok = False
    body = {
        "status": "healthy" if database_ok else "degraded",
        "app": "Synapsed",
        "database": database_ok,
    }
    return JSONResponse(status_code=200 if database_ok else 503, content=body)
