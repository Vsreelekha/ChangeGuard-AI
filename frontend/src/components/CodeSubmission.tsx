import { useState } from "react";
import type { ChangeEvent } from "react";
import type { ProjectUploadResponse } from "../services/api";

type Props = {
  gitDiff: string;
  onDiffChange: (diff: string) => void;
  onSubmit: (zipFile: File, diff: string) => Promise<void>;
  onClear: () => void;
  loading: boolean;
  phase: "uploading" | "running" | null;
  error: string | null;
  uploadMetadata: ProjectUploadResponse | null;
  projectId: string | null;
};

function CodeSubmission({
  gitDiff,
  onDiffChange,
  onSubmit,
  onClear,
  loading,
  phase,
  error,
  uploadMetadata,
  projectId,
}: Props) {
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [diffFileName, setDiffFileName] = useState("");
  const [validationError, setValidationError] = useState("");

  function handleZipChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setValidationError("");
    if (file && !file.name.toLowerCase().endsWith(".zip")) {
      setZipFile(null);
      setValidationError("Choose a ZIP archive containing the Python project.");
      event.target.value = "";
      return;
    }
    setZipFile(file);
  }

  function handleDiffFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setValidationError("");
    setDiffFileName(file.name);
    const reader = new FileReader();
    reader.onload = () => onDiffChange(String(reader.result ?? ""));
    reader.onerror = () => setValidationError("Unable to read the selected diff file.");
    reader.readAsText(file);
  }

  async function handleSubmit() {
    if (!zipFile) {
      setValidationError("Choose a project ZIP file first.");
      return;
    }
    if (!gitDiff.trim()) {
      setValidationError("Choose a diff file or paste the Git diff contents.");
      return;
    }
    setValidationError("");
    await onSubmit(zipFile, gitDiff);
  }

  function handleClear() {
    setZipFile(null);
    setDiffFileName("");
    setValidationError("");
    onClear();
  }

  return (
    <section className="submission">
      <div className="section-heading">
        <div>
          <h2>Submit a project change</h2>
          <p>The project is uploaded to a temporary server workspace and analyzed there.</p>
        </div>
        <span className="count-badge">Python ZIP</span>
      </div>

      <label className="file-picker">
        <span>Choose a Python project ZIP</span>
        <span className="file-picker-hint">{zipFile?.name ?? ".zip"}</span>
        <input
          type="file"
          accept=".zip,application/zip"
          onChange={handleZipChange}
          disabled={loading}
          aria-label="Choose a Python project ZIP file"
        />
      </label>

      <label className="file-picker diff-file-picker">
        <span>Choose a Git diff file (optional)</span>
        <span className="file-picker-hint">{diffFileName || ".diff, .patch, .txt"}</span>
        <input
          type="file"
          accept=".diff,.patch,.txt"
          onChange={handleDiffFileChange}
          disabled={loading}
          aria-label="Choose a Git diff file"
        />
      </label>

      <textarea
        value={gitDiff}
        onChange={(event) => onDiffChange(event.target.value)}
        placeholder="Paste the Git diff contents here..."
        rows={12}
        disabled={loading}
        aria-label="Git diff contents"
      />
      <p className="field-note">The ZIP and diff are sent to the configured ChangeGuard backend.</p>

      <div className="submission-actions">
        <button type="button" onClick={handleSubmit} disabled={loading}>
          {phase === "uploading" ? "Uploading project..." : phase === "running" ? "Running workflow..." : "Upload and analyze"}
        </button>
        <button type="button" onClick={handleClear} disabled={loading}>Clear</button>
      </div>

      {loading && (
        <div className="loading-container" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true" />
          <p>{phase === "uploading" ? "Uploading and validating the project archive..." : "Analyzing changes and running selected tests..."}</p>
        </div>
      )}

      {(validationError || error) && (
        <p className="error" role="alert">{validationError || error}</p>
      )}

      {uploadMetadata && projectId && (
        <p className="field-note" role="status">
          Project uploaded ({uploadMetadata.file_count} files). Temporary project ID: <code>{projectId}</code>.
          {error ? " The workflow request did not return a report; start a new analysis to submit again." : ""}
        </p>
      )}
    </section>
  );
}

export default CodeSubmission;
