/** JSON values accepted by the backend's structured result dictionaries. */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface BackendHealthResponse {
  status: "healthy";
  project: string;
}

export interface ProjectUploadResponse {
  project_id: string;
  file_count: number;
  /** ISO-8601 datetime serialized by Pydantic. */
  expires_at: string;
}

export interface ProjectRunRequest {
  git_diff: string;
}

export interface ChangedFileRecord {
  file_path: string;
  change_type: "added" | "modified" | "deleted" | "renamed";
  added_lines_count: number;
  deleted_lines_count: number;
}

export interface ChangedFunctionRecord {
  id: string;
  name: string;
  qualified_name: string;
  file_path: string;
  start_line: number;
  end_line: number;
  function_type: string;
  changed_lines: number[];
}

export interface ImpactedFunctionRecord {
  id: string;
  name: string;
  qualified_name: string;
  file_path: string;
  start_line: number;
  end_line: number;
  function_type: string;
  reason: string;
  distance: number;
}

export interface UnassignedChangedLinesRecord {
  file_path: string;
  lines: number[];
}

export interface AnalyzerErrorRecord {
  file_path: string;
  error: string;
}

export interface ImpactAnalysisSummary {
  changed_files_count: number;
  changed_functions_count: number;
  impacted_functions_count: number;
  unassigned_lines_count: number;
  errors_count: number;
}

/** Exact structured result returned by code_analyzer.impact_analyzer. */
export interface ImpactAnalysis {
  success: boolean;
  changed_files: ChangedFileRecord[];
  changed_functions: ChangedFunctionRecord[];
  impacted_functions: ImpactedFunctionRecord[];
  unassigned_changed_lines: UnassignedChangedLinesRecord[];
  errors: AnalyzerErrorRecord[];
  summary: ImpactAnalysisSummary;
}

export interface SelectedTestRecord {
  test_id: string;
  test_file: string;
  test_name: string;
  target_functions: string[];
  selection_reason: string;
  priority: string;
}

export interface TestSelectionSummary {
  high_priority_count: number;
  medium_priority_count: number;
  module_level_count: number;
  total_selected: number;
  total_discovered: number;
}

export interface TestSelectionError {
  file_path?: string;
  message?: string;
  error?: string;
}

/** Full selector result persisted for project-ID workflow runs. */
export interface TestSelectionResult {
  success: boolean;
  selected_tests: SelectedTestRecord[];
  total_tests_discovered: number;
  total_tests_selected: number;
  reduction_percentage: number;
  pytest_args: string[];
  selection_summary: TestSelectionSummary;
  errors: TestSelectionError[];
}

export interface TestExecutionSummary {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
  /** The runner may also report xfailed, xpassed, and deselected counters. */
  [counter: string]: number;
}

export interface TestFailureDetail {
  test: string;
  message: string;
}

/** Normalized execution block assembled by the existing report generator. */
export interface WorkflowTestExecution {
  status: string;
  execution_time: number;
  exit_code: number | null;
  summary: TestExecutionSummary;
  failures: TestFailureDetail[];
  message: string;
  stdout: string;
  stderr: string;
}

/** Runner output when Dockerized pytest was actually invoked. */
export interface RunnerTestExecutionResult {
  total_tests: number;
  passed: number;
  failed: number;
  failures: string[];
  success: boolean;
  status: string;
  summary: TestExecutionSummary;
  execution_time: number;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  failure_details: TestFailureDetail[];
  message: string;
}

/** Synthesized result used when execution is skipped, times out, or errors. */
export interface NonRunnerTestExecutionResult {
  status: "skipped" | "timeout" | "error";
  success: false;
  summary: TestExecutionSummary;
  execution_time: number;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  failures: string[];
  failure_details: TestFailureDetail[];
  message: string;
}

export type PersistedTestExecutionResult =
  | RunnerTestExecutionResult
  | NonRunnerTestExecutionResult;

export interface RiskFactor {
  name: string;
  points: number;
  max_points: number;
  explanation: string;
}

export interface RiskMetrics {
  changed_function_count: number;
  impacted_function_count: number;
  direct_caller_count: number;
  transitive_caller_count: number;
  unassigned_line_count: number;
  discovered_test_count: number;
  selected_test_count: number;
  uncovered_changed_function_count: number;
  failed_test_count: number;
  execution_error_count: number;
  skipped_test_count: number;
}

export interface RiskAssessment {
  score: number;
  level: "LOW" | "MEDIUM" | "HIGH";
  factors: RiskFactor[];
  metrics: RiskMetrics;
  safety_overrides: string[];
  recommendation: string;
  verification_status:
    | "TIMEOUT"
    | "ERROR"
    | "FAILED"
    | "SKIPPED"
    | "UNVERIFIED"
    | "VERIFIED"
    | "UNCERTAIN";
}

export interface WorkflowImpact {
  summary: ImpactAnalysisSummary;
  changed_files: ChangedFileRecord[];
  changed_functions: ChangedFunctionRecord[];
  impacted_functions: ImpactedFunctionRecord[];
  unassigned_changed_lines: UnassignedChangedLinesRecord[];
}

export interface WorkflowEvidence {
  protected_functions: Array<Record<string, JsonValue>>;
  exposed_functions: Array<Record<string, JsonValue>>;
  direct_call_paths: Array<Record<string, JsonValue>>;
}

export interface WorkflowError {
  source: string;
  file_path: string;
  error: string;
}

/** Report-generator structure plus project workflow service fields. */
export interface WorkflowReport {
  report_id: string;
  generated_at: string;
  success: boolean;
  metadata: Record<string, JsonValue> | null;
  risk: RiskAssessment;
  impact: WorkflowImpact;
  test_selection: Omit<TestSelectionResult, "success" | "pytest_args" | "errors">;
  test_execution: WorkflowTestExecution;
  evidence: WorkflowEvidence;
  errors: WorkflowError[];
  verification_success: boolean;
  test_selection_result: TestSelectionResult;
  test_execution_result: PersistedTestExecutionResult;
}

export interface ReportTestSummary {
  total_tests: number;
  passed: number;
  failed: number;
  errors: number;
  failures: string[];
}

export interface ReportResponse {
  run_id: string;
  risk_level: string;
  changed_functions: ChangedFunctionRecord[];
  impacted_functions: ImpactedFunctionRecord[];
  impacted_modules: string[];
  tests: ReportTestSummary;
  recommendations: string[];
  created_at: string | null;
  impact_analysis: ImpactAnalysis;
  workflow_report: WorkflowReport;
}

export interface BackendErrorResponse {
  error: string;
  status_code: number;
  /** Domain errors use an object, validation errors use an array, and generic 500s omit it. */
  details?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(
    message: string,
    status: number,
    details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000")
  .replace(/\/+$/, "");

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isNonNegativeIntegerArray(value: unknown): value is number[] {
  return Array.isArray(value) && value.every(isNonNegativeInteger);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function isJsonObject(value: unknown): value is Record<string, JsonValue> {
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function isBackendHealthResponse(value: unknown): value is BackendHealthResponse {
  return isRecord(value) && value.status === "healthy" && typeof value.project === "string";
}

function isProjectUploadResponse(value: unknown): value is ProjectUploadResponse {
  return (
    isRecord(value) &&
    typeof value.project_id === "string" &&
    typeof value.file_count === "number" &&
    Number.isInteger(value.file_count) &&
    value.file_count >= 1 &&
    typeof value.expires_at === "string" &&
    !Number.isNaN(Date.parse(value.expires_at))
  );
}

function isChangedFileRecord(value: unknown): value is ChangedFileRecord {
  return (
    isRecord(value) && isString(value.file_path) &&
    ["added", "modified", "deleted", "renamed"].includes(String(value.change_type)) &&
    isNonNegativeInteger(value.added_lines_count) &&
    isNonNegativeInteger(value.deleted_lines_count)
  );
}

function isChangedFunctionRecord(value: unknown): value is ChangedFunctionRecord {
  return (
    isRecord(value) && isString(value.id) && isString(value.name) &&
    isString(value.qualified_name) && isString(value.file_path) &&
    isNonNegativeInteger(value.start_line) && isNonNegativeInteger(value.end_line) &&
    isString(value.function_type) && isNonNegativeIntegerArray(value.changed_lines)
  );
}

function isImpactedFunctionRecord(value: unknown): value is ImpactedFunctionRecord {
  return (
    isRecord(value) && isString(value.id) && isString(value.name) &&
    isString(value.qualified_name) && isString(value.file_path) &&
    isNonNegativeInteger(value.start_line) && isNonNegativeInteger(value.end_line) &&
    isString(value.function_type) && isString(value.reason) &&
    isNonNegativeInteger(value.distance)
  );
}

function isImpactSummary(value: unknown): value is ImpactAnalysisSummary {
  return isRecord(value) &&
    isNonNegativeInteger(value.changed_files_count) &&
    isNonNegativeInteger(value.changed_functions_count) &&
    isNonNegativeInteger(value.impacted_functions_count) &&
    isNonNegativeInteger(value.unassigned_lines_count) &&
    isNonNegativeInteger(value.errors_count);
}

function isAnalyzerError(value: unknown): value is AnalyzerErrorRecord {
  return isRecord(value) && isString(value.file_path) && isString(value.error);
}

function isUnassignedLines(value: unknown): value is UnassignedChangedLinesRecord {
  return isRecord(value) && isString(value.file_path) && Array.isArray(value.lines) &&
    value.lines.every(isNonNegativeInteger);
}

function isImpactAnalysis(value: unknown): value is ImpactAnalysis {
  return (
    isRecord(value) && typeof value.success === "boolean" &&
    Array.isArray(value.changed_files) && value.changed_files.every(isChangedFileRecord) &&
    Array.isArray(value.changed_functions) && value.changed_functions.every(isChangedFunctionRecord) &&
    Array.isArray(value.impacted_functions) && value.impacted_functions.every(isImpactedFunctionRecord) &&
    Array.isArray(value.unassigned_changed_lines) && value.unassigned_changed_lines.every(isUnassignedLines) &&
    Array.isArray(value.errors) && value.errors.every(isAnalyzerError) &&
    isImpactSummary(value.summary)
  );
}

function isSelectedTest(value: unknown): value is SelectedTestRecord {
  return isRecord(value) && isString(value.test_id) && isString(value.test_file) &&
    isString(value.test_name) && isStringArray(value.target_functions) &&
    isString(value.selection_reason) && isString(value.priority);
}

function isSelectionSummary(value: unknown): value is TestSelectionSummary {
  return isRecord(value) && isNonNegativeInteger(value.high_priority_count) &&
    isNonNegativeInteger(value.medium_priority_count) &&
    isNonNegativeInteger(value.module_level_count) &&
    isNonNegativeInteger(value.total_selected) &&
    isNonNegativeInteger(value.total_discovered);
}

function isSelectionError(value: unknown): value is TestSelectionError {
  return isRecord(value) &&
    (value.file_path === undefined || isString(value.file_path)) &&
    (value.message === undefined || isString(value.message)) &&
    (value.error === undefined || isString(value.error)) &&
    (isString(value.message) || isString(value.error));
}

function isTestSelectionResult(value: unknown): value is TestSelectionResult {
  return isRecord(value) && typeof value.success === "boolean" &&
    Array.isArray(value.selected_tests) && value.selected_tests.every(isSelectedTest) &&
    isNonNegativeInteger(value.total_tests_discovered) &&
    isNonNegativeInteger(value.total_tests_selected) &&
    isFiniteNumber(value.reduction_percentage) && isStringArray(value.pytest_args) &&
    isSelectionSummary(value.selection_summary) &&
    Array.isArray(value.errors) && value.errors.every(isSelectionError);
}

function isTestExecutionSummary(value: unknown): value is TestExecutionSummary {
  return isRecord(value) &&
    isNonNegativeInteger(value.total) && isNonNegativeInteger(value.passed) &&
    isNonNegativeInteger(value.failed) && isNonNegativeInteger(value.skipped) &&
    isNonNegativeInteger(value.errors) &&
    Object.values(value).every(isNonNegativeInteger);
}

function isFailureDetail(value: unknown): value is TestFailureDetail {
  return isRecord(value) && isString(value.test) && isString(value.message);
}

function isWorkflowTestExecution(value: unknown): value is WorkflowTestExecution {
  return isRecord(value) && isString(value.status) && isFiniteNumber(value.execution_time) &&
    (value.exit_code === null || Number.isInteger(value.exit_code)) &&
    isTestExecutionSummary(value.summary) && Array.isArray(value.failures) &&
    value.failures.every(isFailureDetail) && isString(value.message) &&
    isString(value.stdout) && isString(value.stderr);
}

function isPersistedExecutionResult(value: unknown): value is PersistedTestExecutionResult {
  if (!isRecord(value) || !isString(value.status) || typeof value.success !== "boolean" ||
      !isTestExecutionSummary(value.summary) || !isFiniteNumber(value.execution_time) ||
      !isString(value.stdout) || !isString(value.stderr) ||
      !(value.exit_code === null || Number.isInteger(value.exit_code)) ||
      !Array.isArray(value.failure_details) || !value.failure_details.every(isFailureDetail) ||
      !isString(value.message)) return false;

  const runnerShape = isNonNegativeInteger(value.total_tests) &&
    isNonNegativeInteger(value.passed) && isNonNegativeInteger(value.failed) &&
    isStringArray(value.failures);
  const synthesizedShape = value.success === false &&
    ["skipped", "timeout", "error"].includes(value.status) && isStringArray(value.failures);
  return runnerShape || synthesizedShape;
}

function isRiskAssessment(value: unknown): value is RiskAssessment {
  const verificationStatuses = ["TIMEOUT", "ERROR", "FAILED", "SKIPPED", "UNVERIFIED", "VERIFIED", "UNCERTAIN"];
  if (!isRecord(value) || !isNonNegativeInteger(value.score) ||
      !["LOW", "MEDIUM", "HIGH"].includes(String(value.level)) ||
      !Array.isArray(value.factors) || !value.factors.every((factor) =>
        isRecord(factor) && isString(factor.name) && isFiniteNumber(factor.points) &&
        isFiniteNumber(factor.max_points) && isString(factor.explanation)) ||
      !isRecord(value.metrics) || !Object.values(value.metrics).every(isNonNegativeInteger) ||
      !Array.isArray(value.safety_overrides) || !isStringArray(value.safety_overrides) ||
      !isString(value.recommendation) || !verificationStatuses.includes(String(value.verification_status))) {
    return false;
  }
  const metrics = value.metrics;
  const expectedMetrics: (keyof RiskMetrics)[] = [
    "changed_function_count", "impacted_function_count", "direct_caller_count",
    "transitive_caller_count", "unassigned_line_count", "discovered_test_count",
    "selected_test_count", "uncovered_changed_function_count", "failed_test_count",
    "execution_error_count", "skipped_test_count",
  ];
  return expectedMetrics.every((key) => isNonNegativeInteger(metrics[key]));
}

function isWorkflowImpact(value: unknown): value is WorkflowImpact {
  return isRecord(value) && isImpactSummary(value.summary) &&
    Array.isArray(value.changed_files) && value.changed_files.every(isChangedFileRecord) &&
    Array.isArray(value.changed_functions) && value.changed_functions.every(isChangedFunctionRecord) &&
    Array.isArray(value.impacted_functions) && value.impacted_functions.every(isImpactedFunctionRecord) &&
    Array.isArray(value.unassigned_changed_lines) && value.unassigned_changed_lines.every(isUnassignedLines);
}

function isWorkflowError(value: unknown): value is WorkflowError {
  return isRecord(value) && isString(value.source) && isString(value.file_path) && isString(value.error);
}

function isWorkflowReport(value: unknown): value is WorkflowReport {
  const metadataIsValid = isRecord(value) &&
    (value.metadata === null || isJsonObject(value.metadata));
  return (
    isRecord(value) && isString(value.report_id) && isString(value.generated_at) &&
    typeof value.success === "boolean" && metadataIsValid && isRiskAssessment(value.risk) &&
    isWorkflowImpact(value.impact) && isRecord(value.test_selection) &&
    isNonNegativeInteger(value.test_selection.total_tests_discovered) &&
    isNonNegativeInteger(value.test_selection.total_tests_selected) &&
    isFiniteNumber(value.test_selection.reduction_percentage) &&
    isSelectionSummary(value.test_selection.selection_summary) &&
    Array.isArray(value.test_selection.selected_tests) && value.test_selection.selected_tests.every(isSelectedTest) &&
    isWorkflowTestExecution(value.test_execution) &&
    isRecord(value.evidence) && Array.isArray(value.evidence.protected_functions) &&
    value.evidence.protected_functions.every(isJsonObject) && Array.isArray(value.evidence.exposed_functions) &&
    value.evidence.exposed_functions.every(isJsonObject) && Array.isArray(value.evidence.direct_call_paths) &&
    value.evidence.direct_call_paths.every(isJsonObject) && Array.isArray(value.errors) &&
    value.errors.every(isWorkflowError) && typeof value.verification_success === "boolean" &&
    isTestSelectionResult(value.test_selection_result) &&
    isPersistedExecutionResult(value.test_execution_result)
  );
}

function isReportTestSummary(value: unknown): value is ReportTestSummary {
  return (
    isRecord(value) &&
    isNonNegativeInteger(value.total_tests) &&
    isNonNegativeInteger(value.passed) &&
    isNonNegativeInteger(value.failed) &&
    isNonNegativeInteger(value.errors) &&
    isStringArray(value.failures)
  );
}

function isReportResponse(value: unknown): value is ReportResponse {
  return (
    isRecord(value) &&
    isString(value.run_id) &&
    isString(value.risk_level) &&
    Array.isArray(value.changed_functions) && value.changed_functions.every(isChangedFunctionRecord) &&
    Array.isArray(value.impacted_functions) && value.impacted_functions.every(isImpactedFunctionRecord) &&
    isStringArray(value.impacted_modules) &&
    isReportTestSummary(value.tests) &&
    isStringArray(value.recommendations) &&
    (isString(value.created_at) || value.created_at === null) &&
    isImpactAnalysis(value.impact_analysis) &&
    isWorkflowReport(value.workflow_report)
  );
}

const SENSITIVE_ERROR_DETAILS = /(?:[A-Za-z]:[\\/]|\\\\[^\s]+[\\/]|(?:^|[\s"'(])\/(?:[^/\s]+\/)+[^/\s]*|traceback|stack trace|internal server|exception in|\.py:\d+)/i;

function safeDetailMessage(value: unknown): string | null {
  if (!isString(value)) return null;
  const message = value.replace(/[\r\n\t]+/g, " ").trim();
  if (!message || message.length > 240 || SENSITIVE_ERROR_DETAILS.test(message)) return null;
  return message;
}

function safeFieldName(value: unknown): string | null {
  const segments = Array.isArray(value) ? value : [value];
  const field = segments
    .filter((part): part is string => isString(part))
    .filter((part) => !["body", "query", "path", "header", "cookie"].includes(part.toLowerCase()))
    .at(-1);
  return field && /^[A-Za-z_][A-Za-z0-9_.-]{0,79}$/.test(field) ? field : null;
}

/** Extract concise user-facing validation hints without echoing inputs or paths. */
export function summarizeApiErrorDetails(details: unknown): string[] {
  const messages: string[] = [];
  const add = (message: string) => {
    if (!messages.includes(message) && messages.length < 5) messages.push(message);
  };

  const visit = (value: unknown) => {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!isRecord(value)) return;

    const field = safeFieldName(value.loc ?? value.field ?? value.name);
    const detail = safeDetailMessage(value.msg ?? value.message ?? value.error ?? value.reason);
    if (detail) add(field ? `${field}: ${detail}` : detail);
    else if (field) add(`Invalid value for ${field}.`);

    // Also accept common object-shaped errors such as { errors: [...] } or
    // { field: { message: ... } }, while never rendering arbitrary values.
    if (!detail && !field) {
      for (const [key, nested] of Object.entries(value)) {
        if (["errors", "details", "validation_errors"].includes(key.toLowerCase())) visit(nested);
      }
    }
  };

  if (isString(details)) {
    const safe = safeDetailMessage(details);
    if (safe) add(safe);
  } else {
    visit(details);
  }
  return messages;
}

function errorMessageForStatus(status: number): string {
  if (status === 413) return "The project upload exceeds the configured size limit.";
  if (status === 429) return "The backend is busy or its workspace quota is full. Try again later.";
  if (status >= 500) return "The backend could not complete the request.";
  return `The backend request failed with status ${status}.`;
}

function safeBackendErrorMessage(value: unknown, status: number): string {
  const message = safeDetailMessage(value);
  return message ?? errorMessageForStatus(status);
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  isExpectedResponse: (value: unknown) => value is T,
  invalidResponseMessage = "The backend returned an unexpected response body.",
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      `Unable to reach the ChangeGuard backend at ${API_BASE_URL}. Check that it is running and VITE_API_BASE_URL is correct.`,
      0,
    );
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    if (!response.ok) {
      throw new ApiError(errorMessageForStatus(response.status), response.status);
    }
    throw new ApiError("The backend returned an invalid JSON response.", response.status);
  }

  if (!response.ok) {
    const baseMessage = isRecord(body)
      ? safeBackendErrorMessage(body.error, response.status)
      : errorMessageForStatus(response.status);
    const details = isRecord(body) ? body.details : undefined;
    const detailMessages = summarizeApiErrorDetails(details);
    throw new ApiError(
      detailMessages.length ? `${baseMessage} ${detailMessages.join(" ")}` : baseMessage,
      response.status,
      details,
    );
  }

  if (!isExpectedResponse(body)) {
    throw new ApiError(invalidResponseMessage, response.status);
  }
  return body;
}

export function getBackendHealth(): Promise<BackendHealthResponse> {
  return requestJson("/health", { method: "GET" }, isBackendHealthResponse);
}

export function uploadProject(file: File): Promise<ProjectUploadResponse> {
  const formData = new FormData();
  formData.append("file", file, file.name);
  return requestJson(
    "/api/v1/projects",
    { method: "POST", body: formData },
    isProjectUploadResponse,
  );
}

export function runProject(
  projectId: string,
  request: ProjectRunRequest,
): Promise<ReportResponse> {
  return requestJson(
    `/api/v1/projects/${encodeURIComponent(projectId)}/runs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    isReportResponse,
    "The project workflow returned an incomplete or malformed report; it does not contain the full workflow data required by this client.",
  );
}

export function getReport(runId: string): Promise<ReportResponse> {
  return requestJson(
    `/api/v1/reports/${encodeURIComponent(runId)}`,
    { method: "GET" },
    isReportResponse,
    "This report is legacy, incomplete, or malformed and does not contain the full workflow data required by this client.",
  );
}

/* Deprecated UI projections remain for compatibility with external imports.
 * Active UI screens use the structured backend response types above. */
/** @deprecated Display projection only; use ImpactAnalysis/ReportResponse for API data. */
export type AnalysisResult = {
  changed_functions: string[];
  impacted_functions: string[];
  impacted_modules: string[];
};

/** @deprecated Display projection only; backend records use selection_reason. */
export type SelectedTest = { test_name: string; reason: string };
/** @deprecated Display projection only; use TestSelectionResult for backend data. */
export type LegacyTestSelectionResult = { selected_tests: SelectedTest[] };
/** @deprecated UI display projection; this is not the backend execution result. */
export type TestExecutionResult = {
  total_tests: number;
  passed: number;
  failed: number;
  failures: string[];
};
/** @deprecated Display projection only; use RiskAssessment for backend data. */
export type RiskAssessmentResult = {
  risk_level: "Low" | "Medium" | "High";
  risk_reason: string;
  deployment_recommendation: string;
};

/** @deprecated Workflow is now a single uploaded-project run request. */
export async function analyzeCode(_diff: string): Promise<AnalysisResult> {
  throw new ApiError("Upload a project ZIP and use uploadProject() then runProject().", 0);
}

/** @deprecated Test selection is returned by runProject(); no separate API exists. */
export async function selectTests(
  _impactedFunctions: string[],
): Promise<LegacyTestSelectionResult> {
  throw new ApiError("Test selection is part of runProject(); no separate request is available.", 0);
}

/** @deprecated Test execution is performed by runProject(); no separate API exists. */
export async function runTests(
  _selectedTests: string[],
): Promise<TestExecutionResult> {
  throw new ApiError("Test execution is part of runProject(); no separate request is available.", 0);
}
