# ChangeGuard AI – Backend Service

ChangeGuard AI is an AI-assisted Code Change Impact Analysis and Regression Testing platform.

This repository houses the complete backend service, built with **Python 3.12+**, **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.0**, **PostgreSQL**, **Docker**, and **Pytest**.

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
├── Dockerfile                    # Production container image definition
├── requirements.txt              # Production and test Python dependencies
└── README.md                     # Backend documentation
```

---

## 4. Python Environment Setup (Windows)

1. **Prerequisite**: Ensure Python 3.12+ is installed:
   ```powershell
   python --version
   ```

2. **Navigate to the backend directory**:
   ```powershell
   cd E:\ChangeGuard-AI\backend
   ```

3. **Activate the Virtual Environment**:
   - **PowerShell**:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - **Command Prompt (CMD)**:
     ```cmd
     .\venv\Scripts\activate.bat
     ```

---

## 5. Dependency Installation

With the virtual environment activated, install dependencies:
```powershell
pip install -r requirements.txt
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
DOCKER_IMAGE=python:3.12-slim
DOCKER_TIMEOUT_SECONDS=60
DOCKER_MEMORY_LIMIT=512m
DOCKER_CPU_LIMIT=1.0
DOCKER_PIDS_LIMIT=100
APPROVED_PROJECT_ROOTS=["."]
```

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
3. Tables (`analysis_runs`) are automatically created upon application startup via `init_db()`.

---

## 8. Docker Security & Isolated Test Runner

The Pytest execution engine enforces containment security:
- **Zero Network Access**: Containers run with `--network none` to prevent data exfiltration.
- **Resource Constraints**: Capped at `--memory 512m --cpus 1.0 --pids-limit 100`.
- **Non-Root Execution**: Runs under an unprivileged user (UID `1000`).
- **Read-Only Mounts**: Project directory mounted with `:ro` to prevent test suites from modifying source code.
- **No Shell Execution**: Arbitrary user commands are prohibited; test names are validated with strict regex (`^[a-zA-Z0-9_./\-:]+$`).
- **No Unsafe Fallbacks**: If Docker is unavailable, the runner immediately returns HTTP `503 Service Unavailable` rather than falling back to unisolated host execution.

---

## 9. Starting the FastAPI Server

Launch Uvicorn with auto-reload:
```powershell
cd E:\ChangeGuard-AI\backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Or run directly:
```powershell
python app/main.py
```

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
  "git_diff": "diff --git a/billing.py b/billing.py\n--- a/billing.py\n+++ b/billing.py\n@@ -10,3 +10,3 @@\n-def calculate_total(items):\n+def calculate_total(items, discount=0.0):\n     return sum(items) - discount"
}
```

**Response (`200 OK`)**:
```json
{
  "changed_functions": ["calculate_total"],
  "impacted_functions": ["calculate_total", "checkout"],
  "impacted_modules": ["billing.py", "checkout.py"]
}
```

### 2. Intelligent Test Selection (`POST /api/v1/tests/select`)

**Request**:
```json
{
  "impacted_functions": ["calculate_total", "checkout"]
}
```

**Response (`200 OK`)**:
```json
{
  "selected_tests": [
    {
      "test_name": "test_calculate_total",
      "reason": "Tests the modified billing function",
      "priority": "high"
    }
  ]
}
```

### 3. Safe Pytest Execution (`POST /api/v1/tests/execute`)

**Request**:
```json
{
  "project_path": "sample_project",
  "selected_tests": ["test_calculate_total"]
}
```

**Response (`200 OK`)**:
```json
{
  "total_tests": 5,
  "passed": 4,
  "failed": 1,
  "failures": ["test_calculate_total"]
}
```

### 4. Complete Workflow Run (`POST /api/v1/runs`)

**Request**:
```json
{
  "git_diff": "diff --git a/billing.py b/billing.py\n--- a/billing.py\n+++ b/billing.py\n@@ -10,3 +10,3 @@\n-def calculate_total(items):\n+def calculate_total(items, discount=0.0):\n     return sum(items) - discount",
  "project_path": "sample_project"
}
```

**Response (`201 Created`)**:
```json
{
  "run_id": "run-a1b2c3d4-e5f6",
  "risk_level": "HIGH",
  "changed_functions": ["calculate_total"],
  "impacted_functions": ["calculate_total", "checkout"],
  "impacted_modules": ["billing.py", "checkout.py"],
  "tests": {
    "total_tests": 5,
    "passed": 4,
    "failed": 1,
    "failures": ["test_calculate_total"]
  },
  "recommendations": [
    "CRITICAL: 1 regression test(s) failed (test_calculate_total). Resolve these failures before promoting code to production.",
    "Note: Successful regression test execution significantly lowers risk but does not mathematically guarantee absence of defects. Standard peer code review is still required."
  ],
  "created_at": "2026-11-19T16:20:00.000Z"
}
```

---

## 13. Running Automated Backend Tests

Execute the complete automated test suite:
```powershell
cd E:\ChangeGuard-AI\backend
.\venv\Scripts\Activate.ps1
pytest tests -v
```

All 19 tests run with transactional database isolation and custom adapter verification.

---

## 14. Connecting Teammate Modules

The backend contains plug-and-play adapter layers in `app/integrations/`:

### Connecting the Code Analyzer (Python AST + NetworkX)
In `backend/app/integrations/analyzer_adapter.py`:
1. **Option A (Package)**: Install teammate's analyzer package named `changeguard_analyzer` or `impact_analyzer`. The adapter automatically discovers `mod.analyze_diff(git_diff)`.
2. **Option B (Programmatic)**: In your integration script or application bootstrap:
   ```python
   from app.integrations.analyzer_adapter import CodeAnalyzerAdapter
   from my_teammate_analyzer import analyze_diff_function

   CodeAnalyzerAdapter.register_custom_analyzer(analyze_diff_function)
   ```

### Connecting the Test Selector
In `backend/app/integrations/selector_adapter.py`:
1. **Option A (Package)**: Install teammate's test selector package named `changeguard_selector` or `test_selector`. The adapter automatically calls `mod.select_tests(impacted_functions)`.
2. **Option B (Programmatic)**:
   ```python
   from app.integrations.selector_adapter import TestSelectorAdapter
   from my_teammate_selector import select_tests_function

   TestSelectorAdapter.register_custom_selector(select_tests_function)
   ```

If either module is not yet connected, the endpoints return an informative HTTP `503 Service Unavailable` explaining the integration pending status.

---

## 15. Connecting the React Frontend

The backend is pre-configured with CORS middleware allowing requests from React development servers:
- `http://localhost:3000` (Create React App)
- `http://localhost:5173` (Vite)

In your React frontend:
```typescript
// Example frontend fetch call
const runAnalysis = async (gitDiff: string) => {
  const response = await fetch("http://127.0.0.1:8000/api/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ git_diff: gitDiff }),
  });
  const report = await response.json();
  return report;
};
```
