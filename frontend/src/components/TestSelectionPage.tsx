import { useState } from "react";

import {
  selectTests,
  runTests,
  type AnalysisResult,
  type SelectedTest,
  type TestExecutionResult,
} from "../services/api";

import type { WorkflowStageStatus } from "./WorkflowStatus";

type Props = {
  analysisResult: AnalysisResult | null;

  onSelectionStatusChange: (status: WorkflowStageStatus) => void;

  onExecutionStatusChange: (status: WorkflowStageStatus) => void;

  onExecutionComplete: (result: TestExecutionResult | null) => void;
};

function TestSelectionPage({
  analysisResult,
  onSelectionStatusChange,
  onExecutionStatusChange,
  onExecutionComplete,
}: Props) {
  const [tests, setTests] = useState<SelectedTest[]>([]);
  const [loading, setLoading] = useState(false);
  const [runningTests, setRunningTests] = useState(false);
  const [error, setError] = useState("");
  const [hasRequested, setHasRequested] = useState(false);

  // Request regression test recommendations
  async function handleSelectTests() {
    if (!analysisResult) {
      setError("Please analyze a Git diff first.");
      return;
    }

    setLoading(true);
    setError("");
    setHasRequested(false);
    setTests([]);

    // Update workflow statuses
    onSelectionStatusChange("In Progress");
    onExecutionStatusChange("Pending");
    onExecutionComplete(null);

    try {
      const result = await selectTests(analysisResult.impacted_functions);

      setTests(result.selected_tests);
      setHasRequested(true);

      onSelectionStatusChange("Completed");
    } catch (err) {
      onSelectionStatusChange("Failed");

      setError(
        err instanceof Error
          ? err.message
          : "Unable to select regression tests.",
      );
    } finally {
      setLoading(false);
    }
  }

  // Execute the selected regression tests
  async function handleRunTests() {
    if (tests.length === 0) {
      setError("Please select regression tests first.");
      return;
    }

    setRunningTests(true);
    setError("");

    onExecutionStatusChange("In Progress");
    onExecutionComplete(null);

    try {
      const result = await runTests(tests.map((test) => test.test_name));

      // Send execution results to App.tsx
      onExecutionComplete(result);
      onExecutionStatusChange("Completed");
    } catch (err) {
      onExecutionStatusChange("Failed");

      setError(err instanceof Error ? err.message : "Unable to execute tests.");
    } finally {
      setRunningTests(false);
    }
  }

  return (
    <section className="page-container test-selection-page">
      <h1>Test Selection</h1>

      <p>
        Select regression tests based on the functions affected by your code
        changes.
      </p>
      <div className="demo-notice">
        DEMO MODE — Recommended tests are examples and are not retrieved from a backend.
      </div>

      {!analysisResult ? (
        <div className="empty-state">
          <h2>Analysis required</h2>
          <p>Analyze a Git diff before selecting regression tests.</p>
        </div>
      ) : (
        <>
          <div className="content-card impacted-functions">
            <div className="section-heading">
              <div>
                <h2>Impacted functions</h2>
                <p>Functions identified in the latest demo analysis.</p>
              </div>
              <span className="count-badge">
                {analysisResult.impacted_functions.length}
              </span>
            </div>

            {analysisResult.impacted_functions.length === 0 ? (
              <div className="empty-inline">
                <p>No impacted functions were found for this change.</p>
              </div>
            ) : (
              <ul className="function-list">
                {analysisResult.impacted_functions.map((func) => (
                  <li key={func}>
                    <code>{func}</code>
                  </li>
                ))}
              </ul>
            )}

            <button
              className="button-primary"
              type="button"
              onClick={handleSelectTests}
              disabled={
                loading ||
                runningTests ||
                analysisResult.impacted_functions.length === 0
              }
            >
              {loading ? "Selecting tests..." : "Select regression tests"}
            </button>
          </div>
        </>
      )}

      {loading && (
        <div className="loading-container" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true"></div>
          <p>Finding relevant demo tests...</p>
        </div>
      )}

      {runningTests && (
        <div className="loading-container" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true"></div>
          <p>Running the selected demo tests...</p>
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {hasRequested && (
        <div className="content-card recommended-tests">
          <div className="section-heading">
            <div>
              <h2>Recommended regression tests</h2>
              <p>{tests.length} tests selected for this demo run.</p>
            </div>
            {tests.length > 0 && (
              <span className="count-badge">{tests.length}</span>
            )}
          </div>

          {tests.length === 0 ? (
            <div className="empty-inline">
              <p>No regression tests were recommended for these functions.</p>
            </div>
          ) : (
            tests.map((test) => (
              <div className="test-card" key={test.test_name}>
                <h3>{test.test_name}</h3>
                <p>{test.reason}</p>
                <span className="test-tag">Recommended</span>
              </div>
            ))
          )}

          {tests.length > 0 && (
            <button
              className="button-primary"
              type="button"
              onClick={handleRunTests}
              disabled={runningTests || loading}
            >
              {runningTests ? "Running tests..." : "Run selected tests"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

export default TestSelectionPage;
