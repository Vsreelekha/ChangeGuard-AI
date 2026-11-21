"""
Safe Pytest Execution Runner for ChangeGuard AI.

Executes selected pytest tests in an isolated subprocess using sys.executable,
validates arguments and execution directory, parses pytest stdout/stderr,
and generates structured JSON-serializable test execution reports.
"""

import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional


def run_tests(
    pytest_args: List[str],
    cwd: Optional[str] = None,
    timeout: int = 60
) -> Dict[str, Any]:
    """
    Execute pytest on selected test files or node IDs in a subprocess.

    Args:
        pytest_args: List of test paths or pytest node IDs (e.g. 'tests/test_x.py::test_y').
        cwd: Optional working directory path.
        timeout: Execution timeout in seconds (must be positive).

    Returns:
        JSON-serializable dictionary with execution status, summary counts,
        stdout, stderr, exit code, failure details, and message.
    """
    # 1. Validate timeout
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        return {
            "success": False,
            "status": "error",
            "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
            "execution_time": 0.0,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "failure_details": [],
            "message": f"Invalid timeout: {timeout}. Timeout must be a positive number."
        }

    # 2. Validate working directory
    if cwd is not None:
        if not isinstance(cwd, str) or not os.path.isdir(cwd):
            return {
                "success": False,
                "status": "error",
                "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
                "execution_time": 0.0,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "failure_details": [],
                "message": f"Working directory does not exist: {cwd}"
            }

    # 3. Validate pytest_args
    if not isinstance(pytest_args, list):
        return {
            "success": False,
            "status": "error",
            "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
            "execution_time": 0.0,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "failure_details": [],
            "message": "pytest_args must be a list of test paths or node IDs."
        }

    # 4. Zero-selection safeguard: Never run pytest when pytest_args is empty!
    if len(pytest_args) == 0:
        return {
            "success": True,
            "status": "skipped",
            "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
            "execution_time": 0.0,
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "failure_details": [],
            "message": "No tests selected for execution."
        }

    # Validate each argument: reject options/flags and non-strings
    clean_args: List[str] = []
    for arg in pytest_args:
        if not isinstance(arg, str):
            return {
                "success": False,
                "status": "error",
                "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
                "execution_time": 0.0,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "failure_details": [],
                "message": f"Invalid test argument {arg!r}: expected string, got {type(arg).__name__}."
            }
        stripped = arg.strip()
        if not stripped:
            return {
                "success": False,
                "status": "error",
                "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
                "execution_time": 0.0,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "failure_details": [],
                "message": "Invalid test argument: empty string."
            }
        if stripped.startswith("-"):
            return {
                "success": False,
                "status": "error",
                "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
                "execution_time": 0.0,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "failure_details": [],
                "message": f"Invalid test argument '{stripped}': flags or options starting with '-' are rejected."
            }
        clean_args.append(stripped)

    # 5. Build command and execute via subprocess
    cmd = [sys.executable, "-m", "pytest"] + clean_args + ["-v", "--tb=short"]
    start_time = time.perf_counter()

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False
        )
        elapsed = time.perf_counter() - start_time
    except subprocess.TimeoutExpired as e:
        elapsed = time.perf_counter() - start_time
        stdout = e.stdout if isinstance(e.stdout, str) else ""
        stderr = e.stderr if isinstance(e.stderr, str) else ""
        return {
            "success": False,
            "status": "timeout",
            "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
            "execution_time": round(elapsed, 3),
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": -1,
            "failure_details": [],
            "message": f"Test execution timed out after {timeout} seconds."
        }
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        return {
            "success": False,
            "status": "error",
            "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
            "execution_time": round(elapsed, 3),
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "failure_details": [],
            "message": f"Subprocess execution failed: {str(e)}"
        }

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # 6. Parse counts from pytest output
    passed_match = re.search(r"\b(\d+)\s+passed\b", stdout)
    failed_match = re.search(r"\b(\d+)\s+failed\b", stdout)
    skipped_match = re.search(r"\b(\d+)\s+skipped\b", stdout)

    passed_count = int(passed_match.group(1)) if passed_match else 0
    failed_count = int(failed_match.group(1)) if failed_match else 0
    skipped_count = int(skipped_match.group(1)) if skipped_match else 0
    total_count = passed_count + failed_count + skipped_count

    # 7. Parse failure details
    failure_details: List[Dict[str, str]] = []
    # Match FAILED lines: e.g. "FAILED test_file.py::test_name - AssertionError: foo"
    failed_lines = re.findall(r"^FAILED\s+([^\s\-]+)(?:\s+-\s+(.*))?$", stdout, re.MULTILINE)
    for test_id, reason in failed_lines:
        failure_details.append({
            "test": test_id.strip(),
            "message": reason.strip() if reason else "Assertion failed or test error."
        })

    # Fallback to FAILURES blocks if no FAILED summary lines found
    if failed_count > 0 and not failure_details:
        blocks = re.findall(r"_{3,}\s*(.*?)\s*_{3,}\n(.*?)(?=\n_{3,}|\n={3,}|\Z)", stdout, re.DOTALL)
        for header, content in blocks:
            err_lines = [l.strip() for l in content.strip().splitlines() if l.strip().startswith("E   ")]
            err_msg = err_lines[-1][4:] if err_lines else (content.strip().splitlines()[-1] if content.strip() else "Test failed.")
            failure_details.append({
                "test": header.strip(),
                "message": err_msg
            })

    # 8. Determine overall status and success
    exit_code = proc.returncode
    if exit_code == 0:
        if passed_count == 0 and skipped_count > 0:
            status = "skipped"
            success = True
            message = f"All {skipped_count} test(s) were skipped."
        else:
            status = "passed"
            success = True
            message = f"Tests completed successfully: {passed_count} passed."
    elif exit_code == 1:
        status = "failed"
        success = False
        message = f"Test execution failed: {failed_count} failed, {passed_count} passed."
    elif exit_code == 5:
        # pytest exit code 5: no tests collected or all skipped
        status = "skipped"
        success = True
        message = "No tests were executed or all selected tests were skipped."
    else:
        status = "error"
        success = False
        message = f"Pytest exited with non-standard returncode {exit_code}."

    return {
        "success": success,
        "status": status,
        "summary": {
            "passed": passed_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "total": total_count
        },
        "execution_time": round(elapsed, 3),
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "failure_details": failure_details,
        "message": message
    }


def run_selected_tests(
    selection_result: Dict[str, Any],
    cwd: Optional[str] = None,
    timeout: int = 60
) -> Dict[str, Any]:
    """
    Execute tests selected by the Intelligent Test Selector.

    Extracts pytest_args from the selection result, invokes run_tests(),
    and preserves both selection metrics and execution results.

    Args:
        selection_result: Dictionary returned by select_tests().
        cwd: Optional working directory path.
        timeout: Subprocess execution timeout in seconds.

    Returns:
        Combined JSON-serializable dictionary with selection and execution blocks.
    """
    if not isinstance(selection_result, dict):
        return {
            "success": False,
            "status": "error",
            "selection": {},
            "execution": {
                "success": False,
                "status": "error",
                "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
                "execution_time": 0.0,
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "failure_details": [],
                "message": "Invalid selection_result: expected dictionary."
            }
        }

    pytest_args = selection_result.get("pytest_args", [])
    exec_result = run_tests(pytest_args, cwd=cwd, timeout=timeout)

    return {
        "success": exec_result["success"],
        "status": exec_result["status"],
        "selection": {
            "total_tests_discovered": selection_result.get("total_tests_discovered", 0),
            "total_tests_selected": selection_result.get("total_tests_selected", len(selection_result.get("selected_tests", []))),
            "reduction_percentage": selection_result.get("reduction_percentage", 0.0),
            "pytest_args": pytest_args,
            "selected_tests": selection_result.get("selected_tests", [])
        },
        "execution": exec_result
    }
