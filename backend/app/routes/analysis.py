from fastapi import APIRouter, Depends, status
from app.schemas.analysis import AnalysisRequest, AnalysisResponse
from app.services.analyzer_service import AnalyzerService
from app.core.logging_config import logger

router = APIRouter(prefix="/analysis", tags=["Code Change Analysis"])


def get_analyzer_service() -> AnalyzerService:
    return AnalyzerService()


@router.post(
    "",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze Git diff for changed and impacted functions",
    description=(
        "Receives a unified Git diff, validates the input, and delegates to the "
        "code analyzer integration module (Python AST & NetworkX dependency graph) "
        "to discover directly modified functions, affected downstream functions, and impacted modules."
    ),
    responses={
        200: {"description": "Impact analysis completed successfully"},
        400: {"description": "Invalid or empty Git diff provided"},
        503: {"description": "Code analyzer integration module is unavailable or pending"},
    },
)
def analyze_code_change(
    payload: AnalysisRequest,
    service: AnalyzerService = Depends(get_analyzer_service),
) -> AnalysisResponse:
    logger.info("Received request on POST /api/v1/analysis")
    return service.analyze_git_diff(payload.git_diff)
