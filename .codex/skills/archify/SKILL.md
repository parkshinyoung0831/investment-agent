---
name: archify
description: "Create and compile polished, validated C4 architecture, workflow, sequence, dataflow, and lifecycle diagrams as standalone interactive HTML with showcase quality. Use when visualizing system architecture, execution runbooks, order lifecycles, and data pipelines in docs/diagrams/."
---

# Archify (System Architecture & Workflow Diagram Compiler)

Archify compiles typed JSON diagram specifications into self-contained, interactive HTML diagrams with inline SVG, dark/light themes, and animation trace controls.

## Execution on Windows

Invoke Archify via the repository batch wrapper or the automated diagram builder:
```powershell
# Run archify CLI commands
.\scripts\archify.bat [command] [options]

# Validate a diagram candidate against 9 showcase composition checks
.\scripts\archify.bat validate <type> <candidate.json> --quality showcase --json

# Deliver/compile a diagram to HTML
.\scripts\archify.bat deliver <type> <candidate.json> <output.html> --quality showcase --json

# Build and validate all 7 project diagrams at once
& (Get-Content graphify-out\.graphify_python) scripts/build_diagrams.py
```

## Diagram Types

| Type | Specification | Use for |
|---|---|---|
| `architecture` | `docs/diagrams/*.architecture.json` | C4 components, services, database storage maps |
| `workflow` | `docs/diagrams/*.workflow.json` | Execution runbooks, approval gates, maintenance procedures |
| `sequence` | `docs/diagrams/*.sequence.json` | Event flows, SEC earnings notifications, broker orders |
| `dataflow` | `docs/diagrams/*.dataflow.json` | Market ETL, feature pipelines, DuckDB/Supabase dataflow |
| `lifecycle` | `docs/diagrams/*.lifecycle.json` | Order state machines, proposal status lifecycles |

## Quality Standards
- All project diagrams must achieve **Showcase** profile (0 composition errors, 0 warnings, all 9 checks passed).
- Output diagrams are delivered to `docs/diagrams/*.html`.
