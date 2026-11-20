import type { TestExecutionResult } from "../services/api";
import type { WorkflowStageStatus } from "./WorkflowStatus";

type Props = {
  result: TestExecutionResult | null;
  status: WorkflowStageStatus;
};

function TestResultsPage({ result, status }: Props) {
  return (
    <section className="page-container test-results-page">
      <h1>Test Results</h1>
      <p>View the results of your regression test execution.</p>
      <div className="demo-notice">
        DEMO MODE — Results are generated from the local sample test set.
      </div>

      {status === "In Progress" ? (
        <div className="loading-container" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true"></div>
          <p>Running demo tests...</p>
        </div>
      ) : status === "Failed" ? (
        <div className="error" role="alert">
          <h2>Test run did not complete</h2>
          <p>Return to Test Selection and try running the selected tests again.</p>
        </div>
      ) : !result ? (
        <div className="empty-state">
          <h2>No test results yet</h2>
          <p>Select regression tests and run them to see the results here.</p>
        </div>
      ) : (
        <>
          <div className="success-message" role="status">
            Demo test run completed.
          </div>
          <div className="result-summary">
            <div className="result-card">
              <h3>Total Tests</h3>
              <p>{result.total_tests}</p>
            </div>

            <div className="result-card">
              <h3>Passed</h3>
              <p className="metric-success">{result.passed}</p>
            </div>

            <div className="result-card">
              <h3>Failed</h3>
              <p className={result.failed > 0 ? "metric-danger" : ""}>
                {result.failed}
              </p>
            </div>
          </div>

          <div className="failed-tests">
            <h2>Failed Tests</h2>

            {result.failures.length === 0 ? (
              <p className="all-passed">All tests passed successfully.</p>
            ) : (
              <ul>
                {result.failures.map((testName) => (
                  <li key={testName}>{testName}</li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}

export default TestResultsPage;
