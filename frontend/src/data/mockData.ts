export const mockAnalysis = {
  changed_functions: ["calculate_total"],
  impacted_functions: ["calculate_total", "checkout"],
  impacted_modules: ["billing.py", "checkout.py"],
};

export const mockTests = [
  {
    test_name: "test_calculate_total",
    reason: "Tests the modified billing function",
  },
  {
    test_name: "test_checkout",
    reason: "Tests the affected checkout flow",
  },
];

export const mockExecution = {
  total_tests: 5,
  passed: 4,
  failed: 1,
  failures: ["test_calculate_total"],
};

