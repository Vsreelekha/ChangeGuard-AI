import type { ReportResponse } from "../services/api";
import WorkflowInProgress from "./WorkflowInProgress";

type Props = { report: ReportResponse | null; loading: boolean };

function TestSelectionPage({ report, loading }: Props) {
  const selection = report?.workflow_report.test_selection_result;
  return (
    <section className="page-container test-selection-page">
      <h1>Test Selection</h1>
      <p>Tests are selected and executed as part of the uploaded-project workflow.</p>
      {loading ? <WorkflowInProgress /> : !selection ? (
        <div className="empty-state"><h2>No workflow results yet</h2><p>Upload a project and run an analysis to see the backend test selection.</p></div>
      ) : (
        <>
          <div className="content-card">
            <div className="section-heading">
              <div><h2>Selected regression tests</h2><p>{selection.total_tests_selected} of {selection.total_tests_discovered} discovered tests selected · {selection.reduction_percentage}% reduction</p></div>
              <span className="count-badge">{selection.total_tests_selected}</span>
            </div>
            {selection.selected_tests.length === 0 ? (
              <div className="empty-inline"><p>The backend did not select any regression tests.</p></div>
            ) : selection.selected_tests.map((test) => (
              <article className="test-card" key={test.test_id}>
                <h3>{test.test_name}</h3>
                <p><code>{test.test_file}</code></p>
                <p><strong>Priority:</strong> {test.priority}</p>
                <p><strong>Target functions:</strong> {test.target_functions.length ? test.target_functions.join(", ") : "None reported"}</p>
                <p><strong>Selection reason:</strong> {test.selection_reason}</p>
                <span className="field-note">Test ID: <code>{test.test_id}</code></span>
              </article>
            ))}
            {selection.errors.length > 0 && (
              <div className="error" role="status">
                <h3>Selection messages</h3>
                {selection.errors.map((item, index) => <p key={`${item.file_path}:${index}`}>{item.file_path}: {item.message ?? item.error ?? "Selection issue"}</p>)}
              </div>
            )}
          </div>
          <div className="field-note">The backend has already completed selection and execution. This screen does not submit a second test request.</div>
        </>
      )}
    </section>
  );
}

export default TestSelectionPage;
