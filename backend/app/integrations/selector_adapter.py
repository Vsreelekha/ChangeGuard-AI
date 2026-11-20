from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from app.core.exceptions import TestSelectorIntegrationError
from app.core.logging_config import logger
from test_selector.selector import select_tests as run_test_selection
from test_selector.test_mapper import map_tests_to_code


class BaseSelectorAdapter(ABC):
    """Interface to the repository's test mapper and selector."""

    @abstractmethod
    def map_tests(self, test_files: List[str], app_files: List[str]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def select_tests(
        self, impact_report: Dict[str, Any], test_mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        raise NotImplementedError


class TestSelectorAdapter(BaseSelectorAdapter):
    """Explicit adapter for ``map_tests_to_code`` and ``select_tests``."""

    _custom_selector: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None

    @classmethod
    def register_custom_selector(
        cls,
        selector_func: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
    ) -> None:
        """Register a two-argument selector override for tests or dependency injection."""
        cls._custom_selector = selector_func

    def map_tests(self, test_files: List[str], app_files: List[str]) -> Dict[str, Any]:
        try:
            return map_tests_to_code(test_files, app_files)
        except Exception as exc:
            logger.error("Test-to-code mapping failed: %s", exc, exc_info=True)
            raise TestSelectorIntegrationError(f"Test-to-code mapping failed: {exc}") from exc

    def select_tests(
        self, impact_report: Dict[str, Any], test_mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            selector = self.__class__._custom_selector or run_test_selection
            result = selector(impact_report, test_mapping)
        except Exception as exc:
            logger.error("Test selection failed: %s", exc, exc_info=True)
            raise TestSelectorIntegrationError(f"Test selection failed: {exc}") from exc

        required_fields = {
            "success": bool,
            "selected_tests": list,
            "total_tests_discovered": int,
            "total_tests_selected": int,
            "reduction_percentage": (int, float),
            "pytest_args": list,
            "selection_summary": dict,
            "errors": list,
        }
        if not isinstance(result, dict):
            raise TestSelectorIntegrationError("Test selector returned an invalid response: expected a dictionary.")
        for field, expected_type in required_fields.items():
            if field not in result or not isinstance(result[field], expected_type):
                expected_name = (
                    "/".join(item.__name__ for item in expected_type)
                    if isinstance(expected_type, tuple)
                    else expected_type.__name__
                )
                raise TestSelectorIntegrationError(
                    f"Test selector response field '{field}' must be {expected_name}."
                )
        return result
