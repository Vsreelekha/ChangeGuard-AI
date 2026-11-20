"""
Reports and Risk Scoring module for ChangeGuard AI.

Calculates explainable, deterministic risk scores based on static blast radius,
test selection coverage, and dynamic test execution results.
"""

from reports.risk_scorer import calculate_risk_score

__all__ = ["calculate_risk_score"]
