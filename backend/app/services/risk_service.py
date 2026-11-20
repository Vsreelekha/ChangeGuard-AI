from typing import Any, Dict, List, Tuple
from app.schemas.report import RiskLevel, TestSummary
from app.core.logging_config import logger


class RiskService:
    """
    Evaluates change risk deterministically based on factual evidence from
    impacted code surface and regression test execution metrics.
    """

    def calculate_risk(
        self,
        changed_functions: List[str],
        impacted_functions: List[str],
        impacted_modules: List[str],
        test_summary: TestSummary,
    ) -> Tuple[str, List[str]]:
        """
        Determines the overall risk level (HIGH, MEDIUM, LOW) and generates
        actionable recommendations.

        Returns:
            Tuple of (risk_level_str, recommendations_list)
        """
        logger.info("Evaluating deployment risk based on impact analysis and test evidence...")
        recommendations: List[str] = []

        total_tests = test_summary.total_tests
        passed = test_summary.passed
        failed = test_summary.failed
        failures = test_summary.failures

        num_changed = len(changed_functions)
        num_impacted_funcs = len(impacted_functions)
        num_impacted_mods = len(impacted_modules)

        # Rule 1: HIGH RISK
        # Triggers if any selected regression test fails, or severe test failures occur
        if failed > 0:
            risk_level = RiskLevel.HIGH.value
            if failures:
                recommendations.append(
                    f"CRITICAL: {failed} regression test(s) failed ({', '.join(failures)}). "
                    "Resolve these failures before promoting code to production."
                )
            else:
                recommendations.append(
                    f"CRITICAL: {failed} regression test(s) failed during execution. Block deployment."
                )

        # Rule 2: MEDIUM RISK
        # Triggers if no tests failed, but verification is incomplete or blast radius is large
        elif (
            total_tests == 0
            or num_impacted_funcs >= 3
            or num_impacted_mods >= 2
            or (num_changed > 0 and total_tests < num_changed)
        ):
            risk_level = RiskLevel.MEDIUM.value

            if total_tests == 0 and num_impacted_funcs > 0:
                recommendations.append(
                    f"ATTENTION: No regression tests were executed for {num_impacted_funcs} impacted function(s). "
                    f"Impacted functions ({', '.join(impacted_functions[:5])}) lack test coverage."
                )
            elif num_impacted_mods >= 2:
                recommendations.append(
                    f"MODERATE BLAST RADIUS: Code change impacts {num_impacted_mods} modules ({', '.join(impacted_modules[:5])}). "
                    "Ensure integration testing is performed across module boundaries."
                )
            elif num_impacted_funcs >= 3:
                recommendations.append(
                    f"DOWNSTREAM IMPACT: {num_impacted_funcs} functions affected. Manual smoke testing is recommended."
                )
            else:
                recommendations.append(
                    "Test coverage is partial compared to the extent of modified code. Expand test coverage."
                )

        # Rule 3: LOW RISK
        # Triggers when relevant tests executed and all passed
        elif total_tests > 0 and passed == total_tests:
            risk_level = RiskLevel.LOW.value
            recommendations.append(
                f"All {passed} targeted regression test(s) executed and passed successfully. "
                "Blast radius appears controlled."
            )

        # Default fallback
        else:
            risk_level = RiskLevel.LOW.value
            recommendations.append("Minimal change footprint detected with no recorded test failures.")

        # Always include engineering disclaimer to avoid false certainty
        recommendations.append(
            "Note: Successful regression test execution significantly lowers risk but does not "
            "mathematically guarantee absence of defects. Standard peer code review is still required."
        )

        logger.info(f"Risk calculation complete. Result: {risk_level}")
        return risk_level, recommendations
