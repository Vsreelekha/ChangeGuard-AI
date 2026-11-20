-- Apply once to an existing database before deploying this backend version.
-- Fresh databases receive these nullable JSON columns from SQLAlchemy metadata.
ALTER TABLE analysis_runs ADD COLUMN impact_analysis JSON;
ALTER TABLE analysis_runs ADD COLUMN workflow_report JSON;
