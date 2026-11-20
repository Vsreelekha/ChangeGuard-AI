import importlib
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from app.core.exceptions import TestSelectorIntegrationError
from app.core.logging_config import logger


class BaseSelectorAdapter(ABC):
    """Abstract interface defining the intelligent test selector adapter."""

    @abstractmethod
    def select_tests(self, impacted_functions: List[str]) -> List[Dict[str, Any]]:
        """Maps impacted functions to relevant regression tests with rationale."""
        pass


class TestSelectorAdapter(BaseSelectorAdapter):
    """
    Adapter bridging ChangeGuard AI Backend to the Test Selector module.

    Receives impacted functions, connects to teammate's test selector,
    and returns selected pytest test names with selection reasons and priorities.
    If the teammate module is not installed or registered, raises TestSelectorIntegrationError.
    """

    _custom_selector: Optional[Callable[[List[str]], List[Dict[str, Any]]]] = None

    @classmethod
    def register_custom_selector(
        cls, selector_func: Optional[Callable[[List[str]], List[Dict[str, Any]]]]
    ) -> None:
        """Allows direct programmatic registration of teammate's test selector function."""
        cls._custom_selector = staticmethod(selector_func) if selector_func is not None else None

    def select_tests(self, impacted_functions: List[str]) -> List[Dict[str, Any]]:
        """
        Executes test selection for given impacted functions.

        Expected output structure:
        [
            {
                "test_name": "test_calculate_total",
                "reason": "Tests the modified billing function",
                "priority": "high"
            }
        ]
        """
        if not impacted_functions:
            return []

        # 1. Check if a custom selector function was registered
        selector = self.__class__._custom_selector
        if selector is not None:
            logger.info("Executing registered custom test selector function...")
            try:
                raw_tests = selector(impacted_functions)
                return self._sanitize_tests(raw_tests)
            except Exception as e:
                logger.error(f"Registered test selector encountered an error: {e}", exc_info=True)
                raise TestSelectorIntegrationError(f"Test selector execution failed: {str(e)}")

        # 2. Check if teammate's module is available in python path
        candidate_modules = ["changeguard_selector", "test_selector.service", "test_selector"]
        for mod_name in candidate_modules:
            try:
                mod = importlib.import_module(mod_name)
                if hasattr(mod, "select_tests"):
                    logger.info(f"Using discovered test selector module: {mod_name}")
                    raw_tests = mod.select_tests(impacted_functions)
                    return self._sanitize_tests(raw_tests)
            except ImportError:
                continue
            except Exception as e:
                logger.error(f"Error running test selector module '{mod_name}': {e}", exc_info=True)
                raise TestSelectorIntegrationError(f"Error running test selector '{mod_name}': {str(e)}")

        # 3. If unavailable, raise clear integration error
        logger.warning("Test selector module not found. Teammate selector is not connected.")
        raise TestSelectorIntegrationError(
            "Test selector integration pending: Teammate's intelligent test selection module "
            "is not currently installed or registered in backend/app/integrations. "
            "Please provide the selector package (e.g. changeguard_selector) or register it via TestSelectorAdapter."
        )

    def _sanitize_tests(self, raw_tests: Any) -> List[Dict[str, Any]]:
        """Sanitizes test selection output and enforces schema consistency."""
        if not isinstance(raw_tests, list):
            raise TestSelectorIntegrationError("Test selector must return a list of selected tests.")

        sanitized = []
        for item in raw_tests:
            if isinstance(item, str):
                sanitized.append({
                    "test_name": item,
                    "reason": "Selected based on impacted function dependencies",
                    "priority": "medium",
                })
            elif isinstance(item, dict):
                test_name = item.get("test_name") or item.get("name")
                if not test_name:
                    continue
                sanitized.append({
                    "test_name": str(test_name),
                    "reason": str(item.get("reason", "Selected by regression analysis")),
                    "priority": str(item.get("priority", "medium")).lower(),
                })
        return sanitized
