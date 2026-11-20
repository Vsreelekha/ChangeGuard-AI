import type {
  TestExecutionResult,
  RiskAssessmentResult,
} from "../services/api";
import type { WorkflowStageStatus } from "./WorkflowStatus";

type Props = {
  executionResult: TestExecutionResult | null;
  status: WorkflowStageStatus;
};

function RiskReportPage({ executionResult, status }: Props) {
  let risk: RiskAssessmentResult | null = null;

  const passPercentage =
    executionResult && executionResult.total_tests > 0
      ? Math.round((executionResult.passed / executionResult.total_tests) * 100)
      : null;

  const riskScore =
    executionResult && executionResult.total_tests > 0
      ? Math.round((executionResult.failed / executionResult.total_tests) * 100)
      : null;

  if (executionResult && executionResult.total_tests > 0) {
    const riskLevel =
      executionResult.failed === 0
        ? "Low"
        : executionResult.failed / executionResult.total_tests >= 0.5
          ? "High"
          : "Medium";
    risk = {
      risk_level: riskLevel,
      risk_reason:
        executionResult.failed === 0
          ? "All executed regression tests passed."
          : `${executionResult.failed} of ${executionResult.total_tests} demo regression tests failed.`,
      deployment_recommendation:
        riskLevel === "Low" ? "Ready for review" : "Review required",
    };
  }

  return (
    <section className="page-container risk-report-page">
      <h1>Risk Report</h1>

      <p>Review the potential deployment risk based on test execution.</p>

      <p className="demo-notice">
        DEMO MODE — Risk is estimated locally from demo test results; this is not a deployment decision.
      </p>

      {status === "In Progress" ? (
        <div className="loading-container" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true"></div>
          <p>Waiting for the demo test run to finish...</p>
        </div>
      ) : status === "Failed" ? (
        <div className="error" role="alert">
          <h2>Risk report unavailable</h2>
          <p>The test run did not complete. Retry it from Test Selection.</p>
        </div>
      ) : !risk ? (
        <div className="empty-state">
          <h2>Risk not assessed yet</h2>
          <p>Execute regression tests first to generate a risk report.</p>
        </div>
      ) : (
        <div className={`risk-card risk-card-${risk.risk_level.toLowerCase()}`}>
          <div className="risk-heading">
            <div>
              <p className="eyebrow">DEMO RISK ASSESSMENT</p>
              <h2>
                Risk level{" "}
                <span className={`risk-${risk.risk_level.toLowerCase()}`}>
                  {risk.risk_level}
                </span>
              </h2>
            </div>
            <span className="risk-score">{riskScore}/100</span>
          </div>

          <div className="risk-metrics">
            <div>
              <h3>Pass rate</h3>
              <p>{passPercentage ?? "N/A"}%</p>
            </div>
            <div>
              <h3>Tests failed</h3>
              <p>{executionResult?.failed ?? 0}</p>
            </div>
            <div>
              <h3>Tests executed</h3>
              <p>{executionResult?.total_tests ?? 0}</p>
            </div>
          </div>

          <div className="risk-detail">
            <h3>Assessment</h3>
            <p>{risk.risk_reason}</p>
            <p className="risk-calculation">
              Demo rule: no failures = Low; fewer than half failed = Medium;
              half or more failed = High.
            </p>
          </div>

          <div className="recommendation">
            <strong>Suggested next step</strong>
            <p>{risk.deployment_recommendation}</p>
          </div>
          <p className="risk-disclaimer">
            This sample assessment is not a release approval. A human reviewer
            should make the final deployment decision.
          </p>
        </div>
      )}
    </section>
  );
}

export default RiskReportPage;
