# ChangeGuard AI – Predict Before You Deploy

> **Hackathon Project** | AI-assisted code change impact analysis and intelligent regression testing platform

---

## 📌 Project Description

ChangeGuard AI helps engineering teams understand the blast radius of every code change *before* it reaches production. By combining static code analysis, dependency graph traversal, and LLM-powered reasoning, it automatically identifies which parts of the codebase are affected by a diff, recommends the most relevant regression tests to run, and explains the potential risk in plain English — so teams can deploy with confidence.

---

## 🛠 Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | React, TypeScript, Vite |
| **Backend** | Python, FastAPI |
| **Code Analysis** | Python AST, Git diff parsing, NetworkX |
| **Testing** | pytest |
| **AI Assistance** | LLM API (test suggestions & natural-language explanations) |

---

## 🔄 Planned Workflow

```
1. Developer opens a Pull Request / provides a Git diff
        │
        ▼
2. Code Analyzer parses the diff using Python AST
   → Builds a dependency graph with NetworkX
   → Identifies changed functions, classes, and modules
        │
        ▼
3. Test Selector maps changed code nodes to existing tests
   → Scores and ranks tests by relevance
   → Surfaces tests that cover impacted code paths
        │
        ▼
4. LLM Engine generates:
   → Plain-English explanation of the change impact
   → Suggestions for new regression tests if gaps are found
        │
        ▼
5. Test Runner executes the selected tests via pytest
        │
        ▼
6. Report Generator produces a structured impact report
   → Risk level, affected modules, test results, recommendations
        │
        ▼
7. Frontend Dashboard displays results to the developer
```

---

## 📁 Repository Structure

```
ChangeGuard-AI/
├── frontend/          # React + TypeScript + Vite UI
├── backend/           # FastAPI server
│   ├── routes/        # API route handlers
│   └── services/      # Business logic layer
├── code_analyzer/     # AST parsing & dependency graph (NetworkX)
├── test_selector/     # Test relevance scoring & selection logic
├── sample_project/    # Demo codebase used for evaluation
│   └── tests/         # Tests for the demo codebase
├── test_runner/       # pytest orchestration layer
├── reports/           # Generated impact report outputs
├── evaluation/        # Accuracy & benchmarking scripts
└── README.md
```

---

## 🚀 Getting Started

> ⚙️ Setup and installation instructions will be added as the project develops.

---

## 👥 Team

> Team details to be added.
