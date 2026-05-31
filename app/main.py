"""
Store Intelligence API — FastAPI entrypoint.
Structured logging middleware, CORS, graceful error handling.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.health import set_start_time
from app.ingestion import router as ingestion_router
from app.metrics import router as metrics_router
from app.funnel import router as funnel_router
from app.heatmap import router as heatmap_router
from app.anomalies import router as anomalies_router
from app.health import router as health_router
from app.dashboard import router as dashboard_router

# ─── Structured Logging Setup ─────────────────────────────────────────────────

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add extra fields if present
        for key in ("trace_id", "store_id", "endpoint", "latency_ms", 
                     "event_count", "status_code", "method"):
            if hasattr(record, key):
                log_data[key] = getattr(record, key)
        return json.dumps(log_data)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    
    logger = logging.getLogger("store_intelligence")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    # Also configure uvicorn access logs
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.handlers = [handler]
    
    return logger


logger = setup_logging()


# ─── Application Lifecycle ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    logger.info("Starting Store Intelligence API...")
    await init_db()
    set_start_time()
    logger.info("Database initialized. API ready.")
    yield
    logger.info("Shutting down Store Intelligence API...")


# ─── FastAPI Application ──────────────────────────────────────────────────────

app = FastAPI(
    title="Store Intelligence API",
    description="Real-time store analytics from CCTV detection pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Structured Logging Middleware ────────────────────────────────────────────

@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    """Log every request with trace_id, store_id, endpoint, latency_ms, status_code."""
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    
    start_time = time.time()
    
    try:
        response = await call_next(request)
    except Exception as exc:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        logger.error(
            "Request failed",
            extra={
                "trace_id": trace_id,
                "endpoint": request.url.path,
                "method": request.method,
                "latency_ms": latency_ms,
                "status_code": 500,
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "message": "An unexpected error occurred", "trace_id": trace_id},
        )
    
    latency_ms = round((time.time() - start_time) * 1000, 2)
    
    # Extract store_id from path if present
    store_id = None
    path_parts = request.url.path.strip("/").split("/")
    if "stores" in path_parts:
        idx = path_parts.index("stores")
        if idx + 1 < len(path_parts):
            store_id = path_parts[idx + 1]
    
    logger.info(
        f"{request.method} {request.url.path} -> {response.status_code}",
        extra={
            "trace_id": trace_id,
            "store_id": store_id,
            "endpoint": request.url.path,
            "method": request.method,
            "latency_ms": latency_ms,
            "status_code": response.status_code,
        },
    )
    
    # Add trace_id to response headers
    response.headers["X-Trace-ID"] = trace_id
    return response


# ─── Global Exception Handler ─────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions — no raw stack traces in responses."""
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.error(f"Unhandled exception: {exc}", extra={"trace_id": trace_id})
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "trace_id": trace_id,
        },
    )


# ─── Register Routers ────────────────────────────────────────────────────────

app.include_router(ingestion_router, tags=["ingestion"])
app.include_router(metrics_router, tags=["metrics"])
app.include_router(funnel_router, tags=["funnel"])
app.include_router(heatmap_router, tags=["heatmap"])
app.include_router(anomalies_router, tags=["anomalies"])
app.include_router(health_router, tags=["health"])
app.include_router(dashboard_router, tags=["dashboard"])

# Mount static files for dashboard
_dashboard_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
if os.path.exists(_dashboard_dir):
    app.mount("/dashboard/static", StaticFiles(directory=_dashboard_dir), name="dashboard_static")


# ─── Root Endpoint ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "Store Intelligence API",
        "version": "1.0.0",
        "endpoints": {
            "ingest": "POST /events/ingest",
            "metrics": "GET /stores/{id}/metrics",
            "funnel": "GET /stores/{id}/funnel",
            "heatmap": "GET /stores/{id}/heatmap",
            "anomalies": "GET /stores/{id}/anomalies",
            "health": "GET /health",
            "dashboard": "GET /dashboard",
        },
    }
