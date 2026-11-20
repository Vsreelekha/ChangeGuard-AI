from fastapi import APIRouter, Depends, status
from app.schemas.testing import TestSelectionRequest, TestSelectionResponse
from app.services.test_selector_service import TestSelectorService
from app.core.logging_config import logger

router = APIRouter(prefix="/tests", tags=["Intelligent Test Selection"])


def get_test_selector_service() -> TestSelectorService:
    return TestSelectorService()


@router.post(
    "/select",
    response_model=TestSelectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Select relevant regression tests for impacted functions",
    description=(
        "Receives a list of impacted functions and delegates to the intelligent "
        "test selector module to identify targeted pytest test cases with selection "
        "rationale and priority rankings."
    ),
    responses={
        200: {"description": "Relevant tests successfully selected"},
        400: {"description": "Invalid input or empty impacted functions list"},
        503: {"description": "Test selector integration module is pending or unavailable"},
    },
)
def select_tests_endpoint(
    payload: TestSelectionRequest,
    service: TestSelectorService = Depends(get_test_selector_service),
) -> TestSelectionResponse:
    logger.info("Received request on POST /api/v1/tests/select")
    return service.select_tests_for_project(payload.impact_report, payload.project_path)
