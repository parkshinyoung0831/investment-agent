---
name: ast-grep
description: "Fast AST-based code search, linting, and structural rewriting CLI (sg). Use for codebase-wide refactoring, structural pattern matching, enforcing architectural rules, or replacing syntax safely without regex pitfalls."
---

# ast-grep (Fast AST-based Code Search & Rewrite)

ast-grep (`sg`) searches and rewrites code using Abstract Syntax Tree (AST) patterns instead of fragile regular expressions. It understands language syntax, variable scoping, and node structures.

## Execution on Windows

Use the repository batch wrappers to run ast-grep without environment PATH issues:
```powershell
.\scripts\sg.bat [options]
# or
.\scripts\ast-grep.bat [options]
```

## Common Workflows

### 1. Structural Pattern Search
Search for syntactic structures across the codebase:
```powershell
# Search for all class definitions
.\scripts\sg.bat run --pattern 'class $NAME($$$):' --lang python src/

# Search for specific method or function calls with wildcards ($$$ matches multiple arguments)
.\scripts\sg.bat run --pattern 'datetime.now()' --lang python src/
```

### 2. Codebase Rule Scanning (`scan`)
Scan the project against architectural rules defined in `rules/ast-grep/`:
```powershell
# Scan entire source tree using rules configured in sgconfig.yml
.\scripts\sg.bat scan src/investment_agent/
```

### 3. Safe Structural Rewrite (`--rewrite`)
Rewrite code patterns across dozens of files with AST precision:
```powershell
# Preview pattern matches and replacements interactively
.\scripts\sg.bat run --pattern '$A == None' --rewrite '$A is None' --lang python -i

# Apply all rewrites immediately across the codebase
.\scripts\sg.bat run --pattern 'old_method($$$ARGS)' --rewrite 'new_method($$$ARGS)' --lang python -U
```

### 4. Exploring AST Structure (`--debug-query`)
Inspect how ast-grep parses a pattern into tree-sitter nodes:
```powershell
.\scripts\sg.bat run --pattern 'def $F($$$): $$$' --lang python --debug-query=ast
```

## Rule Configuration
- Root configuration file: `sgconfig.yml`
- Rule files: `rules/ast-grep/*.yml`
- Example rules enforce no bare excepts (`no-bare-except.yml`) and no naive datetime constructors (`no-naive-datetime-now.yml`).
