from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logging_config import logger
from app.integrations.selector_adapter import BaseSelectorAdapter, TestSelectorAdapter
from app.services.project_path_service import discover_python_source_files, validate_project_path


class TestSelectorService:
    """Maps discovered tests to application functions and selects regression tests."""

    def __init__(self, adapter: Optional[BaseSelectorAdapter] = None):
        self.adapter = adapter if adapter is not None else TestSelectorAdapter()

    @staticmethod
    def _split_test_and_application_files(
        source_files: List[str], project_root: Path
    ) -> tuple[List[str], List[str]]:
        test_files: List[str] = []
        app_files: List[str] = []
        for source in source_files:
            path = Path(source)
            relative = path.relative_to(project_root)
            path_parts = {part.casefold() for part in relative.parts[:-1]}
            filename = path.name.casefold()
            is_test = (
                "tests" in path_parts
                or filename.startswith("test_")
                or filename.endswith("_test.py")
            )
            (test_files if is_test else app_files).append(str(path))
        return test_files, app_files

    def select_tests_for_project(
        self, impact_report: Dict[str, Any], project_path: str
    ) -> Dict[str, Any]:
        project_root = validate_project_path(project_path)
        source_files = discover_python_source_files(str(project_root))
        test_files, app_files = self._split_test_and_application_files(source_files, project_root)
        return self.select_tests_for_files(impact_report, test_files, app_files, project_root)

    def select_tests_for_files(
        self,
        impact_report: Dict[str, Any],
        test_files: List[str],
        app_files: List[str],
        project_root: Path,
    ) -> Dict[str, Any]:
        """Return the complete selector result; normalize test paths for Docker pytest."""
        logger.info(
            "Mapping %s test files against %s application files.", len(test_files), len(app_files)
        )
        test_mapping = self.adapter.map_tests(test_files, app_files)

        # The mapper reads absolute paths. Its result is kept keyed by its original IDs,
        # while test_file is made project-relative so selector pytest node IDs work in /app.
        for test in test_mapping.get("tests", []):
            file_path = test.get("file_path")
            if file_path:
                test["file_path"] = Path(file_path).resolve().relative_to(project_root).as_posix()

        selection = self.adapter.select_tests(impact_report, test_mapping)
        if not test_mapping.get("success", False):
            selection["success"] = False
        return selection
