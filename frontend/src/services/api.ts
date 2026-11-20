import { mockAnalysis, mockExecution, mockTests } from "../data/mockData";

// Local demo adapters; replace these implementations after the FastAPI contract is agreed.
export type AnalysisResult = {
  changed_functions: string[];
  impacted_functions: string[];
  impacted_modules: string[];
};

export type SelectedTest = {
  test_name: string;
  reason: string;
};

export type TestSelectionResult = {
  selected_tests: SelectedTest[];
};

export type TestExecutionResult = {
  total_tests: number;
  passed: number;
  failed: number;
  failures: string[];
};

export type RiskAssessmentResult = {
  risk_level: "Low" | "Medium" | "High";
  risk_reason: string;
  deployment_recommendation: string;
};

const demoDelay = () =>
  new Promise<void>((resolve) => window.setTimeout(resolve, 350));

export async function analyzeCode(diff: string): Promise<AnalysisResult> {
  if (!diff.trim()) {
    throw new Error("Please upload or paste a Git diff first.");
  }

  await demoDelay();
  return {
    changed_functions: [...mockAnalysis.changed_functions],
    impacted_functions: [...mockAnalysis.impacted_functions],
    impacted_modules: [...mockAnalysis.impacted_modules],
  };
}

export async function selectTests(
  impactedFunctions: string[],
): Promise<TestSelectionResult> {
  await demoDelay();
  const selected_tests =
    impactedFunctions.length > 0
      ? mockTests.map((test) => ({ ...test }))
      : [];
  return { selected_tests };
}

export async function runTests(
  selectedTests: string[],
): Promise<TestExecutionResult> {
  await demoDelay();
  const failures = mockExecution.failures.filter((failure) =>
    selectedTests.includes(failure),
  );
  const total_tests = selectedTests.length;
  const failed = failures.length;

  return {
    total_tests,
    passed: total_tests - failed,
    failed,
    failures,
  };
}
