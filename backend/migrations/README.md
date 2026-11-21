# Backend database migrations

`AnalysisRun` now stores the original analyzer payload in `impact_analysis` and
the assembled pipeline report in `workflow_report`. Fresh databases receive
these JSON columns through SQLAlchemy `create_all`. Existing databases must
apply `001_add_structured_workflow_columns.sql` once before running this version.

Configure project access through the `APPROVED_PROJECT_ROOTS` environment
variable as a JSON array of absolute directory paths, for example:

```text
APPROVED_PROJECT_ROOTS=["C:/changeguard/projects"]
```

An empty value or the unsafe `.` default is rejected; there is no implicit
workspace-wide approval.
