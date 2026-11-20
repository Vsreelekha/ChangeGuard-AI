import uuid
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

    def execute_complete_workflow(self, request: WorkflowRunRequest, db: Session) -> ReportResponse:
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

        risk = self.risk_service.calculate_structured_risk(impact, selection, execution)
        report = generate_impact_report(
            impact,
            selection,
            execution,
            metadata={"project_path": str(project_root)},
            include_raw_output=True,
        )
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
    def _db_to_response(db_run: AnalysisRun) -> ReportResponse:
        raw_tests = db_run.test_results or {}
        summary = raw_tests.get("summary", raw_tests)
        return ReportResponse(
            run_id=db_run.run_id,
            risk_level=db_run.risk_level,
            changed_functions=db_run.changed_functions or [],
            impacted_functions=db_run.impacted_functions or [],
            impacted_modules=db_run.impacted_modules or [],
            tests=TestSummary(
                total_tests=summary.get("total", summary.get("total_tests", 0)),
                passed=summary.get("passed", 0),
                failed=summary.get("failed", 0),
                failures=raw_tests.get("failures", []),
                errors=summary.get("errors", 0),
            ),
            recommendations=db_run.recommendations or [],
            created_at=db_run.created_at.isoformat() if db_run.created_at else None,
            impact_analysis=db_run.impact_analysis or {},
            workflow_report=db_run.workflow_report or {},
        )
