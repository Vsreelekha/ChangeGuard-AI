from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TestSummary(BaseModel):
    """Summary of executed regression tests."""

    total_tests: int = Field(default=0, description="Total executed tests", examples=[5])
    passed: int = Field(default=0, description="Passed tests count", examples=[4])
    failed: int = Field(default=0, description="Failed tests count", examples=[1])
    errors: int = Field(default=0, description="Pytest collection or setup errors", examples=[0])
    failures: List[str] = Field(
        default_factory=list,
        description="Failing test identifiers",
        examples=[["test_calculate_total"]],
    )


class ReportCreateRequest(BaseModel):
    """Payload to generate and persist a new risk evaluation report."""

    git_diff: Optional[str] = Field(default=None, description="Raw Git diff string")
    impact_analysis: Optional[Dict[str, Any]] = Field(
        default=None, description="Complete structured analyzer result"
    )
    changed_functions: List[Any] = Field(
        default_factory=list,
        description="Directly modified functions",
        examples=[["calculate_total"]],
    )
    impacted_functions: List[Any] = Field(
        default_factory=list,
        description="Downstream impacted functions",
        examples=[["calculate_total", "checkout"]],
    )
    impacted_modules: List[str] = Field(
        default_factory=list,
        description="Impacted code files or modules",
        examples=[["billing.py", "checkout.py"]],
    )
    selected_tests: Optional[List[Any]] = Field(
        default_factory=list,
        description="Tests selected for regression analysis",
    )
    tests: Optional[TestSummary] = Field(
        default_factory=TestSummary,
        description="Execution results of tests",
    )


class ReportResponse(BaseModel):
    """Comprehensive risk assessment report."""

    run_id: str = Field(
        ...,
        description="Unique identifier for the analysis run",
        examples=["run-a1b2c3d4-e5f6"],
    )
    risk_level: str = Field(
        ...,
        description="Calculated risk level: 'LOW', 'MEDIUM', or 'HIGH'",
        examples=["HIGH"],
    )
    changed_functions: List[Any] = Field(
        ...,
        description="List of modified functions",
        examples=[["calculate_total"]],
    )
    impacted_functions: List[Any] = Field(
        ...,
        description="List of impacted functions",
        examples=[["calculate_total", "checkout"]],
    )
    impacted_modules: List[str] = Field(
        ...,
        description="List of impacted modules",
        examples=[["billing.py", "checkout.py"]],
    )
    tests: TestSummary = Field(
        ...,
        description="Test execution metrics and failures",
    )
    recommendations: List[str] = Field(
        ...,
        description="Actionable remediation advice and deployment safety notes",
        examples=[["Review the failing billing test before deployment."]],
    )
    created_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 creation timestamp",
    )
    impact_analysis: Dict[str, Any] = Field(
        default_factory=dict,
        description="Complete structured result from the code impact analyzer",
    )
    workflow_report: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed selection, execution, risk, and evidence report",
    )


class WorkflowRunRequest(BaseModel):
    """Request payload to execute the complete end-to-end ChangeGuard AI pipeline."""

    git_diff: str = Field(
        ...,
        description="Git diff of changed code",
        examples=[
            """diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@ -10,3 +10,3 @@
-def calculate_total(items):
+def calculate_total(items, discount=0.0):
     return sum(items) - discount"""
        ],
    )
    project_path: str = Field(
        ...,
        description="Path to a project inside configured approved roots",
    )

    @field_validator("git_diff")
    @classmethod
    def validate_diff(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Git diff cannot be empty or contain only whitespace.")
        return value.strip()

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, value: str) -> str:
        clean = value.strip()
        if not clean or "\x00" in clean:
            raise ValueError("Project path must be a non-empty valid path.")
        return clean
