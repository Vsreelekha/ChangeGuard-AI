from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ProjectUploadResponse(BaseModel):
    """Public response for a successfully uploaded project archive."""

    project_id: str = Field(..., description="Opaque identifier for the uploaded project")
    file_count: int = Field(..., ge=1, description="Number of regular files extracted")
    expires_at: datetime = Field(..., description="UTC time after which the workspace expires")


class ProjectRunRequest(BaseModel):
    """Run the stored project identified by the URL using a Git diff."""

    git_diff: str = Field(..., min_length=1, description="Git diff for the uploaded project")

    @field_validator("git_diff")
    @classmethod
    def validate_git_diff(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Git diff cannot be empty or contain only whitespace.")
        return clean
