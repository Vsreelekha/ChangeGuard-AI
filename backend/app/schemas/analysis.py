from typing import List
from pydantic import BaseModel, Field, field_validator


class AnalysisRequest(BaseModel):
    """Payload containing raw Git diff for impact analysis."""

    git_diff: str = Field(
        ...,
        description="Raw unified Git diff string representing the code changes",
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

    @field_validator("git_diff")
    @classmethod
    def validate_non_empty_diff(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Git diff cannot be empty or contain only whitespace.")
        return value.strip()


class AnalysisResponse(BaseModel):
    """Structured code change impact analysis results."""

    changed_functions: List[str] = Field(
        ...,
        description="Functions directly modified in the Git diff",
        examples=[["calculate_total"]],
    )
    impacted_functions: List[str] = Field(
        ...,
        description="Downstream and caller functions affected by the change",
        examples=[["calculate_total", "checkout"]],
    )
    impacted_modules: List[str] = Field(
        ...,
        description="Source code modules affected by the change",
        examples=[["billing.py", "checkout.py"]],
    )
