function WorkflowInProgress() {
  return (
    <div className="loading-container" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>ChangeGuard is processing the project, selecting tests, and preparing the report...</p>
    </div>
  );
}

export default WorkflowInProgress;
