from typing import Any, Dict, List, Optional

from app.core.exceptions import AnalyzerIntegrationError
from app.core.logging_config import logger
from app.integrations.analyzer_adapter import BaseAnalyzerAdapter, CodeAnalyzerAdapter


class AnalyzerService:
    """Service handling code change impact analysis business logic."""

    def __init__(self, adapter: Optional[BaseAnalyzerAdapter] = None):
        self.adapter = adapter if adapter is not None else CodeAnalyzerAdapter()

    def analyze_git_diff(self, git_diff: str, source_files: List[str]) -> Dict[str, Any]:
        """Analyze a diff against supplied source files and return the full report."""
        logger.info("Starting code change impact analysis for provided Git diff...")
        result = self.adapter.analyze_diff(git_diff, source_files)

        if not result.get("success"):
            raise AnalyzerIntegrationError(
                "Code change impact analysis did not complete successfully.",
                details=result,
            )

        summary = result.get("summary", {})
        logger.info(
            "Analysis complete: %s changed, %s impacted functions.",
            summary.get("changed_functions_count", len(result.get("changed_functions", []))),
            summary.get("impacted_functions_count", len(result.get("impacted_functions", []))),
        )
        return result
