import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

# Regex for safe test identifiers (e.g. test_billing, tests/test_billing.py::test_calculate_total)
SAFE_TEST_PATTERN = re.compile(r"^[a-zA-Z0-9_./\-:]+$")


class TestSelectionRequest(BaseModel):
    """Request payload containing impacted functions to select relevant tests for."""

    impacted_functions: List[str] = Field(
        ...,
        description="List of impacted function names to map to relevant tests",
        examples=[["calculate_total", "checkout"]],
    )

    @field_validator("impacted_functions")
    @classmethod
    def validate_functions_list(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("Impacted functions list cannot be empty.")
        clean = [f.strip() for f in value if f and f.strip()]
        if not clean:
            raise ValueError("Impacted functions must contain valid function names.")
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
    """Response containing intelligently selected regression tests."""

    selected_tests: List[SelectedTestItem] = Field(
        ...,
        description="List of pytest tests selected with selection rationale",
    )


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
            t = test.strip()
            if not t:
                continue
            if not SAFE_TEST_PATTERN.match(t):
                raise ValueError(
                    f"Invalid test name '{t}'. Test names must only contain alphanumeric characters, underscores, dashes, dots, or colons."
                )
            clean_tests.append(t)
        if not clean_tests:
            raise ValueError("At least one valid test name is required.")
        return clean_tests


class TestExecutionResponse(BaseModel):
    """Results from isolated pytest execution."""

    total_tests: int = Field(..., description="Total number of executed tests", examples=[5])
    passed: int = Field(..., description="Number of passed tests", examples=[4])
    failed: int = Field(..., description="Number of failed tests", examples=[1])
    failures: List[str] = Field(
        default_factory=list,
        description="Names of tests that failed during execution",
        examples=[["test_calculate_total"]],
    )
