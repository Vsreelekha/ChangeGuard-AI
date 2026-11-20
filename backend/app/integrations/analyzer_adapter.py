import importlib
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from app.core.exceptions import AnalyzerIntegrationError
from app.core.logging_config import logger


class BaseAnalyzerAdapter(ABC):
    """Abstract interface defining the code change impact analyzer adapter."""

    @abstractmethod
    def analyze_diff(self, git_diff: str) -> Dict[str, List[str]]:
        """Analyzes a Git diff and returns changed/impacted functions and modules."""
        pass


class CodeAnalyzerAdapter(BaseAnalyzerAdapter):
    """
    Adapter that bridges ChangeGuard AI Backend to the Code Analyzer module.

    Designed to easily plug into the analysis teammate's Python AST and NetworkX implementation.
    Checks dynamically for registered callable or external package (e.g. `changeguard_analyzer`).
    If unavailable, raises a descriptive AnalyzerIntegrationError instead of inventing fake data.
    """

    _custom_analyzer: Optional[Callable[[str], Dict[str, Any]]] = None

    @classmethod
    def register_custom_analyzer(cls, analyzer_func: Optional[Callable[[str], Dict[str, Any]]]) -> None:
        """Allows direct programmatic registration of teammate's analyzer function."""
        cls._custom_analyzer = staticmethod(analyzer_func) if analyzer_func is not None else None

    def analyze_diff(self, git_diff: str) -> Dict[str, List[str]]:
        """
        Executes AST-based code change analysis.

        Expected output structure:
        {
            "changed_functions": ["func_a"],
            "impacted_functions": ["func_a", "caller_b"],
            "impacted_modules": ["mod_a.py", "mod_b.py"]
        }
        """
        if not git_diff or not git_diff.strip():
            raise AnalyzerIntegrationError("Git diff is empty or invalid.")

        # 1. Check if a custom analyzer callable has been registered (e.g. during integration or testing)
        analyzer = self.__class__._custom_analyzer
        if analyzer is not None:
            logger.info("Executing registered custom code analyzer function...")
            try:
                result = analyzer(git_diff)
                return self._sanitize_result(result)
            except Exception as e:
                logger.error(f"Registered code analyzer encountered an error: {e}", exc_info=True)
                raise AnalyzerIntegrationError(f"Analyzer module execution failed: {str(e)}")

        # 2. Check if the teammate's external module is available in python path
        # Teammate module candidate names: `changeguard_analyzer`, `analyzer`, `impact_analyzer`
        candidate_modules = ["changeguard_analyzer", "analyzer.service", "impact_analyzer"]
        for mod_name in candidate_modules:
            try:
                mod = importlib.import_module(mod_name)
                if hasattr(mod, "analyze_diff"):
                    logger.info(f"Using discovered analyzer module: {mod_name}")
                    result = mod.analyze_diff(git_diff)
                    return self._sanitize_result(result)
            except ImportError:
                continue
            except Exception as e:
                logger.error(f"Error executing analyzer module '{mod_name}': {e}", exc_info=True)
                raise AnalyzerIntegrationError(f"Error running analyzer '{mod_name}': {str(e)}")

        # 3. If no external module is available, raise clear integration error
        logger.warning("Code analyzer module not found. Teammate AST/NetworkX module is not connected.")
        raise AnalyzerIntegrationError(
            "Code analyzer integration pending: Teammate's Python AST and NetworkX module "
            "is not currently installed or registered in backend/app/integrations. "
            "Please provide the analyzer package (e.g. changeguard_analyzer) or register it via CodeAnalyzerAdapter."
        )

    def _sanitize_result(self, raw_result: Any) -> Dict[str, List[str]]:
        """Ensures the analyzer output conforms strictly to expected schema."""
        if not isinstance(raw_result, dict):
            raise AnalyzerIntegrationError("Analyzer returned an invalid response format (must be a dictionary).")

        changed = raw_result.get("changed_functions", [])
        impacted = raw_result.get("impacted_functions", [])
        modules = raw_result.get("impacted_modules", [])

        return {
            "changed_functions": [str(f) for f in changed],
            "impacted_functions": [str(f) for f in impacted],
            "impacted_modules": [str(m) for m in modules],
        }
