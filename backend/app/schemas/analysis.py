from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator


class AnalysisRequest(BaseModel):
    """Git diff and approved project directory to analyze."""

    git_diff: str = Field(..., description="Raw unified Git diff string representing the code changes")
    project_path: str = Field(..., description="Path to a project inside configured approved roots")

    @field_validator("git_diff")
    @classmethod
    def validate_non_empty_diff(cls, value: str) -> str:
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


class AnalysisResponse(BaseModel):
    """Complete structured output of ``analyze_code_impact``."""

    success: bool
    changed_files: List[Dict[str, Any]]
    changed_functions: List[Dict[str, Any]]
    impacted_functions: List[Dict[str, Any]]
    unassigned_changed_lines: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    summary: Dict[str, Any]
