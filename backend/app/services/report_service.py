import uuid
import os
import re
import ntpath
import posixpath
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    DockerUnavailableError,
    ReportNotFoundError,
    TestExecutionError,
    TestExecutionTimeoutError,
)
from app.core.logging_config import logger
from app.database.models import AnalysisRun
from app.schemas.report import ReportCreateRequest, ReportResponse, TestSummary, WorkflowRunRequest
from app.services.analyzer_service import AnalyzerService
from app.services.project_path_service import discover_python_source_files, validate_project_path
from app.services.risk_service import RiskService
from app.services.test_runner_service import TestRunnerService
from app.services.test_selector_service import TestSelectorService
from reports.report_generator import generate_impact_report


_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\/\r\n\s]+[\\/][^\\/\r\n\s]+[\\/])[^\r\n\"'<>|]*",
    re.IGNORECASE,
)
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9:/])/(?:[^\r\n\"'<>|]*)"
)
_PRIVATE_PATH_KEYS = {"project_path", "workspace_path", "workspace_root", "root_path"}


def _is_absolute_path(value: str) -> bool:
    candidate = value.strip()
    return posixpath.isabs(candidate) or ntpath.isabs(candidate)


class ReportService:
    """Generate reports and orchestrate the existing ChangeGuard analysis pipeline."""

    def __init__(
        self,
        analyzer_service: Optional[AnalyzerService] = None,
        selector_service: Optional[TestSelectorService] = None,
        runner_service: Optional[TestRunnerService] = None,
        risk_service: Optional[RiskService] = None,
    ):
        self.analyzer_service = analyzer_service if analyzer_service is not None else AnalyzerService()
        self.selector_service = selector_service if selector_service is not None else TestSelectorService()
        self.runner_service = runner_service if runner_service is not None else TestRunnerService()
        self.risk_service = risk_service if risk_service is not None else RiskService()

    def create_report(self, request: ReportCreateRequest, db: Session) -> ReportResponse:
        test_summary = request.tests or TestSummary()
        risk_level, recommendations = self.risk_service.calculate_risk(
            changed_functions=request.changed_functions,
            impacted_functions=request.impacted_functions,
            impacted_modules=request.impacted_modules,
            test_summary=test_summary,
        )
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        db_run = AnalysisRun(
            run_id=run_id,
            git_diff=request.git_diff,
            changed_functions=request.changed_functions,
            impacted_functions=request.impacted_functions,
            impacted_modules=request.impacted_modules,
            selected_tests=request.selected_tests or [],
            test_results=test_summary.model_dump(),
            impact_analysis=request.impact_analysis,
            workflow_report={},
            risk_level=risk_level,
            recommendations=recommendations,
        )
        return self._persist(db, db_run)

    def get_report_by_id(self, run_id: str, db: Session) -> ReportResponse:
        db_run = db.query(AnalysisRun).filter(AnalysisRun.run_id == run_id).first()
        if not db_run:
            raise ReportNotFoundError(run_id=run_id)
        return self._db_to_response(db_run)

    def execute_complete_workflow(
        self,
        request: WorkflowRunRequest,
        db: Session,
        *,
        report_metadata: Optional[Dict[str, Any]] = None,
    ) -> ReportResponse:
        logger.info("Initiating full ChangeGuard AI pipeline.")
        project_root = validate_project_path(request.project_path)
        source_files = discover_python_source_files(str(project_root))

        impact = self.analyzer_service.analyze_git_diff(request.git_diff, source_files)
        test_files, app_files = self.selector_service._split_test_and_application_files(
            source_files, project_root
        )
        selection = self.selector_service.select_tests_for_files(
            impact, test_files, app_files, project_root
        )

        selected_test_ids = list(selection.get("pytest_args", []))
        if selection.get("success") and selected_test_ids:
            try:
                execution = self.runner_service.execute_tests(str(project_root), selected_test_ids).model_dump()
            except TestExecutionTimeoutError as exc:
                execution = self._execution_timeout(str(exc), exc.details)
            except (DockerUnavailableError, TestExecutionError) as exc:
                execution = self._execution_error(str(exc))
        elif not selection.get("success"):
            execution = self._execution_error("Test mapping or selection did not complete successfully.")
        else:
            execution = self._execution_skipped("No Python test files or relevant tests were discovered.")

        metadata: Dict[str, Any] = {"project_path": str(project_root)}
        if report_metadata is not None:
            # Project-ID callers keep the full structured evidence while replacing
            # all embedded host paths with project-relative paths before persistence.
            self._redact_project_paths(project_root, impact, selection, execution)
            metadata = report_metadata

        risk = self.risk_service.calculate_structured_risk(impact, selection, execution)
        report = generate_impact_report(
            impact,
            selection,
            execution,
            metadata=metadata,
            include_raw_output=True,
        )
        # Uploaded-project callers receive the original structured contracts
        # alongside the generator's presentation fields. Existing path-based
        # workflow responses retain their established shape.
        if report_metadata is not None:
            report["test_selection_result"] = selection
            report["test_execution_result"] = execution
        # The report generator's success describes report assembly. This flag conveys verification.
        execution_summary = execution.get("summary", {})
        report["verification_success"] = bool(
            risk.get("verification_status") == "VERIFIED"
            and selection.get("success") is True
            and bool(selection.get("selected_tests"))
            and execution.get("status") == "passed"
            and execution.get("success") is True
            and execution_summary.get("total", 0) > 0
            and execution_summary.get("passed", 0) >= len(selection.get("selected_tests", []))
            and execution_summary.get("passed", 0) == execution_summary.get("total", 0)
            and execution_summary.get("failed", 0) == 0
            and execution_summary.get("skipped", 0) == 0
            and execution_summary.get("errors", 0) == 0
        )
        report["risk"] = risk

        summary = execution.get("summary", {})
        failures = execution.get("failures", [])
        test_summary = TestSummary(
            total_tests=summary.get("total", 0),
            passed=summary.get("passed", 0),
            failed=summary.get("failed", 0),
            failures=failures,
            errors=summary.get("errors", 0),
        )
        changed_functions = impact.get("changed_functions", [])
        impacted_functions = impact.get("impacted_functions", [])
        impacted_modules = sorted({
            str(item.get("file_path", ""))
            for item in [*changed_functions, *impacted_functions]
            if isinstance(item, dict) and item.get("file_path")
        })
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        db_run = AnalysisRun(
            run_id=run_id,
            git_diff=request.git_diff,
            changed_functions=changed_functions,
            impacted_functions=impacted_functions,
            impacted_modules=impacted_modules,
            selected_tests=selection.get("selected_tests", []),
            test_results={**test_summary.model_dump(), "execution": execution},
            impact_analysis=impact,
            workflow_report=report,
            risk_level=risk.get("level", "MEDIUM"),
            recommendations=[risk.get("recommendation", "Review workflow evidence.")],
        )
        logger.info("Workflow finished with verification status %s.", risk.get("verification_status"))
        return self._persist(db, db_run)

    @staticmethod
    def _redact_project_paths(project_root, *results: Any) -> None:
        root_text = str(project_root).rstrip("\\/")
        variants = {root_text, root_text.replace("\\", "/"), root_text.replace("/", "\\")}
        flags = re.IGNORECASE if os.name == "nt" else 0

        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                for key, nested in value.items():
                    value[key] = clean(nested)
                return value
            if isinstance(value, list):
                for index, nested in enumerate(value):
                    value[index] = clean(nested)
                return value
            if isinstance(value, tuple):
                return tuple(clean(nested) for nested in value)
            if isinstance(value, str):
                result = value
                for variant in sorted(variants, key=len, reverse=True):
                    result = re.sub(re.escape(variant) + r"[\\/]+", "", result, flags=flags)
                    result = re.sub(re.escape(variant), ".", result, flags=flags)
                return result
            return value

        for result in results:
            clean(result)

    @staticmethod
    def _execution_skipped(message: str) -> Dict[str, Any]:
        return {
            "status": "skipped", "success": False,
            "summary": {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "total": 0},
            "execution_time": 0.0, "stdout": "", "stderr": "", "exit_code": None,
            "failures": [], "failure_details": [], "message": message,
        }

    @classmethod
    def _execution_error(cls, message: str) -> Dict[str, Any]:
        result = cls._execution_skipped(message)
        result.update(status="error", exit_code=-1)
        return result

    @classmethod
    def _execution_timeout(cls, message: str, details: Dict[str, Any]) -> Dict[str, Any]:
        result = cls._execution_skipped(message)
        result.update(
            status="timeout",
            exit_code=details.get("exit_code"),
            stdout=details.get("stdout", ""),
            stderr=details.get("stderr", ""),
            execution_time=details.get("execution_time", 0.0),
        )
        return result

    @staticmethod
    def _persist(db: Session, db_run: AnalysisRun) -> ReportResponse:
        db.add(db_run)
        db.commit()
        db.refresh(db_run)
        logger.info("Persisted report with run_id=%s (Risk=%s)", db_run.run_id, db_run.risk_level)
        return ReportService._db_to_response(db_run)

    @staticmethod
    def _sanitize_public_report_values(*values: Any) -> list[Any]:
        """Return report values with server-local paths removed from API data.

        Keep this at the serialization boundary so it protects both reports
        created by the current request and old rows returned from the database.
        The ORM objects are not mutated, and relative project paths are retained.
        """
        known_paths: set[str] = set()

        def collect_paths(value: Any, key: str = "", *, include_file_paths: bool = False) -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    collect_paths(
                        child,
                        str(child_key).lower(),
                        include_file_paths=include_file_paths,
                    )
            elif isinstance(value, (list, tuple)):
                for child in value:
                    collect_paths(child, key, include_file_paths=include_file_paths)
            elif isinstance(value, str) and _is_absolute_path(value):
                if key in _PRIVATE_PATH_KEYS or (
                    include_file_paths and key in {"file_path", "path"}
                ):
                    trimmed = value.strip().rstrip("\\/")
                    if trimmed:
                        known_paths.add(trimmed)
                        known_paths.add(trimmed.replace("\\", "/"))
                        known_paths.add(trimmed.replace("/", "\\"))

        for value in values:
            collect_paths(value)
        if not known_paths:
            for value in values:
                collect_paths(value, include_file_paths=True)

        path_flags = re.IGNORECASE if os.name == "nt" else 0
        path_prefixes = sorted(known_paths, key=len, reverse=True)

        def clean(value: Any, key: str = "") -> Any:
            if isinstance(value, dict):
                result = {}
                for child_key, child in value.items():
                    normalized_key = str(child_key).lower()
                    if normalized_key in _PRIVATE_PATH_KEYS:
                        continue
                    result[child_key] = clean(child, normalized_key)
                return result
            if isinstance(value, list):
                return [clean(child, key) for child in value]
            if isinstance(value, tuple):
                return tuple(clean(child, key) for child in value)
            if not isinstance(value, str):
                return value

            result = value
            for path_prefix in path_prefixes:
                result = re.sub(
                    re.escape(path_prefix) + r"(?:[\\/]+|(?=$))",
                    "",
                    result,
                    flags=path_flags,
                )

            # If an absolute path was collected only because it was a standalone
            # file_path/path field, its parent root is unknown. Do not serialize
            # an empty value that could be mistaken for a valid relative path.
            if not result and value.strip() and _is_absolute_path(value) and key in {"file_path", "path"}:
                return "[redacted path]"

            # Known project roots above preserve their relative suffixes. This
            # catches unrelated absolute paths in older report text/output.
            result = _WINDOWS_ABSOLUTE_PATH.sub("[redacted path]", result)
            result = _POSIX_ABSOLUTE_PATH.sub("[redacted path]", result)
            if _is_absolute_path(result) and ("path" in key or key == "path"):
                return "[redacted path]"
            return result

        return [clean(value) for value in values]

    @staticmethod
    def _db_to_response(db_run: AnalysisRun) -> ReportResponse:
        raw_tests = db_run.test_results or {}
        summary = raw_tests.get("summary", raw_tests)
        (
            changed_functions,
            impacted_functions,
            impacted_modules,
            test_failures,
            recommendations,
            impact_analysis,
            workflow_report,
        ) = ReportService._sanitize_public_report_values(
            db_run.changed_functions or [],
            db_run.impacted_functions or [],
            db_run.impacted_modules or [],
            raw_tests.get("failures", []),
            db_run.recommendations or [],
            db_run.impact_analysis or {},
            db_run.workflow_report or {},
        )
        return ReportResponse(
            run_id=db_run.run_id,
            risk_level=db_run.risk_level,
            changed_functions=changed_functions,
            impacted_functions=impacted_functions,
            impacted_modules=impacted_modules,
            tests=TestSummary(
                total_tests=summary.get("total", summary.get("total_tests", 0)),
                passed=summary.get("passed", 0),
                failed=summary.get("failed", 0),
                failures=test_failures,
                errors=summary.get("errors", 0),
            ),
            recommendations=recommendations,
            created_at=db_run.created_at.isoformat() if db_run.created_at else None,
            impact_analysis=impact_analysis,
            workflow_report=workflow_report,
        )
