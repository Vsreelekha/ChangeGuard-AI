import "./App.css";
import { useState } from "react";

import {
  ApiError,
  runProject,
  uploadProject,
  type ProjectUploadResponse,
  type ReportResponse,
} from "./services/api";

import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import DashboardOverview from "./components/DashboardOverview";
import CodeSubmission from "./components/CodeSubmission";
import AnalysisResults from "./components/AnalysisResults";
import TestSelectionPage from "./components/TestSelectionPage";
import TestResultsPage from "./components/TestResultsPage";
import RiskReportPage from "./components/RiskReportPage";
import type { PageName } from "./components/Sidebar";

type SubmissionPhase = "uploading" | "running" | null;

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "The workflow could not be completed.";
}

function App() {
  const [activePage, setActivePage] = useState<PageName>("Dashboard");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [uploadMetadata, setUploadMetadata] =
    useState<ProjectUploadResponse | null>(null);
  const [gitDiff, setGitDiff] = useState("");
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [submissionPhase, setSubmissionPhase] = useState<SubmissionPhase>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  async function handleRunAnalysis(zipFile: File, diff: string) {
    // Clear old results before starting so another project's data is never shown
    // while a new upload or workflow request is in progress.
    setProjectId(null);
    setUploadMetadata(null);
    setReport(null);
    setGitDiff(diff);
    setApiError(null);
    setSubmissionPhase("uploading");

    try {
      const uploaded = await uploadProject(zipFile);
      setUploadMetadata(uploaded);
      setProjectId(uploaded.project_id);
      setSubmissionPhase("running");

      // The workflow POST is intentionally issued once. A network failure can
      // leave its outcome uncertain, so the UI does not automatically retry it.
      const completedReport = await runProject(uploaded.project_id, {
        git_diff: diff,
      });
      setReport(completedReport);
      setActivePage("Code Analysis");
    } catch (error) {
      setApiError(errorText(error));
      setActivePage("Code Analysis");
    } finally {
      setSubmissionPhase(null);
    }
  }

  function handleClearAnalysis() {
    setProjectId(null);
    setUploadMetadata(null);
    setGitDiff("");
    setReport(null);
    setApiError(null);
  }

  const navigate = (page: PageName) => {
    setActivePage(page);
    setIsSidebarOpen(false);
  };

  return (
    <div className="app-layout">
      <button
        className="mobile-menu-button"
        onClick={() => setIsSidebarOpen((open) => !open)}
        aria-label="Toggle navigation menu"
        aria-expanded={isSidebarOpen}
        aria-controls="primary-navigation"
      >
        ☰
      </button>

      <Sidebar activePage={activePage} setActivePage={navigate} isOpen={isSidebarOpen} />
      {isSidebarOpen && (
        <button
          className="sidebar-backdrop"
          onClick={() => setIsSidebarOpen(false)}
          aria-label="Close navigation menu"
        />
      )}

      <main className="main-content">
        <Header activePage={activePage} />

        {activePage === "Dashboard" && (
          <DashboardOverview
            report={report}
            loading={submissionPhase !== null}
            onStartAnalysis={() => navigate("Code Analysis")}
          />
        )}

        {activePage === "Code Analysis" && (
          <div className="page-container">
            <h1>Code Analysis</h1>
            <p>Upload a Python project ZIP and provide the Git diff to run the workflow.</p>
            <CodeSubmission
              gitDiff={gitDiff}
              onDiffChange={setGitDiff}
              onSubmit={handleRunAnalysis}
              onClear={handleClearAnalysis}
              loading={submissionPhase !== null}
              phase={submissionPhase}
              error={apiError}
              uploadMetadata={uploadMetadata}
              projectId={projectId}
            />
            {report && <AnalysisResults report={report} />}
          </div>
        )}

        {activePage === "Test Selection" && (
          <TestSelectionPage report={report} loading={submissionPhase !== null} />
        )}

        {activePage === "Test Results" && (
          <TestResultsPage report={report} loading={submissionPhase !== null} />
        )}

        {activePage === "Risk Report" && (
          <RiskReportPage report={report} loading={submissionPhase !== null} />
        )}
      </main>
    </div>
  );
}

export default App;
