import type { AnalysisResult } from "../services/api";

type Props = {
  result: AnalysisResult;
};

function AnalysisResults({ result }: Props) {
  return (
    <section className="results-section">
      <h2>Code Analysis Results</h2>

      <div className="results-grid">
        <div className="result-card">
          <h3>Changed Functions</h3>
          <h2>{result.changed_functions.length}</h2>
          {result.changed_functions.map((name) => (
            <p key={name}>{name}</p>
          ))}
        </div>

        <div className="result-card">
          <h3>Impacted Functions</h3>
          <h2>{result.impacted_functions.length}</h2>
          {result.impacted_functions.map((name) => (
            <p key={name}>{name}</p>
          ))}
        </div>

        <div className="result-card">
          <h3>Impacted Modules</h3>
          <h2>{result.impacted_modules.length}</h2>
          {result.impacted_modules.map((name) => (
            <p key={name}>{name}</p>
          ))}
        </div>
      </div>
    </section>
  );
}

export default AnalysisResults;
