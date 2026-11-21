from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from app.database.connection import Base


class AnalysisRun(Base):
    """Stores full records of change impact analysis runs and risk reports."""

    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(String(64), unique=True, index=True, nullable=False)
    git_diff = Column(Text, nullable=True)

    # Structured impact analysis data
    changed_functions = Column(JSON, nullable=False, default=list)
    impacted_functions = Column(JSON, nullable=False, default=list)
    impacted_modules = Column(JSON, nullable=False, default=list)

    # Test selection and execution results
    selected_tests = Column(JSON, nullable=False, default=list)
    test_results = Column(JSON, nullable=True)
    impact_analysis = Column(JSON, nullable=True)
    workflow_report = Column(JSON, nullable=True)

    # Risk evaluation and recommendations
    risk_level = Column(String(20), nullable=False, default="LOW")
    recommendations = Column(JSON, nullable=False, default=list)

    # Metadata
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self):
        """Convert database model instance to dictionary representation."""
        return {
            "run_id": self.run_id,
            "risk_level": self.risk_level,
            "changed_functions": self.changed_functions or [],
            "impacted_functions": self.impacted_functions or [],
            "impacted_modules": self.impacted_modules or [],
            "selected_tests": self.selected_tests or [],
            "tests": self.test_results or {
                "total_tests": 0,
                "passed": 0,
                "failed": 0,
                "failures": [],
            },
            "impact_analysis": self.impact_analysis or {},
            "workflow_report": self.workflow_report or {},
            "recommendations": self.recommendations or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
