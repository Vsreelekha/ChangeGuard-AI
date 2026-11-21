"""
Unit tests for the ChangeGuard AI Test Runner module.

Validates safe subprocess execution, timeout handling, output parsing, argument
validation, zero-selection safeguards, and integration with test selection.
"""

import json
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from test_runner.runner import run_selected_tests, run_tests


class TestTestRunnerExecution:
    """Tests for executing pytest subprocesses and parsing outputs."""

    def test_successful_test_execution(self, tmp_path):
        """Verify successful test execution returns status 'passed' with correct summary."""
        test_file = tmp_path / "test_success.py"
        test_file.write_text(
            "def test_one():\n"
            "    assert True\n\n"
            "def test_two():\n"
            "    assert 2 + 2 == 4\n"
        )

        res = run_tests([str(test_file)], cwd=str(tmp_path))

        assert res["success"] is True
        assert res["status"] == "passed"
        assert res["exit_code"] == 0
        assert res["summary"]["passed"] == 2
        assert res["summary"]["failed"] == 0
        assert res["summary"]["skipped"] == 0
        assert res["summary"]["total"] == 2
        assert res["execution_time"] > 0
        assert len(res["failure_details"]) == 0
        assert "passed" in res["message"].lower()

    def test_failed_test_execution(self, tmp_path):
        """Verify failed test execution returns status 'failed' and captures failure details."""
        test_file = tmp_path / "test_failure.py"
        test_file.write_text(
            "def test_pass():\n"
            "    assert True\n\n"
            "def test_fail():\n"
            "    assert 1 == 2, 'intentional failure'\n"
        )

        res = run_tests([str(test_file)], cwd=str(tmp_path))

        assert res["success"] is False
        assert res["status"] == "failed"
        assert res["exit_code"] == 1
        assert res["summary"]["passed"] == 1
        assert res["summary"]["failed"] == 1
        assert res["summary"]["total"] == 2
        assert len(res["failure_details"]) >= 1
        fail = res["failure_details"][0]
        assert "test_fail" in fail["test"]
        assert "intentional failure" in fail["message"] or "AssertionError" in fail["message"]

    def test_skipped_test_execution(self, tmp_path):
        """Verify tests marked as skipped return status 'skipped'."""
        test_file = tmp_path / "test_skipped.py"
        test_file.write_text(
            "import pytest\n\n"
            "@pytest.mark.skip(reason='skipping for test')\n"
            "def test_skip():\n"
            "    pass\n"
        )

        res = run_tests([str(test_file)], cwd=str(tmp_path))

        assert res["success"] is True
        assert res["status"] == "skipped"
        assert res["exit_code"] == 0
        assert res["summary"]["passed"] == 0
        assert res["summary"]["skipped"] == 1
        assert res["summary"]["total"] == 1

    def test_empty_pytest_args_safeguard(self):
        """Verify empty pytest_args returns status 'skipped' without running subprocess."""
        with patch("subprocess.run") as mock_run:
            res = run_tests([])

            assert mock_run.call_count == 0
            assert res["success"] is True
            assert res["status"] == "skipped"
            assert res["summary"]["total"] == 0
            assert res["execution_time"] == 0.0
            assert res["exit_code"] == 0
            assert "No tests selected" in res["message"]

    def test_timeout_handling(self, tmp_path):
        """Verify long-running tests are terminated when timeout is reached."""
        test_file = tmp_path / "test_slow.py"
        test_file.write_text(
            "import time\n\n"
            "def test_hang():\n"
            "    time.sleep(5)\n"
            "    assert True\n"
        )

        res = run_tests([str(test_file)], cwd=str(tmp_path), timeout=1)

        assert res["success"] is False
        assert res["status"] == "timeout"
        assert res["exit_code"] == -1
        assert "timed out" in res["message"].lower()

    def test_invalid_test_arguments_rejected(self):
        """Verify arguments with option flags starting with '-' are rejected."""
        res1 = run_tests(["-v"])
        assert res1["success"] is False
        assert res1["status"] == "error"
        assert "flags or options" in res1["message"]

        res2 = run_tests(["--tb=long"])
        assert res2["success"] is False
        assert res2["status"] == "error"

        res3 = run_tests(["   -s   "])
        assert res3["success"] is False
        assert res3["status"] == "error"

    def test_invalid_argument_types(self):
        """Verify non-list, non-string, or empty arguments return error status."""
        res_none = run_tests(None)  # type: ignore
        assert res_none["success"] is False
        assert res_none["status"] == "error"

        res_str = run_tests("test_foo.py")  # type: ignore
        assert res_str["success"] is False
        assert res_str["status"] == "error"

        res_non_str_items = run_tests([123])  # type: ignore
        assert res_non_str_items["success"] is False
        assert res_non_str_items["status"] == "error"

        res_empty_str = run_tests(["   "])
        assert res_empty_str["success"] is False
        assert res_empty_str["status"] == "error"

    def test_missing_working_directory(self):
        """Verify non-existent working directory returns error status."""
        fake_dir = "C:/path/that/definitely/does_not_exist_changeguard"
        res = run_tests(["tests/test_sample.py"], cwd=fake_dir)

        assert res["success"] is False
        assert res["status"] == "error"
        assert "Working directory does not exist" in res["message"]

    def test_invalid_timeout_values(self):
        """Verify negative, zero, or non-numeric timeout values return error status."""
        for invalid_timeout in [0, -5, "60", None, True, False]:
            res = run_tests(["tests/test_sample.py"], timeout=invalid_timeout)  # type: ignore
            assert res["success"] is False
            assert res["status"] == "error"
            assert "Invalid timeout" in res["message"]

    def test_subprocess_invocation_parameters(self, tmp_path):
        """Verify subprocess.run is invoked with shell=False, sys.executable, and safe flags."""
        fake_test = str(tmp_path / "test_mock.py")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "1 passed in 0.05s"
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            res = run_tests([fake_test], cwd=str(tmp_path), timeout=30)

            assert mock_run.call_count == 1
            cmd_called = mock_run.call_args[0][0]
            kwargs_called = mock_run.call_args[1]

            assert cmd_called[0] == sys.executable
            assert cmd_called[1] == "-m"
            assert cmd_called[2] == "pytest"
            assert fake_test in cmd_called
            assert "-v" in cmd_called
            assert "--tb=short" in cmd_called
            assert kwargs_called["shell"] is False
            assert kwargs_called["capture_output"] is True
            assert kwargs_called["text"] is True
            assert kwargs_called["timeout"] == 30
            assert kwargs_called["cwd"] == str(tmp_path)
            assert res["status"] == "passed"


class TestRunSelectedTestsIntegration:
    """Tests for run_selected_tests high-level integration with test selection output."""

    def test_run_selected_tests_integration(self, tmp_path):
        """Verify run_selected_tests combines selection metadata with execution output."""
        test_file = tmp_path / "test_selected.py"
        test_file.write_text("def test_payment(): assert True\n")
        node_id = f"{test_file}::test_payment"

        selection_input = {
            "success": True,
            "total_tests_discovered": 10,
            "total_tests_selected": 1,
            "reduction_percentage": 90.0,
            "pytest_args": [node_id],
            "selected_tests": [
                {
                    "test_file": str(test_file),
                    "test_name": "test_payment",
                    "priority": "high",
                    "reason": "Directly mapped to changed function"
                }
            ]
        }

        res = run_selected_tests(selection_input, cwd=str(tmp_path))

        assert res["success"] is True
        assert res["status"] == "passed"
        assert "selection" in res
        assert "execution" in res

        selection = res["selection"]
        assert selection["total_tests_discovered"] == 10
        assert selection["total_tests_selected"] == 1
        assert selection["reduction_percentage"] == 90.0
        assert selection["pytest_args"] == [node_id]

        execution = res["execution"]
        assert execution["status"] == "passed"
        assert execution["summary"]["passed"] == 1
        assert execution["summary"]["total"] == 1

    def test_run_selected_tests_empty_selection(self):
        """Verify run_selected_tests handles empty selection gracefully without running pytest."""
        selection_input = {
            "success": True,
            "total_tests_discovered": 5,
            "total_tests_selected": 0,
            "reduction_percentage": 100.0,
            "pytest_args": [],
            "selected_tests": []
        }

        with patch("subprocess.run") as mock_run:
            res = run_selected_tests(selection_input)

            assert mock_run.call_count == 0
            assert res["success"] is True
            assert res["status"] == "skipped"
            assert res["selection"]["total_tests_selected"] == 0
            assert res["execution"]["status"] == "skipped"
            assert res["execution"]["summary"]["total"] == 0

    def test_run_selected_tests_invalid_input(self):
        """Verify run_selected_tests handles non-dict input safely."""
        res = run_selected_tests("not a dict")  # type: ignore

        assert res["success"] is False
        assert res["status"] == "error"
        assert res["execution"]["status"] == "error"

    def test_json_serializability(self, tmp_path):
        """Verify all outputs from run_tests and run_selected_tests are JSON-serializable."""
        test_file = tmp_path / "test_serial.py"
        test_file.write_text("def test_ok(): assert 1 == 1\n")

        raw_res = run_tests([str(test_file)], cwd=str(tmp_path))
        serialized_raw = json.dumps(raw_res)
        assert isinstance(serialized_raw, str)
        deserialized_raw = json.loads(serialized_raw)
        assert deserialized_raw["status"] == "passed"

        selection_input = {
            "total_tests_discovered": 1,
            "total_tests_selected": 1,
            "reduction_percentage": 0.0,
            "pytest_args": [str(test_file)],
            "selected_tests": [{"name": "test_ok"}]
        }
        selected_res = run_selected_tests(selection_input, cwd=str(tmp_path))
        serialized_selected = json.dumps(selected_res)
        assert isinstance(serialized_selected, str)
        deserialized_selected = json.loads(serialized_selected)
        assert deserialized_selected["execution"]["status"] == "passed"
