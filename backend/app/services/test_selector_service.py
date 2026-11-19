from typing import List
from app.integrations.selector_adapter import TestSelectorAdapter
from app.schemas.testing import SelectedTestItem, TestSelectionResponse
from app.core.logging_config import logger


class TestSelectorService:
    """Service handling intelligent regression test selection business logic."""

    def __init__(self, adapter: TestSelectorAdapter = None):
        self.adapter = adapter or TestSelectorAdapter()

    def select_tests(self, impacted_functions: List[str]) -> TestSelectionResponse:
        """
        Maps impacted functions to relevant regression tests with priority ranking.
        """
        logger.info(f"Selecting regression tests for {len(impacted_functions)} impacted functions...")
        raw_selected = self.adapter.select_tests(impacted_functions)

        # Convert to Pydantic items
        items: List[SelectedTestItem] = []
        for raw in raw_selected:
            items.append(
                SelectedTestItem(
                    test_name=raw["test_name"],
                    reason=raw.get("reason", "Selected by regression dependency graph"),
                    priority=raw.get("priority", "medium"),
                )
            )

        # Sort tests by priority (high > medium > low)
        priority_order = {"high": 0, "medium": 1, "low": 2}
        items.sort(key=lambda t: priority_order.get(t.priority.lower(), 1))

        logger.info(f"Test selection complete: selected {len(items)} regression tests.")
        return TestSelectionResponse(selected_tests=items)
