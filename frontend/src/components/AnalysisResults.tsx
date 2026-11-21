import type { ReportResponse } from "../services/api";

type Props = { report: ReportResponse };

function AnalysisResults({ report }: Props) {
  const impact = report.impact_analysis;

  return (
    <section className="results-section" aria-labelledby="analysis-results-title">
      <h2 id="analysis-results-title">Code Analysis Results</h2>
      {!impact.success && <p className="error">The analyzer reported an unsuccessful analysis.</p>}

      <div className="results-grid">
        <div className="result-card">
          <h3>Changed files</h3><h2>{impact.summary.changed_files_count}</h2>
          {impact.changed_files.map((file) => (
            <p key={`${file.file_path}:${file.change_type}`}>
              {file.change_type}: {file.file_path} (+{file.added_lines_count} / -{file.deleted_lines_count})
            </p>
          ))}
        </div>
        <div className="result-card">
          <h3>Changed functions</h3><h2>{impact.summary.changed_functions_count}</h2>
          {impact.changed_functions.map((func) => (
            <p key={func.id} title={`${func.file_path}:${func.start_line}-${func.end_line}`}>
              {func.qualified_name} · {func.file_path}:{func.start_line}
            </p>
          ))}
        </div>
        <div className="result-card">
          <h3>Impacted functions</h3><h2>{impact.summary.impacted_functions_count}</h2>
          {impact.impacted_functions.map((func) => (
            <p key={func.id} title={func.reason}>
              {func.qualified_name} · {func.file_path}:{func.start_line} (distance {func.distance})
            </p>
          ))}
        </div>
      </div>

      <section className="content-card">
        <h3>Impacted modules</h3>
        {report.impacted_modules.length ? report.impacted_modules.map((module) => <p key={module}><code>{module}</code></p>) : <p>No impacted modules were identified.</p>}
      </section>

      {impact.unassigned_changed_lines.length > 0 && (
        <section className="content-card">
          <h3>Changed lines not assigned to a function</h3>
          {impact.unassigned_changed_lines.map((record) => (
            <p key={record.file_path}><code>{record.file_path}</code>: lines {record.lines.join(", ")}</p>
          ))}
        </section>
      )}

      {impact.errors.length > 0 && (
        <section className="content-card" aria-label="Analyzer warnings and errors">
          <h3>Analyzer warnings and errors</h3>
          {impact.errors.map((item, index) => <p key={`${item.file_path}:${index}`}><code>{item.file_path}</code>: {item.error}</p>)}
        </section>
      )}

      {report.workflow_report.errors.length > 0 && (
        <section className="content-card" aria-label="Workflow warnings and errors">
          <h3>Workflow warnings and errors</h3>
          {report.workflow_report.errors.map((item, index) => <p key={`${item.source}:${item.file_path}:${index}`}>{item.source} · {item.file_path}: {item.error}</p>)}
        </section>
      )}
    </section>
  );
}

export default AnalysisResults;
