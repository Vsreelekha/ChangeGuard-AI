import uuid
from typing import Optional
from sqlalchemy.orm import Session
from app.core.exceptions import ReportNotFoundError
from app.core.logging_config import logger
from app.database.models import AnalysisRun
from app.schemas.report import (
    ReportCreateRequest,
    ReportResponse,
    TestSummary,
    WorkflowRunRequest,
)
from app.services.analyzer_service import AnalyzerService
from app.services.risk_service import RiskService
from app.services.test_runner_service import TestRunnerService
from app.services.test_selector_service import TestSelectorService


class ReportService:
    """Manages report generation, persistence, retrieval, and complete workflow orchestration."""

    def __init__(
        self,
        analyzer_service: AnalyzerService = None,
        selector_service: TestSelectorService = None,
        runner_service: TestRunnerService = None,
        risk_service: RiskService = None,
    ):
        self.analyzer_service = analyzer_service or AnalyzerService()
        self.selector_service = selector_service or TestSelectorService()
        self.runner_service = runner_service or TestRunnerService()
        self.risk_service = risk_service or RiskService()

    def create_report(self, request: ReportCreateRequest, db: Session) -> ReportResponse:
        """
        Calculates risk and persists an analysis report into the database.
        """
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
            risk_level=risk_level,
            recommendations=recommendations,
        )

        db.add(db_run)
        db.commit()
        db.refresh(db_run)

        logger.info(f"Persisted report with run_id={run_id} (Risk={risk_level})")
        return self._db_to_response(db_run)

    def get_report_by_id(self, run_id: str, db: Session) -> ReportResponse:
        """Retrieves a previously stored report by its unique run_id."""
        db_run = db.query(AnalysisRun).filter(AnalysisRun.run_id == run_id).first()
        if not db_run:
            raise ReportNotFoundError(run_id=run_id)
        return self._db_to_response(db_run)

    def execute_complete_workflow(self, request: WorkflowRunRequest, db: Session) -> ReportResponse:
        """
        Coordinates the complete ChangeGuard AI workflow:
        1. Code change impact analysis (Git diff -> changed & impacted functions/modules)
        2. Intelligent test selection (impacted functions -> targeted pytest tests)
        3. Safe isolated test execution (Docker runner if project_path provided)
        4. Evidence-based risk analysis (calculates HIGH/MEDIUM/LOW + recommendations)
        5. Database record creation & return to client
        """
        logger.info("Initiating full ChangeGuard AI pipeline execution...")

        # Stage 1: Analyze Code Diff
        analysis_res = self.analyzer_service.analyze_git_diff(request.git_diff)

        # Stage 2: Select Tests
        selection_res = self.selector_service.select_tests(analysis_res.impacted_functions)
        selected_tests_data = [t.model_dump() for t in selection_res.selected_tests]
        test_names = [t.test_name for t in selection_res.selected_tests]

        # Stage 3: Execute Tests (if project_path provided and tests selected)
        test_summary = TestSummary()
        if request.project_path and test_names:
            logger.info(f"Executing {len(test_names)} tests in project at '{request.project_path}'...")
            exec_res = self.runner_service.execute_tests(
                project_path=request.project_path,
                selected_tests=test_names,
            )
            test_summary = TestSummary(
                total_tests=exec_res.total_tests,
                passed=exec_res.passed,
                failed=exec_res.failed,
                failures=exec_res.failures,
            )
        elif request.project_path and not test_names:
            logger.info("Project path was provided, but no regression tests were selected.")

        # Stage 4: Risk Calculation
        risk_level, recommendations = self.risk_service.calculate_risk(
            changed_functions=analysis_res.changed_functions,
            impacted_functions=analysis_res.impacted_functions,
            impacted_modules=analysis_res.impacted_modules,
            test_summary=test_summary,
        )

        # Stage 5: Save Run in Database
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        db_run = AnalysisRun(
            run_id=run_id,
            git_diff=request.git_diff,
            changed_functions=analysis_res.changed_functions,
            impacted_functions=analysis_res.impacted_functions,
            impacted_modules=analysis_res.impacted_modules,
            selected_tests=selected_tests_data,
            test_results=test_summary.model_dump(),
            risk_level=risk_level,
            recommendations=recommendations,
        )

        db.add(db_run)
        db.commit()
        db.refresh(db_run)

        logger.info(f"Pipeline completed successfully. Run ID: {run_id}")
        return self._db_to_response(db_run)

    def _db_to_response(self, db_run: AnalysisRun) -> ReportResponse:
        """Converts an AnalysisRun database model to ReportResponse schema."""
        raw_tests = db_run.test_results or {}
        test_summary = TestSummary(
            total_tests=raw_tests.get("total_tests", 0),
            passed=raw_tests.get("passed", 0),
            failed=raw_tests.get("failed", 0),
            failures=raw_tests.get("failures", []),
        )

        created_at_val = None
        if hasattr(db_run.created_at, "isoformat"):
            created_at_val = db_run.created_at.isoformat()
        elif db_run.created_at:
            created_at_val = str(db_run.created_at)

        return ReportResponse(
            run_id=db_run.run_id,
            risk_level=db_run.risk_level,
            changed_functions=db_run.changed_functions or [],
            impacted_functions=db_run.impacted_functions or [],
            impacted_modules=db_run.impacted_modules or [],
            tests=test_summary,
            recommendations=db_run.recommendations or [],
            created_at=created_at_val,
        )
