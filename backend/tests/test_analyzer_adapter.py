from unittest.mock import patch

import pytest

from app.core.exceptions import AnalyzerIntegrationError
from app.integrations.analyzer_adapter import CodeAnalyzerAdapter


@pytest.fixture(autouse=True)
def reset_custom_analyzer():
    CodeAnalyzerAdapter.register_custom_analyzer(None)
    yield
    CodeAnalyzerAdapter.register_custom_analyzer(None)


def analyzer_result():
    return {
        "success": True,
        "changed_files": [{"file_path": "src/billing.py", "change_type": "modified"}],
        "changed_functions": [
            {
                "id": "src/billing.py:calculate_total",
                "name": "calculate_total",
                "changed_lines": [12],
            }
        ],
        "impacted_functions": [
            {"id": "src/checkout.py:checkout", "name": "checkout", "distance": 1}
        ],
        "unassigned_changed_lines": [],
        "errors": [],
        "summary": {"changed_functions_count": 1, "impacted_functions_count": 1},
    }


def test_calls_real_analyzer_with_diff_and_source_files_and_preserves_result():
    git_diff = "diff --git a/src/billing.py b/src/billing.py"
    source_files = ["/project/src/billing.py", "/project/src/checkout.py"]
    expected = analyzer_result()

    with patch("app.integrations.analyzer_adapter.analyze_code_impact", return_value=expected) as analyze:
        actual = CodeAnalyzerAdapter().analyze_diff(git_diff, source_files)

    analyze.assert_called_once_with(git_diff, source_files)
    assert actual is expected
    assert actual["changed_functions"][0]["changed_lines"] == [12]
    assert actual["impacted_functions"][0]["distance"] == 1


def test_wraps_analyzer_exception_as_integration_error():
    with patch(
        "app.integrations.analyzer_adapter.analyze_code_impact",
        side_effect=RuntimeError("graph construction failed"),
    ):
        with pytest.raises(AnalyzerIntegrationError, match="graph construction failed"):
            CodeAnalyzerAdapter().analyze_diff("some diff", ["/project/main.py"])


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {**analyzer_result(), "changed_functions": "calculate_total"},
        {**analyzer_result(), "summary": []},
    ],
)
def test_rejects_malformed_analyzer_results(result):
    with patch("app.integrations.analyzer_adapter.analyze_code_impact", return_value=result):
        with pytest.raises(AnalyzerIntegrationError, match="Analyzer"):
            CodeAnalyzerAdapter().analyze_diff("some diff", ["/project/main.py"])


def test_registered_analyzer_override_receives_both_arguments_and_preserves_result():
    git_diff = "some diff"
    source_files = ["/project/main.py"]
    expected = analyzer_result()
    calls = []

    def custom_analyzer(diff, files):
        calls.append((diff, files))
        return expected

    CodeAnalyzerAdapter.register_custom_analyzer(custom_analyzer)

    actual = CodeAnalyzerAdapter().analyze_diff(git_diff, source_files)

    assert calls == [(git_diff, source_files)]
    assert actual is expected


@pytest.mark.parametrize(
    "git_diff, source_files",
    [("", ["/project/main.py"]), ("diff", None), ("diff", [""])],
)
def test_rejects_invalid_arguments(git_diff, source_files):
    with pytest.raises(AnalyzerIntegrationError):
        CodeAnalyzerAdapter().analyze_diff(git_diff, source_files)
