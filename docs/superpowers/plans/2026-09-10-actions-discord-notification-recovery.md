# Actions Discord Notification Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore GitHub Actions and Discord notification jobs so fresh hosted runners can initialize and retain notification state, CI reports real test results, and upstream data defects no longer suppress downstream alerts.

**Architecture:** Keep authoritative market/fundamental data in Supabase and keep the runtime/outbox contract in SQLite. GitHub-hosted notification jobs will restore a producer-scoped runtime ledger from Actions cache, initialize the SQLite schema before any read-only command, then save the updated ledger under a unique run key. Workflows that can touch the same producer ledger will share a concurrency group. Local-only portfolio proposals remain owned by the local harness; the hosted `notify_investment` schedule will be removed because no cloud runner can observe that ledger.

**Tech Stack:** Python 3.11, `unittest`, SQLite, Supabase client, GitHub Actions YAML, `actions/cache@v4`, `uv`.

**Spec:** `docs/OPERATIONS.md`, `docs/STORAGE_MAP.md`, `CLAUDE.md`, and the 2026-09-08 through 2026-09-10 Actions incident evidence supplied with this task.

---

## File map

- Create `.github/actions/runtime-ledger/action.yml`: restore/cache a producer-scoped runtime SQLite directory and initialize its schema.
- Create `src/investment_agent/operations/commands/runtime_init.py`: explicit write-mode runtime schema initializer used by hosted jobs.
- Modify `.github/workflows/ci.yml`: install the dev group consistently and run package-root-aware test discovery through `uv`.
- Modify notification workflows under `.github/workflows/`: add runtime-ledger preparation and serialize workflows that share a producer ledger.
- Modify `.github/workflows/notify_investment.yml`: remove its hosted schedule and explain the local-ledger boundary.
- Modify `tests/test_workflow_wiring.py`: pin CI, runtime-ledger, concurrency, and local-only investment contracts.
- Modify `src/investment_agent/data/fundamentals/application/process_filing.py` and its callers/tests: propagate the requested CIK when filing references omit it.
- Modify `src/investment_agent/data/market/infrastructure/sources/yahoo.py` and `tests/test_market_source_contract.py`: quarantine isolated malformed Yahoo rows without hiding whole-symbol coverage loss.
- Modify stale entrypoint/page tests or their narrow production seams only where the baseline suite proves they no longer isolate external configuration or optional UI components.

## Task 1: Make CI execute the intended offline suite

- [x] Add a structural regression test in `tests/test_workflow_wiring.py` asserting that `ci.yml` uses `uv sync --locked --group dev` and `uv run python -m unittest discover -s tests -t .`.
- [x] Run `uv run python -m unittest tests.test_workflow_wiring` and confirm the new test fails on the current workflow.
- [x] Update `.github/workflows/ci.yml` to remove the contradictory `--no-dev`, keep the locked dev install, and run compile/tests through `uv run`; include `-t .` so `tests/investment_agent` cannot shadow `src/investment_agent`.
- [x] Re-run the targeted workflow wiring test and confirm it passes.

## Task 2: Give hosted notification jobs a durable initialized runtime ledger

- [x] Add `tests/investment_agent/operations/test_runtime_init.py` proving `runtime_init.main(["--path", ...])` creates a readable SQLite ledger with `notification_outbox` and `notification_deliveries` tables.
- [x] Run that test and confirm the command module is missing.
- [x] Implement `runtime_init.py` as a small explicit boundary around `runtime_connection(path)`; never make read-only database access create files implicitly.
- [x] Add a workflow wiring test requiring every hosted outbox workflow to invoke `./.github/actions/runtime-ledger` after `python-job`, with a nonempty producer scope.
- [x] Create `.github/actions/runtime-ledger/action.yml` using `actions/cache@v4` on `data/local/runtime`, a unique save key `${{ runner.os }}-runtime-${{ inputs.scope }}-${{ github.run_id }}-${{ github.run_attempt }}`, a producer restore prefix, and `uv run python -m investment_agent.operations.commands.runtime_init`.
- [x] Wire producer scopes into hosted notification readers; make `fundamentals_earnings_watch.yml` collection-only so the cache-backed follow-up notifier owns Discord delivery.
- [x] Make notification workflows that share a producer also share one concurrency group and ledger scope.
- [x] Remove the schedule trigger from `notify_investment.yml`, retain manual diagnostics, and document that scheduled investment alerts are emitted by the local harness which owns `portfolio_proposals`.
- [x] Run runtime initializer and workflow wiring tests; inspect all notification YAML for cache-key and concurrency consistency.

## Task 3: Preserve the parent CIK for SEC filing rows

- [x] Add an application regression test where a `FilingRef` has no embedded CIK but `process_company_facts(..., cik="320193")` passes a row with `cik == "0000320193"` to the repository before financial facts are written.
- [x] Run the test and confirm the current API either rejects `cik` or persists `0000000000`.
- [x] Extend `process_company_facts` with a required filing-context CIK when `filings` are supplied, normalize each filing through `filing_row(filing, cik)`, and update daily/history callers.
- [x] Keep the repository's strict foreign key behavior; do not suppress the database error or invent entity rows.
- [x] Run the fundamentals application, repository, daily sync, and backfill tests.

## Task 4: Quarantine one malformed Yahoo bar without accepting incomplete symbols

- [x] Add a download regression test containing two valid DTE rows and one large incoherent DTE row; assert the malformed date is omitted and the valid rows remain.
- [x] Add a second regression assertion that a ticker with only malformed rows still fails the existing coverage check.
- [x] Run those tests and confirm the first currently aborts the full batch.
- [x] Implement a row-classification helper that applies the existing strict validation to individual rows, logs a bounded warning for rejected `(ticker, trade_date, reason)` tuples, then validates the remaining batch for duplicates, values, and symbol coverage.
- [x] Keep `_validate_price_rows` strict for direct callers and preserve the small deterministic OHLC repair before quarantine.
- [x] Run all market source contract and price-repair tests.

## Task 5: Repair baseline offline-test isolation exposed by fixed CI

- [x] Re-run the exact CI command locally and capture the remaining failures after Tasks 1–4.
- [x] For macro and earnings-calendar entrypoint tests that construct a real Supabase boundary before their patched seam, patch the correct factory/boundary in the tests or move construction behind the already-injected seam without changing production behavior.
- [x] For dashboard page wiring failures, load the Streamlit skill instructions before editing, then make offline page rendering independent of optional animated-component registration and page-navigation runtime state.
- [x] Run each formerly failing module until green, followed by the complete offline suite.

## Task 6: Verify the full recovery and prepare operations follow-up

- [x] Run `uv run python -m compileall -q src tests`.
- [x] Run `uv run python -m unittest discover -s tests -t .` and require zero failures/errors.
- [x] Run `git diff --check` and review the complete diff for secrets, destructive database behavior, and accidental live-mode changes.
- [x] Confirm the maintenance hold remains on; do not change live settings automatically.
- [ ] Record the remaining data operation: after this branch is integrated, rerun `fundamentals_daily`, then `fundamentals_dimensions_backfill`, then `fundamentals_integrity` to repair and verify the 13 pre-existing missing segment-processing states.
- [ ] Record the remaining deployment operation: push/integrate the branch before expecting remote Actions behavior to change; no workflow run on `main` can exercise unmerged code.
