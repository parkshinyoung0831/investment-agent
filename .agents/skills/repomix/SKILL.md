---
name: repomix
description: "Pack repository files or subtrees into a single, clean AI-optimized context file (XML/Markdown) with token estimation, Tree-sitter AST compression, and security scanning. Use when reviewing large cross-module features, auditing components, or assembling prompts."
---

# Repomix (Repository Context Packer)

Repomix is a high-speed tool that packs your repository into AI-friendly formats (XML, Markdown, JSON, plain text) with token counting, security checks, and AST-based code compression.

## Execution on Windows

Always invoke repomix via the repository script to ensure Node.js is correctly resolved:
```powershell
.\scripts\repomix.bat [options]
```

## Common Workflows

### 1. Check Token Distribution
Quickly analyze which modules consume the most tokens:
```powershell
# Show directory tree with modules having >= 5,000 tokens
.\scripts\repomix.bat --token-count-tree 5000
```

### 2. Pack a Specific Subtree or Domain
Instead of the whole codebase, pack only relevant directories for targeted AI analysis:
```powershell
# Pack trading domain into XML
.\scripts\repomix.bat --include "src/investment_agent/trading/**" -o repomix-trading.xml

# Pack notifications and reporting
.\scripts\repomix.bat --include "src/investment_agent/notifications/**,src/investment_agent/reporting/**" -o repomix-notify.xml
```

### 3. Tree-sitter AST Code Compression (`--compress`)
Extract only classes, method signatures, and interfaces while stripping function bodies to preserve maximum context within token budgets:
```powershell
.\scripts\repomix.bat --compress --include "src/investment_agent/data/**" -o repomix-data-skeleton.xml
```

### 4. Output Formats and Options
- `--style xml` (default, best for Claude & Gemini structured prompt comprehension)
- `--style markdown` (best for human reading or GitHub Gist)
- `--token-budget <N>` (fails CI if packed tokens exceed limit)
- `--output-show-line-numbers` (useful for code review references)

## Project Configuration
The repository root contains `repomix.config.json` with preconfigured ignore patterns:
- Security exclusion for `.env*` and keys
- Exclusion of local databases (`db/duckdb/`, `data/local/`)
- Exclusion of graphify visual caches (`graphify-out/cache/`)
