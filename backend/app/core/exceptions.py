from typing import Any, Dict, Optional


class ChangeGuardException(Exception):
    """Base exception class for ChangeGuard AI application."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class InvalidInputError(ChangeGuardException):
    """Raised when request payload or input data fails validation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=400, details=details)


class UploadTooLargeError(InvalidInputError):
    """Raised when an upload or extracted archive exceeds a configured byte cap."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, details=details)
        self.status_code = 413


class WorkspaceQuotaError(ChangeGuardException):
    """Raised when aggregate workspace storage or upload capacity is exhausted."""

    def __init__(self, message: str):
        super().__init__(message=message, status_code=429)


class AnalyzerIntegrationError(ChangeGuardException):
    """Raised when teammate's code analyzer module is unavailable or errors out."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=503, details=details)


class TestSelectorIntegrationError(ChangeGuardException):
    """Raised when teammate's test selector module is unavailable or errors out."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=503, details=details)


class DockerUnavailableError(ChangeGuardException):
    """Raised when Docker daemon is not running or accessible for safe test isolation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=503, details=details)


class TestExecutionError(ChangeGuardException):
    """Raised when test execution times out or encounters runner errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=500, details=details)


class TestExecutionTimeoutError(TestExecutionError):
    """Raised when Dockerized pytest exceeds its configured time limit."""

    __test__ = False


class ReportNotFoundError(ChangeGuardException):
    """Raised when requested report is not found in the database."""

    def __init__(self, run_id: str):
        super().__init__(
            message=f"Report with run_id '{run_id}' was not found.",
            status_code=404,
            details={"run_id": run_id},
        )


class DatabaseError(ChangeGuardException):
    """Raised when database query or persistence encounters an error."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, status_code=500, details=details)
