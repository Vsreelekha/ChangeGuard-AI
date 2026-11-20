from fastapi import APIRouter, Depends, status
from app.schemas.testing import TestExecutionRequest, TestExecutionResponse
from app.services.test_runner_service import TestRunnerService
from app.core.logging_config import logger

router = APIRouter(prefix="/tests", tags=["Safe Pytest Execution"])


def get_test_runner_service() -> TestRunnerService:
    return TestRunnerService()


@router.post(
    "/execute",
    response_model=TestExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Safely execute selected pytest tests in an isolated Docker container",
    description=(
        "Executes selected pytest tests against an approved project path. "
        "Strictly isolated inside a hardened Docker container with non-root execution, "
        "disabled networking, capped resources (CPU, RAM, PIDs), and read-only mounts. "
        "Host execution is forbidden if Docker is unavailable."
    ),
    responses={
        200: {"description": "Pytest execution completed with pass/fail metrics"},
        400: {"description": "Invalid test identifier or project path"},
        500: {"description": "Test execution timeout or execution runtime failure"},
        503: {"description": "Docker runner is not available (host fallback forbidden)"},
    },
)
def execute_tests_endpoint(
    payload: TestExecutionRequest,
    service: TestRunnerService = Depends(get_test_runner_service),
) -> TestExecutionResponse:
    logger.info(
        f"Received request on POST /api/v1/tests/execute for project '{payload.project_path}' "
        f"with {len(payload.selected_tests)} tests."
    )
    return service.execute_tests(
        project_path=payload.project_path,
        selected_tests=payload.selected_tests,
    )
