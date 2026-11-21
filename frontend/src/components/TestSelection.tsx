type SelectedTest = {
  test_name: string;
  reason: string;
};

type Props = {
  tests: SelectedTest[];
};

function TestSelection({ tests }: Props) {
  return (
    <section className="test-selection">
      <h2>Recommended Regression Tests</h2>

      <p>{tests.length} tests selected for regression testing.</p>

      {tests.length === 0 ? (
        <p>No regression tests were recommended.</p>
      ) : (
        tests.map((test) => (
          <div className="test-card" key={test.test_name}>
            <h3>{test.test_name}</h3>
            <p>{test.reason}</p>
            <span>Recommended</span>
          </div>
        ))
      )}
    </section>
  );
}

export default TestSelection;
