import pytest

from app.core.exceptions import AnalyzerIntegrationError
from app.services.analyzer_service import AnalyzerService


def structured_result(success=True):
    return {
        "success": success,
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
        "unassigned_changed_lines": [{"file_path": "src/billing.py", "lines": [14]}],
        "errors": [] if success else [{"file_path": "src/billing.py", "error": "unavailable"}],
        "summary": {
            "changed_files_count": 1,
            "changed_functions_count": 1,
            "impacted_functions_count": 1,
            "unassigned_lines_count": 1,
            "errors_count": 0 if success else 1,
        },
    }


class StubAnalyzerAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def analyze_diff(self, git_diff, source_files):
        self.calls.append((git_diff, source_files))
        if self.error:
            raise self.error
        return self.result


def test_service_passes_diff_and_source_files_and_returns_full_result():
    git_diff = "unified diff"
    source_files = ["/repo/src/billing.py", "/repo/src/checkout.py"]
    expected = structured_result()
    adapter = StubAnalyzerAdapter(result=expected)

    actual = AnalyzerService(adapter=adapter).analyze_git_diff(git_diff, source_files)

    assert adapter.calls == [(git_diff, source_files)]
    assert actual is expected
    assert actual["changed_functions"][0]["changed_lines"] == [12]
    assert actual["impacted_functions"][0]["distance"] == 1
    assert actual["summary"]["unassigned_lines_count"] == 1


def test_service_propagates_adapter_integration_error():
    error = AnalyzerIntegrationError("Analyzer execution failed")
    service = AnalyzerService(adapter=StubAnalyzerAdapter(error=error))

    with pytest.raises(AnalyzerIntegrationError) as raised:
        service.analyze_git_diff("unified diff", ["/repo/main.py"])

    assert raised.value is error


def test_unsuccessful_result_raises_integration_error_with_full_result_details():
    result = structured_result(success=False)
    service = AnalyzerService(adapter=StubAnalyzerAdapter(result=result))

    with pytest.raises(AnalyzerIntegrationError) as raised:
        service.analyze_git_diff("unified diff", ["/repo/src/billing.py"])

    assert raised.value.details == result


def test_custom_adapter_injection_is_used():
    adapter = StubAnalyzerAdapter(result=structured_result())

    result = AnalyzerService(adapter=adapter).analyze_git_diff("diff", ["/repo/main.py"])

    assert result is adapter.result
    assert len(adapter.calls) == 1
