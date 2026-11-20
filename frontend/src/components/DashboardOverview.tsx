import type { AnalysisResult, TestExecutionResult } from "../services/api";

import AnalysisResults from "./AnalysisResults";
import TestResults from "./TestResults";
import RiskAssessment from "./RiskAssessment";
import BackendStatus from "./BackendStatus";
import WorkflowStatus from "./WorkflowStatus";
import type { WorkflowStageStatus } from "./WorkflowStatus";
import StatCard from "./StatCard";

type Props = {
  analysisResult: AnalysisResult | null;
  executionResult: TestExecutionResult | null;

  analysisStatus: WorkflowStageStatus;
  selectionStatus: WorkflowStageStatus;
  executionStatus: WorkflowStageStatus;
  riskStatus: WorkflowStageStatus;
};

function DashboardOverview({
  analysisResult,
  executionResult,
  analysisStatus,
  selectionStatus,
  executionStatus,
  riskStatus,
}: Props) {
  const risk = executionResult
    ? {
        risk_level: executionResult.failed > 0 ? ("High" as const) : ("Low" as const),
        risk_reason:
          executionResult.failed > 0
            ? `${executionResult.failed} demo regression test(s) failed.`
            : "All executed demo regression tests passed.",
        deployment_recommendation:
          executionResult.failed > 0 ? "Review required" : "Ready for review",
      }
    : null;

  return (
    <div className="dashboard-overview">
      <BackendStatus />
      <div className="page-intro">
        <div>
          <p className="eyebrow">OVERVIEW</p>
          <h1>ChangeGuard AI Dashboard</h1>
          <p>Understand the impact of a change and focus regression testing.</p>
        </div>
        <span className="demo-pill">DEMO MODE</span>
      </div>

      <div className="stats-grid">
        <StatCard
          title="Changed Functions"
          value={analysisResult ? analysisResult.changed_functions.length : "—"}
          description="Functions detected in the latest diff"
        />

        <StatCard
          title="Impacted Functions"
          value={
            analysisResult ? analysisResult.impacted_functions.length : "—"
          }
          description="Functions potentially affected"
        />

        <StatCard
          title="Impacted Modules"
          value={analysisResult ? analysisResult.impacted_modules.length : "—"}
          description="Modules identified for review"
        />

        <StatCard
          title="Failed Tests"
          value={executionResult ? executionResult.failed : "—"}
          description={
            executionResult
              ? `${executionResult.passed} ${
                  executionResult.passed === 1 ? "test" : "tests"
                } passed`
              : "Tests not executed yet"
          }
        />
      </div>
      <WorkflowStatus
        analysisStatus={analysisStatus}
        selectionStatus={selectionStatus}
        executionStatus={executionStatus}
        riskStatus={riskStatus}
      />

      <section className="dashboard-section">
        <h2>Latest Code Analysis</h2>

        {analysisResult ? (
          <AnalysisResults result={analysisResult} />
        ) : (
          <div className="empty-state">
            <h3>No analysis yet</h3>
            <p>Submit a Git diff to see changed functions and impacted modules.</p>
          </div>
        )}
      </section>

      {executionResult && (
        <div className="dashboard-lower-grid">
          <section className="dashboard-section">
            <h2>Latest Test Execution</h2>
            <TestResults result={executionResult} />
          </section>
          {risk && <RiskAssessment risk={risk} />}
        </div>
      )}
    </div>
  );
}

export default DashboardOverview;
