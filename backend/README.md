# ChangeGuard AI – Backend Service

ChangeGuard AI is an AI-assisted Code Change Impact Analysis and Regression Testing platform.

This repository contains the backend and the canonical shared `code_analyzer/`, `test_selector/`, and `reports/` Python packages. The backend uses **Python 3.12+**, **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.0**, **PostgreSQL**, **Docker**, and **Pytest**.

---

## 1. Project Overview

ChangeGuard AI protects software repositories during the pull request and deployment lifecycle:
1. **Change Ingestion**: Ingests unified Git diffs representing proposed code changes.
2. **Impact Analysis**: Analyzes abstract syntax trees (AST) and dependency call graphs to identify modified and impacted functions and modules.
3. **Intelligent Test Selection**: Maps impacted functions to relevant regression tests with priority rankings and selection reasons.
4. **Isolated Pytest Execution**: Safely executes selected pytest tests inside isolated, non-root Docker containers with zero network access and resource constraints.
5. **Factual Risk Assessment**: Evaluates deployment risk (`HIGH`, `MEDIUM`, `LOW`) using empirical test execution evidence and blast-radius metrics.
6. **Report Persistence**: Generates and stores comprehensive risk reports in PostgreSQL and serves structured results to the React frontend.

---

## 2. Backend Architecture

ChangeGuard AI follows clean, modular, and layered REST architecture:

```
[ Git Diff / Code Changes ]
            │
            ▼
┌────────────────────────────────────────────────────────┐
│                   FastAPI Routing Layer                │
│  /api/v1/analysis  │  /api/v1/tests  │  /api/v1/reports │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                   Service Business Logic               │
│  AnalyzerService   │ TestSelectorService │ RiskService │
│  TestRunnerService │ ReportService                     │
└──────────────┬─────────────────────────────┬───────────┘
               │                             │
               ▼                             ▼
┌──────────────────────────────┐ ┌───────────────────────┐
│     Integration Adapters     │ │    SQLAlchemy Layer   │
│ CodeAnalyzer │ TestSelector  │ │ PostgreSQL / SQLite   │
│ (AST/NetworkX) (Pytest Graph)│ │ AnalysisRun Models    │
└──────────────┬───────────────┘ └───────────────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Docker Execution Isolation  │
│  - Non-root user (1000:1000) │
│  - Network disabled (--none) │
│  - Resource limits (CPU/RAM) │
│  - Read-only volume mount    │
└──────────────────────────────┘
```

---

## 3. Project Directory Structure

```text
backend/
├── app/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py             # Pydantic BaseSettings & environment configs
│   │   ├── exceptions.py         # Domain exceptions (503 integration, 400, 404, etc.)
│   │   └── logging_config.py     # Structured Python logging setup
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py         # SQLAlchemy engine, session maker, get_db dependency
│   │   └── models.py             # AnalysisRun database model
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── analyzer_adapter.py   # Teammate AST/NetworkX code analyzer bridge
│   │   └── selector_adapter.py   # Teammate intelligent test selector bridge
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── analysis.py           # POST /api/v1/analysis
│   │   ├── testing.py            # POST /api/v1/tests/select
│   │   ├── execution.py          # POST /api/v1/tests/execute
│   │   └── reports.py            # POST /reports, GET /reports/{id}, POST /runs
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── analysis.py           # AnalysisRequest, AnalysisResponse
│   │   ├── testing.py            # TestSelectionRequest, TestExecutionRequest, etc.
│   │   └── report.py             # ReportResponse, RiskLevel, TestSummary, etc.
│   ├── services/
│   │   ├── __init__.py
│   │   ├── analyzer_service.py   # AST diff analysis orchestration
│   │   ├── test_selector_service.py # Test mapping & prioritization
│   │   ├── test_runner_service.py   # Hardened Docker containerized pytest runner
│   │   ├── risk_service.py       # Deterministic risk & recommendations calculator
│   │   └── report_service.py     # Report persistence & pipeline orchestration
│   ├── __init__.py
│   └── main.py                   # FastAPI initialization, CORS, routers & lifecycle
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Test database fixtures and client setup
│   ├── test_health.py            # Tests for /health and / endpoints
│   ├── test_analysis_api.py      # Tests for code change impact analysis
│   ├── test_selection_api.py     # Tests for intelligent test selection
│   ├── test_execution_api.py     # Tests for containerized test execution & security
│   └── test_reports_api.py       # Tests for reports & full workflow pipeline
├── .env.example                  # Environment template
├── .gitignore                    # Git ignore file
├── Dockerfile                    # Production API container image definition
├── runner.Dockerfile             # Isolated pytest runner image definition
├── requirements.txt              # Production and test Python dependencies
└── README.md                     # Backend documentation
```

The Docker build and local Python import path use these packages directly from the repository root; they are not copied into duplicate implementations under `backend/`.

---

## 4. Python Environment Setup (Windows)

1. **Prerequisite**: Ensure Python 3.12+ is installed:
   ```powershell
   python --version
   ```

2. **Navigate to the backend directory** (from a clean checkout, replace the path with your repository location):
   ```powershell
   cd C:\path\to\ChangeGuard-AI\backend
   ```

3. **Create and activate the backend virtual environment**:
   - **PowerShell**:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **Command Prompt (CMD)**:
     ```cmd
     python -m venv .venv
     .venv\Scripts\activate.bat
     ```

---

## 5. Dependency Installation

With `backend/.venv` activated, install dependencies declared by the backend:
```powershell
python -m pip install -r requirements.txt
```

---

## 6. Environment Variable Configuration

Create a `.env` file in `backend/` from the template:
```powershell
copy .env.example .env
```

Key environment options in `.env`:
```ini
ENVIRONMENT=development
LOG_LEVEL=INFO
API_V1_STR=/api/v1

# Database URL
DATABASE_URL=sqlite:///./changeguard.db
# For PostgreSQL:
# DATABASE_URL=postgresql://changeguard_user:changeguard_password@localhost:5432/changeguard_db

# CORS Configuration
CORS_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","http://localhost:5173","http://127.0.0.1:5173"]

# Isolated Pytest Runner Settings
DOCKER_IMAGE=changeguard-runner:latest
DOCKER_TIMEOUT_SECONDS=60
DOCKER_MEMORY_LIMIT=512m
DOCKER_CPU_LIMIT=1.0
DOCKER_PIDS_LIMIT=100
# Replace with an existing absolute path visible to the backend process.
APPROVED_PROJECT_ROOTS=["C:/changeguard/projects"]
```

`APPROVED_PROJECT_ROOTS` must contain one or more existing absolute directories. `project_path` must resolve inside one of them. For a containerized backend, mount the project directory into the backend container and configure the in-container absolute path. A browser's local filesystem path is not automatically available to a remote backend.

---

## 7. PostgreSQL Configuration

ChangeGuard AI defaults to SQLite for local development without external dependencies, but **PostgreSQL** is the intended production database.

To connect PostgreSQL:
1. Start PostgreSQL (e.g. via Docker):
   ```bash
   docker run --name changeguard-pg -e POSTGRES_USER=changeguard_user -e POSTGRES_PASSWORD=changeguard_password -e POSTGRES_DB=changeguard_db -p 5432:5432 -d postgres:16-alpine
   ```
2. Update `.env`:
   ```ini
   DATABASE_URL=postgresql://changeguard_user:changeguard_password@localhost:5432/changeguard_db
   ```
3. On a fresh database, tables are created upon application startup via `init_db()`. For an existing database, apply the one-time migration in `backend/migrations/001_add_structured_workflow_columns.sql` before deploying this version. Run it once against the configured database; `create_all()` does not add columns to an existing table.

---

## 8. Docker Security & Isolated Test Runner

The Pytest execution engine enforces containment security:
- **Zero Network Access**: Containers run with `--network none` to prevent data exfiltration.
- **Resource Constraints**: Capped at `--memory 512m --cpus 1.0 --pids-limit 100`.
- **Non-Root Execution**: Runs under UID:GID `1000:1000`.
- **Reduced Privileges**: Drops all Linux capabilities and enables `no-new-privileges`.
- **Read-Only Mounts**: Project directory mounted with `:ro` to prevent test suites from modifying source code.
- **Read-Only Root Filesystem**: The container root is read-only; `/tmp` is a bounded writable tmpfs for pytest cache files.
- **No Shell Execution**: Arbitrary user commands are prohibited; test names are validated with strict regex (`^[a-zA-Z0-9_./\-:]+$`).
- **No Unsafe Fallbacks**: If Docker is unavailable, the runner immediately returns HTTP `503 Service Unavailable` rather than falling back to unisolated host execution.

Build the dedicated runner image from the repository root. The runner image installs pytest (matching the backend's `pytest>=8.0.0` requirement), does not copy project files, and has no application entrypoint. The service invokes pytest directly against each project's read-only `/app` mount.
```powershell
docker build -f backend/runner.Dockerfile -t changeguard-runner:latest .
```

---

## 9. Starting the FastAPI Server

Launch Uvicorn with auto-reload:
```powershell
cd C:\path\to\ChangeGuard-AI\backend
.\.venv\Scripts\Activate.ps1
$repoRoot = (Resolve-Path ..).Path
$backendRoot = (Resolve-Path .).Path
$env:PYTHONPATH = "$repoRoot;$backendRoot"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
For Bash, from `backend/` use `PYTHONPATH="..:." python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`. The working directory remains `backend/` so its `.env` file is loaded.

Build the API image from the repository root (the Dockerfile needs the shared packages):
```sh
docker build -f backend/Dockerfile -t changeguard-api .
```

Run the API with an approved project mount (adapt the host directory to your deployment):
```sh
docker run --rm -p 8000:8000 -v /srv/projects:/projects:ro -e 'APPROVED_PROJECT_ROOTS=["/projects"]' changeguard-api
```
Use `project_path: "/projects/sample_project"` in requests. The path must be visible inside the backend container.

The API image does not expose the host Docker socket. Safe test execution therefore requires a separately configured isolated runner; do not mount the Docker socket into an API container without an explicit security review.

---

## 10. Swagger Documentation

Once the server is running, explore the interactive OpenAPI documentation:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc UI**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **OpenAPI JSON**: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

---

## 11. API Endpoints

| Method | Endpoint | Description | Status Code |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | System health check | `200 OK` |
| `GET` | `/` | API metadata & root info | `200 OK` |
| `POST` | `/api/v1/analysis` | Analyze Git diff for impacted functions & modules | `200 OK` |
| `POST` | `/api/v1/tests/select` | Intelligent regression test selection | `200 OK` |
| `POST` | `/api/v1/tests/execute` | Safely execute selected pytest tests in Docker | `200 OK` |
| `POST` | `/api/v1/reports` | Compute risk and persist evaluation report | `201 Created` |
| `GET` | `/api/v1/reports/{run_id}` | Retrieve stored report by run ID | `200 OK` |
| `POST` | `/api/v1/runs` | Execute complete end-to-end ChangeGuard pipeline | `201 Created` |

---

## 12. Sample API Requests and Responses

### 1. Code Analysis (`POST /api/v1/analysis`)

**Request**:
```json
{
  "git_diff": "diff --git a/billing.py b/billing.py\n--- a/billing.py\n+++ b/billing.py\n@@ -1 +1 @@\n-def total(): return 1\n+def total(): return 2",
  "project_path": "C:/changeguard/projects/sample_project"
}
```

**Response (`200 OK`)**:
```json
{
  "success": true,
  "changed_files": [],
  "changed_functions": [],
  "impacted_functions": [],
  "unassigned_changed_lines": [],
  "errors": [],
  "summary": {}
}
```

### 2. Intelligent Test Selection (`POST /api/v1/tests/select`)

**Request**:
```json
{
  "project_path": "C:/changeguard/projects/sample_project",
  "impact_report": {"success": true, "changed_files": [], "changed_functions": [], "impacted_functions": [], "unassigned_changed_lines": [], "errors": [], "summary": {}}
}
```

**Response (`200 OK`)**:
```json
{
  "success": true,
  "selected_tests": [{"test_id": "tests/test_billing.py::test_calculate_total"}],
  "total_tests_discovered": 1,
  "total_tests_selected": 1,
  "reduction_percentage": 0.0,
  "pytest_args": ["tests/test_billing.py::test_calculate_total"],
  "selection_summary": {},
  "errors": []
}
```

### 3. Safe Pytest Execution (`POST /api/v1/tests/execute`)

**Request**:
```json
{
  "project_path": "C:/changeguard/projects/sample_project",
  "selected_tests": ["tests/test_billing.py::test_calculate_total"]
}
```

**Response (`200 OK`)**:
```json
{
  "total_tests": 5,
  "passed": 4,
  "failed": 1,
  "status": "failed",
  "success": false,
  "summary": {"passed": 4, "failed": 1, "skipped": 0, "errors": 0, "total": 5},
  "failures": ["tests/test_billing.py::test_calculate_total"]
}
```

### 4. Complete Workflow Run (`POST /api/v1/runs`)

**Request**:
```json
{
  "git_diff": "diff --git a/billing.py b/billing.py\n--- a/billing.py\n+++ b/billing.py\n@@ -1 +1 @@\n-def total(): return 1\n+def total(): return 2",
  "project_path": "C:/changeguard/projects/sample_project"
}
```

**Response (`201 Created`)**:
```json
{
  "run_id": "run-a1b2c3d4-e5f6",
  "risk_level": "HIGH",
  "impact_analysis": {"success": true, "changed_files": [], "changed_functions": [], "impacted_functions": [], "unassigned_changed_lines": [], "errors": [], "summary": {}},
  "workflow_report": {"verification_success": false, "risk": {"verification_status": "FAILED"}},
  "changed_functions": [],
  "impacted_functions": [],
  "impacted_modules": [],
  "tests": {"total_tests": 1, "passed": 0, "failed": 1, "errors": 0, "failures": []},
  "recommendations": ["DO NOT DEPLOY: Regression tests failed. Fix the failures before proceeding."],
  "created_at": "2026-11-19T16:20:00.000Z"
}
```

---

## 13. Running Automated Backend Tests

Execute the complete automated test suite:
```powershell
cd C:\path\to\ChangeGuard-AI\backend
.\.venv\Scripts\Activate.ps1
pytest tests -v
```

---

## 14. Shared Integration Packages

The backend adapters import the canonical sibling packages from the repository root:

### Connecting the Code Analyzer (Python AST + NetworkX)
The analyzer entry point is `code_analyzer.impact_analyzer.analyze_code_impact(git_diff, source_files)`. The selector uses its in-repository mapper and selector interfaces; neither integration relies on dynamic package-name discovery. `source_files` are discovered under the validated `project_path` supplied to the workflow.

The API image build imports all shared packages and `app.main` to catch packaging/import failures before deployment.

---

## 15. Connecting the React Frontend

The backend is pre-configured with CORS middleware allowing requests from React development servers:
- `http://localhost:3000` (Create React App)
- `http://localhost:5173` (Vite)

In your React frontend:
```typescript
// Example frontend fetch call
const runAnalysis = async (gitDiff: string, projectPath: string) => {
  const response = await fetch("http://127.0.0.1:8000/api/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // projectPath must name a server-visible directory under APPROVED_PROJECT_ROOTS.
    body: JSON.stringify({ git_diff: gitDiff, project_path: projectPath }),
  });
  const report = await response.json();
  return report;
};
```

## 16. Secure Project Upload Operations

Project uploads are limited per request and per extracted archive. Configure
`PROJECT_WORKSPACE_MAX_BYTES` for aggregate workspace storage and
`PROJECT_UPLOAD_MAX_CONCURRENT` for concurrent uploads handled by one backend
process. These in-process controls do **not** coordinate reservations across
multiple Uvicorn workers, containers, or hosts. Use one worker or add a shared
quota/lease coordinator before scaling horizontally.

Configure the reverse proxy or ingress to enforce a request-body limit no
higher than `PROJECT_UPLOAD_MAX_BYTES` plus multipart overhead, a request
timeout, and per-client rate limits. The application also counts actual request
bytes and rejects excess concurrent uploads, but proxy limits protect resources
before requests reach Python.

On Windows, create the workspace directory with an ACL granting access only to
the backend service identity and administrators. Python's `mode=0o700` is not
a substitute for Windows ACLs. Keep the workspace outside all public/static
directories and ensure no other process can create or replace its contents.

Expired workspace cleanup honors in-process active leases. Any workflow using
an uploaded project must hold `ProjectWorkspaceService.lease_project_id()`
for its entire execution, including timeout and error paths. Leases and upload
reservations are process-local; multi-process lease coordination is not
implemented.
