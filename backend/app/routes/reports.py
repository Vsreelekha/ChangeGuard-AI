from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.schemas.report import (
    ReportCreateRequest,
    ReportResponse,
    WorkflowRunRequest,
)
from app.services.report_service import ReportService
from app.core.logging_config import logger

router = APIRouter(tags=["Risk Reports & Workflow"])


def get_report_service() -> ReportService:
    return ReportService()


@router.post(
    "/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and persist a risk assessment report",
    description=(
        "Calculates deterministic deployment risk (HIGH, MEDIUM, LOW) using provided "
        "code impact metrics and test execution evidence, and persists the record to PostgreSQL."
    ),
    responses={
        201: {"description": "Risk report successfully generated and saved"},
        400: {"description": "Invalid report payload"},
    },
)
def create_report_endpoint(
    payload: ReportCreateRequest,
    db: Session = Depends(get_db),
    service: ReportService = Depends(get_report_service),
) -> ReportResponse:
    logger.info("Received request on POST /api/v1/reports")
    return service.create_report(payload, db)


@router.get(
    "/reports/{run_id}",
    response_model=ReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a stored risk assessment report by Run ID",
    description="Fetches a previously executed analysis and test report from the database.",
    responses={
        200: {"description": "Report retrieved successfully"},
        404: {"description": "Report with the specified run_id was not found"},
    },
)
def get_report_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
    service: ReportService = Depends(get_report_service),
) -> ReportResponse:
    logger.info(f"Received request on GET /api/v1/reports/{run_id}")
    return service.get_report_by_id(run_id, db)


@router.post(
    "/runs",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute complete ChangeGuard AI workflow end-to-end",
    description=(
        "Coordinates the complete pipeline from Git diff to final deployment risk assessment:\n"
        "1. Analyzes Git diff (identifying changed and impacted functions/modules).\n"
        "2. Selects relevant regression tests.\n"
        "3. Executes selected tests safely in Docker (if project_path provided).\n"
        "4. Computes deterministic risk and actionable recommendations.\n"
        "5. Saves and returns the complete run record."
    ),
    responses={
        201: {"description": "Full workflow completed and report created"},
        400: {"description": "Invalid Git diff or project path"},
        503: {"description": "Required stage integration (analyzer/selector/docker) is unavailable"},
    },
)
def run_complete_workflow_endpoint(
    payload: WorkflowRunRequest,
    db: Session = Depends(get_db),
    service: ReportService = Depends(get_report_service),
) -> ReportResponse:
    logger.info("Received request on POST /api/v1/runs")
    return service.execute_complete_workflow(payload, db)
