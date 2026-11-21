import type { ReportResponse } from "../services/api";

import AnalysisResults from "./AnalysisResults";
import BackendStatus from "./BackendStatus";
import { ExecutionDetails } from "./TestResultsPage";
import RiskAssessment from "./RiskAssessment";
import StatCard from "./StatCard";
import WorkflowInProgress from "./WorkflowInProgress";

type Props = {
  report: ReportResponse | null;
  loading: boolean;
  onStartAnalysis: () => void;
};

function DashboardOverview({ report, loading, onStartAnalysis }: Props) {
  const impact = report?.impact_analysis;
  const execution = report?.workflow_report.test_execution;
  const risk = report?.workflow_report.risk;

  return (
    <div className="dashboard-overview">
      <BackendStatus />
      <div className="page-intro">
        <div>
          <p className="eyebrow">OVERVIEW</p>
          <h1>ChangeGuard AI Dashboard</h1>
          <p>Review the latest backend analysis, regression results, and risk assessment.</p>
        </div>
        <button className="button-primary" type="button" onClick={onStartAnalysis}>New analysis</button>
      </div>

      {loading ? (
        <WorkflowInProgress />
      ) : report ? (
        <>
          <div className="stats-grid">
            <StatCard title="Changed Functions" value={impact?.summary.changed_functions_count ?? "—"} description="Reported by the analyzer" />
            <StatCard title="Impacted Functions" value={impact?.summary.impacted_functions_count ?? "—"} description="Reported by the analyzer" />
            <StatCard title="Tests Selected" value={report.workflow_report.test_selection_result.total_tests_selected} description={`${report.workflow_report.test_selection_result.total_tests_discovered} discovered`} />
            <StatCard title="Failed Tests" value={execution?.summary.failed ?? "—"} description={`${execution?.summary.passed ?? 0} passed · ${execution?.summary.skipped ?? 0} skipped`} />
          </div>

          <section className="dashboard-section">
            <h2>Latest Code Analysis</h2>
            <AnalysisResults report={report} />
          </section>

          <div className="dashboard-lower-grid">
            <section className="dashboard-section">
              <h2>Latest Test Execution</h2>
              {execution ? <ExecutionDetails execution={execution} /> : <p>Execution data is unavailable in this report.</p>}
            </section>
            {risk && <RiskAssessment risk={risk} />}
          </div>
        </>
      ) : (
        <div className="empty-state">
          <h2>No workflow report yet</h2>
          <p>Upload a Python project ZIP and submit a Git diff to see actual analysis, test, and risk results.</p>
          <button className="button-primary" type="button" onClick={onStartAnalysis}>Start an analysis</button>
        </div>
      )}
    </div>
  );
}

export default DashboardOverview;
