from typing import Dict, List
from app.integrations.analyzer_adapter import CodeAnalyzerAdapter
from app.schemas.analysis import AnalysisResponse
from app.core.logging_config import logger


class AnalyzerService:
    """Service handling code change impact analysis business logic."""

    def __init__(self, adapter: CodeAnalyzerAdapter = None):
        self.adapter = adapter or CodeAnalyzerAdapter()

    def analyze_git_diff(self, git_diff: str) -> AnalysisResponse:
        """
        Processes Git diff through the AST/NetworkX analyzer adapter.

        Returns structured analysis response with changed functions,
        impacted functions, and impacted modules.
        """
        logger.info("Starting code change impact analysis for provided Git diff...")
        raw_result: Dict[str, List[str]] = self.adapter.analyze_diff(git_diff)

        response = AnalysisResponse(
            changed_functions=raw_result.get("changed_functions", []),
            impacted_functions=raw_result.get("impacted_functions", []),
            impacted_modules=raw_result.get("impacted_modules", []),
        )
        logger.info(
            f"Analysis complete: {len(response.changed_functions)} changed, "
            f"{len(response.impacted_functions)} impacted functions."
        )
        return response
