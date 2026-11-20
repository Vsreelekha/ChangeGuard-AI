function BackendStatus() {
  return (
    <div className="backend-status demo-status" role="status">
      <span className="status-dot" aria-hidden="true"></span>
      <span>
        DEMO MODE — Backend integration is pending the FastAPI API contract.
      </span>
    </div>
  );
}

export default BackendStatus;
