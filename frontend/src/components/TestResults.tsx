type ExecutionResult = {
  total_tests: number;
  passed: number;
  failed: number;
  failures: string[];
};

type Props = {
  result: ExecutionResult;
};

function TestResults({ result }: Props) {
  return (
    <section className="execution-results">
      <h2>Test Execution Results</h2>

      <div className="execution-grid">
        <div className="execution-card">
          <h3>Total Tests</h3>
          <p>{result.total_tests}</p>
        </div>

        <div className="execution-card passed">
          <h3>Passed</h3>
          <p>{result.passed}</p>
        </div>

        <div className="execution-card failed">
          <h3>Failed</h3>
          <p>{result.failed}</p>
        </div>
      </div>

      <h3>Failed Tests</h3>

      {result.failures.length === 0 ? (
        <p>All executed tests passed!</p>
      ) : (
        result.failures.map((failure) => (
          <div className="failure-item" key={failure}>
            {failure}
          </div>
        ))
      )}
    </section>
  );
}

export default TestResults;
