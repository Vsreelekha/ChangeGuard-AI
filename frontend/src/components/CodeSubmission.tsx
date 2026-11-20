import { useState } from "react";
import type { ChangeEvent } from "react";

import { analyzeCode, type AnalysisResult } from "../services/api";

import type { WorkflowStageStatus } from "./WorkflowStatus";
import AnalysisResults from "./AnalysisResults";

type Props = {
  onAnalysisComplete: (result: AnalysisResult | null) => void;
  onAnalysisStatusChange: (status: WorkflowStageStatus) => void;
};

function CodeSubmission({ onAnalysisComplete, onAnalysisStatusChange }: Props) {
  const [diff, setDiff] = useState("");
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [progressStage, setProgressStage] = useState(0);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    if (!file) return;

    setFileName(file.name);
    setError("");
    setSuccess("");
    setResult(null);
    setDiff("");
    onAnalysisComplete(null);
    onAnalysisStatusChange("Pending");

    const reader = new FileReader();

    reader.onload = () => {
      setDiff(String(reader.result ?? ""));
    };

    reader.onerror = () => {
      setError("Unable to read the selected file.");
    };

    reader.readAsText(file);
  }

  function handleDiffChange(value: string) {
    setDiff(value);
    setResult(null);
    setError("");
    setSuccess("");
    onAnalysisComplete(null);
    onAnalysisStatusChange("Pending");
  }

  async function handleSubmit() {
    if (!diff.trim()) {
      setError("Please upload or paste a Git diff first.");
      setSuccess("");
      return;
    }

    setLoading(true);
    onAnalysisStatusChange("In Progress");

    setProgressStage(1);
    setError("");
    setSuccess("");
    setResult(null);

    try {
      // Stage 1: Submitting Git diff
      setProgressStage(1);

      // Stage 2: Waiting for backend analysis
      setProgressStage(2);

      const data = await analyzeCode(diff);

      // Stage 3: Preparing results
      setProgressStage(3);

      setResult(data);
      onAnalysisComplete(data);

      onAnalysisStatusChange("Completed");

      setSuccess("Code analysis completed successfully!");
    } catch (err) {
      onAnalysisStatusChange("Failed");

      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Analysis could not be completed. Please try again.");
      }
    } finally {
      setLoading(false);
      setProgressStage(0);
    }
  }

  function handleClear() {
    setDiff("");
    setFileName("");
    setResult(null);
    setError("");
    setSuccess("");
    setProgressStage(0);
    onAnalysisComplete(null);
    onAnalysisStatusChange("Pending");
  }

  return (
    <section className="submission">
      <div className="section-heading">
        <div>
          <h2>Submit code changes</h2>
          <p>Upload a Git diff or paste its contents to start the workflow.</p>
        </div>
        <span className="demo-pill">DEMO MODE</span>
      </div>

      <label className="file-picker">
        <span>Choose a diff file</span>
        <span className="file-picker-hint">{fileName || ".diff, .patch, .txt"}</span>
        <input
          type="file"
          accept=".diff,.patch,.txt"
          onChange={handleFileChange}
          disabled={loading}
          aria-label="Choose a Git diff file"
        />
      </label>

      <textarea
        value={diff}
        onChange={(event) => handleDiffChange(event.target.value)}
        placeholder="Paste your Git diff content here..."
        rows={12}
        disabled={loading}
        aria-label="Git diff contents"
      />

      <p className="field-note">
        Demo analysis uses sample results. Your diff is not sent to a backend.
      </p>

      <div className="submission-actions">
        <button type="button" onClick={handleSubmit} disabled={loading}>
          {loading ? "Analyzing..." : "Analyze Code Changes"}
        </button>

        <button type="button" onClick={handleClear} disabled={loading}>
          Clear
        </button>
      </div>

      {loading && (
        <div className="loading-container" role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true"></div>
          <p>
            {progressStage === 1 && "Preparing demo analysis..."}
            {progressStage === 2 && "Analyzing code changes..."}
            {progressStage === 3 && "Preparing results..."}
          </p>
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {error && diff.trim() && (
        <button
          className="button-secondary retry-button"
          type="button"
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading ? "Retrying..." : "Retry Analysis"}
        </button>
      )}

      {success && (
        <p className="success-message" role="status">
          {success}
        </p>
      )}

      {result && <AnalysisResults result={result} />}
    </section>
  );
}

export default CodeSubmission;
