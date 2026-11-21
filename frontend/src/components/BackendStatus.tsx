import { useEffect, useState } from "react";
import { getBackendHealth } from "../services/api";

type ConnectionState = "checking" | "connected" | "disconnected";

function BackendStatus() {
  const [state, setState] = useState<ConnectionState>("checking");

  useEffect(() => {
    let mounted = true;
    getBackendHealth().then(
      () => { if (mounted) setState("connected"); },
      () => { if (mounted) setState("disconnected"); },
    );
    return () => { mounted = false; };
  }, []);

  const message = state === "checking"
    ? "Checking FastAPI backend..."
    : state === "connected"
      ? "FastAPI backend is connected."
      : "FastAPI backend is unavailable.";
  return (
    <div className={`backend-status backend-status-${state}`} role="status" aria-live="polite">
      <span className="status-dot" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export default BackendStatus;
