import type { ReportResponse } from "../services/api";
import WorkflowInProgress from "./WorkflowInProgress";

type Props = { report: ReportResponse | null; loading: boolean };

function RiskReportPage({ report, loading }: Props) {
  const workflow = report?.workflow_report;
  const risk = workflow?.risk;
  if (loading) {
    return <section className="page-container risk-report-page"><h1>Risk Report</h1><WorkflowInProgress /></section>;
  }
  if (!workflow || !risk) {
    return <section className="page-container risk-report-page"><h1>Risk Report</h1><div className="empty-state"><h2>Risk assessment unavailable</h2><p>Run the uploaded-project workflow to view its backend risk assessment.</p></div></section>;
  }

  const level = risk.level.toLowerCase();
  const verified = risk.verification_status === "VERIFIED" && workflow.verification_success;
  const metricLabels: Record<keyof typeof risk.metrics, string> = {
    changed_function_count: "Changed functions",
    impacted_function_count: "Impacted functions",
    direct_caller_count: "Direct callers",
    transitive_caller_count: "Transitive callers",
    unassigned_line_count: "Unassigned changed lines",
    discovered_test_count: "Tests discovered",
    selected_test_count: "Tests selected",
    uncovered_changed_function_count: "Uncovered changed functions",
    failed_test_count: "Tests failed",
    execution_error_count: "Execution errors",
    skipped_test_count: "Tests skipped",
  };
  return (
    <section className="page-container risk-report-page">
      <h1>Risk Report</h1>
      <p>Risk assessment returned by the backend workflow.</p>
      <div className={`risk-card risk-card-${level}`}>
        <div className="risk-heading">
          <div>
            <p className="eyebrow">BACKEND RISK ASSESSMENT</p>
            <h2>Risk level <span className={`risk-${level}`}>{risk.level}</span></h2>
          </div>
          <span className="risk-score" aria-label={`Risk score ${risk.score} out of 100`}>{risk.score}/100</span>
        </div>

        <div className="risk-metrics">
          {(Object.keys(metricLabels) as Array<keyof typeof risk.metrics>).map((key) => (
            <div key={key}><h3>{metricLabels[key]}</h3><p>{risk.metrics[key]}</p></div>
          ))}
        </div>

        <section className="risk-detail">
          <h3>Risk factors</h3>
          {risk.factors.length ? (
            <ul>{risk.factors.map((factor, index) => <li key={`${factor.name}:${index}`}><strong>{factor.name}</strong> · {factor.points}/{factor.max_points} points — {factor.explanation}</li>)}</ul>
          ) : <p>No contributing risk factors were reported.</p>}
        </section>

        {risk.safety_overrides.length > 0 && (
          <section className="error" aria-label="Risk safety overrides">
            <h3>Safety overrides</h3>
            <ul>{risk.safety_overrides.map((override, index) => <li key={`${override}:${index}`}>{override}</li>)}</ul>
          </section>
        )}

        <div className="recommendation">
          <strong>Backend recommendation</strong>
          <p>{risk.recommendation}</p>
        </div>
        {report.recommendations.length > 0 && (
          <div className="recommendation">
            <strong>Report recommendations</strong>
            <ul>{report.recommendations.map((recommendation, index) => <li key={`${recommendation}:${index}`}>{recommendation}</li>)}</ul>
          </div>
        )}
        <p className="field-note">Verification status: <strong>{risk.verification_status}</strong></p>
        {verified && <p className="success-message" role="status">The backend marked verification as successful.</p>}
        {!verified && <p className="field-note">The workflow has not marked verification successful.</p>}
      </div>
    </section>
  );
}

export default RiskReportPage;
