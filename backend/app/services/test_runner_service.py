import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from app.core.config import get_settings
from app.core.exceptions import (
    DockerUnavailableError,
    InvalidInputError,
    TestExecutionError,
    TestExecutionTimeoutError,
)
from app.core.logging_config import logger
from app.schemas.testing import TestExecutionResponse, validate_pytest_target_syntax
from app.services.project_path_service import validate_project_path

settings = get_settings()


class TestRunnerService:
    """
    Safely executes selected pytest regression tests in an isolated Docker container.
    Enforces strict security restrictions: non-root user, no network, CPU/RAM/process limits,
    read-only mounts, and mandatory container isolation.
    """

    _custom_runner: Optional[Callable[[str, List[str]], Dict[str, Any]]] = None

    @classmethod
    def register_custom_runner(
        cls, runner_func: Optional[Callable[[str, List[str]], Dict[str, Any]]]
    ) -> None:
        """Allows registration of a mock or custom test execution runner in tests."""
        cls._custom_runner = staticmethod(runner_func) if runner_func is not None else None

    def execute_tests(self, project_path: str, selected_tests: List[str]) -> TestExecutionResponse:
        """
        Executes selected tests with full container isolation.

        Args:
            project_path: Path to the target project directory.
            selected_tests: List of validated test names/paths to run.

        Returns:
            TestExecutionResponse containing total_tests, passed, failed, and failure list.
        """
        resolved_path = self._validate_and_resolve_project_path(project_path)
        sanitized_tests = self._validate_test_names(selected_tests, resolved_path)

        # 1. Check if a custom/mock runner was registered (for backend testing without live docker)
        runner = self.__class__._custom_runner
        if runner is not None:
            logger.info("Executing registered custom test runner...")
            raw_res = runner(str(resolved_path), sanitized_tests)
            passed = raw_res.get("passed", 0)
            failed = raw_res.get("failed", 0)
            total = raw_res.get("total_tests", passed + failed)
            summary = raw_res.get("summary") or {
                "passed": passed, "failed": failed,
                "skipped": raw_res.get("skipped", 0),
                "errors": raw_res.get("errors", 0), "total": total,
            }
            skipped = summary.get("skipped", 0)
            errors = summary.get("errors", 0)
            raw_status = str(raw_res.get("status", "")).lower()
            if raw_status == "timeout":
                status = "timeout"
            elif raw_status == "error" or errors:
                status = "error"
            elif failed:
                status = "failed"
            elif skipped or total == 0 or passed < len(sanitized_tests):
                status = "skipped"
            elif passed == total and raw_res.get("success", True) is True:
                status = "passed"
            else:
                status = "error"
            failures = raw_res.get("failures", [])
            return TestExecutionResponse(
                total_tests=total,
                passed=passed,
                failed=failed,
                failures=failures,
                success=status == "passed",
                status=status,
                summary=summary,
                execution_time=raw_res.get("execution_time", 0.0),
                stdout=raw_res.get("stdout", ""),
                stderr=raw_res.get("stderr", ""),
                exit_code=raw_res.get("exit_code"),
                failure_details=raw_res.get(
                    "failure_details", [{"test": name, "message": "Test failed."} for name in failures]
                ),
                message=raw_res.get("message", ""),
            )

        # 3. Verify Docker availability (Strict isolation policy)
        if not self.is_docker_available():
            logger.error("Docker daemon is not available. Refusing unsafe host execution.")
            raise DockerUnavailableError(
                "Safe test execution runner is unavailable: Docker is not installed or the Docker daemon "
                "is not running. ChangeGuard AI strictly prohibits unisolated host execution of arbitrary test "
                "suites for security reasons. Please start Docker and retry."
            )

        # 4. Construct safe Docker execution command
        docker_cmd = self._build_docker_command(resolved_path, sanitized_tests)
        logger.info(f"Executing tests in Docker container for {len(sanitized_tests)} tests...")

        try:
            started = time.perf_counter()
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=settings.DOCKER_TIMEOUT_SECONDS,
            )
            elapsed = time.perf_counter() - started
            return self._parse_pytest_output(
                result.stdout or "",
                result.stderr or "",
                sanitized_tests,
                result.returncode,
                elapsed,
            )

        except subprocess.TimeoutExpired as exc:
            logger.error(f"Pytest execution timed out after {settings.DOCKER_TIMEOUT_SECONDS}s.")
            elapsed = time.perf_counter() - started
            raise TestExecutionTimeoutError(
                f"Test execution exceeded maximum permitted runtime of {settings.DOCKER_TIMEOUT_SECONDS} seconds.",
                details={
                    "status": "timeout",
                    "stdout": self._decode_output(exc.stdout),
                    "stderr": self._decode_output(exc.stderr),
                    "execution_time": round(elapsed, 3),
                    "exit_code": None,
                },
            ) from exc
        except Exception as e:
            logger.error(f"Failed to execute test runner: {e}", exc_info=True)
            raise TestExecutionError(f"Containerized test execution failed: {str(e)}")

    def is_docker_available(self) -> bool:
        """Checks if Docker CLI and daemon are accessible."""
        docker_bin = shutil.which("docker")
        if not docker_bin:
            return False
        try:
            res = subprocess.run(
                [docker_bin, "info"],
                capture_output=True,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    def _validate_and_resolve_project_path(self, project_path: str) -> Path:
        """Validate project paths with the shared approved-root policy."""
        return validate_project_path(project_path, settings.APPROVED_PROJECT_ROOTS)

    def _validate_test_names(self, selected_tests: List[str], project_root: Path) -> List[str]:
        """Validate pytest node IDs and ensure every file target stays inside the project."""
        if not selected_tests:
            raise InvalidInputError("At least one test must be selected for execution.")

        validated = []
        for test in selected_tests:
            try:
                clean = validate_pytest_target_syntax(test)
                relative_file = clean.split("::", 1)[0]
                resolved_file = (project_root / Path(relative_file)).resolve(strict=True)
            except (ValueError, OSError, RuntimeError) as exc:
                raise InvalidInputError(f"Invalid pytest target '{test}'.") from exc
            try:
                resolved_file.relative_to(project_root)
            except ValueError as exc:
                raise InvalidInputError(f"Pytest target '{test}' resolves outside the project directory.") from exc
            if not resolved_file.is_file() or resolved_file.suffix.casefold() != ".py":
                raise InvalidInputError(f"Pytest target '{test}' does not identify a Python file in the project.")
            validated.append(clean)

        if not validated:
            raise InvalidInputError("No valid test identifiers provided.")
        return validated

    @staticmethod
    def _decode_output(output: Any) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output)

    def _build_docker_command(self, resolved_path: Path, test_names: List[str]) -> List[str]:
        """
        Builds a hardened Docker CLI invocation:
        - Non-root user
        - --network none
        - CPU and Memory caps
        - Read-only volume mount for project
        - No privileged escalation
        """
        # Build pytest arguments with cache directed to writable tmpfs
        pytest_args = ["pytest", "-q", "-o", "cache_dir=/tmp/.pytest_cache"] + test_names

        # Convert Windows paths if necessary for Docker volume binding
        mount_path = str(resolved_path)

        return [
            "docker", "run", "--rm",
            "--user", "1000:1000",
            "--network", "none",
            "--memory", settings.DOCKER_MEMORY_LIMIT,
            "--cpus", str(settings.DOCKER_CPU_LIMIT),
            "--pids-limit", str(settings.DOCKER_PIDS_LIMIT),
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-v", f"{mount_path}:/app:ro",
            "-w", "/app",
            settings.DOCKER_IMAGE,
        ] + pytest_args

    def _parse_pytest_output(
        self,
        stdout: str,
        stderr: str,
        requested_tests: List[str],
        exit_code: int,
        execution_time: float,
    ) -> TestExecutionResponse:
        """Use pytest's final terminal summary; never infer counts from test output."""
        failures: List[str] = []
        failure_details: List[Dict[str, str]] = []
        summary_line = None
        for line in stdout.splitlines():
            candidate = line.strip().strip("= ").strip()
            has_duration = re.search(r"\bin\s+\d+(?:\.\d+)?s\s*$", candidate)
            has_result = re.search(
                r"\b(?:passed|failed|skipped|errors?|xfailed|xpassed|deselected)\b|no tests ran",
                candidate,
                re.IGNORECASE,
            )
            if has_duration and has_result:
                summary_line = candidate

        counts = {name: 0 for name in ("passed", "failed", "skipped", "errors", "xfailed", "xpassed", "deselected")}
        no_tests_ran = False
        if summary_line:
            no_tests_ran = bool(re.search(r"\bno tests ran\b", summary_line, re.IGNORECASE))
            for name, pattern in (
                ("passed", r"(\d+)\s+passed\b"),
                ("failed", r"(\d+)\s+failed\b"),
                ("skipped", r"(\d+)\s+skipped\b"),
                ("errors", r"(\d+)\s+errors?\b"),
                ("xfailed", r"(\d+)\s+xfailed\b"),
                ("xpassed", r"(\d+)\s+xpassed\b"),
                ("deselected", r"(\d+)\s+deselected\b"),
            ):
                match = re.search(pattern, summary_line, re.IGNORECASE)
                if match:
                    counts[name] = int(match.group(1))

        passed = counts["passed"]
        failed = counts["failed"]
        errors = counts["errors"]
        # Expected failures, unexpected passes, and deselected requested cases are not verification.
        skipped = counts["skipped"] + counts["xfailed"] + counts["xpassed"] + counts["deselected"]

        for line in stdout.splitlines():
            match = re.match(r"\s*(FAILED|ERROR)\s+([^\s]+)", line)
            if match:
                test_id = match.group(2).split(" - ")[0].strip()
                if test_id not in failures:
                    failures.append(test_id)
                    failure_details.append({
                        "test": test_id,
                        "message": "Test collection/setup error." if match.group(1) == "ERROR" else "Test failed.",
                    })

        if (failed or errors) and not failures:
            failures = requested_tests[:failed + errors]
            failure_details = [{"test": name, "message": "Test failed or errored."} for name in failures]

        total_tests = passed + failed + skipped + errors
        if summary_line is None:
            status, success = ("skipped", False) if exit_code == 5 else ("error", False)
            message = "No tests were collected." if exit_code == 5 else "Pytest did not produce a recognizable final summary."
        elif errors > 0:
            status, success = "error", False
            message = f"Pytest reported {errors} collection or setup error(s)."
        elif failed > 0 or exit_code == 1:
            status, success = "failed", False
            message = f"Test execution failed: {failed} failed, {passed} passed."
        elif no_tests_ran or exit_code == 5:
            status, success = "skipped", False
            message = "No selected tests were collected or executed."
        elif skipped > 0:
            status, success = "skipped", False
            message = f"Execution was incomplete: {skipped} selected test(s) were skipped or deselected."
        elif exit_code == 0 and passed >= len(requested_tests) and total_tests == passed:
            status, success = "passed", True
            message = f"All {passed} executed test(s) passed successfully."
        else:
            status, success = "error", False
            message = f"Pytest exited with return code {exit_code} without complete passing evidence."

        return TestExecutionResponse(
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            failures=failures,
            success=success,
            status=status,
            summary={
                **counts,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": errors,
                "total": total_tests,
            },
            execution_time=round(execution_time, 3),
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            failure_details=failure_details,
            message=message,
        )
