import "./App.css";
import { useState } from "react";

import type { AnalysisResult, TestExecutionResult } from "./services/api";

import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import DashboardOverview from "./components/DashboardOverview";
import CodeSubmission from "./components/CodeSubmission";
import TestSelectionPage from "./components/TestSelectionPage";
import TestResultsPage from "./components/TestResultsPage";
import RiskReportPage from "./components/RiskReportPage";
import type { WorkflowStageStatus } from "./components/WorkflowStatus";
import type { PageName } from "./components/Sidebar";

function App() {
  const [activePage, setActivePage] = useState<PageName>("Dashboard");
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(
    null,
  );
  const [executionResult, setExecutionResult] =
    useState<TestExecutionResult | null>(null);
  const [analysisStatus, setAnalysisStatus] =
    useState<WorkflowStageStatus>("Pending");
  const [selectionStatus, setSelectionStatus] =
    useState<WorkflowStageStatus>("Pending");
  const [executionStatus, setExecutionStatus] =
    useState<WorkflowStageStatus>("Pending");
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [riskStatus, setRiskStatus] = useState<WorkflowStageStatus>("Pending");

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

      <Sidebar
        activePage={activePage}
        setActivePage={(page: PageName) => {
          setActivePage(page);
          setIsSidebarOpen(false);
        }}
        isOpen={isSidebarOpen}
      />
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
            analysisResult={analysisResult}
            executionResult={executionResult}
            analysisStatus={analysisStatus}
            selectionStatus={selectionStatus}
            executionStatus={executionStatus}
            riskStatus={riskStatus}
          />
        )}

        {activePage === "Code Analysis" && (
          <div className="page-container">
            <h1>Code Analysis</h1>
            <p>Upload or paste your Git diff to analyze code changes.</p>

            <CodeSubmission
              onAnalysisComplete={(result) => {
                setAnalysisResult(result);
                setExecutionResult(null);
                setAnalysisStatus(result ? "Completed" : "Pending");
                setSelectionStatus("Pending");
                setExecutionStatus("Pending");
                setRiskStatus("Pending");
              }}
              onAnalysisStatusChange={(status) => {
                setAnalysisStatus(status);

                if (status === "In Progress") {
                  setAnalysisResult(null);
                  setExecutionResult(null);
                  setSelectionStatus("Pending");
                  setExecutionStatus("Pending");
                  setRiskStatus("Pending");
                }
              }}
            />
          </div>
        )}

        {activePage === "Test Selection" && (
          <TestSelectionPage
            analysisResult={analysisResult}
            onSelectionStatusChange={setSelectionStatus}
            onExecutionStatusChange={(status) => {
              setExecutionStatus(status);
              setRiskStatus(status === "Completed" ? "Completed" : "Pending");
            }}
            onExecutionComplete={(result) => {
              setExecutionResult(result);
              setRiskStatus(result ? "Completed" : "Pending");
            }}
          />
        )}

        {activePage === "Test Results" && (
          <TestResultsPage result={executionResult} status={executionStatus} />
        )}

        {activePage === "Risk Report" && (
          <RiskReportPage
            executionResult={executionResult}
            status={executionStatus}
          />
        )}
      </main>
    </div>
  );
}

export default App;
