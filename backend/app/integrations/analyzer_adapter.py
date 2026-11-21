from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from app.core.exceptions import AnalyzerIntegrationError
from app.core.logging_config import logger
from code_analyzer.impact_analyzer import analyze_code_impact


class BaseAnalyzerAdapter(ABC):
    """Abstract interface defining the code change impact analyzer adapter."""

    @abstractmethod
    def analyze_diff(self, git_diff: str, source_files: List[str]) -> Dict[str, Any]:
        """Analyze a Git diff against the supplied Python source files."""
        raise NotImplementedError


class CodeAnalyzerAdapter(BaseAnalyzerAdapter):
    """Adapter for the in-repository AST and NetworkX code impact analyzer."""

    _custom_analyzer: Optional[Callable[[str, List[str]], Dict[str, Any]]] = None

    @classmethod
    def register_custom_analyzer(
        cls, analyzer_func: Optional[Callable[[str, List[str]], Dict[str, Any]]]
    ) -> None:
        """Register an analyzer override, primarily for tests and dependency injection."""
        cls._custom_analyzer = analyzer_func

    def analyze_diff(self, git_diff: str, source_files: List[str]) -> Dict[str, Any]:
        """Run the real analyzer (or registered override) and preserve its full report."""
        if not isinstance(git_diff, str) or not git_diff.strip():
            raise AnalyzerIntegrationError("Git diff is empty or invalid.")
        if not isinstance(source_files, list) or any(
            not isinstance(path, str) or not path.strip() for path in source_files
        ):
            raise AnalyzerIntegrationError("Source files must be a list of non-empty file paths.")

        analyzer = self.__class__._custom_analyzer or analyze_code_impact
        try:
            result = analyzer(git_diff, source_files)
        except Exception as exc:
            logger.error("Code analyzer execution failed: %s", exc, exc_info=True)
            raise AnalyzerIntegrationError(f"Code analyzer execution failed: {exc}") from exc

        return self._validate_result(result)

    @staticmethod
    def _validate_result(raw_result: Any) -> Dict[str, Any]:
        """Check the analyzer's required top-level shape without altering its data."""
        if not isinstance(raw_result, dict):
            raise AnalyzerIntegrationError("Analyzer returned an invalid response: expected a dictionary.")

        required_types = {
            "success": bool,
            "changed_files": list,
            "changed_functions": list,
            "impacted_functions": list,
            "unassigned_changed_lines": list,
            "errors": list,
            "summary": dict,
        }
        for key, expected_type in required_types.items():
            if key not in raw_result:
                raise AnalyzerIntegrationError(f"Analyzer response is missing required field '{key}'.")
            if not isinstance(raw_result[key], expected_type):
                raise AnalyzerIntegrationError(
                    f"Analyzer response field '{key}' must be {expected_type.__name__}."
                )

        return raw_result
