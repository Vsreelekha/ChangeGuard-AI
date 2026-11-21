"""API routes package.
"""
from app.routes.analysis import router as analysis_router
from app.routes.execution import router as execution_router
from app.routes.reports import router as reports_router
from app.routes.testing import router as testing_router
from app.routes.projects import router as projects_router

__all__ = [
    "analysis_router",
    "testing_router",
    "execution_router",
    "reports_router",
    "projects_router",
]
