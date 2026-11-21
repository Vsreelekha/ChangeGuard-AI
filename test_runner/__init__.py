"""
Test Runner module for ChangeGuard AI.

Executes selected pytest tests safely in an isolated subprocess, captures output,
parses execution results, and provides test failure reporting.
"""

from test_runner.runner import run_selected_tests, run_tests

__all__ = ["run_tests", "run_selected_tests"]
