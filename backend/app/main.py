from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import ChangeGuardException
from app.core.logging_config import logger, setup_logging
from app.core.upload_limit import MULTIPART_REQUEST_OVERHEAD_BYTES, ProjectUploadLimitMiddleware
from app.database.connection import init_db
from app.routes.analysis import router as analysis_router
from app.routes.execution import router as execution_router
from app.routes.reports import router as reports_router
from app.routes.testing import router as testing_router
from app.routes.projects import router as projects_router
from app.services.project_workspace_service import ProjectWorkspaceService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown events."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("Initializing ChangeGuard AI backend services...")
    init_db()
    try:
        removed = ProjectWorkspaceService().cleanup_expired_workspaces()
        if removed:
            logger.info("Removed %s expired or incomplete project workspace(s).", removed)
    except Exception as exc:
        # Upload support is opt-in; existing API routes remain available when
        # its dedicated private workspace has not been configured.
        logger.warning("Project workspace cleanup was unavailable: %s", exc)
    yield
    logger.info("ChangeGuard AI backend shutdown complete.")


# Initialize FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "ChangeGuard AI is an AI-assisted Code Change Impact Analysis and "
        "Regression Testing platform designed to safely analyze Git diffs, identify impacted "
        "code paths, select relevant regression tests, run isolated pytest suites, and evaluate deployment risk."
    ),
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Configure CORS Middleware for future React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    ProjectUploadLimitMiddleware,
    path=f"{settings.API_V1_STR}/projects",
    max_request_bytes=settings.PROJECT_UPLOAD_MAX_BYTES + MULTIPART_REQUEST_OVERHEAD_BYTES,
    max_concurrent_uploads=settings.PROJECT_UPLOAD_MAX_CONCURRENT,
)


# Global Exception Handlers
@app.exception_handler(ChangeGuardException)
async def changeguard_exception_handler(request: Request, exc: ChangeGuardException):
    """Handles domain-specific application exceptions."""
    logger.warning(f"Domain exception on {request.method} {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "status_code": exc.status_code,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles Pydantic request validation errors."""
    logger.warning(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "Request validation failed.",
            "status_code": 422,
            "details": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catches unhandled errors and returns generic message without exposing internal details."""
    logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "An unexpected internal server error occurred.",
            "status_code": 500,
        },
    )


# Health & Root Endpoints
@app.get("/health", tags=["System Health"])
def health_check():
    """Health check endpoint to verify backend service availability."""
    return {
        "status": "healthy",
        "project": "ChangeGuard AI",
    }


@app.get("/", tags=["General"])
def read_root():
    """Root endpoint providing basic API information and navigation links."""
    return {
        "title": settings.PROJECT_NAME,
        "description": "AI-assisted Code Change Impact Analysis and Regression Testing platform",
        "version": settings.VERSION,
        "docs_url": "/docs",
        "health_check": "/health",
    }


# Register API Routers
app.include_router(analysis_router, prefix=settings.API_V1_STR)
app.include_router(testing_router, prefix=settings.API_V1_STR)
app.include_router(execution_router, prefix=settings.API_V1_STR)
app.include_router(reports_router, prefix=settings.API_V1_STR)
app.include_router(projects_router, prefix=settings.API_V1_STR)


if __name__ == "__main__":
    import uvicorn

    backend_dir = Path(__file__).resolve().parent.parent
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(backend_dir))
