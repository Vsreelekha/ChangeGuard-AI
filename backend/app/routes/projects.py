from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.core.exceptions import ChangeGuardException
from app.core.logging_config import logger
from app.database.connection import get_db
from app.schemas.project import ProjectRunRequest, ProjectUploadResponse
from app.schemas.report import ReportResponse, WorkflowRunRequest
from app.services.report_service import ReportService
from app.services.project_workspace_service import ProjectWorkspaceService
from app.services.project_run_workspace_service import ProjectRunWorkspaceService


router = APIRouter(prefix="/projects", tags=["Project Uploads"])


def get_project_workspace_service() -> ProjectWorkspaceService:
    return ProjectWorkspaceService()


def get_project_report_service() -> ReportService:
    return ReportService()


def get_run_workspace_service() -> ProjectRunWorkspaceService:
    return ProjectRunWorkspaceService()


@router.post(
    "",
    response_model=ProjectUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and safely extract a Python project ZIP",
    responses={
        201: {"description": "Project archive safely extracted"},
        400: {"description": "Invalid or unsafe project archive"},
        413: {"description": "Project upload or extraction exceeds the configured limit"},
        503: {"description": "Project workspace uploads are not configured"},
    },
)
async def upload_project_endpoint(
    file: UploadFile = File(..., description="ZIP archive containing a Python project"),
    service: ProjectWorkspaceService = Depends(get_project_workspace_service),
) -> ProjectUploadResponse:
    logger.info("Received request on POST /api/v1/projects")
    try:
        result = service.create_project(file.file)
        return ProjectUploadResponse(**result)
    finally:
        await file.close()


@router.post(
    "/{project_id}/runs",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run the complete workflow for an uploaded project",
    responses={
        201: {"description": "Workflow completed and report persisted"},
        400: {"description": "Project identifier is invalid, missing, or expired"},
        503: {"description": "A workflow integration is unavailable"},
    },
)
def run_uploaded_project_endpoint(
    project_id: str,
    payload: ProjectRunRequest,
    db: Session = Depends(get_db),
    workspace_service: ProjectWorkspaceService = Depends(get_project_workspace_service),
    run_workspace_service: ProjectRunWorkspaceService = Depends(get_run_workspace_service),
    report_service: ReportService = Depends(get_project_report_service),
) -> ReportResponse:
    logger.info("Received request on POST /api/v1/projects/{project_id}/runs")
    try:
        # Keep the lease over discovery, analysis, selection, Docker execution,
        # scoring, report generation, and database commit/refresh.
        with workspace_service.lease_project_id(project_id) as project_root:
            # Create an isolated temporary copy of the uploaded project.
            # The original upload directory is never read or written by the workflow.
            # Cleanup of the run directory is guaranteed on both success and exception.
            with run_workspace_service.create_run_workspace(project_root) as run_project:
                workflow_request = WorkflowRunRequest(
                    git_diff=payload.git_diff,
                    project_path=str(run_project),
                )
                return report_service.execute_complete_workflow(
                    workflow_request,
                    db,
                    report_metadata={"project_id": project_id},
                )
    except ChangeGuardException as exc:
        # Preserve the domain status while avoiding host-path leakage through
        # integration exception messages or diagnostic details.
        logger.warning(
            "Uploaded-project workflow failed with status %s: %s",
            exc.status_code,
            exc.message,
            exc_info=True,
        )
        message = (
            "Project is invalid, unavailable, or expired."
            if exc.status_code == 400
            else "A workflow integration is unavailable."
            if exc.status_code == 503
            else "The uploaded-project workflow could not be completed."
        )
        raise ChangeGuardException(message, status_code=exc.status_code) from None
