import type { ReportResponse, WorkflowTestExecution } from "../services/api";
import { displayStatus } from "../utils/displayStatus";
import WorkflowInProgress from "./WorkflowInProgress";

type Props = { report: ReportResponse | null; loading: boolean };

function TestResultsPage({ report, loading }: Props) {
  const execution = report?.workflow_report.test_execution;
  if (loading) {
    return <section className="page-container test-results-page"><h1>Test Results</h1><WorkflowInProgress /></section>;
  }
  if (!execution) {
    return <section className="page-container test-results-page"><h1>Test Results</h1><div className="empty-state"><h2>No test results yet</h2><p>Run the uploaded-project workflow to see backend test execution results.</p></div></section>;
  }
  return (
    <section className="page-container test-results-page">
      <h1>Test Results</h1>
      <p>Execution status: <strong>{displayStatus(execution.status)}</strong> · {execution.execution_time.toFixed(2)} seconds</p>
      <ExecutionDetails execution={execution} />
    </section>
  );
}

export function ExecutionDetails({ execution }: { execution: WorkflowTestExecution }) {
  const { summary } = execution;
  const status = execution.status.trim().toLowerCase();
  const counts = [summary.total, summary.passed, summary.failed, summary.skipped, summary.errors];
  const countsAreValid = counts.every((count) => Number.isInteger(count) && count >= 0);
  const allPassed = status === "passed" && countsAreValid && summary.total > 0 &&
    summary.passed === summary.total && summary.failed === 0 && summary.skipped === 0 &&
    summary.errors === 0 &&
    summary.total === summary.passed + summary.failed + summary.skipped + summary.errors &&
    execution.failures.length === 0 && execution.exit_code === 0;
  return (
    <>
      <div className="result-summary">
        <div className="result-card"><h3>Total</h3><p>{summary.total}</p></div>
        <div className="result-card"><h3>Passed</h3><p className="metric-success">{summary.passed}</p></div>
        <div className="result-card"><h3>Failed</h3><p className={summary.failed > 0 ? "metric-danger" : ""}>{summary.failed}</p></div>
        <div className="result-card"><h3>Skipped</h3><p>{summary.skipped}</p></div>
        <div className="result-card"><h3>Errors</h3><p className={summary.errors > 0 ? "metric-danger" : ""}>{summary.errors}</p></div>
      </div>

      {status === "timeout" ? (
        <div className="error" role="status"><h2>Test execution timed out</h2><p>{execution.message || "The backend stopped the test run after its time limit."}</p></div>
      ) : status === "skipped" ? (
        <div className="empty-inline" role="status"><strong>Test execution was skipped.</strong> {execution.message}</div>
      ) : status === "error" || status === "failed" ? (
        <div className="error" role="status"><h2>Test execution {status}</h2><p>{execution.message}</p></div>
      ) : allPassed ? (
        <div className="success-message" role="status">All {summary.total} selected test(s) passed.</div>
      ) : status === "passed" ? (
        <div className="error" role="status"><h2>Execution evidence is incomplete or inconsistent</h2><p>The backend reported a passed status, but the counts, failure details, or exit code do not confirm that every selected test passed.</p></div>
      ) : (
        <div className="empty-inline" role="status">Execution status was not recognized: {execution.status || "missing"}. Use the counts and output below to review the run.</div>
      )}

      <section className="failed-tests">
        <h2>Failure details</h2>
        {execution.failures.length === 0 ? <p>No failure details were reported.</p> : (
          <ul>{execution.failures.map((failure, index) => <li key={`${failure.test}:${index}`}><strong>{failure.test}</strong>{failure.message && <p>{failure.message}</p>}</li>)}</ul>
        )}
      </section>
      {(execution.stdout || execution.stderr) && (
        <details className="content-card">
          <summary>Execution output</summary>
          {execution.stdout && <><h3>Standard output</h3><pre>{execution.stdout}</pre></>}
          {execution.stderr && <><h3>Standard error</h3><pre>{execution.stderr}</pre></>}
        </details>
      )}
      {execution.exit_code !== null && <p className="field-note">Process exit code: {execution.exit_code}</p>}
    </>
  );
}

export default TestResultsPage;
