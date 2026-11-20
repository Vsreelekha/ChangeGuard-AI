"""
Reports and Risk Scoring module for ChangeGuard AI.

Calculates explainable, deterministic risk scores based on static blast radius,
test selection coverage, and dynamic test execution results.
"""

from reports.risk_scorer import calculate_risk_score
from reports.report_generator import generate_impact_report, format_markdown_report

__all__ = ["calculate_risk_score", "generate_impact_report", "format_markdown_report"]
