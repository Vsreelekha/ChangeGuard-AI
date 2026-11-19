import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from app.core.config import get_settings
from app.core.exceptions import DockerUnavailableError, InvalidInputError, TestExecutionError
from app.core.logging_config import logger
from app.schemas.testing import SAFE_TEST_PATTERN, TestExecutionResponse

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
        # 1. Check if a custom/mock runner was registered (for backend testing without live docker)
        runner = self.__class__._custom_runner
        if runner is not None:
            logger.info("Executing registered custom test runner...")
            raw_res = runner(project_path, selected_tests)
            return TestExecutionResponse(
                total_tests=raw_res.get("total_tests", 0),
                passed=raw_res.get("passed", 0),
                failed=raw_res.get("failed", 0),
                failures=raw_res.get("failures", []),
            )

        # 2. Validate input and sanitize project path
        resolved_path = self._validate_and_resolve_project_path(project_path)
        sanitized_tests = self._validate_test_names(selected_tests)

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
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=settings.DOCKER_TIMEOUT_SECONDS,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            return self._parse_pytest_output(output, sanitized_tests)

        except subprocess.TimeoutExpired:
            logger.error(f"Pytest execution timed out after {settings.DOCKER_TIMEOUT_SECONDS}s.")
            raise TestExecutionError(
                f"Test execution exceeded maximum permitted runtime of {settings.DOCKER_TIMEOUT_SECONDS} seconds."
            )
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
        """Validates that project path exists, is a directory, and does not violate approved roots."""
        path = Path(project_path).resolve()
        if not path.exists():
            raise InvalidInputError(f"Specified project path does not exist: '{project_path}'")
        if not path.is_dir():
            raise InvalidInputError(f"Specified project path is not a directory: '{project_path}'")

        # Check approved roots if configured and not default wildcard
        if settings.APPROVED_PROJECT_ROOTS != ["."]:
            approved = False
            for root in settings.APPROVED_PROJECT_ROOTS:
                approved_path = Path(root).resolve()
                if approved_path in path.parents or path == approved_path:
                    approved = True
                    break
            if not approved:
                raise InvalidInputError("Project path is outside the explicitly approved directory roots.")

        return path

    def _validate_test_names(self, selected_tests: List[str]) -> List[str]:
        """Validates test names against strict regex to eliminate shell injection vulnerabilities."""
        if not selected_tests:
            raise InvalidInputError("At least one test must be selected for execution.")

        validated = []
        for test in selected_tests:
            clean = test.strip()
            if not clean:
                continue
            if not SAFE_TEST_PATTERN.match(clean):
                raise InvalidInputError(
                    f"Test identifier '{clean}' contains illegal characters. Only alphanumeric, _, -, ., : are allowed."
                )
            validated.append(clean)

        if not validated:
            raise InvalidInputError("No valid test identifiers provided.")
        return validated

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

    def _parse_pytest_output(self, output: str, requested_tests: List[str]) -> TestExecutionResponse:
        """Parses stdout/stderr from pytest to extract execution metrics and failure names."""
        passed = 0
        failed = 0
        failures: List[str] = []

        # Match passed count: e.g. "4 passed"
        passed_match = re.search(r"(\d+)\s+passed", output)
        if passed_match:
            passed = int(passed_match.group(1))

        # Match failed count: e.g. "1 failed" or "2 errors"
        failed_match = re.search(r"(\d+)\s+failed", output)
        if failed_match:
            failed += int(failed_match.group(1))

        error_match = re.search(r"(\d+)\s+error", output)
        if error_match:
            failed += int(error_match.group(1))

        # Extract failed test identifiers: e.g. "FAILED tests/test_billing.py::test_calculate_total"
        failed_lines = re.findall(r"FAILED\s+([^\s]+)", output)
        for f in failed_lines:
            test_id = f.split(" - ")[0].strip()
            if test_id not in failures:
                failures.append(test_id)

        # Fallback if failures occurred but names weren't captured by regex
        if failed > 0 and not failures:
            failures = requested_tests[:failed]

        total_tests = passed + failed
        return TestExecutionResponse(
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            failures=failures,
        )
