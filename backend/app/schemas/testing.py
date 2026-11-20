import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

# Regex for safe test identifiers (e.g. test_billing, tests/test_billing.py::test_calculate_total)
SAFE_TEST_PATTERN = re.compile(r"^[a-zA-Z0-9_./\-:]+$")
SAFE_NODE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_pytest_target_syntax(target: str) -> str:
    """Accept only a project-relative Python file target and safe pytest node path."""
    if not isinstance(target, str):
        raise ValueError("Each pytest target must be a string.")
    clean = target.strip()
    if not clean or not SAFE_TEST_PATTERN.fullmatch(clean) or "\\" in clean:
        raise ValueError(f"Invalid or unsafe pytest target: {target!r}.")

    file_part, *node_parts = clean.split("::")
    if (
        not file_part
        or file_part.startswith("/")
        or PureWindowsPath(file_part).is_absolute()
        or ":" in file_part
        or "//" in file_part
    ):
        raise ValueError(f"Pytest target must use a project-relative path: {target!r}.")
    path_parts = PurePosixPath(file_part).parts
    if any(part in {".", ".."} for part in path_parts) or not file_part.casefold().endswith(".py"):
        raise ValueError(f"Pytest target must name a project-relative .py file: {target!r}.")
    if node_parts and any(not SAFE_NODE_NAME.fullmatch(part) for part in node_parts):
        raise ValueError(f"Pytest node ID contains an invalid node name: {target!r}.")
    return clean


class TestSelectionRequest(BaseModel):
    """Request payload to map project tests against an analyzer impact report."""

    project_path: str = Field(..., description="Path to a project inside configured approved roots")
    impact_report: Dict[str, Any] = Field(
        ...,
        description="Complete structured result returned by the code impact analyzer",
    )

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, value: str) -> str:
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise ValueError("Project path must be a non-empty valid path.")
        return clean


class SelectedTestItem(BaseModel):
    """An individual test case selected for regression verification."""

    test_name: str = Field(
        ...,
        description="Pytest test identifier or name",
        examples=["test_calculate_total"],
    )
    reason: str = Field(
        ...,
        description="Explanation why this regression test was selected",
        examples=["Tests the modified billing function"],
    )
    priority: Optional[str] = Field(
        default="medium",
        description="Test priority: 'high', 'medium', or 'low'",
        examples=["high"],
    )


class TestSelectionResponse(BaseModel):
    """Complete structured result from the test mapper and selector."""

    success: bool
    selected_tests: List[Dict[str, Any]]
    total_tests_discovered: int
    total_tests_selected: int
    reduction_percentage: float
    pytest_args: List[str]
    selection_summary: Dict[str, Any]
    errors: List[Dict[str, Any]]


class TestExecutionRequest(BaseModel):
    """Request to safely execute selected pytest tests in an isolated container."""

    project_path: str = Field(
        ...,
        description="Path to approved project containing test suite",
        examples=["sample_project"],
    )
    selected_tests: List[str] = Field(
        ...,
        description="List of test names or paths to execute",
        examples=[["test_calculate_total"]],
    )

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Project path cannot be empty.")
        # Reject obvious path traversal or injection characters
        if "\x00" in clean or any(char in clean for char in [";", "&", "|", "`", "$"]):
            raise ValueError("Invalid characters detected in project path.")
        return clean

    @field_validator("selected_tests")
    @classmethod
    def validate_test_names(cls, tests: List[str]) -> List[str]:
        if not tests:
            raise ValueError("selected_tests list cannot be empty.")
        clean_tests = []
        for test in tests:
            t = validate_pytest_target_syntax(test)
            clean_tests.append(t)
        if not clean_tests:
            raise ValueError("At least one valid test name is required.")
        return clean_tests


class TestExecutionResponse(BaseModel):
    """Metrics and captured output from isolated pytest execution."""

    total_tests: int = Field(..., description="Total number of executed tests", examples=[5])
    passed: int = Field(..., description="Number of passed tests", examples=[4])
    failed: int = Field(..., description="Number of failed tests", examples=[1])
    failures: List[str] = Field(
        default_factory=list,
        description="Names of tests that failed during execution",
        examples=[["test_calculate_total"]],
    )
    success: bool = False
    status: str = "unknown"
    summary: Dict[str, int] = Field(default_factory=dict)
    execution_time: float = 0.0
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    failure_details: List[Dict[str, str]] = Field(default_factory=list)
    message: str = ""
