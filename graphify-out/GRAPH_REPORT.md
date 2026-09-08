# Graph Report - investment-agent-main  (2026-09-08)

## Corpus Check
- 1149 files · ~863,829 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 14624 nodes · 31926 edges · 658 communities (529 shown, 92 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 1544 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `68a11575`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- web.py
- quant.py
- app_pages/earnings.py
- EvidenceBundle
- PolicyAndModelRepositoryTest
- live_worker.py
- ExecutionIntent
- ReleaseWatchTest
- actuals.py
- execution/db.py
- artifacts.py
- awaiting_message
- companyfacts.py
- launcher.py
- .create
- investment_harness.py
- commands/common_shares.py
- ExecutionRepository
- sec.py
- charts.py
- dashboard/db.py
- portfolio/contracts.py
- _tree
- rl/contracts.py
- MarketQuote
- switch.py
- reserve_provider_call
- MacroArchitectureTest
- readers/intelligence.py
- FundamentalsRepository
- FeatureDataset
- test_historical_earnings_estimates.py
- parse_earnings_release.py
- refresh_earnings_season.py
- _ensure_filings
- supabase_repository.py
- 90_reporting.sql
- continuous_retrain.py
- ProductionInvestmentAdapters
- emergency.py
- _fetch
- build_events.py
- HarnessScheduler
- FiscalPeriod
- AccountSnapshot
- DiscordApprovalClient
- Investment Agent Design System
- MacroRepository
- releases/db.py
- DailyBar
- SelectOnlyGatewayTests
- ReportingQueries
- postgres.py
- inspect_harness_state
- RunLifecycleTest
- run_backtest
- _ExecutionRepository
- TradingRepository
- candidate_ranker.py
- fundamentals/repository.py
- yahoo_finance/consensus.py
- ResearchDataset
- refresh_expectations
- discord_admin/client.py
- _flatten
- BuildEventsTest
- normalize_ticker
- app_pages/intelligence.py
- f
- calculations/__init__.py
- toss/client.py
- UniverseRepository
- BrokerAdapter
- _text
- create_execution_intent.py
- market_daily.py
- tradingagents_adapter.py
- FakeRepository
- features/db.py
- reported_observations.py
- worker.py
- econ_calendar.py
- PersistenceSecurityQueriesTest
- Database
- home.py
- SupabaseRepository
- canonical_json
- storage_paths.py
- export_dataset
- .from_row
- application/etl.py
- WeightEnvironmentCore
- ShadowFillTest
- institutional/test_service.py
- CompanyFinancialRepository
- snapshots.py
- macro/format.py
- size_portfolio
- normalize_segment_facts.py
- logging.py
- renderers/text.py
- provider.py
- OpenAICompatibleClient
- RawPosition
- _snap
- parse_xbrl.py
- make_filing_record
- FeatureLayer
- parser.py
- TradingAgentsAdapterTest
- test_roles.py
- LocalEvidenceCache
- CLAUDE.md
- src/investment_agent/data/fundamentals/application/__init__.py
- evaluate
- NotificationServiceTest
- BackfillWindow
- 설치, 자동 실행, 상태 확인과 장애 대응
- select_tracked_tickers
- BacktestRequest
- detect_earnings_events.py
- RunContext
- parse_external_payload
- services/investment/__init__.py
- parse_shares.py
- HarnessMode
- infrastructure/sources/yfinance.py
- releases/schedule.py
- EarningsCalendarStore
- What You Must Do When Invoked
- factor_risk.py
- _snap
- auth.py
- ics.py
- TossOrderApiTest
- backtest/contracts.py
- calendar.py
- FilingRef
- fit_baseline
- fsds.py
- alfred.py
- process_filing.py
- earnings_report/embeds.py
- strategies.py
- LocalTradingDatabase
- DossierBuilder
- _wf
- README.md
- earnings/schedule.py
- control_center.py
- json_value
- ExpectationRetentionTest
- ExecutionSafetyError
- 저장 계층 구조·스키마 축소 설계
- collection.py
- build
- DispatchResult
- ForumDeliveryTest
- compute_rl_blend
- _run
- _modules
- archive_daily_rows
- expectations_exit_code
- normalize.py
- validated_weights
- universe/persistence.py
- _intent
- FakeDatabase
- strategies/db.py
- select_session_targets.py
- parse_datetime
- filing_documents.py
- main
- _Repository
- press_releases.py
- app_pages/macro.py
- _run
- test_workflow_wiring.py
- market_schedule.py
- MeasureCalculationTest
- TransactionCostModel
- filings.py
- install_investment_harness.py
- price_risk_profile
- _canonical_filing_focus
- build_labels.py
- IntelligenceRepositoryTest
- TossTokenManagerTest
- What You Must Do When Invoked
- What You Must Do When Invoked
- market/persistence.py
- shadow_daily.py
- TossAuthError
- Path
- _Query
- GuildDirectory
- _row
- inputs.py
- main
- capture_toss_account_snapshot
- Third-party data notice — `gaap_mappings.json`
- ._at
- valuation_history
- OrderIdentityTest
- valuation_history.py
- select_model_for_ticker
- fact_checker.py
- eval_row
- PolicyConceptChoice
- Trading package
- test_schema_alignment.py
- test_provider_fail_closed.py
- construct.py
- test_strategy_guardrails.py
- _row
- classify_session
- ensure_aware
- attribution.py
- IntelligenceRepository
- QualityAssessmentTest
- layer.py
- _Query
- 투자 판단, ML/RL, Backtest와 Portfolio Risk
- segment_concepts.py
- analysis.py
- OperationalRetentionTest
- ManifestTest
- sources/toss_holdings.py
- filing_xbrl.py
- GuruRoutingTest
- select_timed_targets
- DimensionPreservationTest
- earnings_calendar/card.py
- ResearchStore
- breadth_200dma
- watchlists/db.py
- drop_implausible_share_rows
- SubprocessModuleRunner
- promotion/gate.py
- release_catalog.py
- SegmentMetricRepository
- portfolio_shadow.py
- run_preflight
- format_guidance_headline
- edgartools_13f.py
- backtest/cli.py
- StrategyTests
- experiments
- validate_snapshot
- Investment Operations Harness — 로컬 상시 오케스트레이션 계층
- 20_decisions.sql
- ActiveMembersTest
- monitoring/discord.py
- ArtifactRef
- sec13f.py
- Execution package
- _Repository
- 저장 계층 최소화 검토와 Markdown 개정안
- FailureAlertTest
- test_logging.py
- Filing13F
- Outbox
- AI Investor Constitution
- finite_float
- backtest/metrics.py
- BuildTest
- ticker_label
- _db
- ViewTest
- 데이터, Supabase, PIT와 로컬 뉴스 Cache
- test_edgartools_13f.py
- github_actions.py
- SurpriseRowsTest
- src/investment_agent/research/features/__init__.py
- load_or_create_approval_secret
- map_fiscal_periods.py
- _ops_webhook
- test_reporting_guards.py
- _row
- fusion.py
- storable_share_rows
- DashboardLauncherCliTest
- universe/infrastructure/sources/__init__.py
- SegmentHighlightsTest
- object
- SelectOnlyGateway
- ContextBuilder
- MacroChainTest
- 적응형 정보 구조
- extract_summary_financials
- gdpnow_archive.py
- normalize_positions
- safe_fetch
- institutional/card.py
- src/investment_agent/research/rl/__init__.py
- strategy/embeds.py
- QlibPITAdapter
- 주문 실행, 승인, Broker와 단계별 안전장치
- digest.py
- verify_postgres_sql_syntax.py
- load
- fomc_calendar.py
- macro_indicator_rows
- reconcile_orders
- EnvFileTest
- earnings_report/quickchart.py
- CollectSocialTest
- test_watchlists.py
- build_valuations
- _Builder
- SignalBlender
- ._history
- _Repository
- _Repository
- test_serving.py
- test_config.py
- notifications/macro.py
- Investment Agent
- 자주 발생하는 문제
- IntelligenceArchitectureTest
- test_view_reachability.py
- TradingAgentsDecisionEngine
- test_workflow_storage_paths.py
- 30_execution.sql
- openfigi.py
- OpenFigiIdentifierTest
- IntelligenceReaderTest
- MembershipReconcileTest
- FiresBetweenTest
- _called_schemas
- store
- Fundamentals domain
- taxonomy/__init__.py
- main
- test_market_retention.py
- Macro 경제발표
- InstitutionalArchitectureTest
- EconIcsTest
- DiscordTest
- apply_downstream_api_key
- CandidateFeatureReadTest
- Research Features — 일간 기술지표와 PIT 학습 입력
- Strategy — 팩터/룰 기반 자산배분 전략 6종 파이프라인
- PITScalar
- 18. 검수 체크리스트
- _by_key
- CollectNewsTest
- earnings/__init__.py
- application/service.py
- test_segments_quality.py
- CardInstallGuardTest
- 처음 보는 사람을 위한 시스템 지도
- HarnessReporter
- db_capacity.py
- Any
- social_normalize.py
- compute_all
- model_pool.py
- Notifications — 시각화 알림(Playwright PNG 카드 & Discord Embed) 서브시스템
- test_inputs.py
- overwrites
- FindTickersTest
- context.py
- ActualProviderTest
- investment/embeds.py
- redact
- _service
- application/backfill_history.py
- v1 현재 상태
- cron.py
- test_universe_sic.py
- MACRO — v1 market-state pipeline
- test_ecos.py
- news_normalize.py
- validate
- installation_files
- DependencyDeclarationTest
- features/etl.py
- Universe watchlists — 관심 기업 & 토스증권 보유종목 동기화
- Discord Admin — 코드 기반 선언적 Discord 서버 관리 (IaC)
- Tracked universe 후보 선정
- AGENTS.md
- KindsWiringTest
- 10. 데이터 시각화
- test_continuous_retrain_exit_code.py
- FundamentalsArchitectureTest
- _domain_precisions
- test_operational_guardrails.py
- test_macro_release_watch_dedup.py
- report.py
- 16. 구현 계약
- StrategyLabelsTest
- 9. 핵심 컴포넌트
- split_dataset
- 2. 핵심 결정과 우선순위
- trading/contracts.py
- graphify reference: extra exports and benchmark
- 3. 제품 철학
- retry_on_5xx
- Fundamentals
- Universe v1
- is_earnings_item
- validate_series
- HarnessModuleAllowlistTest
- UniverseArchitectureTest
- test_filing_xbrl_fallback.py
- earnings/metrics.py
- SourceBudgetTest
- EconSnapshotShapeTest
- validate_live_candidate_as_of
- 40_macro.sql
- 5. 색 시스템
- resolve_flash_period
- 저장 계층 전면 개편 인계 메모
- _LabelRepository
- test_research_store_read_paths.py
- WorkflowNameTest
- 11. 라이트·다크 모드 운영
- 14. 보이스 앤 톤
- social_source.py
- 2. 핵심 헬퍼 모듈 사용법
- download_monthly_close
- 6. 타이포그래피
- 8. 모양, 보더, 깊이
- lifecycle.py
- SetMembershipTest
- Institutional — SEC 13F 원천·유효 포트폴리오
- DecisionTest
- Market v1
- valuation/engine.py
- earnings_report/__init__.py
- normalize_accession
- test_failure_reporter_deps.py
- graphify reference: extra exports and benchmark
- graphify reference: extra exports and benchmark
- _submissions_document
- VersionSelectionTest
- 10_universe.sql
- run
- LocalArtifactStore
- _entrypoints
- platform/artifacts.py
- EntityMention
- NewsSocialPageTest
- PriceTargetTest
- decision_and_apply_dates
- releases/test_db.py
- pending_filings
- Native Autonomous Investment System
- content_index
- discord_admin/guide.py
- Path
- v1 내부 정리 로드맵
- MarketArchitectureTest
- retry.py
- src/investment_agent/execution/__init__.py
- news_social.py
- InstitutionalSchemaContractTest
- strategies/catalog.py
- .bars
- releases/baseline.py
- _run_backfill
- FullPortfolioSchemaTest
- operations_view.py
- SharedSetupTest
- us_market_today
- actions_budget.py
- twap.py
- main
- SegmentSnapshotOrderTest
- Operations — Discord-first 운영 관측과 로컬 하네스
- discord_admin/sync.py
- yahoo.py
- build_valuations.py
- process_segment_cik
- test_channel_names_are_declared.py
- change_manifest.py
- ExecutionBoundaryTest
- MembershipHistoryStorageTest
- 10. Intelligence: Parquet로 옮길 때 필요한 운영 계약
- _complete_tail
- PostgresSchemaLayoutTest
- graphify reference: query, path, explain
- graphify reference: query, path, explain
- 7. 간격과 레이아웃
- DashboardLauncherPortTest
- test_segments_unmapped.py
- DashboardLauncherSafetyStateTest
- ExecutionPackageLayoutTest
- test_table_query_contracts.py
- test_repo_conventions.py
- PackagingContractTest
- _payload_key_sets
- PriceCollectionContractTests
- EarningsWatchStatus
- test_company_financials_upsert.py
- test_fundamentals_consensus.py
- test_forum_kinds_are_wired.py
- DefaultPoolTest
- RepositoryLayoutTest
- V1ResetContractTest
- runtime/v1/00_init.sql
- UniverseNamingContractTest
- anon_client
- 7. Fundamentals: canonical 수치와 과거 사용 가능성을 구분
- 11. Research: 대용량 Wide와 불변 실행 metadata
- 16. 구현 순서와 완료 기준
- calibrator.py
- ExhibitExtractorTest
- fundamentals/test_service.py
- 12. Runtime: SQLite에 돈의 사실과 안전 상태를 보존
- institutional/db.py
- BlindSpotCaveatTest
- StrategyWorkflowOrderingTest
- 15. Markdown 파일별 개정 지도
- 6. Market: 얇은 행 + 명시적인 공개·변경 계약
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- execution_view.py
- graphify reference: query, path, explain
- 8. Macro: fact를 분리하되 의미 metadata는 유지
- InstitutionalRetentionTest
- d_day_label
- DangerFloorTest
- RadarCodeContractTest
- 4. 500MB 예산을 올바르게 정의하기
- test_entrypoint.py
- 5. Universe: identity를 보존하며 간소화
- migrate_local_storage.py
- test_adapter_contracts.py
- PITValuationInputs
- _imported_modules
- TechnicalIndicatorRetryTest
- evidence/cache.py
- DataPackageLayoutTest
- test_subscription_routing_contract.py
- EarningsFlashOutbox
- identifiers.py
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- test_evaluator.py
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- ExpectationsRepositoryPagingTest
- verify_data.py
- test_calculations_facade.py
- .claude/skills/graphify/references/extraction-spec.md
- .codex/skills/graphify/references/extraction-spec.md
- ReportingPackageLayoutTest
- intelligence/v1/00_init.sql
- graphify reference: add a URL and watch a folder
- test_default_paths.py
- graphify reference: commit hook and native CLAUDE.md integration
- FilingRowAcceptsEveryShapeTest
- graphify reference: incremental update and cluster-only
- src/investment_agent/data/fundamentals/infrastructure/__init__.py
- _StubModel
- investment-agent
- src/investment_agent/data/__init__.py
- institutional/commands/__init__.py
- institutional/NOTICE.md
- 20_market.sql
- 40_notifications.sql
- CandidateCoverageRepositoryTest
- src/investment_agent/__init__.py
- entries/__init__.py
- test_fundamentals_integrity.py
- DerivedQuartersCarryNoBalances
- src/investment_agent/notifications/__init__.py
- StorageLayoutTest
- test_earnings_consensus_reader.py
- test_universe_names.py
- ResearchStoreTest
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- test_watchlist_toss.py
- 50_institutional.sql
- src/investment_agent/research/valuation/__init__.py
- src/investment_agent/trading/decision/llm/__init__.py
- src/investment_agent/trading/evidence/__init__.py
- .agents/skills/graphify/references/extraction-spec.md
- src/investment_agent/trading/portfolio/__init__.py
- test_model_pool_providers.py
- src/investment_agent/trading/risk/__init__.py
- tests/__init__.py
- tests/investment_agent/data/fundamentals/application/__init__.py
- tests/investment_agent/data/fundamentals/domain/__init__.py
- tests/investment_agent/data/fundamentals/infrastructure/__init__.py
- tests/investment_agent/data/macro/releases/__init__.py
- tests/investment_agent/notifications/__init__.py
- tests/investment_agent/operations/commands/__init__.py
- tests/investment_agent/reporting/__init__.py
- tests/investment_agent/research/features/__init__.py
- tests/investment_agent/research/__init__.py
- tests/investment_agent/trading/decision/__init__.py
- tests/investment_agent/trading/decision/llm/agents/__init__.py
- tests/investment_agent/trading/decision/llm/__init__.py
- tests/investment_agent/trading/evidence/__init__.py
- tests/investment_agent/trading/portfolio/__init__.py
- native/__init__.py
- 10_account.sql
- NotifyPackageShapeTest
- macro/domain/__init__.py
- src/investment_agent/data/macro/__init__.py
- 30_fundamentals.sql
- components/__init__.py
- src/investment_agent/data/fundamentals/__init__.py
- approval/__init__.py
- orders/__init__.py
- market.split_events
- reconciliation/__init__.py
- safety/__init__.py
- src/investment_agent/intelligence/__init__.py
- src/investment_agent/operations/__init__.py
- src/investment_agent/platform/__init__.py
- KillSwitchTest
- RunnerImageTest

## God Nodes (most connected - your core abstractions)
1. `parse_datetime()` - 238 edges
2. `get_logger()` - 167 edges
3. `canonical_json()` - 155 edges
4. `FakeDatabase` - 155 edges
5. `ExecutionSafetyError` - 151 edges
6. `SupabaseRepository` - 136 edges
7. `ContractError` - 130 edges
8. `Database` - 128 edges
9. `EvidenceBundle` - 98 edges
10. `ExecutionRepository` - 91 edges

## Surprising Connections (you probably didn't know these)
- `run()` --uses--> `Database`  [INFERRED]
  scripts/verify_integration.py → src/investment_agent/platform/db/postgres.py
- `run()` --uses--> `MacroNotificationStore`  [INFERRED]
  scripts/verify_integration.py → src/investment_agent/reporting/notifications/macro.py
- `run()` --uses--> `SupabaseRepository`  [INFERRED]
  scripts/verify_integration.py → src/investment_agent/trading/supabase_repository.py
- `LoadConfigTest` --uses--> `ConfigError`  [INFERRED]
  tests/investment_agent/test_config.py → src/investment_agent/config.py
- `_config()` --uses--> `Config`  [INFERRED]
  tests/investment_agent/notifications/test_channel_directory.py → src/investment_agent/config.py

## Import Cycles
- None detected.

## Communities (658 total, 92 thin omitted)

### Community 0 - "web.py"
Cohesion: 0.09
Nodes (42): _cboe_put_call(), _cboe_put_call_on(), _cboe_vix(), _cnn_fear_greed(), fetch_batch(), _get(), _month_starts(), _multpl() (+34 more)

### Community 1 - "quant.py"
Cohesion: 0.06
Nodes (67): _allocation_items(), _allocation_summary(), _allocation_text(), _asset_label(), _assets_for_allocations(), _comparison_chart(), _is_equal_weight_allocation(), _metric_row() (+59 more)

### Community 2 - "app_pages/earnings.py"
Cohesion: 0.04
Nodes (109): _frame_from_prices(), _latest(), Any, DataFrame, 저장된 AI 투자 판단을 선택한 깊이만큼 읽기 전용으로 검토한다., 선택된 가격 뷰 안에서만 저장된 OHLCV를 읽고 지표를 계산한다., 주문·체결 페이지가 탭 하나로 불러 쓴다. 페이지 단독 진입점은 아니다. 스크립트였을 때의 st.stop()은 return으로 바꿨다 — 탭…, render() (+101 more)

### Community 3 - "EvidenceBundle"
Cohesion: 0.07
Nodes (35): EvidenceBundle, EvidenceItem, _estimates(), _external_live(), _find(), _fundamentals(), _macro_events(), _missing_reason() (+27 more)

### Community 5 - "live_worker.py"
Cohesion: 0.04
Nodes (75): LiveExecutionPermit, 소비된 승인 하나가 허용하는 주문 집합. **몇 분짜리다.**, 저장소 표기(BRK-B)를 토스 표기(BRK.B)로 변환한다., to_toss_symbol(), TossUsRegularSession, _decimal(), _decimal_text(), parse_personal_order_event() (+67 more)

### Community 6 - "ExecutionIntent"
Cohesion: 0.07
Nodes (39): Toss 인증·계좌 조회·주문 API client 패키지., ExecutionIntent, IntentError, datetime, ValueError, 지금 이 의도로 주문을 만들어도 되는가. 아니면 예외. `required_mode`를 인자로 받는 이유: 부르는 쪽이 **자기가 어느 경로인지…, 현금을 뺀 대상 종목. 주문 계획이 도는 목록이다., 실행 의도가 계약을 어겼다. **주문을 만들지 않는다.** (+31 more)

### Community 7 - "ReleaseWatchTest"
Cohesion: 0.10
Nodes (7): Macro application orchestration boundary., Macro domain의 실행 가능한 명령 진입점., HistoricalForecastTest, ALFRED forecast reconstruction이 measure/PIT 계약을 지키는지 검사한다., ECON release-time watcher의 due/filter/pending/idempotency 계약., _release(), ReleaseWatchTest

### Community 8 - "actuals.py"
Cohesion: 0.12
Nodes (35): ActualConfigurationError, ActualDataError, ActualNotAvailableYetError, ActualProviderError, ActualsError, _canonical_period(), _contract(), _ecos() (+27 more)

### Community 9 - "execution/db.py"
Cohesion: 0.04
Nodes (44): Connection, Broker에 전달하기 전 주문 계획 계약., _attempt_event(), latest_order(), latest_paper_account_snapshot(), latest_reconciliation_run(), _order_attempt(), 로컬 SQLite 실행 원장과 canonical 종목 identity 조회 경계. (+36 more)

### Community 10 - "artifacts.py"
Cohesion: 0.11
Nodes (24): archive_case_evidence(), ArchivedCaseEvidence, _bounded_texts(), build_evidence_digest(), EvidenceArtifactError, EvidenceArtifactManifest, EvidenceArtifactStore, _latest_timestamp() (+16 more)

### Community 11 - "awaiting_message"
Cohesion: 0.31
Nodes (4): awaiting_message(), 비어 있는 화면에 붙일 안내 문구를 만든다. 빈 화면만으로는 "코드가 죽었다"와 "아직 안 쌓였다"를 구분할 수 없다. 무엇이 없는지와 언제…, AwaitingMessageTest, 빈 화면이 고장인지 데이터가 없는 건지 구분되게 한다. 지금까지는 그냥 비어 있어서, 코드가 죽은 것(호출자 0)과 아직 안 쌓인 것을 화면만…

### Community 12 - "companyfacts.py"
Cohesion: 0.07
Nodes (48): normalize_form(), 공시와 회계기간을 식별하는 순수 값 객체., 수정 공시 표기를 원 공시 유형으로 정규화한다., _accession_coverage(), _affected_fiscal_years(), _annual_fiscal_year(), _available_daily_index_urls(), companyfacts_to_facts() (+40 more)

### Community 13 - "launcher.py"
Cohesion: 0.14
Nodes (28): clear_screen(), configure_console(), developer_tools_menu(), find_available_port(), harness_switch_command(), interactive_menu(), is_port_available(), main() (+20 more)

### Community 14 - ".create"
Cohesion: 0.11
Nodes (14): create_approval_id(), issue_live_execution_permit(), datetime, timedelta, `intent` 만료를 넘지 않는 pending 요청을 만든다. `latest_expiry`로 자르는 이유: 의도가 끝난 뒤에도 살아 있는…, 소비된 승인을 짧은 실주문 permit으로 바꾼다. **DB를 바꾸지도, 네트워크를 부르지도 않는다.** 부르는 쪽이 먼저…, ApprovalBridgeTest, _consumed() (+6 more)

### Community 15 - "investment_harness.py"
Cohesion: 0.07
Nodes (47): build_registry(), _emit(), main(), 항상 켜진 로컬 장비용 투자 분석 운영 하네스. 인자 없이 실행하면 상태 파일이나 외부 서비스에 손대지 않고 계획만 출력한다., JobDefinition, StageDefinition, HealthReport, inspect_health() (+39 more)

### Community 16 - "commands/common_shares.py"
Cohesion: 0.07
Nodes (45): main(), _parse_args(), Namespace, SEC 보통주 발행주식수 수집 및 백필 엔트리포인트., main(), _parse_args(), Namespace, 적재된 fundamentals 데이터의 불변조건을 주기적으로 점검하는 canonical 잡. 수집 성공 여부만으로는 저장 행의 완전성과 파생… (+37 more)

### Community 17 - "ExecutionRepository"
Cohesion: 0.05
Nodes (20): _approval(), ExecutionRepository, _intent(), datetime, 실행 컴퓨터의 SQLite 원장만 사용하는 주문·승인 저장소., 원본 응답을 내용 주소 파일로 보존하고 원장에는 경로·해시만 남긴다., 실행을 위해 보존해야 하는 판단 원문을 local runtime에 기록한다., DurableControlState (+12 more)

### Community 18 - "sec.py"
Cohesion: 0.09
Nodes (36): _get_text_optional(), archive_cik(), filing_archive_base(), filing_archive_items(), filing_document_url(), filing_homepage_url(), filings_filed_since(), get_bytes_optional() (+28 more)

### Community 19 - "charts.py"
Cohesion: 0.07
Nodes (44): _as_date(), _axis_money(), _bridge_parts(), cashflow_quarters(), combo(), _div(), dividend_trend(), earnings_quality() (+36 more)

### Community 20 - "dashboard/db.py"
Cohesion: 0.03
Nodes (170): Figure, P, R, blending_weights(), _load_real_active_policy(), Any, AI·강화학습(ML/RL) 자율진화 관제 랩 대시보드 페이지. 하네스 7대 전자동 잡의 실제 실행 상태, PPO 강화학습 챔피언 정책…, 승격된 정책의 DSR 확률이 만드는 (LLM 가중치, RL 가중치). 정책이 없으면 None. 실제 판단 경로가 RL 목표비중을 넘기지… (+162 more)

### Community 21 - "portfolio/contracts.py"
Cohesion: 0.06
Nodes (43): baseline을 실행 권한 없는 RL challenger PortfolioProposal로 변환한다., PortfolioProposal, _probability(), Any, LLM·RL·룰 전략이 공유하는 포트폴리오 비중 계약., FinRL-X의 weight-centric 경계를 저장 가능한 형태로 엄격화한다., long-only 비중을 검증하고 현금 항목을 포함한 정렬 사본을 반환한다., 종목 분석 결과다. 실제 주문 권한은 갖지 않는다. (+35 more)

### Community 22 - "_tree"
Cohesion: 0.14
Nodes (16): DatabaseNameConstantsTest, FutureAnnotationsTest, _has_main_guard(), _modules(), _posix(), PublicExportTest, Module, `if __name__ == "__main__":` 블록이 있으면 CLI로 직접 실행되는 모듈이다. (+8 more)

### Community 23 - "rl/contracts.py"
Cohesion: 0.06
Nodes (51): 단일 horizon label을 구간 종료가 확정된 뒤에만 만든다. `label_available_at`을 넘기면 실제 적재 시각을 근거로…, 1/5/20 거래일 종료 뒤에만 label을 생성한다., ResearchStore의 PIT feature snapshot을 Qlib research workflow에만 연결한다., FeatureSnapshot, _finite(), ForwardReturnLabel, _hash(), MembershipSnapshot (+43 more)

### Community 24 - "MarketQuote"
Cohesion: 0.17
Nodes (10): MarketQuote, MarketState, _number(), Any, datetime, 최신값만 덮어쓰는 RAM cache. source of truth나 주문 ledger가 아니다., 최신 quote를 원자적으로 교체한다., 호출자가 수정할 수 없는 정렬된 shallow snapshot을 반환한다. (+2 more)

### Community 25 - "switch.py"
Cohesion: 0.07
Nodes (45): interactive_loop(), main(), print_status_dashboard(), Path, 투자 하네스 ON/OFF 스위치 및 제어판 CLI 진입점. 사용 예시: # 1. 종합 상태 조회 python -m…, _safe_print(), clear_maintenance_hold(), get_maintenance_path() (+37 more)

### Community 26 - "reserve_provider_call"
Cohesion: 0.06
Nodes (42): main(), 서브레딧 새 글을 수집해 intelligence.duckdb에 적재한다., 수집 대상 서브레딧 선언. 환경변수가 아니라 코드가 선언을 갖는다 — 어떤 채널을 보는지는 실행 환경마다 달라야 할 설정이 아니라 이 저장소의…, RuntimeError, 뉴스 provider가 data 계층에서 반환하는 결과 계약., Reddit 자격증명이 없다. 오류가 아니라 아직 켜지지 않은 상태다., 오늘 provider 한도를 다 썼다. 수집 유스케이스와 reddit 어댑터가 함께 쓰는 계약이라 둘 중 어느 계층에도 두지 않는다.…, SocialCredentialsMissing (+34 more)

### Community 27 - "MacroArchitectureTest"
Cohesion: 0.10
Nodes (18): ImportFrom, _application_code_files(), _command_code_files(), _domain_code_files(), _import_from_modules(), _importing_package(), _imports(), _infrastructure_code_files() (+10 more)

### Community 28 - "readers/intelligence.py"
Cohesion: 0.13
Nodes (27): default_database_path(), 이번 실행이 쓸 Intelligence DB 경로., connect(), ddl_statements(), DuckDBStoreError, Any, Path, RuntimeError (+19 more)

### Community 29 - "FundamentalsRepository"
Cohesion: 0.05
Nodes (27): Filing, 공시가 존재한다는 사실. 우리가 그것을 어떻게 처리했는지는 여기 없다., FundamentalsRepository, Any, date, datetime, 기간별 canonical provenance. 호환을 위해 목록 모양은 유지하지만 각 기간에는 최대 한 행만 들어간다., canonical 재무 행. 정정 전 숫자는 저장하지 않으므로 ``as_of``는 source filing date보다 앞선 행을 제외한다.… (+19 more)

### Community 30 - "FeatureDataset"
Cohesion: 0.05
Nodes (37): PPOAllocationTimingSpec, Any, PPO의 초기 범위를 allocation·timing으로 제한한다., PPO가 broker나 종목 수량을 직접 만들지 않는 연구 명세., RewardConfig, FeatureDataset, make_gym_environment(), 종목 수량이 아니라 목표 비중을 학습하는 FinRL용 환경. (+29 more)

### Community 31 - "test_historical_earnings_estimates.py"
Cohesion: 0.07
Nodes (25): backfill_historical_eps_estimates(), Any, ExpectationsRepository, 과거 8-K 실적 속보에 EPS 예상치 재구성값을 채운다., 기존 실적 속보에만 Yahoo의 과거 EPS 예상치를 재구성해 저장한다., build_historical_eps_estimates(), _finite_number(), HistoricalEpsEstimateBatch (+17 more)

### Community 32 - "parse_earnings_release.py"
Cohesion: 0.12
Nodes (17): _first_table_amount(), _html_table_priority(), _normalize_text(), _normalized_label(), 실적 보도자료 HTML에서 실제 매출과 가이던스 문장을 추출한다., HTML에서 읽은 공백과 글머리표를 비교 가능한 한 줄로 정리한다., 표 행의 각주·기호를 빼고 허용한 매출 레이블과 비교한다., 표 안이나 가까운 제목의 표시 단위를 달러 원단위 배수로 바꾼다. (+9 more)

### Community 33 - "refresh_earnings_season.py"
Cohesion: 0.08
Nodes (21): _as_date(), _env_int(), evaluate_earnings_season(), lag_days(), lead_days(), date, 발표 예정일을 기준으로 관심종목 fast path 실행 여부를 판정한다., 실적 예정일 전에 fast path를 시작할 일수. (+13 more)

### Community 34 - "_ensure_filings"
Cohesion: 0.29
Nodes (10): _ensure_filings(), _filing_state_row(), mark_empty_filing_targets(), mark_processed_filing_targets(), mark_superseded_filing_targets(), 공시 사실을 processing 상태보다 먼저 canonical filings에 기록한다., 허용된 표준 fact가 없는 공시를 정상 완료(empty)로 기록한다., 현재 CIK의 동일 기간이 대신하는 전임 CIK 공시를 terminal로 기록한다. (+2 more)

### Community 35 - "supabase_repository.py"
Cohesion: 0.05
Nodes (44): Return the v1 security identity for each current ticker., select_security_ids_by_ticker(), normalize_ticker(), universe의 Yahoo식 표기(BRK-B)에 맞춘다., _feature_snapshot(), _finite(), _guru_candidate_signals(), _iso() (+36 more)

### Community 36 - "90_reporting.sql"
Cohesion: 0.09
Nodes (33): reporting.company_financials_latest, reporting.earnings_schedule, reporting.earnings_surprise, reporting.institutional_filings, reporting.institutional_positions, reporting.macro_latest, reporting.macro_measures, reporting.macro_observation_history (+25 more)

### Community 37 - "continuous_retrain.py"
Cohesion: 0.07
Nodes (38): default_spec(), _load_champion_score(), main(), _parse_args(), Any, datetime, Namespace, Path (+30 more)

### Community 38 - "ProductionInvestmentAdapters"
Cohesion: 0.07
Nodes (36): ApprovalRepositoryPort, _clock(), DecisionRepositoryPort, _metadata_id(), _positive_float(), _positive_int(), ProductionInvestmentAdapters, Any (+28 more)

### Community 39 - "emergency.py"
Cohesion: 0.13
Nodes (23): main(), 투자 하네스 비상 긴급 정지(Emergency Stop) 및 재활성화(Re-arm) CLI 도구. 사용 예시: # 1. 상태 및 Durable…, _safe_print(), check_runtime_status(), emergency_stop(), get_lockdown_path(), is_execution_locked_down(), _is_process_alive() (+15 more)

### Community 40 - "_fetch"
Cohesion: 0.10
Nodes (16): AnalystSnapshot, ConsensusSnapshots, _earnings_estimate(), _FakeTicker, _fetch(), FiscalPeriodNormalization, _history(), DataFrame (+8 more)

### Community 41 - "build_events.py"
Cohesion: 0.10
Nodes (37): build_events(), EventRepository, main(), _normalized(), _parse_args(), Any, Namespace, Protocol (+29 more)

### Community 42 - "HarnessScheduler"
Cohesion: 0.05
Nodes (33): 운영 하네스 job·stage의 실행 계약., KillSwitches, 알 수 없는 값은 안전하게 ON으로 해석한다., _switch(), 한 장비에서 하네스 프로세스가 하나만 실행되게 하는 OS file lock., HarnessScheduler, _idempotency_key(), datetime (+25 more)

### Community 43 - "FiscalPeriod"
Cohesion: 0.06
Nodes (29): derive_fourth_quarter(), FiscalPeriod, parse_period(), period_end_is_plausible(), PeriodError, date, ValueError, 회계기간의 규칙. ## 달력 분기가 아니다 회사마다 회계연도 끝이 다르다(애플은 9월, 마이크로소프트는 6월). `period_end`가… (+21 more)

### Community 44 - "AccountSnapshot"
Cohesion: 0.05
Nodes (37): AccountSnapshot, 현금과 보유 평가액을 합친 스냅샷 기준 순자산., CASH를 포함해 합이 1인 현재 포트폴리오 비중., 계좌 조회 결과에서 내용 기반 ID를 만드는 불변 snapshot., PortfolioConstructor, Any, datetime, SignalBook과 실제 계좌 snapshot을 전체 목표 비중으로 결합한다. (+29 more)

### Community 45 - "DiscordApprovalClient"
Cohesion: 0.07
Nodes (26): DiscordApprovalClient, DiscordMessageRef, _interaction_payload(), InteractionHandler, Any, Protocol, 투자 승인 카드 전용 Discord REST/Gateway 경계., 원 승인 카드 한 장의 상태 문구만 멱등 PATCH한다. (+18 more)

### Community 46 - "Investment Agent Design System"
Cohesion: 0.22
Nodes (9): 12. 모션, 13. 접근성, 15. 아이콘과 일러스트, 17. 컴포넌트 상태 매트릭스, 19. 절대 하지 않는 것, 1. 한 문장 정의, 20. 설계 근거, 4. 토큰 구조 (+1 more)

### Community 47 - "MacroRepository"
Cohesion: 0.03
Nodes (68): SeriesValidator, SourceFetcher, Any, date, datetime, v1 macro 원천 결과를 revision-safe observation 원장에 적재한다., source별 결과를 독립 수집해 원천 수집 시각으로만 버전을 남긴다., refresh_macro() (+60 more)

### Community 48 - "releases/db.py"
Cohesion: 0.14
Nodes (47): ingest_raw(), 미래 발표의 예상값을 매번 확인하고, 달라진 상태만 DB가 원자적으로 저장한다., 원자료를 한 번만 저장한다. 최초 관측 판정은 계산 결과의 전후 차이로 얻는다., 현재 일정의 제한된 발표창만 조회하며 아직 계산 가능한 값이 없으면 기다린다., snapshot_forecasts(), watch_once(), event_key(), Any (+39 more)

### Community 49 - "DailyBar"
Cohesion: 0.06
Nodes (30): adjust(), dividend_factors(), _previous_close(), date, 분할·배당으로 과거 가격을 조정한다. ## 왜 저장하지 않고 계산하는가 조정가를 저장하면 **분할이 하나 새로 들어올 때마다 과거 행 전체를…, 거래일마다 곱할 분할 계수. 분할 당일(`action_date`)의 가격은 이미 분할 후 가격이다. 따라서 조정 대상은 **그 전날까지**다.…, 거래일마다 곱할 배당 계수(총수익 기준). 배당락일 전날 종가를 기준으로 `1 - 배당/종가`를 누적한다. 종가를 모르면 그 배당은 건너뛴다…, 배당락일 **직전 거래일**의 종가. 휴장을 건너뛰어야 하므로 목록을 거슬러 찾는다. (+22 more)

### Community 50 - "SelectOnlyGatewayTests"
Cohesion: 0.05
Nodes (18): DashboardStaticBoundaryTests, _FakeBuilder, _FakeClient, _FakeFunction, _FakeSchema, OfflineBoundaryTests, Any, SimpleNamespace (+10 more)

### Community 51 - "ReportingQueries"
Cohesion: 0.08
Nodes (10): 화면과 알림에 같은 DataResult를 반환한다. 실패를 빈 결과로 숨기지 않는다., ReportingQueries, Builder, Client, LocalRuntimeViewTest, 공통 조회 계약을 실제 페이지네이션과 오프라인 응답으로 검증한다., LOCAL_VIEWS는 Postgres가 아니라 실행 컴퓨터의 runtime.sqlite3가 소유한다 —…, LOCAL_VIEWS는 Postgres가 아니라 로컬 runtime.sqlite3가 소유한다 — 별도 real-SQLite 계약은… (+2 more)

### Community 52 - "postgres.py"
Cohesion: 0.02
Nodes (160): 영구 저장이 허용된 기업 전체 재무 wide 컬럼 집합. SEC fact는 변환 중에만 long 형태로 다루며, 이 목록에 없는 값은 표준화…, ColumnPolicy, _load_maps(), SEC us-gaap 태그를 프로젝트 표준 재무 컬럼으로 매핑한다. edgartools의 ``gaap_mappings.json``을 기본…, 중요 wide 컬럼의 허용 태그와 결정적 우선순위., CamelCase나 라벨 형태의 문자열을 snake_case로 바꾼다., 원시 태그 매핑, 표준 컬럼 매핑, 충돌 우선순위를 읽는다., _snake() (+152 more)

### Community 53 - "inspect_harness_state"
Cohesion: 0.04
Nodes (40): inspect_harness_state(), Any, datetime, 하네스 JSON을 변경하지 않고 PID·heartbeat·잡 건강 상태로 요약한다. 반환값은 ``available``,…, add_technical_indicators(), DataFrame, OHLC 프레임 복사본에 ``SMA20``, ``SMA60``, ``RSI14``를 추가한다. 종가는 ``Close`` 또는 ``close``…, _harness_health() (+32 more)

### Community 54 - "RunLifecycleTest"
Cohesion: 0.25
Nodes (3): 둘 다 있으면 나중에 읽는 사람이 어느 쪽을 믿을지 모른다., completed로 적으면 빠진 종목이 '신호 없음'으로 보인다., RunLifecycleTest

### Community 55 - "run_backtest"
Cohesion: 0.32
Nodes (6): 작은 호출 경계를 제공해 향후 entry·FinRL adapter가 엔진 타입에 결합되지 않게 한다., run_backtest(), BacktestEngineTest, market_bar(), request(), weight_point()

### Community 56 - "_ExecutionRepository"
Cohesion: 0.17
Nodes (13): _config(), _DecisionRepository, _ExecutionRepository, _existing(), _handoff(), _intent(), _planner(), _proposal() (+5 more)

### Community 57 - "TradingRepository"
Cohesion: 0.05
Nodes (21): Any, datetime, 승인 전 제안·거절 audit만 기록한다. 승인은 수동 게이트를 거친다., 현재 단계를 잠근 뒤 승인 audit만 추가한다., reporting read model에서 artifact의 현재 승인 단계를 읽는다., 이미 계산된 회차 상태를 v1 원장에 기록한다., 완전성 배치와 immutable 종목 신호를 함께 기록한다., 회차를 연다. 아직 끝나지 않았으므로 `finished_at`은 비운다. (+13 more)

### Community 58 - "candidate_ranker.py"
Cohesion: 0.09
Nodes (32): normalize_ticker(), 종목 심볼을 대문자 및 표준 dash 형태로 정규화한다., assemble_candidate_features(), CandidateFeatures, CandidateRank, _dense_percentiles(), _group_by_ticker(), _latest() (+24 more)

### Community 59 - "fundamentals/repository.py"
Cohesion: 0.10
Nodes (21): latest(), latest_known_at(), datetime, 여러 버전 중 "그 시점의 최신"을 고르는 규칙. ## 왜 고르는 일이 따로 있어야 하나 v1은 정정공시가 원본을 덮지 않는다. 같은…, 버전 하나를 고르는 데 필요한 것 전부., PostgREST는 timestamptz를 **문자열**로 준다. 그대로 두면 비교하는 순간에야 터지는데, 그 자리는 저장소에서 한참 떨어져…, 지금 기준 최신. 제출일이 늦은 것, 같으면 나중에 손에 넣은 것. 제출일이 같은 정정이 실제로 있다(같은 날 두 번 낸다). 그때…, `as_of` 시점에 우리가 알고 있던 것 중 최신. 이것이 v1이 정정 이력을 남기는 이유 그 자체다 — "2026년 3월에 우리가 알던… (+13 more)

### Community 60 - "yahoo_finance/consensus.py"
Cohesion: 0.14
Nodes (35): _add_quarter(), _analyst_snapshot(), _as_date(), fetch_consensus(), _frame(), _int(), _next_quarter_end(), _next_report() (+27 more)

### Community 61 - "ResearchDataset"
Cohesion: 0.06
Nodes (47): _default_splits(), main(), _parse_args(), Namespace, 선형 Ridge 정책을 Walk-Forward 교차 검증으로 학습하고 평가 아티팩트를 저장한다., 시점 경계로 60/20/20을 나누고 label이 겹치는 시점을 purge한다. 행 번호로 자르면 같은 날짜의 종목이 train과…, DatasetManifest, FeatureRecord (+39 more)

### Community 62 - "refresh_expectations"
Cohesion: 0.06
Nodes (24): changed_analyst_snapshots(), _is_changed(), 애널리스트 커버리지 관측값의 변경 여부를 판정한다., 직전 값과 다른 관측만 남긴다. 날짜는 자연키에 포함되지만 값 비교에서는 제외한다. 같은 값의 일별 행을 만들면 이력이 아니라 중복이므로,…, _snapshot_key(), collect_expectations(), CollectionBudgetExceeded, persist_expectations() (+16 more)

### Community 63 - "discord_admin/client.py"
Cohesion: 0.10
Nodes (40): add_member_role(), admin_user_id(), create_channel(), create_role(), create_webhook(), delete_channel(), edit_channel(), edit_everyone() (+32 more)

### Community 64 - "_flatten"
Cohesion: 0.14
Nodes (14): 자동매매 보고서 embed 색 토큰 — DESIGN-system.md의 화면 색 SSOT. embed는 왼쪽 세로 스트라이프 하나만 색을…, Discord embed는 색을 정수로 받는다. hex 문자열이 SSOT다., _to_int(), CandidateEmbedTest, _decision(), _flatten(), _order(), PortfolioEmbedTest (+6 more)

### Community 65 - "BuildEventsTest"
Cohesion: 0.27
Nodes (4): BuildEventsTest, _item(), DuckDB 원문 → 사건 → 학습용 feature snapshot 배선을 검증한다., _Repository

### Community 66 - "normalize_ticker"
Cohesion: 0.11
Nodes (14): normalize_ticker(), 밖에서 온 종목 표기를 우리 표기로. 읽을 수 없으면 `None`. 점을 하이픈으로 바꾸는 이유: 같은 종목을 SEC은 `BRK.B`,…, Any, ValueError, 더 깊이 볼 회사. 알림 여부는 여기서 정하지 않는다(notifications의 몫). 관심의 identity는 `cik`다.…, 출처가 하나라도 남아 있으면 계속 본다. 토스 보유가 빠져도 수동 등록이 남아 있으면 활성이다. 저장소도 같은 식으로 `is_active`를…, 저장소 행이 universe의 계약을 어겼다., UniverseDataError (+6 more)

### Community 67 - "app_pages/intelligence.py"
Cohesion: 0.07
Nodes (61): _engine_snapshot(), _engine_steps(), _list(), _mapping(), _merge_execution_payload(), _normalise_article(), _provider_payload(), Any (+53 more)

### Community 68 - "f"
Cohesion: 0.08
Nodes (40): profit_measure_label(), `profit_measure_kind`의 사람이 읽는 이름. 모르는 값은 일반 표기로 돌려준다., adjustment(), f(), 자본구조에서 EV 가산분을 계산하는 순수 함수. financial_versions 한 행을 받아 총부채·현금성자산·우선주·비지배지분을…, 숫자로 바꿀 수 없으면 None. Decimal·문자열·None이 섞여 들어온다., 단기차입·유동성 장기부채·장기부채·운용리스 부채 합계., EV 가산분 = 총부채 - 현금성자산 + 우선주 + 비지배지분. (+32 more)

### Community 69 - "calculations/__init__.py"
Cohesion: 0.03
Nodes (135): _manager_investment_style(), _manager_investment_summary(), _money_short(), Any, 13F 거장 레이더 — 매니저별 포트폴리오 구성을 먼저 보고, 고른 매니저만 파고든다. 13F는 **분기말 long equity 장부**다.…, 이 장부를 얼마나 믿을 수 있는지. 공시 표에만 있던 사실을 문장으로 올린다., 보고된 장부를 기기별로 읽기 좋은 비중 차트와 보유 목록으로 보여준다., 비교 가능한 두 분기의 포지션 변화를 보여준다. (+127 more)

### Community 70 - "toss/client.py"
Cohesion: 0.08
Nodes (37): access_token(), _authorized_headers(), fetch_accounts(), fetch_buying_power(), fetch_exchange_rate(), fetch_holdings(), fetch_open_orders(), fetch_prices() (+29 more)

### Community 71 - "UniverseRepository"
Cohesion: 0.03
Nodes (45): MembershipSnapshot, 그날 지수에 무엇이 있었는가. 이것이 없으면 backtest가 생존 편향에 걸린다 — 지금 살아남은 종목만 과거에 넣게 되기 때문이다. 그래서…, configure(), Any, date, 다른 스키마에서 받은 identity를 사람이 읽는 현재 ticker로 되돌린다., CUSIP·과거 ticker 같은 외부 식별자를 security_id로 옮긴다. `on_date`를 주면 그 시점에 유효했던 매핑만 본다.…, 그날(또는 그 이전 마지막) 구성 종목. 정확히 그날 스냅샷이 없을 수 있다(휴장·수집 실패). 그때 `None`을 주면 부르는 쪽이 "그날은… (+37 more)

### Community 72 - "BrokerAdapter"
Cohesion: 0.11
Nodes (15): BrokerAccount, BrokerAdapter, BrokerError, BrokerFill, BrokerOrder, BrokerOutcomeUnknown, BrokerPosition, BrokerQuote (+7 more)

### Community 73 - "_text"
Cohesion: 0.12
Nodes (11): _crons(), EconCalendarChainTest, ExpectationsWorkflowTest, NotifyChainTest, 무관한 CIK 하나로 ETL이 exit 1 하는 일이 잦다 — success로 잠그면 알림이 묻힌다., 워치가 볼 수 있는 새 관측치는 macro ETL이 넣어주는 것뿐이다. `macro.observation_versions`는…, 워크플로의 schedule cron 목록(주석 처리된 줄은 제외)., watcher가 같은 러너에서 이미 보내므로 여기에 workflow_run을 걸지 않는다. 걸면 watch가 도는 족족 러너가 한 번 더… (+3 more)

### Community 74 - "create_execution_intent.py"
Cohesion: 0.13
Nodes (14): ExecutionRepository, main(), Paper intent 생성 및 승인 요청 진입점., 부분 분석이나 실제 계좌 기준이 없는 목표 비중을 주문으로 승격하지 않는다., validate_paper_scope(), create_execution_intent(), main(), datetime (+6 more)

### Community 75 - "market_daily.py"
Cohesion: 0.10
Nodes (34): _backfill_prices(), main(), _parse_args(), Namespace, Market history backfill for prices, splits, and dividends., 시세 이력 백필 — 평시는 신규만, 수동 보수 시 현재 멤버 전체., _targets(), changed_rows() (+26 more)

### Community 76 - "tradingagents_adapter.py"
Cohesion: 0.05
Nodes (78): _date_ok(), _domain_payload(), fetch_fundamentals(), fetch_macro_indicators(), fetch_statement(), TradingAgents Fundamentals Analyst를 위한 SEC 재무제표·Gurus·거시지표 데이터 소스 어댑터., 재무제표, 밸류에이션, 세그먼트, 13F 기관 대가 지분을 시점 일치 번들에서 읽는다., 손익계산서/대차대조표/현금흐름표를 시점 일치 번들에서 읽는다. (+70 more)

### Community 77 - "FakeRepository"
Cohesion: 0.10
Nodes (17): OrderAttemptReservation, 예약 결과. **이미 있었는지**가 여기서 유일하게 중요한 정보다., 새로 예약한 것만 통과시킨다. 기존 예약을 재전송 허가로 오인하면 같은 주문이 두 번 나간다. 이미 있으면 보낼 것이 아니라 **결과를…, S&P 500 미국주식 sleeve의 읽기 전용 계좌 스냅샷., TossManualSnapshot, approval(), FakeApi, FakeRepository (+9 more)

### Community 78 - "features/db.py"
Cohesion: 0.13
Nodes (25): changed_indicators(), delete_before(), earliest_market_change_since(), existing_indicators_since(), features_for_ticker(), features_since(), _latest_date(), latest_indicator_date() (+17 more)

### Community 79 - "reported_observations.py"
Cohesion: 0.06
Nodes (61): non_liability_claims(), Any, 자본 범위를 구분해 회계항등식의 비부채 청구권을 계산한다., 선택된 common_equity 태그의 포함 범위를 반환한다., 총자산에서 총부채를 제외한 청구권 합계를 계산한다., source_scope(), _clone(), _credible_total_equity() (+53 more)

### Community 80 - "worker.py"
Cohesion: 0.04
Nodes (35): ApprovalStatusClient, ApprovalStatusPublishSummary, ApprovalStatusRepository, publish_reconciliation_statuses(), Protocol, 재조정 결과를 원래 Discord 승인 카드에만 best-effort로 되돌린다., 허용한 broker 축약 상태만 사람용 문구로 바꾼다., 원장 변경 뒤 exact approval/message에만 PATCH하며 실패를 전파하지 않는다. 승인봇 설정이 아직 없으면 조용히… (+27 more)

### Community 81 - "econ_calendar.py"
Cohesion: 0.10
Nodes (39): dialog, _as_date(), _calendar_query_window(), _country_emoji(), _event_card(), _expected_number(), _korean_time(), _number() (+31 more)

### Community 83 - "Database"
Cohesion: 0.03
Nodes (112): load_config(), Path, 설정을 한 번 읽는다. **진입점에서만** 부른다. `use_dotenv=False`는 테스트용이다 — 로컬 `.env`가 테스트 결과를…, all_financial_filings(), cutoff 이후의 10-K/10-Q 전부를 반환한다. `financial_filings`는 submissions의…, main(), main(), configure() (+104 more)

### Community 84 - "home.py"
Cohesion: 0.21
Nodes (19): _allocation_text(), _close_prices(), _econ_table(), _expected_value(), _market_snapshot(), _market_value(), _mode_text(), _page_link() (+11 more)

### Community 85 - "SupabaseRepository"
Cohesion: 0.06
Nodes (18): date, 현재 tracked를 과거에 대입하지 않는 MembershipTimeline 입력 행이다., artifact에 연결된 local Research 평가를 안전 증명 컬럼까지 포함해 조회한다., 평가 원장 전체를 보수적인 승격 요약으로 집계한다., 평가 재검증 뒤 현재 단계를 잠그고 승인 audit만 기록한다., 사후 평가용 경로. PIT 조회가 아니다., LLM에는 노출하지 않는 제한된 읽기 도구와 판단 저장소., v1 trading 원장의 domain owner를 지연 생성한다. (+10 more)

### Community 86 - "canonical_json"
Cohesion: 0.07
Nodes (24): 실시간 quote를 보관하는 단일 프로세스 RAM Hot State., canonical_json(), content_hash(), Any, JSON 직렬화·해싱·URL 정규화. ## 왜 표준 json으로 부족한가 `json.dumps`는 `Decimal`과 `date`를 못…, 같은 내용이면 항상 같은 문자열. 해시와 중복 판정의 기준이다., 내용 지문(sha256 hex). 근거 번들이 바뀌었는지 판정하는 유일한 기준., build_training_sample() (+16 more)

### Community 87 - "storage_paths.py"
Cohesion: 0.17
Nodes (21): parquet_root(), Path, Intelligence의 DuckDB catalog와 Parquet archive 위치. 표 이름을 문자열 리터럴로 흩뿌리면 이름을 바꿀 때…, 본문 Parquet 루트. 기본 production 경로는 명시적으로 고정한다. 테스트나 별도 profile에서 DuckDB 경로를 주면 그…, _configured_path(), evidence_cache_path(), intelligence_database_path(), intelligence_parquet_root() (+13 more)

### Community 88 - "export_dataset"
Cohesion: 0.16
Nodes (10): export_dataset(), Any, Path, 원장을 읽어 label이 확정된 행만 학습 dataset으로 결합한다., _snapshot(), ExportDatasetTest, _features(), datetime (+2 more)

### Community 89 - ".from_row"
Cohesion: 0.08
Nodes (24): first_print(), latest_known_at(), MacroDataError, Any, ValueError, `as_of` 시점에 알고 있던 것 중 가장 최근에 유효해진 값., 최초 발표에서 최종값까지의 변화량. 정정이 없었으면 `None`. 크게 고쳐지는 지표는 최초 발표를 그대로 믿으면 안 된다는 신호다., 최초 발표값. 정정 전 숫자라 서프라이즈 계산의 기준이 된다. (+16 more)

### Community 90 - "application/etl.py"
Cohesion: 0.04
Nodes (76): AllGuruManagersFailedError, GuruConfigurationError, GuruEtlError, GuruProviderError, main(), _make_filing_error_sink(), _make_shadow_sink(), Any (+68 more)

### Community 91 - "WeightEnvironmentCore"
Cohesion: 0.08
Nodes (19): action_to_weights(), _project_to_constraints(), Any, ndarray, optimizer와 RiskGate의 현재 한도를 단일 기준으로 읽어온다., long-only 비중을 종목 상한·종목 수·dust 규칙 안으로 밀어 넣는다. 상한을 넘은 몫은 아직 여유가 있는 종목에 비례 배분하고,…, 연속 action을 실행 가능한 long-only risky assets + CASH 비중으로 바꾼다., Gym과 분리된 결정적 상태 전이로 reward·비중 계약을 단위 테스트한다. (+11 more)

### Community 92 - "ShadowFillTest"
Cohesion: 0.27
Nodes (4): 매도 수수료·슬리피지는 매도 시점 금액에 붙으므로 많이 오를수록 더 낸다., 수익률이 흔들려도 비용은 왕복 요율 근처에 머문다 — 예산을 잡을 수 있다., 이게 gross label로 학습하면 안 되는 이유다., ShadowFillTest

### Community 93 - "institutional/test_service.py"
Cohesion: 0.39
Nodes (4): InstitutionalWriterTest, SimpleNamespace, v1 13F writer는 SEC 원문 행과 provenance를 함께 남긴다., _record()

### Community 94 - "CompanyFinancialRepository"
Cohesion: 0.06
Nodes (7): CompanyFinancialRepository, EarningsEventRepository, ExpectationsRepository, Any, date, Protocol, 시장 예상치·발표 일정·애널리스트 커버리지 저장소.

### Community 95 - "snapshots.py"
Cohesion: 0.13
Nodes (14): PositionSnapshot, PositionSnapshot, Any, 브로커 계좌의 변경 불가능한 포트폴리오 스냅샷 계약., 한 시점의 long-only 보유 수량과 USD 평가액., PortfolioConstructionPolicy, 모델이 변경할 수 없는 계좌 병합 규칙., AccountSnapshotTest (+6 more)

### Community 96 - "macro/format.py"
Cohesion: 0.06
Nodes (46): _build_ctx(), _pct(), Any, 레짐 리본 톤 칩용 화살표(플레인 글리프 — 이모지 변형 selector 미사용)., 개별 카드의 freshness를 집계한다., shoot(), _stale_info(), _tone_arrow() (+38 more)

### Community 97 - "size_portfolio"
Cohesion: 0.07
Nodes (20): Any, 승인된 비중을 **실제로 낼 수 있는 수량**으로 바꾼다. ## 비중과 수량 사이에는 현실이 있다 비중 3.7%는 주식 수로 딱 떨어지지…, 한 종목의 목표. 수량은 정수다 — 소수점 주식은 다루지 않는다., 실제로 내야 하는 주문 수량. 양수면 매수, 음수면 매도., 승인된 비중 → 주문 수량. `equity`는 계좌의 총 평가액이다. 현금이 아니라 총액인 이유: 비중은 총액 대비로 정의되고, 현금 대비로…, size_portfolio(), SizingResult, TargetPosition (+12 more)

### Community 98 - "normalize_segment_facts.py"
Cohesion: 0.12
Nodes (22): current_segment_facts(), 공시의 현재 보고기간 fact만 남기고 표준 회계기간 키를 부여한다., bulk_frames_to_filings_and_facts(), _dimension_path(), _dimensions_hash(), _int_to_date(), parse_dimensions(), _period_is_usable() (+14 more)

### Community 99 - "logging.py"
Cohesion: 0.02
Nodes (158): 프로세스로 시작한 CLI만 거치는 자리. 여기서 두 가지를 한다 — 로컬 `.env`를 읽는 것과, 루트 로거를 JSON 한 줄로 맞추는 것.…, 프로세스 진입점 준비. `__main__` 블록에서만 부른다., start_cli(), backfill_company_history(), prune_segment_history(), 정책 보존 기간보다 오래된 세그먼트 지표와 처리 상태를 제거한다., 기업 전체 재무를 accession_no 상태에 따라 선별해 백필한다. daily와 같은 companyfacts 경로를 쓴다. 경로가 갈려…, process_company_facts() (+150 more)

### Community 100 - "renderers/text.py"
Cohesion: 0.09
Nodes (36): build(), _number(), Any, 경제발표 결과를 survey/nowcast/own_model과 혼동 없이 Discord에 표시한다., build_filing(), build_quarterly(), _matrix(), _move_label() (+28 more)

### Community 101 - "provider.py"
Cohesion: 0.12
Nodes (21): NewsResult, Any, provider 호출 결과와 실패 원인을 data 계층 안에서 보존한다., 표시할 뉴스가 준비된 결과인지 반환한다., _canonical_url(), load_live_news(), _news_enabled(), _news_time() (+13 more)

### Community 102 - "OpenAICompatibleClient"
Cohesion: 0.09
Nodes (17): OpenAICompatibleClient, _parse_json_object(), Any, OpenAI 호환 로컬·원격 LLM 호출 어댑터., 모델이 실제로 받는 모양으로 요청 본문을 만든다., 이 모델에 temperature를 실어 보내도 되는가., provider가 돌려준 거절 사유를 짧게 뽑는다. 본문이 없으면 그렇다고 적는다., Ollama·LM Studio·OpenAI 호환 chat/completions 클라이언트. (+9 more)

### Community 103 - "RawPosition"
Cohesion: 0.18
Nodes (12): PositionKey, SEC Information Table 원본 행의 분석·감사 필수 필드., RawPosition, _aggregate(), compare(), errored(), KeyMismatch, 운영 파서와 edgartools shadow 파서의 13F 결과를 대조한다. 순수 비교 로직이라 외부 의존성이 없다. 입력은 양쪽 파서가 만든… (+4 more)

### Community 104 - "_snap"
Cohesion: 0.13
Nodes (8): CardTest, ConfidenceTest, CustomWindowTest, PriorFilingTest, 발표 예정 카드의 주 선택·불확실성 표기 회귀 테스트., 대시보드가 쓰는 임의 구간 조회가 Discord 주간 규칙을 바꾸지 않아야 한다., _snap(), WeekWindowTest

### Community 105 - "parse_xbrl.py"
Cohesion: 0.16
Nodes (32): _clean_number(), _concept_local(), _concept_qname(), _context_ref(), _deep_first_local(), _dimension_path(), _dimensions_hash(), _duration_days() (+24 more)

### Community 106 - "make_filing_record"
Cohesion: 0.13
Nodes (15): SEC Summary와 직접 파싱 결과가 완전히 일치하는지 검증한다., _validate_filing(), make_filing_record(), make_position(), Position, gurus 테스트용 FilingRecord/Position 팩토리. 외부 의존성 없음., edgar.py가 만들어내는 것과 동일한 형태의 검증 통과용 레코드., 13F 적재 전 검증 계약. SEC 요약(tableEntryTotal)이 세는 것은 informationTable의 **원시 행**이다.… (+7 more)

### Community 107 - "FeatureLayer"
Cohesion: 0.15
Nodes (15): FeatureLayer, impute_cross_section(), EvidenceBundle 외의 SQL 접근을 모델에서 금지하는 단일 feature 경계다., 같은 시점 종목들의 중앙값으로 결측을 채워 유한한 학습 행렬을 만든다. 원장(rl_feature_snapshots)에는 None을 그대로…, _bars(), _bundle(), FeatureColumnStabilityTest, ImputationTest (+7 more)

### Community 108 - "parser.py"
Cohesion: 0.19
Nodes (20): _amendment_type(), _boolean(), _child(), _child_text(), _date(), identifier_type(), _integer(), local_name() (+12 more)

### Community 109 - "TradingAgentsAdapterTest"
Cohesion: 0.09
Nodes (9): _bundle(), _Client, _ExternalClient, _ExternalRunner, LocalEvidencePersistenceTest, TradingAgents가 활성 Supabase bundle 밖으로 나가지 않는지 검증한다., 뉴스·소셜 원문이 기사 단위로 남아야 사건 추출이 그것을 읽을 수 있다., _Runner (+1 more)

### Community 110 - "test_roles.py"
Cohesion: 0.04
Nodes (21): EveryoneTest, GrantTest, OnboardingGateTest, PlanTest, PrivateCategoryTest, 역할·권한 선언이 조용히 잘못 열리거나 잘못 닫히지 않는지 지킨다. 권한은 틀려도 아무것도 실패하지 않는 종류다. 너무 열면 아무 일도 안…, 공개 채널을 실수로 숨기면 사람들은 그 채널이 있는 줄도 모른다. ai_investor는 보유종목·비중·체결가가 드러나므로 숨긴다., 이 설계의 전제. @everyone에 쓰기 권한이 붙으면 모든 카드 채널이 한 번에 열린다. (+13 more)

### Community 111 - "LocalEvidenceCache"
Cohesion: 0.11
Nodes (14): LocalEvidenceCache, LocalEvidenceCacheError, Any, datetime, Path, RuntimeError, 기사·게시물을 한 건씩 보관한다. 같은 URL·본문은 한 행으로 합쳐진다., 같은 요청을 다시 던졌을 때 재사용할 응답 원문을 TTL 동안 보관한다. (+6 more)

### Community 112 - "CLAUDE.md"
Cohesion: 0.11
Nodes (18): CI / GitHub Actions, `prompts/` — 코드가 아닙니다, 대시보드 ([src/investment_agent/dashboard/](src/investment_agent/dashboard/README.md)), 데이터·연구 owner (`src/investment_agent/`), 런타임 한계 (넘기면 조용히 틀립니다), 로컬 실행 스크립트, 아키텍처, 알림 ([src/investment_agent/notifications/](src/investment_agent/notifications/README.md)) (+10 more)

### Community 113 - "src/investment_agent/data/fundamentals/application/__init__.py"
Cohesion: 0.10
Nodes (16): build_earnings_estimates(), ConsensusBatch, date, 시장 원천의 상대 기간을 표준 회계기간 스냅샷으로 변환한다., 예상치 수집 한 번에서 만들어진 정규화 결과., 컨센서스와 발표 예정일을 같은 회계기간 키에 맞춘다., CompanyFilingSource, Any (+8 more)

### Community 114 - "evaluate"
Cohesion: 0.09
Nodes (15): CircuitBreakerPolicy, CircuitBreakerStatus, evaluate(), 시스템적 위험 상황에서 **신규 매수만** 자동으로 얼린다. ## 한도와 다른 층이다 `control`의 한도는 "이 주문 하나가 너무…, 신규 매수를 허용할지 판정한다. 순서가 의미를 갖는다. **우리 쪽 고장(연속 실패)을 먼저** 본다 — 주문이 계속 거부되는 상황에서 시장…, EvaluateTest, MissingDataTest, PolicyShapeTest (+7 more)

### Community 115 - "NotificationServiceTest"
Cohesion: 0.06
Nodes (10): FakeClient, FakeQuery, FakeRpc, Any, `sb.schema(s).rpc(name, params)`가 돌려주는 호출 흉내., `sb.schema(s).table(t)`가 돌려주는 빌더 흉내., _Result, NotificationServiceTest (+2 more)

### Community 116 - "BackfillWindow"
Cohesion: 0.10
Nodes (5): BackfillWindow, MarketRetentionTest, v1 market은 append-only 관측 원장이다 — 보존 정리는 아무것도 지우지 않는다. 배치 삭제가 돌아오면 그것이 8초…, 뒷정리 실패가 그날의 수집을 되돌리면 안 된다. 2026-08-27·28에 실제로 그랬다 — 가격을 전부 저장한 뒤 보존 정리가…, TechIndicatorsRetentionTest

### Community 117 - "설치, 자동 실행, 상태 확인과 장애 대응"
Cohesion: 0.10
Nodes (20): Discord-first 운영 기록, GitHub Actions, Maintenance hold, Research Actions 산출물과 로컬 운용, Secret 관리, Supabase 접근과 스키마, 기본 검증, 대시보드 실행 (+12 more)

### Community 118 - "select_tracked_tickers"
Cohesion: 0.12
Nodes (13): datetime, Protocol, AI 판단 대상을 현재 범용 수집 게이트 구성종목으로 제한한다., 한 실행에서 검증된 tracked 전체 집합과 실제 분석 대상을 함께 보존한다., 가장 최근 실행의 마지막 종목 다음부터 순환한다., 명시 종목도 현재 tracked universe 밖이면 fail-closed 한다., rotate_after_latest_cases(), select_tracked_tickers() (+5 more)

### Community 119 - "BacktestRequest"
Cohesion: 0.12
Nodes (20): BacktestRequest, BacktestResult, BacktestSafetyError, RuntimeError, 결측·거래중단·시간 오류 때문에 장부 생성을 중단해야 하는 경우다., 네트워크나 DB 없이 재생할 수 있는 완전한 백테스트 입력이다., 입력 hash와 모든 장부를 포함하는 재현 가능한 결과 artifact다., 목표 비중 시간열을 다음 거래일 시가에 재생하는 엔진. (+12 more)

### Community 120 - "detect_earnings_events.py"
Cohesion: 0.06
Nodes (37): detect_earnings_events(), detect_earnings_events_for_ticker(), determine_fiscal_period(), _parse_release_html(), Any, date, 8-K Item 2.02를 감지해 실적 속보를 만든다., 구조화 결과가 없는 보도자료 HTML에서 누락 필드를 보완한다. (+29 more)

### Community 121 - "RunContext"
Cohesion: 0.06
Nodes (29): case_key(), context_hash(), is_reproducible(), Any, datetime, 판단 하나를 가리키는 키와, 그 판단을 재현할 수 있는지 보는 지문. ## case_key는 계산되는 값이다 UUID를 쓰면 같은 판단을 두…, 마이크로초를 버린다. 재실행이 같은 키로 모이게 하는 유일한 이유다., 판단 하나의 키. 같은 질문이면 항상 같은 문자열. 사람이 읽을 수 있게 앞부분을 그대로 두고 뒤에 지문을 붙인다 — 로그에서 어느 종목·어느… (+21 more)

### Community 122 - "parse_external_payload"
Cohesion: 0.10
Nodes (21): _clean(), _parse_bracketed_messages(), parse_external_payload(), _parse_markdown_articles(), Any, provider 응답 blob을 기사·게시물 단위 ExternalContent로 쪼갠다. upstream TradingAgents는 항목…, `시각 · @작성자 · 태그` 머리말을 시각·작성자·감성으로 나눈다., 대괄호 머리말이 붙은 게시물을 항목별로 나눈다. 이어지는 줄은 앞 글에 붙인다. (+13 more)

### Community 123 - "services/investment/__init__.py"
Cohesion: 0.14
Nodes (26): _bounded_counts(), _bounded_text(), _bounded_texts(), _bounded_timestamps(), build_decision_case_read_model(), build_decision_cases_read_model(), _claim_summaries(), _mapping() (+18 more)

### Community 124 - "parse_shares.py"
Cohesion: 0.08
Nodes (30): fundamentals 수집·검증 명령 패키지., aggregate_company_share_history(), _clean_member_title(), _is_preferred_or_derivative(), _match_class_ticker(), _normalize_class_key(), parse_common_shares_from_companyfacts(), parse_common_shares_from_xbrl_document() (+22 more)

### Community 125 - "HarnessMode"
Cohesion: 0.09
Nodes (26): _format_terminal_output(), main(), 투자 하네스 보안 및 런타임 안전 감사 CLI. 사용 예시: python -m…, _safe_print(), HarnessMode, Enum, str, _check_discord_security() (+18 more)

### Community 126 - "infrastructure/sources/yfinance.py"
Cohesion: 0.16
Nodes (25): _extract_batch_close(), fetch_batch(), _fetch_info_ratio(), _fetch_many(), _fetch_one(), _market_today(), DataFrame, date (+17 more)

### Community 127 - "releases/schedule.py"
Cohesion: 0.10
Nodes (38): _as_datetime(), _failure(), Any, date, datetime, ISO UTC/aware datetime와 datetime 객체를 동일하게 비교한다., 미래 일정 → 예상값 변화 → 최근 원자료 변화만 확인한다., future schedule만 source별로 동기화한다. actual fetch와 섞지 않는다. (+30 more)

### Community 128 - "EarningsCalendarStore"
Cohesion: 0.19
Nodes (10): collect(), _default_store(), force_resend(), pending_state(), date, 이번 주 실적 캘린더 후보를 고르는 entry-side reader., main(), EarningsCalendarStore (+2 more)

### Community 129 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 130 - "factor_risk.py"
Cohesion: 0.16
Nodes (10): FactorExposure, FactorRiskEngine, PortfolioFactorExposure, 다요인(Multi-Factor) 리스크 모델 및 포트폴리오 팩터 익스포저 엔진. 포트폴리오 내 개별 자산의 5대 스타일 팩터(Momentum,…, 개별 자산의 5대 스타일 팩터 로딩 (z-score 정규화 기준, 통상 -3.0 ~ +3.0)., 어떤 팩터도 허용 한계(기본 1.5 표준편차)를 넘지 않는 균형 상태인가., 포트폴리오 다요인 리스크 계산 및 제약 검사기., 자산 비중과 개별 팩터 로딩을 결합하여 포트폴리오 팩터 익스포저를 산출한다. (+2 more)

### Community 131 - "_snap"
Cohesion: 0.16
Nodes (7): NextQuarterTest, PickSnapshotTest, eps_trend 소급분은 수집 시점의 target을 달고 있어 과거 분기에 못 붙인다., 발표 뒤 갱신된 값을 섞으면 '그때의 기대'가 아니라 지금 기대가 된다., 발표 뒤 값은 '기대'가 아니라 결과를 반영한 값이다., 회계기간 식별자는 날짜 근사치 대신 저장된 절대 기간 키로 맞춘다., _snap()

### Community 132 - "auth.py"
Cohesion: 0.13
Nodes (23): _access_token(), _fetch_chunk(), fetch_korean_names(), toss.py — 토스증권 Open API에서 미국 종목의 한글명을 보강한다. OAuth2 client_credentials로 access…, 공용 token을 반환하고 실패는 미시도 상태로 호출자에게 전달한다., 우리 표기(BRK-B) → 토스 표기(BRK.B)., 종목코드 목록 → (찾은 {ticker: 한글명}, 실제로 조회한 ticker 목록). 두 번째 값(attempted)은 '실제로 토스에…, _to_toss_symbol() (+15 more)

### Community 133 - "ics.py"
Cohesion: 0.32
Nodes (12): build(), _escape(), _event_lines(), fold(), group_events(), _moment(), Any, datetime (+4 more)

### Community 134 - "TossOrderApiTest"
Cohesion: 0.20
Nodes (8): command(), controls(), FakeResponse, permit(), remote_order(), risk_state(), TossOrderApiTest, TossOrderCommandTest

### Community 135 - "backtest/contracts.py"
Cohesion: 0.11
Nodes (23): CashEvent, CorporateActionApplication, _date(), FillEvent, _finite(), MarketBar, NavPoint, OrderEvent (+15 more)

### Community 136 - "calendar.py"
Cohesion: 0.11
Nodes (22): completed_bar_cutoff(), market_today(), overlap_window(), date, datetime, 미국 시장의 시간 규칙. ## 왜 platform이 아니라 여기인가 "장이 언제 끝나는가"는 시장 도메인 지식이다.…, 시장이 보는 오늘 날짜. UTC 자정 근처에서 한국 시각과 뉴욕 날짜가 하루 어긋나므로, 날짜가 필요한 자리에서는 반드시 이것을 쓴다., 확정된 일봉의 **상한 날짜**. 이 날짜까지만 적재한다. (+14 more)

### Community 137 - "FilingRef"
Cohesion: 0.08
Nodes (14): FilingRef, 원천 수집기가 넘기는 SEC 공시 참조. ``Filing``은 v1 저장 계약이고, 이 타입은 아직 원문을 읽기 전의 최소 식별자다. 둘을…, canonical `filings` 행. 자식 행의 FK 부모라 먼저 있어야 한다. `Filing.as_row()`와 같은 모양이지만…, BackfillScopeTest, BulkFilingContractTest, _CompanyRepository, _CompanySource, FilingSchemaContractTest (+6 more)

### Community 138 - "fit_baseline"
Cohesion: 0.07
Nodes (32): BaselineEvaluation, _dataset_hash(), _evaluate(), ExpectedReturnModel, fit_baseline(), ModelArtifact, _NaiveModel, _period() (+24 more)

### Community 139 - "fsds.py"
Cohesion: 0.13
Nodes (30): BulkFrames, discover_batches(), ensure_data(), _ensure_segment_data(), _expected_quarters(), iter_batches(), load_batch(), _missing_quarters() (+22 more)

### Community 140 - "alfred.py"
Cohesion: 0.19
Nodes (20): AlfredDataError, fetch_batch(), fetch_first_prints(), fetch_revisions(), _observations(), _observations_window(), _parse(), _parse_revisions() (+12 more)

### Community 141 - "process_filing.py"
Cohesion: 0.09
Nodes (39): derive_segment_rows(), persist_segment_filings(), 공시 한 건의 기업 전체·세그먼트 결과를 처리한다., 저장된 연도 지표와 이번 YTD 관측값으로 discrete 분기를 계산한다., direct·derived 지표가 모두 성공한 뒤 공시를 완료 상태로 전환한다., build_segment_metrics(), Any, 차원이 있는 공시 fact에서 세그먼트 지표를 만든다. (+31 more)

### Community 142 - "earnings_report/embeds.py"
Cohesion: 0.13
Nodes (23): _axis_embed(), build_segments(), _f(), _footnote(), _join(), _lines(), _period_text(), _profit_field() (+15 more)

### Community 143 - "strategies.py"
Cohesion: 0.16
Nodes (24): _adm(), cum_ret(), defensive(), _dmsr(), _gem(), _gtaa5(), _haa_balanced(), _haa_simple() (+16 more)

### Community 144 - "LocalTradingDatabase"
Cohesion: 0.10
Nodes (5): LocalTradingDatabase, _name(), _Query, TradingRepository의 쿼리 계약을 로컬 SQLite 관계형 원장에 연결한다. 금융 데이터용 Database와 같은 작은 주입…, 관계형 판단 원장의 원자 쓰기와 페이지 제한 없는 로컬 조회.

### Community 145 - "DossierBuilder"
Cohesion: 0.10
Nodes (21): DossierBuilder, bundle 하나와 선택적 밸류에이션 관측값으로 서류철을 만든다., _format_number(), Any, 서류철을 LLM 프롬프트용 Markdown으로 줄인다. 원본 서류철은 그대로 보존하고, 여기서만 분량 예산을 적용한다. 예산을 넘으면 잘라내되…, 구조화 호출용. 본문과 근거 ID를 분리해 모델이 인용을 지어내지 못하게 한다., 근거 ID를 함께 적은 사람이 읽을 수 있는 서류철을 만든다., _render_mapping() (+13 more)

### Community 146 - "_wf"
Cohesion: 0.13
Nodes (14): EvaluateTest, 일일 점검 요약 — 무엇을 문제로 셀지가 이 카드의 전부다., 합이 총수와 맞아야 카드가 무엇을 안 보고 있는지 드러난다., 링크가 없으면 원인을 보려고 GitHub에서 그 실행을 손으로 찾아야 한다., 타임아웃은 conclusion이 cancelled로 찍힌다 — 이걸 놓쳐서 알림이 안 갔었다. 실패와 색은 나누되(원인도 대응도 다르다)…, 인프라가 끊은 것과 코드가 깨진 것을 같은 줄에 두면 매일 훑고 넘기게 된다., 아침에 깨졌다가 고쳐 다시 돌린 것을 지금도 깨진 것과 같이 읽으면 안 된다., 마지막 실행이 실패로 끝난 것은 계속 빨강이어야 한다. (+6 more)

### Community 147 - "README.md"
Cohesion: 0.14
Nodes (5): Code of Conduct, Contributing, 환경변수 레퍼런스, Open-source readiness, Security Policy

### Community 148 - "earnings/schedule.py"
Cohesion: 0.15
Nodes (22): date, 선택한 지평을 실제 날짜 구간으로 바꾼다. 반환값은 ``(시작일, 종료일, 기간별 분리 여부)``다. 모르는 라벨은 예외 대신 기본 창으로…, schedule_window(), as_date(), build_rows(), build_rows_in_window(), iso_week(), _latest_by_ticker() (+14 more)

### Community 149 - "control_center.py"
Cohesion: 0.10
Nodes (14): range, control_command(), ControlCenter, dashboard_command(), dashboard_url(), Any, Path, ATLAS 로컬 제어센터. 대시보드는 관측 전용으로 유지하고, 하네스 시작·정지처럼 로컬 프로세스를 변경하는 작업만 이 창에서 명시적으로… (+6 more)

### Community 150 - "json_value"
Cohesion: 0.14
Nodes (4): json_value(), JSON에 실을 수 있는 모양으로 바꾼다. 손실이 생기는 변환은 하지 않는다., Any, Any

### Community 151 - "ExpectationRetentionTest"
Cohesion: 0.08
Nodes (12): ExpectationRetentionTest, _function_body(), 스냅샷 정리 함수가 "계속 읽히는 한 건"을 실제로 지키는지 선언에서 확인한다. ## 왜 텍스트로 보는가 이 정리는 DELETE라서 틀리면…, 나이로만 자르면 아직 발표 안 한 분기의 드리프트가 먼저 사라진다., 서프라이즈가 집는 바로 그 행이 keeper여야 한다., 원천이 둘이면 한쪽이 다른 쪽을 밀어낸다., 최근 구간을 통째로 들고 있어야 그 시점 판단을 재현할 수 있다., 0이면 오늘 것까지 지운다 — 기본값 실수를 조용히 통과시키지 않는다. (+4 more)

### Community 152 - "ExecutionSafetyError"
Cohesion: 0.04
Nodes (76): build_approval_card(), button_components(), Any, 토스 비실행 주문표를 Discord 건별 승인 카드로 바꾼다., 자유문장 대신 서명된 승인/거절 버튼 두 개만 만든다., Discord message create API에 바로 전달할 안전한 payload를 만든다., _ticket_lines(), ApprovalInteraction (+68 more)

### Community 153 - "저장 계층 구조·스키마 축소 설계"
Cohesion: 0.10
Nodes (19): 1. 목표, 2.1 코드 디렉터리 평탄화, 2. 최종 디렉터리, 3.1 Universe, 3.2 Market, 3.3 Fundamentals, 3.4 Macro, 3.5 Institutional (+11 more)

### Community 154 - "collection.py"
Cohesion: 0.05
Nodes (55): SEC·S&P500·Toss 수집 흐름을 조율한다., _membership_hash(), Any, date, SEC·Nasdaq Trader·S&P 500 원천을 v1 universe 계약으로 적재한다., 현재 상장 master와 S&P 500 기준정보를 원천에서 다시 만든다. 기존 DB를 읽어 보충하지 않는다. SEC 상세 metadata가…, refresh_universe(), UniverseRefreshResult (+47 more)

### Community 155 - "build"
Cohesion: 0.09
Nodes (32): _beat_color(), _big(), build(), _expectation_view(), _inconsistent_7d(), _period_text(), 실적 PNG 카드 — 템플릿 컨텍스트(ctx)와 Discord 캡션 조립. candidates.load_pending() 항목 +…, 항목(+extras) → (템플릿 ctx, Discord 캡션). (+24 more)

### Community 156 - "DispatchResult"
Cohesion: 0.12
Nodes (12): DispatchResult, Any, 상류 성공을 가리지 않고 알림 결과만 반환한다., 전송 없이 스냅샷만 보관한다. 실패를 명시적으로 반환하고 상류 예외로 올리지 않는다., 선점 실패면 전송하지 않는다. 보낸 뒤 기록 실패도 자동 재전송하지 않는다., dispatch_pending(), main(), Any (+4 more)

### Community 157 - "ForumDeliveryTest"
Cohesion: 0.09
Nodes (11): _config(), ForumDeliveryTest, ForumThreadsAreReusedTest, 분기마다 오는 공시 사이에 스레드는 보관 상태가 된다., 같은 실행에서 두 장을 보내면 두 번째는 방금 만든 스레드로 간다., 스레드가 하나 느는 것이 카드가 아예 안 나가는 것보다 낫다., 스레드 조회 스텁. 주입하지 않으면 단위 테스트가 실제 Discord로 나간다., 100자를 넘기면 Discord가 400으로 거절한다 — 카드가 통째로 안 나간다. (+3 more)

### Community 158 - "compute_rl_blend"
Cohesion: 0.10
Nodes (21): blend_enabled(), blend_proposals(), compute_rl_blend(), load_active_policy(), Any, Path, 운영 로그에 남길 요약. 원문 비중은 넣지 않는다 — 개수와 차이만 본다., 추론할 수 없을 때의 결과. 실패가 아니라 '아직 없음'이다. (+13 more)

### Community 159 - "_run"
Cohesion: 0.12
Nodes (14): AccountingTest, ChainTest, CountersTest, EmbedTest, 체인 감시·연속 일수·심각도 색 — 전부 '조용히 틀리는' 자리다., 카운터 하나가 실패했다고 점검이 사라지면 점검이 없는 것보다 나쁘다., cron이 없는 워크플로는 상류 성공 말고는 '돌았어야 함'을 알 길이 없다., 상류가 방금 끝났으면 하류는 아직 큐에 있을 수 있다. (+6 more)

### Community 160 - "_modules"
Cohesion: 0.08
Nodes (23): DashboardReportingBoundaryTest, DataBoundaryTest, _imported_names(), LayerDirectionTest, LiveFlagTest, _modules(), PackageImportTest, PlatformBoundaryTest (+15 more)

### Community 161 - "archive_daily_rows"
Cohesion: 0.25
Nodes (13): archive_daily_rows(), archive_root(), _frame(), MarketArchiveError, Any, DataFrame, Path, RuntimeError (+5 more)

### Community 162 - "expectations_exit_code"
Cohesion: 0.17
Nodes (8): expectations_exit_code(), 부분 성공은 성공, 붕괴한 실행만 실패로 돌린다. `failures`는 로그·판단 근거로만 받는다 — 게이트는 적재량이 정한다., ExpectationsExitCodeTest, 부분 성공을 실패로 올리면 알림이 매일 울리고 진짜 고장을 못 가린다. 실측 2026-09-04: Yahoo 레이트리밋으로 503종목 중…, 레이트리밋은 상시 조건이다 — 대부분 적재됐으면 성공이다., 행이 하나도 안 들어갔는데 성공이라고 하면 조용히 비어 간다., 행이 거의 안 들어갔으면 실패 수와 무관하게 붕괴한 실행이다., 실패는 (종목 × 단계) 단위라 종목 수와 단위가 다르다 — 게이트는 적재량이 정한다.

### Community 163 - "normalize.py"
Cohesion: 0.17
Nodes (22): calculate_family(), calculate_measure(), calendar_months_before(), finite(), _lag_period(), MeasureValidationError, _percentage_change(), _previous_observation() (+14 more)

### Community 164 - "validated_weights"
Cohesion: 0.18
Nodes (7): Any, 비중을 검증하고 현금을 포함한 정렬 사본을 돌려준다. **현금을 포함한 합이 1이어야 한다.** 이것이 이 함수의 핵심이다 — 없으면 "10%…, validated_weights(), 10%만 적힌 의도가 통과하면 나머지 90%를 아무도 말하지 않은 채 계획이 결정한다., 0으로 바꾸면 데이터 오류가 매도 주문이 된다., float(True)는 1.0이라 플래그가 100% 비중이 된다., WeightContractTest

### Community 165 - "universe/persistence.py"
Cohesion: 0.09
Nodes (38): _missing_sec_get_json(), Any, 현재 S&P 집합을 비교하고 실제 변경 또는 월간 감사 때만 저장한다. `is_tracked`는 범용 gate이므로, 과거 멤버 전체를…, 추적 종목의 누락 한글명을 토스증권으로 보강한다. 토스 IP 허용목록에 등록된 로컬 환경에서만 별도 실행한다. 기존…, SEC 거래소 master를 동기화하고 새 CIK의 entity 이름만 seed한다., CIK별 SEC submissions metadata를 증분 보강한다., 수집 게이트를 현재 멤버 집합에 맞춘다. 고친 종목 수를 돌려준다., reconcile_membership() (+30 more)

### Community 166 - "_intent"
Cohesion: 0.18
Nodes (6): ExecutabilityTest, _intent(), 실행 의도가 받아들이는 모양. 여기서 막지 못한 것은 주문이 된다., 며칠 전 승인이 오늘 주문으로 나가면 안 된다., 부르는 쪽이 자기가 어느 경로인지 명시해야 한다., ShapeTest

### Community 167 - "FakeDatabase"
Cohesion: 0.03
Nodes (57): 13F 유스케이스 계층. 수집·적재·정리 흐름을 조립한다., InstitutionalRepository, Any, 추적 대상 manager 목록. manager_cik/name/fund_name/is_active의 SSOT는 코드…, 이미 원장에 있는 SEC accession. 신규 수집만 원천에 요청할 때 쓴다., MarketRepository, 주어진 종목 중 가격이 하나라도 있는 종목의 identity., ActiveManagerQueryTest (+49 more)

### Community 168 - "strategies/db.py"
Cohesion: 0.29
Nodes (12): allocation_strategy_ids(), delete_allocations_before(), latest_allocation_per_strategy(), mark_allocations_sent(), date, 전략 계산 결과를 Research 로컬 저장소에 기록하는 경계., _store(), upsert_allocation() (+4 more)

### Community 169 - "select_session_targets.py"
Cohesion: 0.16
Nodes (15): _as_date(), _as_datetime(), _is_date_only_anchor(), latest_schedule_by_ticker(), date, datetime, 지금 이 시각에 발표가 예정된 관심종목만 골라 낸다. 관심종목 50개를 매번 다 훑으면 SEC 호출이 낭비되고, 하루 한 번만 훑으면 장전…, 지금이 ET 기준 어느 세션 구간인지 — 로그와 워크플로 표시에 쓴다. (+7 more)

### Community 170 - "parse_datetime"
Cohesion: 0.07
Nodes (29): _nonnegative_number(), datetime, 계좌와 freshness가 맞지 않으면 전체 포트폴리오 생성을 막는다., build_tca_report(), _finite(), Any, 주문 결과의 arrival·spread·slippage·implementation shortfall 계산., 원시 가격·체결 결과에서 TCA를 한 번 계산한다. (+21 more)

### Community 171 - "filing_documents.py"
Cohesion: 0.15
Nodes (24): _archive_cik(), _available_daily_index_urls(), fetch_xbrl_document(), _filing_section(), filings_filed_since(), _filings_from_document(), _find_xbrl_document(), _get_bytes_optional() (+16 more)

### Community 172 - "main"
Cohesion: 0.13
Nodes (20): _ensure_community(), main(), Any, 포럼을 만들기 전에 길드가 Community인지 확인하고, 아니면 바꾼다., 카테고리와 채널을 매니페스트 선언 순서대로 다시 세운다. 이미 있던 채널은 자기 자리에 있지 않다 — 새로 만든 것만 position을…, _reorder(), Path, values의 키를 갱신하고, 없으면 끝에 덧붙인다. 바뀐 키 이름 목록을 돌려준다. (+12 more)

### Community 173 - "_Repository"
Cohesion: 0.13
Nodes (6): _filing(), FilingRowCapTest, 프롬프트에 실리는 원자료 양을 못박는다. Azure gpt-5-mini 배포 실측(2026-09-03): 50,000 토큰/분, 50…, as_of(2026-09-03)보다 과거인 분기 공시. 최신이 index 0이다., 자른 것을 숨기면 모델이 '이게 전부'라고 읽는다., _Repository

### Community 174 - "press_releases.py"
Cohesion: 0.11
Nodes (18): clean_html_to_markdown(), _document_score(), extract_text(), _item_value(), SEC 8-K archive에서 EX-99 보도자료를 고르고 텍스트를 정제한다., archive 목록 한 건이 실적 보도자료일 가능성을 점수화한다., archive 파일 목록에서 가장 가능성 높은 EX-99 문서를 고른다., 스크립트·스타일을 제거한 사람이 읽는 공시 본문을 반환한다. (+10 more)

### Community 175 - "app_pages/macro.py"
Cohesion: 0.14
Nodes (28): _delta_color(), _map_frame(), _metric_table(), Any, DataFrame, 매크로 시황 — 시장 레짐과 전 지표를 한 화면에서 읽고, 고른 지표만 파고든다. Discord `#오늘의-시장` 코어 카드와 **같은 지표…, 지표 하나를 카드로 그린다 — 값·변화·스파크라인·보조태그·기준일·등급., 카드가 보조태그로 줄여 쓰는 파생지표의 원값을 전부 편다. (+20 more)

### Community 176 - "_run"
Cohesion: 0.06
Nodes (28): _check(), evaluate(), date, 적재 결과의 불변조건을 점검해 조용히 썩는 실패를 드러낸다. 순수 판정만 여기 둔다. 조회는 repository가 하고, 이 함수는 숫자를…, 조회한 데이터 사실을 판정한다. 운영 오류는 DB에 기록하지 않는다., 조회 결과를 점검 항목 목록으로 바꾼다., verify_integrity(), BalanceIdentityBaseline (+20 more)

### Community 177 - "test_workflow_wiring.py"
Cohesion: 0.15
Nodes (18): _declared_flags(), _direct_module_imports(), EntryPointOptionTest, _imported_names(), _invocations(), _module_path(), AST, 워크플로 배선 회귀 테스트 — 어긋나도 조용히 실패하는 것들만 지킨다. 여기 걸린 규칙은 전부 "틀려도 CI가 초록이고, 알림만 안 온다"… (+10 more)

### Community 178 - "market_schedule.py"
Cohesion: 0.18
Nodes (13): get_us_market_phase(), is_us_market_holiday(), MarketPhaseInfo, date, datetime, Enum, str, 미국 정규장 시간표(뉴욕 시간 기준)를 인식하여 하네스 동작 국면과 주기를 계산한다. (+5 more)

### Community 179 - "MeasureCalculationTest"
Cohesion: 0.08
Nodes (5): MeasureCalculationTest, 30-family ECON schedule/measure source contract의 오프라인 회귀 테스트., ReferencePeriodTest, ScheduleTimezoneTest, SeedContractTest

### Community 180 - "TransactionCostModel"
Cohesion: 0.06
Nodes (41): build_training_samples(), main(), _parse_args(), Any, datetime, Namespace, 확정된 feature/label을 **비용 반영 학습 표본**으로 바꿔 원장에 쌓는다. 이 entry가 채점과 학습 사이의 다리다.…, label이 확정된 (종목, 시점)마다 비용 반영 학습 표본을 하나씩 만든다. (+33 more)

### Community 181 - "filings.py"
Cohesion: 0.06
Nodes (35): CompanyFactsSource, FactsNormalizer, _as_datetime(), base_form(), filing_row(), FilingError, is_amendment(), is_periodic() (+27 more)

### Community 182 - "install_investment_harness.py"
Cohesion: 0.16
Nodes (14): main(), _plans(), 로컬 운영 하네스의 OS 서비스 등록 계획을 만들고 선택적으로 적용한다., _require_apply_environment(), _absolute(), apply_install_plan(), macos_launchd_plan(), Any (+6 more)

### Community 183 - "price_risk_profile"
Cohesion: 0.07
Nodes (36): _annual_points(), AnnualPoint, _bars_oldest_first(), _cagr(), fundamental_trend(), _gap_profile(), _number(), _percentile() (+28 more)

### Community 184 - "_canonical_filing_focus"
Cohesion: 0.20
Nodes (7): _canonical_filing_focus(), _quarter_from_annual_distance(), 인접 10-K 기간말과의 거리로 10-Q의 분기 번호를 복원한다., SEC unit의 오염된 ``fy``/``fp`` 대신 filing 기간으로 회계키를 만든다. CompanyFacts는 일부 등록인에서 과거…, CanonicalFilingFocusTest, _filing(), SEC CompanyFacts의 오염된 fy/fp를 filing 기간으로 교정하는 계약.

### Community 185 - "build_labels.py"
Cohesion: 0.07
Nodes (27): Any, run_log_payload(), build_features(), main(), _parse_args(), datetime, Namespace, tracked universe의 PIT feature snapshot을 매일 ResearchStore에 적재한다. 이 command가 없으면… (+19 more)

### Community 186 - "IntelligenceRepositoryTest"
Cohesion: 0.14
Nodes (9): _article(), IntelligenceRepositoryTest, _post(), datetime, intelligence.duckdb 저장 경계의 계약., 다른 provider가 같은 기사를 줘도 한 행이어야 한다., 같은 배치 안에서 서로 충돌하는 경우 — 기존 행과의 충돌과 다른 경로다. `executemany`는 행 단위로 실행되므로 두 번째 레코드가…, 같은 배치 안에서 서로 충돌하는 경우 — 기존 행과의 충돌과 다른 경로다. `SocialPostRecord`는 `content_hash`가… (+1 more)

### Community 187 - "TossTokenManagerTest"
Cohesion: 0.14
Nodes (6): FakeResponse, 토스 OAuth 공용 token manager의 동시성·보안 경계를 검증한다., 모듈 이동이 worker 간 OAuth cache 공유 경로를 바꾸면 안 된다., token_response(), TossSharedClientIntegrationTest, TossTokenManagerTest

### Community 188 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 189 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 190 - "market/persistence.py"
Cohesion: 0.17
Nodes (27): merge_corporate_actions(), 분리 저장한 배당·분할 이벤트를 가격 행에 읽기 전용으로 결합한다., 가격 행의 grain을 바꾸지 않고 같은 거래일의 이벤트만 붙인다., close_history_as_of(), _db(), _events_as_tickers(), forward_closes_after(), _ids() (+19 more)

### Community 191 - "shadow_daily.py"
Cohesion: 0.05
Nodes (36): Claim, InvestmentDecision, _number(), Any, RoleAnalysis, _text_list(), 결정 계층이 공유하는 정책 식별자와 기본 horizon., LLMClient (+28 more)

### Community 192 - "TossAuthError"
Cohesion: 0.13
Nodes (14): Any, Path, RuntimeError, 운영 점검용 캐시 경로. 파일 내용은 외부로 노출하지 않는다., 유효한 공용 token을 반환하고 없을 때만 잠금 안에서 발급한다., 401을 낸 token이 여전히 최신일 때만 잠금 안에서 한 번 갱신한다., 인증 요청을 보내고 401이면 공용 갱신 후 정확히 한 번만 다시 보낸다., 비밀값을 로그에 넣지 않고 network·429·5xx만 제한적으로 재시도한다. (+6 more)

### Community 193 - "Path"
Cohesion: 0.31
Nodes (6): DashboardLauncherPreflightTest, Path, `.venv`에 의존성만 있고 이 저장소가 안 깔린 상태가 실제로 있었다. 서드파티만 세면 사전 점검이 "이상 없음"이라 말한 뒤 앱이…, 모듈 이름만 알려주면 무엇을 실행해야 하는지 알 수 없다., _runtime(), _touch()

### Community 194 - "_Query"
Cohesion: 0.11
Nodes (5): _Client, GatewayInChunkTest, Any, _Query, 대시보드 게이트웨이도 `in` 목록의 URL 한도를 지킨다. PostgREST는 `in` 값을 URL에 그대로 싣는다. 행 상한과 **다른…

### Community 195 - "GuildDirectory"
Cohesion: 0.20
Nodes (10): build_directory(), GuildChannel, GuildDirectory, _normalize(), Any, Discord는 채널 이름을 소문자로 정규화한다. 비교도 같은 기준으로 한다., API 응답을 이름 색인으로 접는다. 순수 함수라 네트워크 없이 시험할 수 있다., 이름 -> 채널. 같은 이름이 둘이면 어느 쪽인지 말할 수 없으므로 담지 않는다. (+2 more)

### Community 196 - "_row"
Cohesion: 0.09
Nodes (15): JudgeTest, ManifestDriftTest, 채널 도착 확인 — '워크플로 초록인데 카드 없음'을 잡는 유일한 장치다. 여기가 틀리면 조용히 틀린다: 거짓 경보를 내면 며칠 만에 아무도…, 포럼의 글은 메시지가 아니라 스레드라 셀 수 없다 — 없는 수를 지어내지 않는다., 워크플로가 전부 초록이어도 채널이 비었으면 '이상 없음'이라고 하면 안 된다., `env`(시크릿) 아니면 `name`(봇이 길드에서 찾음) 중 하나는 있어야 한다., 여기만 따로 두면 채널을 옮길 때 한쪽만 고치게 된다., 감시 목록에서 빠진 채널은 죽어도 아무도 모른다. 랩은 제외한다. (+7 more)

### Community 197 - "inputs.py"
Cohesion: 0.20
Nodes (20): build_valuation_inputs(), _decimal(), _evidence_id(), filing_available_at(), _missing(), price_scalar(), Any, datetime (+12 more)

### Community 198 - "main"
Cohesion: 0.13
Nodes (22): bot_user_id(), fetch_channels(), fetch_guild(), fetch_roles(), 길드의 모든 역할. @everyone은 ID가 길드 ID와 같다., 다른 봇 토큰의 사용자 ID를 그 토큰으로 묻는다. 카드 봇에게 역할을 붙이려면 그 봇의 사용자 ID가 필요하다. 관리형 역할에서 역추적할…, 길드 메타(이름·features). 포럼을 만들 수 있는지는 features의 COMMUNITY가 정한다., main() (+14 more)

### Community 199 - "capture_toss_account_snapshot"
Cohesion: 0.10
Nodes (18): _account_ref(), capture_and_store_risk_snapshot(), datetime, Protocol, 토스 USD sleeve의 일 손실 기준선을 private execution 원장에 기록한다., 브로커 조회만 수행한 뒤 계좌번호를 hash로 바꿔 private DB에 저장한다., RiskSnapshotRepository, StoredRiskSnapshot (+10 more)

### Community 200 - "Third-party data notice — `gaap_mappings.json`"
Cohesion: 0.25
Nodes (7): 5.36.0 -> 5.53.0에서 바뀐 것, MIT License, Third-party data notice — `gaap_mappings.json`, 무결성 확인, 업데이트와 검증 절차, 출처와 현재 스냅샷, 프로젝트에서 사용하는 방식

### Community 201 - "._at"
Cohesion: 0.17
Nodes (7): 시간 메타데이터가 없다고 발표를 놓치는 쪽이 더 나쁘다., 야후는 시각 미공지 발표에 15:00 ET를 넣는다. 그대로 믿으면 창이 어긋난다., 실측: AMAT는 과거 24회가 16:00인데 다음 예정만 15:00이었다., 확정 시각이 있으면 과거 습관이 달라도 그대로 믿는다., 과거 행에 섞인 자리표시는 최빈값 계산에서 빠진다., SessionTargetSelection, YahooPlaceholderTime

### Community 202 - "valuation_history"
Cohesion: 0.12
Nodes (18): _gauge(), _log(), _multiple(), 배수 축은 로그다 — 곱셈 척도이기도 하고, 이익이 0에 가까워지면 발산하기 때문. TSLA는 실제로 PER 5~95분위가…, PER 스파크라인 좌표 + 중앙선/축 라벨 (history.downsample_weekly 결과를 받음). top은 축 라벨이 앉는 자리다 —…, 값 → 트랙 위치(%). 양끝 2~98%로 클램프해 마커가 트랙 밖으로 안 나가게., 배수 표기 — 1000배가 넘으면 소수점을 버려야 칸에 들어간다., valuation_history.compute() 결과 → 역사 밸류에이션 표 행 + PER 스파크라인(색 기준 적용). 트랙은 백분위 축이… (+10 more)

### Community 204 - "valuation_history.py"
Cohesion: 0.15
Nodes (19): _asof(), compute(), daily_series(), downsample_weekly(), _f(), _positive_den_ratio(), Any, date (+11 more)

### Community 205 - "select_model_for_ticker"
Cohesion: 0.20
Nodes (10): apply_candidate(), Path, 오늘치 예산이 남아 있고 API 키가 설정된 첫 후보를 예약하고 돌려준다. 예약은 원자적이라 같은 순간에 여러 프로세스가 불러도 한 자리씩만…, 이 블록 동안만 `AI_INVESTOR_*` 환경변수를 후보 설정으로 덮는다.…, select_model_for_ticker(), ApplyCandidateTest, _candidate(), Path (+2 more)

### Community 206 - "fact_checker.py"
Cohesion: 0.13
Nodes (15): extract_claims(), _extract_evidence_metrics(), FactClaim, FactVerificationGate, FactVerificationResult, _harvest_payload(), Any, LLM 텍스트 내 수치 주장의 사실성 검증 및 환각(Hallucination) 차단 게이트. LLM의 분석 텍스트(reasoning)에 포함된… (+7 more)

### Community 207 - "eval_row"
Cohesion: 0.19
Nodes (14): _check_band(), _check_ma_cross(), _check_signed(), eval_row(), Any, 지표가 '경고할 수준'인지 판단(judgment)하는 곳 — 표시(format)는 format.py. 핵심은 eval_row(행): 그 지표가…, 값이 정해 둔 하한 이하이거나 상한 이상이면 '해당함(True)'., 하락폭·반등폭처럼 부호가 중요한 값을 판단한다 (크기만 비교하거나 범위로 비교). (+6 more)

### Community 208 - "PolicyConceptChoice"
Cohesion: 0.06
Nodes (12): CashFlowConceptChoice, ConflictRejection, PolicyConceptChoice, PolicyUnitGate, 컬럼 매핑 정책 — 단위 게이트와 동률 처리. 적재 결과 실측에서, 정책이 없는 컬럼은 동률일 때 태그 이름의 알파벳 순으로 값을 골랐고 그…, 정책이 없는 wide 컬럼도 기대 단위가 아니면 받지 않는다., 정책이 없어도 동률이면 임의로 고르지 않고 비워둔다., 현금흐름표 계열 — 총계 자리에 라인아이템이 들어오지 않는지. (+4 more)

### Community 209 - "Trading package"
Cohesion: 0.13
Nodes (15): 1. Universe와 후보 선정, 2. Context와 PIT 경계, 3. Feature layer, 4. TradingAgents, 5. SignalBook과 full portfolio, 6. Optimizer와 RiskGate, 7. Backtest, ML, RL, Qlib, 8. 평가와 승격 (+7 more)

### Community 210 - "test_schema_alignment.py"
Cohesion: 0.09
Nodes (25): assert_boundary(), assert_schema_contract(), NotificationGuardsTest, 알림의 도메인/DB/HTTP 경계와 선언 SQL 계약. 위반 주입도 함께 실행한다., outbox.py가 삽입하는 컬럼이 로컬 runtime SQLite 선언에 실제로 있는지 본다. outbox·deliveries는…, _column_tokens(), _columns_of_body(), _declared_schema() (+17 more)

### Community 211 - "test_provider_fail_closed.py"
Cohesion: 0.09
Nodes (8): ActiveSeedContractTest, ActualsFailClosedTest, MarketBreadthFailClosedTest, 활성 provider의 오프라인 fail-closed 계약 테스트., 운영 seed의 provider 설정이 코드 registry와 어긋나지 않는지 검사한다., 등록만 되고 seed가 부르지 않는 파서는 조용히 썩는다., WebFailClosedTest, YFinanceFailClosedTest

### Community 212 - "construct.py"
Cohesion: 0.05
Nodes (36): _args(), construct_portfolio(), main(), _market_risk_metrics(), _optimizer_covariance(), PortfolioConstructionOutcome, datetime, Namespace (+28 more)

### Community 213 - "test_strategy_guardrails.py"
Cohesion: 0.11
Nodes (9): DatetimeIndex, _complete_prices(), _monthly_index(), MonthlyEntrypointGuardrailTest, DataFrame, 월간 전략이 stale/부분 데이터를 정상 신호로 저장하지 않는지 검증한다., StrategyCalculationGuardrailTest, StrategyRetentionTest (+1 more)

### Community 214 - "_row"
Cohesion: 0.21
Nodes (5): FailOpenTest, fast path 시즌 게이트 — 특히 fail-open 규칙 회귀 테스트. 이 게이트가 잘못 "시즌 아님"을 내면 관심종목 공시 알림이…, 근거가 없으면 언제나 수집을 돌린다 — 놓치는 쪽이 훨씬 비싸다., _row(), SeasonWindowTest

### Community 215 - "classify_session"
Cohesion: 0.16
Nodes (17): classify_session(), collect_window(), is_placeholder_time(), is_within_collect_window(), datetime, time, 발표 예정 시각을 거래 세션 구간(BMO/AMC)으로 분류한다. 발표 '날짜'만으로는 언제 수집을 걸어야 하는지 알 수 없다. 같은 날짜라도…, 지금이 그 세션의 수집 창 안인지 판정한다. (+9 more)

### Community 216 - "ensure_aware"
Cohesion: 0.06
Nodes (51): FetchNews, FetchPosts, 세그먼트 수집 대상 관심종목. fast path가 훑을 범위를 정한다. 세그먼트는 별도 구독이 아니라 실적 카드의 한 단면이라 관심종목…, watchlist_tickers(), active_members(), collect_news(), _mention(), datetime (+43 more)

### Community 217 - "attribution.py"
Cohesion: 0.14
Nodes (13): ChallengerComparison, ChallengerPolicy, compare_challenger(), Any, Champion과 Challenger의 비교 결과를 수동 승격 입력으로 만든다., OOS·shadow·paper 증거를 평가하되 자동 운영 승격은 항상 금지한다., AttributionReport, build_attribution_report() (+5 more)

### Community 218 - "IntelligenceRepository"
Cohesion: 0.15
Nodes (12): 저장 시도의 결과. 중복은 실패가 아니라 정상이다., StoreResult, IntelligenceRepository, Any, date, datetime, Path, 이전 v1 DuckDB 본문 table을 한 번만 Parquet로 옮긴다. (+4 more)

### Community 219 - "QualityAssessmentTest"
Cohesion: 0.21
Nodes (3): QualityAssessmentTest, 회사 지표가 0이면 커버리지 비율을 낼 수 없다. None인 채로 임계값 비교에 들어가면 TypeError로 그 배치의 분기 파일 전체가…, _row()

### Community 220 - "layer.py"
Cohesion: 0.21
Nodes (16): _close_returns(), FeatureBundle, _fundamental(), _gurus(), _macro(), _number(), Any, datetime (+8 more)

### Community 221 - "_Query"
Cohesion: 0.08
Nodes (10): _feature(), _label(), _model_version(), _Query, signal_runs는 decision_runs를 FK로 참조한다 — 둘 다 최소한으로 심는다., _Response, RLRepositoryTest, _Schema (+2 more)

### Community 222 - "투자 판단, ML/RL, Backtest와 Portfolio Risk"
Cohesion: 0.09
Nodes (22): Dataset split과 재현성, DeterministicRiskGate, EvidenceBundle 도메인 구성, Feature Layer, LumiBot 외부 검증, Memory와 평가, ML baseline을 먼저 비교한다, Native Backtest (+14 more)

### Community 223 - "segment_concepts.py"
Cohesion: 0.13
Nodes (27): canonical_axis(), canonical_member(), canonical_segment_dimensions(), is_aggregate_member(), local_name(), 세그먼트 XBRL fact의 축과 멤버를 표준 차원으로 분류한다., 원본 차원을 버리지 않고 축·멤버 local name만 정규화한다., 원본 차원에서 대표 축을 고르고 분류 근거를 함께 반환한다. (+19 more)

### Community 224 - "analysis.py"
Cohesion: 0.10
Nodes (22): _authoritative_filings(), build_snapshot(), _change_rows(), _combined_positions(), _consensus_rows(), _coverage_status(), _filing_order(), _instrument() (+14 more)

### Community 225 - "OperationalRetentionTest"
Cohesion: 0.29
Nodes (3): OperationalRetentionTest, Fundamentals 품질 이슈 기록의 실패 전파 계약., canonical 정책은 우리가 처리한 시각(ingested_at)이 아니라 공시 자체의…

### Community 226 - "ManifestTest"
Cohesion: 0.06
Nodes (19): _existing(), ForumTagTest, ManifestTest, PlanTest, PositionTest, 매니페스트 ↔ 서버 대조 — 여기가 틀리면 채널이 중복 생성된다., 발송 코드가 아는 태그 이름과 서버에 만드는 태그가 어긋나면 태그 없이 나간다., 전략 태그 선언과 발송 routing 대응표가 일치해야 한다. (+11 more)

### Community 227 - "sources/toss_holdings.py"
Cohesion: 0.15
Nodes (22): access_token(), _authorized_headers(), fetch_accounts(), fetch_holdings(), _get_json(), Any, RuntimeError, 토스증권 Open API의 계좌·보유종목 조회 클라이언트. 관심종목 API는 아직 제공되지 않으므로 공식 ``accounts``와… (+14 more)

### Community 228 - "filing_xbrl.py"
Cohesion: 0.16
Nodes (20): is_excluded_tag(), policy_accepts(), 원시 us-gaap 태그에 대응하는 프로젝트 컬럼명을 반환한다., 투자 지표 의미가 불명확해 자동 적재하지 않을 SEC 태그인지 반환한다., 정책이 태그와 단위를 허용하는지 반환한다. 정책이 있는 컬럼은 화이트리스트 + 단위로 판정하고, 없는 wide 컬럼은 단위만 검사한다(금액…, to_column_key(), _duration_quarters(), filing_to_facts() (+12 more)

### Community 229 - "GuruRoutingTest"
Cohesion: 0.09
Nodes (14): BuildDirectoryTest, _config(), GuildDirectoryCacheTest, GuruRoutingTest, 채널을 이름으로 찾는 경로를 굳힌다. 거장 채널 ID를 시크릿으로 들고 있던 것을 봇 조회로 바꿨다. 그 조회가 틀리면 카드가 엉뚱한 채널로…, 이름이 없는 거장은 태그도 스레드 제목도 만들 수 없다., 태그 하나 때문에 그 분기 공시를 통째로 막지 않는다., 분기마다 새 스레드를 만들면 7명 × 4분기 = 연 28개가 되어 흐름이 끊긴다. (+6 more)

### Community 230 - "select_timed_targets"
Cohesion: 0.18
Nodes (10): 발표 예정 시각의 신뢰도에 맞춰 지금 SEC를 조회할 종목만 고른다. 정확 시각은 발표 직전부터 짧게, Yahoo 추정·자리표시는 넓게,…, select_timed_targets(), datetime, 발표 세션(BMO/AMC) 분류·타겟 선정과 발송 상호 배제. 하루 한 번 훑던 시절에는 장전 발표가 최대 15시간 늦게 잡혔고, 로컬…, 정확 시각·추정 시각·날짜만 아는 일정을 서로 다른 창으로 다룬다., 09:30 개장·16:00 마감이 경계다. 실측 JPM 06:00·NVDA 16:00., UTC 13:00은 ET 09:00이라 장전이다. 변환 없이 읽으면 장중으로 잘못 본다., SessionClassification (+2 more)

### Community 232 - "earnings_calendar/card.py"
Cohesion: 0.14
Nodes (14): build(), _day_label(), _eps_label(), date, metrics 결과를 템플릿 ctx와 Discord 캡션으로 바꾸는 표시 계층(순수 함수)., 추정 기간말 → '3분기' 같은 사람 말. 회계연도가 어긋나는 회사도 있어 달로 적는다., (템플릿 ctx, Discord 캡션)., _target_label() (+6 more)

### Community 233 - "ResearchStore"
Cohesion: 0.11
Nodes (22): _decode_allocation(), _decode_json(), default_database_path(), _feature_row(), _iso(), Any, date, datetime (+14 more)

### Community 234 - "breadth_200dma"
Cohesion: 0.40
Nodes (6): breadth_200dma(), fetch_batch(), date, Series, market 스키마 입력을 사용하는 MACRO series를 수집한다., S&P 500 현재 구성종목 중 200일선 위에 있는 비율을 반환한다. RPC가 실패해도 같은 가격 테이블을 REST로 계산한다. 두 경로…

### Community 235 - "watchlists/db.py"
Cohesion: 0.28
Nodes (17): add_member(), _cik(), configure(), _db(), list_members(), _member_row(), _member_rows(), normalize_ticker() (+9 more)

### Community 236 - "drop_implausible_share_rows"
Cohesion: 0.24
Nodes (9): drop_implausible_share_rows(), 원본의 자리표시자·자릿수 오류 행만 걸러 낸다. (남길 것, 버린 것). SEC 원본에는 두 종류의 이상값이 섞인다. * 자리표시자 —…, DropImplausibleSharesTest, SEC 원본의 이상값은 그 행만 버린다 — 그 기업 전체를 버리지 않는다. 발행주식수는 시가총액과 주당 지표의 분모다. 틀린 값을 담느니 없는…, 실측: benchmark=1,000 대 실제 1,071,666,977 — 진짜 값이 걸렸었다., 클래스 B가 A보다 훨씬 작은 것은 정상이다 — 섞어 재면 B가 이상값이 된다., 전부 자리표시자면 그 클래스에 대해 아는 것이 없다 — 지어내지 않는다., _row() (+1 more)

### Community 237 - "SubprocessModuleRunner"
Cohesion: 0.05
Nodes (25): Popen, CommandExecutionError, CommandResult, ModuleCommandRunner, Path, Protocol, RuntimeError, shell 없이 고정된 Python entry만 실행하는 하네스 command 경계. (+17 more)

### Community 238 - "promotion/gate.py"
Cohesion: 0.08
Nodes (21): _args(), main(), Namespace, aggregate_evaluations(), _covered_days(), EvaluationSummary, _incident_count(), ManualPromotionGate (+13 more)

### Community 239 - "release_catalog.py"
Cohesion: 0.11
Nodes (22): enrich_series(), measure_definitions(), Any, 고정 30개 지표의 수집기 설정. API 옵션·라이선스 설명은 사실표에 반복하지 않는다., 경제 발표 계산에 필요한 고정 measure 정의를 반환한다., 호출자가 고정 설정을 수정하지 못하도록 복사해 반환한다., DB의 표시·단위 master와 코드의 수집 계약을 실행 시점에 결합한다., 빈 DB의 경제지표 master를 재현할 수 있는 코드 catalog. (+14 more)

### Community 241 - "portfolio_shadow.py"
Cohesion: 0.06
Nodes (39): 내용 기반의 결정론적 식별자를 만든다., stable_id(), build_fusion_policy_read_model(), build_optimizer_policy_read_model(), build_ranker_policy_read_model(), build_risk_policy_read_model(), Any, 투자 정책을 화면용 bounded read model로 투영한다. (+31 more)

### Community 242 - "run_preflight"
Cohesion: 0.20
Nodes (13): build_preflight_report(), load_effective_environment(), PreflightReport, probe_venv_runtime(), Path, 파일을 바꾸지 않고 `.env`와 현재 환경의 유효값을 합친다., `.venv` 프로세스에서 버전과 import 가용성만 확인한다., 외부 호출 없이 파일·환경·런타임 점검 결과를 조립한다. (+5 more)

### Community 243 - "format_guidance_headline"
Cohesion: 0.08
Nodes (23): Pattern, build_flash_embed(), compute_surprise(), format_eps(), format_money(), Any, 8-K 실적 속보 Discord Embed 빌더., 실제값과 예상값으로부터 서프라이즈 비율(%)을 동적으로 계산한다. (+15 more)

### Community 244 - "edgartools_13f.py"
Cohesion: 0.26
Nodes (10): EdgartoolsUnavailable, parse_information_table(), _position_kind(), RuntimeError, _quantity_type(), edgartools 기반 13F information table shadow 파서. 운영…, edgartools가 설치되어 있지 않을 때 발생한다., edgartools로 information table을 파싱해 운영 모델(`RawPosition`)로 정규화한다.… (+2 more)

### Community 245 - "backtest/cli.py"
Cohesion: 0.13
Nodes (20): _atomic_json(), load_backtest_input(), main(), _mapping(), Any, Path, 완전한 오프라인 JSON 입력을 결정론적 백테스트 artifact로 변환한다., BacktestConfig (+12 more)

### Community 246 - "StrategyTests"
Cohesion: 0.12
Nodes (11): DataFrame, 전략 수익률·성과·시뮬레이션이 실제 가격에만 의존하는지 검증한다., 두 적용 구간과 각각 10% 수익인 가격 이력을 반환한다., 적용일별 실제 배분과 실제 가격으로 구간 수익률을 계산해야 한다., 가격이 없는 자산 구간은 0% 수익으로 대체하지 않고 제외해야 한다., yfinance 조회 계약인 종목별 OHLC DataFrame 매핑을 직접 사용할 수 있어야 한다., 수익률이 없으면 모든 성과 숫자는 None이고 누적 시계열은 비어야 한다., 유효 수익률에서는 누적수익과 최대낙폭을 메모리에서 계산해야 한다. (+3 more)

### Community 247 - "experiments"
Cohesion: 0.19
Nodes (9): dataset_runs, datasets, feature_sets, experiments, strategy_allocations, strategy_runs, models, backtests (+1 more)

### Community 248 - "validate_snapshot"
Cohesion: 0.23
Nodes (14): _duplicates(), _event(), Any, datetime, 자연키·시간축·변경 이력의 데이터 품질 규칙. DB 쓰기나 외부 호출은 하지 않는다., 여섯 사실표의 관계와 값만 검사하고 actual 복제표를 요구하지 않는다., _same(), _temporal_errors() (+6 more)

### Community 249 - "Investment Operations Harness — 로컬 상시 오케스트레이션 계층"
Cohesion: 0.18
Nodes (11): 1. 상시 하네스 아키텍처, 2. 운영 모드 비교 (`analysis_only` vs `approval_workflow`), 3. 세션 시간대 및 멱등적 장애 복구, 4. 다중 킬스위치 (Kill Switch) 매트릭스, 5. 실행 및 서비스 등록 가이드, 6. 운영 파라미터 환경변수, Investment Operations Harness — 로컬 상시 오케스트레이션 계층, OS 서비스(백그라운드 데몬) 등록 (+3 more)

### Community 250 - "20_decisions.sql"
Cohesion: 0.32
Nodes (13): attribution_reports, decision_evaluations, decision_evidence, decision_runs, model_promotions, model_versions, policies, portfolio_decisions (+5 more)

### Community 251 - "ActiveMembersTest"
Cohesion: 0.13
Nodes (8): ActiveMembersTest, AddRemoveMemberTest, _entity(), 보유는 종목 단위로 오지만 관심 기업은 하나여야 한다., 해제 이력조차 없는 회사까지 내면 전 종목이 목록에 들어온다., 관심 갱신이 SEC metadata 수집 결과를 덮어쓰면 회사 이름이 사라진다., _security(), SyncTossMembersTest

### Community 252 - "monitoring/discord.py"
Cohesion: 0.23
Nodes (14): activity(), collect(), _guild_directory(), _headers(), Any, datetime, Discord 채널이 실제로 카드를 받았는지 읽는다. **여기가 GitHub Actions로는 못 보는 것을 본다.** 잡이 성공해도 카드는…, 길드 채널 디렉터리. 없으면 `None`을 돌려주고 이유를 남긴다. (+6 more)

### Community 253 - "ArtifactRef"
Cohesion: 0.11
Nodes (9): ArtifactRef, ArtifactStore, Protocol, DB에 적는 것 전부. 내용은 여기 없다., `trading.decision_evidence`가 받는 모양., 저장 백엔드. 지금은 로컬 파일뿐이지만, 나중에 객체 저장소로 바꿔도 DB에 적힌 URI는 그대로여야 한다., LocalArtifactStoreTest, canonical JSON으로 저장하지 않으면 같은 근거가 두 지문을 갖는다. (+1 more)

### Community 254 - "sec13f.py"
Cohesion: 0.16
Nodes (15): FilingErrorSink, ShadowSink, FilingRecord, 13F 수집·저장 경계에서 사용하는 명시적 데이터 모델., RPC에 넘기는 원천 포지션 배열. DB 컬럼 계약과 1:1로 맞춘다., 검증을 마친 13F 공시와 합산 포지션 묶음., _information_table_xml(), iter_filings() (+7 more)

### Community 255 - "Execution package"
Cohesion: 0.17
Nodes (12): Durable safety, Execution package, Live Manual 흐름, Reconciliation, Toss 단일 실행 경로, 분석·검증, 주문 결과가 불명확할 때, 주요 CLI (+4 more)

### Community 256 - "_Repository"
Cohesion: 0.24
Nodes (3): ContinuousRetrainTest, 원장 세 갈래를 그대로 흉내내는 fake. 네트워크를 쓰지 않는다., _Repository

### Community 257 - "저장 계층 최소화 검토와 Markdown 개정안"
Cohesion: 0.15
Nodes (13): 13. Cloud/Local과 알림 상태: 제거 전에 배치를 확정, 14. Reporting과 Dashboard 계약, 17. 테스트와 전환 합격 기준, 18. 전환 전 남은 결정, 19. 권고 최종 모습, 1. 결론과 채택 범위, 20. 이번 문서 작업의 검증 기록, 2. 현재 저장소에서 확인한 사실 (+5 more)

### Community 258 - "FailureAlertTest"
Cohesion: 0.10
Nodes (13): _entry_modules(), FailureAlertTest, _group_requirements(), pyproject의 dependency group을 include-group까지 펼친다., 실패 알림은 timeout 취소(cancelled) 상태도 포착해야 한다. GitHub Actions는 timeout 초과 시 결론을…, source workflow가 공통 리포터를 건너뛰면 조용한 장애가 생긴다., 비싼 설치 앞에 게이트가 있어야 한다 — preflight를 없애면 안 된다., 보낼 카드가 없는 날 Chromium과 61MB 폰트를 받으면 그 시간은 그냥 사라진다. 설치가 composite로 옮겨갔으므로 게이트도 그… (+5 more)

### Community 259 - "test_logging.py"
Cohesion: 0.21
Nodes (6): JsonFormatterTest, LogFieldsTest, 로그는 한 줄 JSON이고, 비밀값은 나가지 않는다., 로그는 관측이다. 직렬화 때문에 프로그램이 죽으면 안 된다., logging이 나중에 KeyError를 던지는 것보다 여기서 막는 편이 낫다., _render()

### Community 260 - "Filing13F"
Cohesion: 0.06
Nodes (35): effective_filings(), Filing13F, HoldingsError, portfolio_weights(), Position, Any, ValueError, 13F 보유 신고를 읽는 규칙. ## 정정이 원본을 대체하는 방식이 두 가지다 13F 정정(13F-HR/A)에는 두 종류가 있고, 처리가… (+27 more)

### Community 261 - "Outbox"
Cohesion: 0.02
Nodes (165): Config, ConfigError, default_config(), RuntimeError, 설정을 명시적으로 읽는 자리. 실제 환경변수가 `.env`보다 우선하고, 필수 값은 호출 시점에 검증하며, 비밀값은 로그에 기록하지 않는다., 설정이 없거나 모양이 틀렸다. 값 자체는 담지 않는다., 이 실행이 쓰는 설정. 값은 프로세스 환경에서 온다., 필요한 값을 지금 확인한다. 없으면 **이름만** 말하고 멈춘다. (+157 more)

### Community 262 - "AI Investor Constitution"
Cohesion: 0.18
Nodes (11): 10. 변경 게이트, 1. 투자 대상, 2. 데이터 Source of Truth, 3. TradingAgents의 책임, 4. 뉴스·소셜 정책, 5. 공통 포트폴리오 계약, 6. 결정론적 계산, 7. 백테스트와 강화학습 (+3 more)

### Community 263 - "finite_float"
Cohesion: 0.07
Nodes (27): finite_float(), 유한한 float만. NaN·Infinity·bool·읽을 수 없는 값은 `default`. bool을 막는 이유: 파이썬에서…, main(), 성숙한 Shadow 판단을 SPY 대비 5·20·60 거래일로 평가한다., Fixed horizons used by post-decision evaluation., _direction(), evaluate_case(), EvaluationRepository (+19 more)

### Community 264 - "backtest/metrics.py"
Cohesion: 0.23
Nodes (8): BacktestMetrics, calculate_metrics(), Any, 백테스트 NAV·체결 장부에서 성과와 위험을 계산한다., 초기 현금을 첫 기준점으로 포함해 일별 수익과 비용 지표를 계산한다., _sample_std(), BacktestMetricsTest, nav()

### Community 265 - "BuildTest"
Cohesion: 0.20
Nodes (4): BuildTest, estimates 커버리지가 100%가 아니다 — 없으면 블록이 통째로 빠져야 한다., GAAP 계산값과 조정 컨센서스를 빼면 없는 서프라이즈가 생긴다., 컨센서스 스냅샷이 없어도 서프라이즈 이력만으로 블록을 낼 수 있다.

### Community 266 - "ticker_label"
Cohesion: 0.12
Nodes (35): _moves_text(), 신규·제거·변경을 기호 하나로 표시한다. embed는 색을 못 주므로 기호가 대신한다., mom(), pct(), Momentum score display: signed percentage-points without a percent sign., ticker_label(), ticker_text(), _canary() (+27 more)

### Community 267 - "_db"
Cohesion: 0.07
Nodes (14): _db(), _FakeBuilder, _FakeClient, _FakeTable, Any, 조용히 잘리거나 빠지는 읽기를 막는지 본다., 정렬 없는 range 읽기는 페이지 경계로 행이 빠질 수 있다. 조용히 두지 않는다., 권한·제약 오류를 '이미 있음'으로 삼키면 알림이 조용히 사라진다. (+6 more)

### Community 268 - "ViewTest"
Cohesion: 0.20
Nodes (3): 7일은 30일에 포함되므로 넘을 수 없다 — 넘으면 출처가 따로 갱신한 것이다. 실측: UBER 상향 7일 7 대 30일 6, TSLA 하향…, 카드에 GAAP EPS도 함께 있으므로 무엇을 비교했는지 밝혀야 한다., ViewTest

### Community 269 - "데이터, Supabase, PIT와 로컬 뉴스 Cache"
Cohesion: 0.11
Nodes (19): Cache와 중복 제거, Feature 소비 경계, Fundamentals cutoff 조회, Macro historical replay, PIT의 핵심 시각, Retention과 복구, Segment metrics, Source of truth와 편의용 최신 표 (+11 more)

### Community 270 - "test_edgartools_13f.py"
Cohesion: 0.11
Nodes (7): skipUnless, EdgartoolsWrapperTest, edgartools shadow 파서 wrapper와 운영 파서의 결과 일치(parity) 테스트. edgartools가 설치되어 있지 않으면…, edgartools 미설치/지연 import 경로. 설치 여부와 무관하게 동작해야 한다., edgartools 출력 컬럼을 운영 모델로 정규화하는 순수 헬퍼. 의존성 불필요., WrapperNormalizerTest, WrapperUnavailableTest

### Community 271 - "github_actions.py"
Cohesion: 0.25
Nodes (14): _headers(), job_log(), jobs_for_run(), list_workflows(), now_utc(), Any, datetime, GitHub Actions 실행 이력 조회. DB의 run_log가 아니라 Actions API를 본다. run_log는 파이프라인 다섯… (+6 more)

### Community 272 - "SurpriseRowsTest"
Cohesion: 0.20
Nodes (4): 공시 시점에는 아직 모르는 분기를 카드에 실으면 안 된다., 관측된 실제 사례(GOOGL +214%/+92%, UBER -82%)를 서프라이즈로 단정하지 않는다., 정상 범위(AAPL 3~7%, TSLA -38%)까지 잘라내면 블록이 쓸모없어진다., SurpriseRowsTest

### Community 273 - "src/investment_agent/research/features/__init__.py"
Cohesion: 0.21
Nodes (4): 일간 기술지표 ETL과 PIT feature layer (RSI·MACD → local ResearchStore). 시세 입력은 v1…, _frame(), DataFrame, TechIndicatorAtomicUpsertTests

### Community 274 - "load_or_create_approval_secret"
Cohesion: 0.26
Nodes (9): _default_path(), load_or_create_approval_secret(), Path, Discord 승인 버튼용 로컬 HMAC 비밀값을 안전하게 준비한다., 환경변수를 우선 사용하고, 없으면 Git 제외 로컬 파일을 원자 생성한다., _read(), _restrict(), _validate() (+1 more)

### Community 275 - "map_fiscal_periods.py"
Cohesion: 0.11
Nodes (25): 외부 I/O 없이 재무 관측값을 변환하고 검증하는 서비스., _add_months(), _annual_period(), _as_date(), _as_datetime(), _calendar_by_ticker(), _coherent_range(), _latest_reported_quarters() (+17 more)

### Community 276 - "_ops_webhook"
Cohesion: 0.23
Nodes (8): _ops_webhook(), (webhook, origin, 사용한 env 이름). Actions 실패와 로컬 하네스 실패는 고치는 방법이 다르다 — 전자는 재실행이나…, OpsWebhookOriginTest, OriginTravelsWithTheMessageTest, 운영 알림은 **실행된 곳**으로 목적지를 가른다. Actions 워크플로 실패와 로컬 하네스 실패는 고치는 방법이 완전히 다르다 — 전자는…, 갈라 두기 전에 알림이 먼저 조용해지는 것이 더 나쁘다., 전용 webhook이 아직 없으면 둘이 한 채널로 떨어진다 — 그때도 구분돼야 한다., _with()

### Community 277 - "test_reporting_guards.py"
Cohesion: 0.24
Nodes (7): assert_boundary(), assert_contract(), 읽기 경계와 SQL 공개 계약. 각 가드에 위반을 하나씩 주입해 실패도 검증한다., reporting 전체가 읽기 전용인지 본다 — 한 파일만 빠져도 그 경로로 쓰기가 샌다., LOCAL_VIEWS는 실제 Postgres 뷰가 아니라 로컬 runtime.sqlite3 읽기라 90_reporting.sql에 선언되지…, ReportingGuardsTest, view_columns()

### Community 278 - "_row"
Cohesion: 0.24
Nodes (3): CompareTest, shadow 대조 로직(shadow_diff.compare) 단위 테스트. 외부 의존성 없음., _row()

### Community 279 - "fusion.py"
Cohesion: 0.05
Nodes (49): OptimizerSignal, load_model(), LoadedModel, predict_numeric(), Any, ndarray, 저장된 ML artifact를 오늘의 feature에 적용해 수치 예측을 만든다. `fit_baseline`이 학습만 하고 끝나면 모델은…, 오늘의 feature 행렬로 종목별 NumericPrediction을 만든다. feature version과 컬럼 순서가 학습 때와 다르면… (+41 more)

### Community 280 - "storable_share_rows"
Cohesion: 0.26
Nodes (7): Any, 저장 계약이 받는 서식만 남기고, 버린 서식 이름을 함께 돌려준다. CompanyFacts의 fact에는 `10-KT`(회계연도 변경 전환기…, storable_share_rows(), 발행주식수 수집은 저장 계약이 받는 서식만 보낸다. CompanyFacts의 fact에는 `10-KT`(회계연도 변경 전환기 보고서)처럼 우리…, 한 건 때문에 그 기업 전체를 잃지 않는다 — 그것이 전에 일어난 일이다., _row(), StorableShareRowsTest

### Community 281 - "DashboardLauncherCliTest"
Cohesion: 0.15
Nodes (3): DashboardLauncherCliTest, 모든 .bat은 CRLF여야 하고, 시스템 python이 아니라 프로젝트 .venv를 쓴다. LF로 저장되면 cmd.exe가 마지막 줄을 삼켜…, 루트에는 run.bat 하나만 둔다 — 나머지는 목적별 scripts/ 하위에 있다.

### Community 282 - "universe/infrastructure/sources/__init__.py"
Cohesion: 0.14
Nodes (9): CompanyFactsKeyContractTest, _document(), 공용 SEC submissions 파서의 키 매핑 계약. `src/investment_agent/data/universe/sec.py`는…, fundamentals 일별 경로가 읽는 SEC 키 계약. `src/investment_agent/data/universe/sec.py`와…, Company Facts unit entry도 원본 이름 `form`을 쓴다., SEC submissions 응답의 모양(키 이름이 계약의 전부다)., 두 날짜가 뒤바뀌면 조회 창이 빗나가고 보존 삭제가 엉뚱한 행을 지운다., 13F 운용사는 10년치가 페이지로 나뉜다 — 최근 페이지만 보면 이력이 통째로 빈다. (+1 more)

### Community 283 - "SegmentHighlightsTest"
Cohesion: 0.10
Nodes (11): EarningsCardTest, EarningsExtrasTest, 실적 알림에 붙는 세그먼트 요약의 기간·중복 방지 규칙을 검증한다., 세그먼트 공시가 끝나기 전에는 빈 축 카드로 선점하지 않는다., 후속 알림 잡도 processing/failed 공시를 선점하지 않는다., 블록 하나 = 질문 하나. 제목이 '뭐와 뭐'면 두 주제가 섞였다는 뜻이다., 1행은 배당 유무로 두 갈래다 — 한쪽에만 붙이면 배당 없는 회사에서 조용히 빠진다. 실측으로 UBER(배당 없음) 카드에서 '추정치 방향'이…, 블록 하나 = 질문 하나 = 그림 하나. (+3 more)

### Community 284 - "object"
Cohesion: 0.22
Nodes (11): object, ModelPoolError, RuntimeError, 풀 후보를 안전하게 적용할 수 없을 때 발생한다., 풀에서 남은 후보를 하나씩 예약·시도해 이 종목의 분석을 완주한다. 한 후보가 실패하면(예약 자체가 없거나 호출 도중 429/404 등) 다음…, _select_and_run(), _candidate(), Path (+3 more)

### Community 285 - "SelectOnlyGateway"
Cohesion: 0.26
Nodes (7): DashboardDataError, RuntimeError, 읽기 결과의 구조가 계약과 다를 때 사용하는 안전한 오류., 허용된 PostgREST SELECT 연산만 조합하는 좁은 게이트웨이. v1 관심 기업은 공개 읽기 전용인…, SELECT와 허용된 필터·정렬·범위만 사용해 행을 읽는다., allowlist에 있는 읽기 전용 SQL 함수의 결과 행만 읽는다. 비공개 스키마(`alerts`)의 사실에 닿는 유일한 경로다. 이름과…, SelectOnlyGateway

### Community 286 - "ContextBuilder"
Cohesion: 0.14
Nodes (4): ContextBuilder, ContextPointInTimeTest, historical replay에서 point-in-time 이력이 없는 데이터를 차단한다., _Repository

### Community 287 - "MacroChainTest"
Cohesion: 0.29
Nodes (4): MacroChainTest, 매크로 알림 3종. 상류가 둘(macro_etl / macro_etl_monday)이라 한쪽만 들으면 요일이 빈다., ECOS 키 하나가 만료돼도 ETL은 exit 1 한다 — success로 잠그면 카드가 묻힌다., workflow_run이 발화하지 않아도 스스로 한 번은 돈다.

### Community 288 - "적응형 정보 구조"
Cohesion: 0.12
Nodes (16): 13F 비중은 '보고된 장부 안에서의 비중'이다, ATLAS 투자 터미널, Discord 알림 대응표, 데이터 출처 설계표, 매크로와 지표 발표는 분리한다, 사이드바는 세 갈래다, 상세를 여는 방식은 고를 수 있다, 선택은 카드 클릭만이 아니다 (+8 more)

### Community 289 - "extract_summary_financials"
Cohesion: 0.09
Nodes (26): parse_8k_earnings(), 8-K 실적 발표에서 저장 가능한 요약값을 조립한다., 내재화한 표·본문 파서로 8-K 실적값을 한 번에 추출한다., extract_guidance_text(), 가이던스·전망을 언급한 원문 문단을 최대 세 개까지 연결한다., SEC 8-K 보도자료에서 필요한 값만 읽는 경량 파서 묶음. 이 패키지는 외부 EDGAR SDK를 호출하지 않는다. SEC archive에서…, extract_summary_financials(), _label_at() (+18 more)

### Community 290 - "gdpnow_archive.py"
Cohesion: 0.30
Nodes (13): _as_date(), fetch_rows(), fetch_workbook(), _frame_rows(), parse_workbook(), Any, date, _quarter_start() (+5 more)

### Community 291 - "normalize_positions"
Cohesion: 0.20
Nodes (10): Position, SEC 원본 한 행을 USD로 정규화한 DB 저장 단위. Combination Report의 중복 보유를 Python에서 먼저 합치면 sub-…, normalize_positions(), Position, 원본 행을 USD로 환산하되 SEC 행 단위로 보존한다., detect_value_scale(), _fallback_scale(), date (+2 more)

### Community 292 - "safe_fetch"
Cohesion: 0.16
Nodes (18): normalize_tz(), Logger, Series, 날짜의 timezone 정보를 떼어 형식 통일(yfinance 등 tz 표기 제각각 대응)., 지표를 하나씩 fetch. 하나 실패해도 멈추지 않고 성공값+실패목록을 함께 반환. budget_sec를 넘기면 그 시점부터 남은 지표는…, safe_fetch(), _api_error(), fetch_batch() (+10 more)

### Community 293 - "institutional/card.py"
Cohesion: 0.15
Nodes (33): blind_spot_caveat(), blind_spots 코드 목록을 운용사별 한국어 caveat 한 줄로 만든다., _activity_rows(), build_filing(), build_quarterly(), _co_held(), _conflicts(), _instrument_rows() (+25 more)

### Community 294 - "src/investment_agent/research/rl/__init__.py"
Cohesion: 0.05
Nodes (61): BaselinePolicyConfig, BaselinePolicyModel, DurablePolicyArtifact, load_baseline_policy(), Any, ndarray, Path, 외부 RL 의존성 없이 재현 가능한 선형 challenger 정책. (+53 more)

### Community 295 - "strategy/embeds.py"
Cohesion: 0.07
Nodes (46): analyze_allocation_change(), Allocation change analysis for strategy notifications., _as_card(), _as_row(), build_card(), build_summary(), _generic_layout(), _layout_for() (+38 more)

### Community 296 - "QlibPITAdapter"
Cohesion: 0.23
Nodes (6): Any, DataFrame, QlibPITAdapter, QlibSegments, Qlib data vendor를 쓰지 않고 StaticDataLoader로 우리 snapshot만 전달한다., QlibAdapterTest

### Community 297 - "주문 실행, 승인, Broker와 단계별 안전장치"
Cohesion: 0.14
Nodes (14): Broker-independent contract, Credential 격리, Discord Live Manual 승인, Idempotency와 결과불명 주문, Kill switch와 Lockdown, Model 승격 최소 증거와 Live Autonomous Permit, Reconciliation, 분석·검증 단계 (+6 more)

### Community 298 - "digest.py"
Cohesion: 0.16
Nodes (23): _ago(), build_embed(), chain_expectations(), evaluate(), failure_streak(), judge_channels(), _kst(), _pad() (+15 more)

### Community 299 - "verify_postgres_sql_syntax.py"
Cohesion: 0.30
Nodes (9): check_all(), check_file(), main(), Path, `db/postgres/v1/*.sql`이 유효한 PostgreSQL 구문인지 오프라인으로 검증한다. `v1_schema_probe.py`는…, 구문 오류가 있으면 사람이 읽을 오류 메시지를, 없으면 None을 돌려준다., sql_files(), PostgresSqlSyntaxTest (+1 more)

### Community 300 - "load"
Cohesion: 0.17
Nodes (9): EvidenceError, load(), ValueError, 판단 근거를 파일로 내보내고 DB에는 주소만 남긴다. ## 왜 DB에 넣지 않는가 근거 번들은 한 건에 수십 KB다. `jsonb`에 넣었더니…, 저장된 근거를 되읽는다. 지문이 다르면 예외 — 조용히 다른 근거를 주지 않는다., IntegrityTest, 근거는 DB 밖에 있고, 조용히 바뀌면 읽을 때 걸려야 한다., 그때 본 근거'가 조용히 바뀌면 판단 기록 전체가 거짓이 된다. (+1 more)

### Community 301 - "fomc_calendar.py"
Cohesion: 0.22
Nodes (13): _current_dates(), _fetch(), fetch_dates(), FomcCalendarError, _historical_dates(), _meeting_end_date(), date, ValueError (+5 more)

### Community 302 - "macro_indicator_rows"
Cohesion: 0.17
Nodes (12): macro_indicator_rows(), `reporting.macro_observations` 원값을 지표별 최신 상태 + 경보 등급으로 접는다. 반환 각 행:…, compute_metrics_series(), DataFrame, Series, KIND_COMPUTE_MATRIX 기반 파생 지표 계산기. 소비자가 macro v1 observation read model로 받은…, metrics DataFrame 한 행 → 스칼라 dict (NaN 제거·float 캐스팅). db.py가 마지막·직전 관측치를…, 시계열 전 구간 metrics DataFrame. db.py가 마지막·직전 행을 metrics/prev_metrics로 환원. (+4 more)

### Community 303 - "reconcile_orders"
Cohesion: 0.22
Nodes (10): LocalOrder, Protocol, 우리 원장과 broker 상태를 다시 맞춘다. ## broker_order_id로만 맞춘다 종목·수량·시각이 비슷하다고 같은 주문으로 묶지…, broker 응답에서 이 모듈이 요구하는 최소한., 양쪽 목록을 `broker_order_id`로만 맞춘다., reconcile_orders(), ReconciliationResult, RemoteOrder (+2 more)

### Community 304 - "EnvFileTest"
Cohesion: 0.27
Nodes (4): EnvFileTest, Path, .env 갱신 — 비밀값 파일을 다루므로 손실이 나면 안 된다., 사람이 적어둔 메모가 날아가면 안 된다.

### Community 305 - "earnings_report/quickchart.py"
Cohesion: 0.20
Nodes (14): axis_chart(), _blue(), _color(), composition_donut(), 세그먼트 embed에 붙일 QuickChart 이미지 URL을 조립한다. 여기서 그림을 그리지 않는다 — Chart.js 설정을 URL에 실어…, 매출 규모 가로 막대 — 비중을 낼 수 없는 축(partial)의 대체 그림. 합계를 모르니 '전체 중 얼마'는 말하지 않고 '서로 얼마나…, 축 하나의 그림 — 비중을 낼 수 있으면 도넛, 아니면 매출 막대., 매출 구성 도넛. 가운데가 비어 있어 집중도가 링 두께로 읽힌다. 비중을 낼 수 있는 행이 둘 미만이면 원 하나가 되어 정보가 없다 →… (+6 more)

### Community 306 - "CollectSocialTest"
Cohesion: 0.07
Nodes (13): 텍스트 정규화와 언급 추출 규칙. 외부 호출도 저장소도 모른다., CollectSocialTest, NormalizeSocialTest, _payload(), Reddit 수집 유스케이스와 저장 형태., 작성자 원문을 90일 들고 있을 이유가 없다., 언급이 없다고 게시물을 버리면 나중에 규칙을 고쳐도 다시 못 찾는다., cap 소진은 provider 오류가 아니다 — 남은 채널을 계속 돌면 예약만 반복 소모한다. (+5 more)

### Community 307 - "test_watchlists.py"
Cohesion: 0.11
Nodes (7): 운영 점검과 하네스 실행 명령 패키지., PendingFilingGroupsTest, PendingStateTest, Supabase 관심종목 관리와 공시 필터 규칙을 검증한다., WatchlistNormalizationTest, 공통 Actions 실패 리포터가 원문을 안전한 사건 카드로 바꾸는지 검증한다., WorkflowFailureReporterTest

### Community 308 - "build_valuations"
Cohesion: 0.16
Nodes (7): build_valuations(), datetime, 종목별 가격·발행주식수·TTM 재무를 하나의 PIT 관측값으로 만든다., BuildValuationsEntryTest, 근거가 모자란 날도 기록한다 — 왜 못 만들었는지가 나중에 필요하다., DB CHECK 제약과 같은 불변식을 코드 쪽에서도 지킨다., _Repository

### Community 309 - "_Builder"
Cohesion: 0.09
Nodes (6): _Supabase, _Builder, 세그먼트 8년 보존 정책과 외래키 안전 삭제 순서를 검증한다., _Response, SegmentsRetentionTest, _Supabase

### Community 310 - "SignalBlender"
Cohesion: 0.09
Nodes (14): BlendedSignal, LLM 정성 분석 신호와 강화학습(RL) 정량 정책 신호의 동적 앙상블 블렌더. TradingAgents(LLM)의 펀더멘털·뉴스·거시…, LLM 신호와 RL 정책의 동적 블렌더., RL 모델의 DSR 확률에 따라 RL 신호 반영 비중을 동적으로 결정한다., 종목별 LLM 신호와 RL 최적 비중을 결합하여 BlendedSignal 매핑을 반환한다., SignalBlender, BlendingRuleChartTest, 융합 차트가 실제 규칙과 어긋나지 않는지. 실측 2026-09-04: 이 화면은 "실제 SignalBlender 엔진을 호출"한다고 적어 놓고… (+6 more)

### Community 311 - "._history"
Cohesion: 0.18
Nodes (5): ComboOverlayTest, EpsBlendTest, 수염이 축 밖으로 잘리면 '기대보다 훨씬 위'가 안 보인다., GAAP 선 범위 밖의 조정값이 잘리면 간극이 안 보인다., 이력이 이번 분기까지 못 왔으면 직전 분기 쌍을 올리지 않는다.

### Community 312 - "_Repository"
Cohesion: 0.16
Nodes (8): BuildTrainingSamplesTest, _features(), datetime, 비용 반영 학습 표본이 gross label을 그대로 베끼지 않는지 고정한다., +0.1% 판단은 비용 후 손실이다. 그 개수가 보고돼야 한다., 최소 수수료가 있으면 비율이 주문 금액에 따라 달라져 계산할 수 없다., 적재 첫 며칠은 horizon이 안 지나 label이 0건이다. 여기서 실패시키면 5거래일 내내 job이 실패로 뜨고, 그 사이 정상 적재된…, _Repository

### Community 313 - "_Repository"
Cohesion: 0.23
Nodes (5): _feature_row(), _label_row(), LoadTrainingSetTest, 원장 행에서 RL 학습용 FeatureDataset을 조립하는 경로를 검증한다., _Repository

### Community 314 - "test_serving.py"
Cohesion: 0.10
Nodes (16): BlendFlagTest, ComparisonRecordTest, ComputeRlBlendTest, LiveMembershipTest, _model(), _Proposal, datetime, Exception (+8 more)

### Community 315 - "test_config.py"
Cohesion: 0.40
Nodes (3): PackageImportTest, 설정은 명시적으로 읽고, 안전 플래그는 fail-closed다., 패키지를 import하는 것만으로 환경이 바뀌면 안 된다.

### Community 316 - "notifications/macro.py"
Cohesion: 0.06
Nodes (26): audit_fx_cross_sources(), _comparison(), date, Series, 매크로 원천 시계열의 단위·범위와 환율 교차검증을 담당한다., BOK 환율을 독립적인 연준/FRED 관측치와 교차검증한다. ECOS를 주 원천으로 유지한다. FRED의 DEXKOUS(원/달러)와…, 경제 발표의 식별·일정·정규화·검증 규칙., MacroNotificationStore (+18 more)

### Community 317 - "Investment Agent"
Cohesion: 0.12
Nodes (16): 1. 데이터 수집과 Supabase, 2. Evidence와 Feature, 3. 후보 선정과 AI 분석, 4. 모델과 포트폴리오, 5. 검증과 실행, Investment Agent, Repository 구조, 각 계층이 하는 일 (+8 more)

### Community 318 - "자주 발생하는 문제"
Cohesion: 0.13
Nodes (15): CVXPY 또는 NumPy 충돌, Discord 승인이 거절됨, DuckDB import 또는 cache 오류, Historical macro/fundamentals가 비어 있음, Live가 실행되지 않음, Optimizer가 infeasible, Reconciliation mismatch, RiskGate가 Shadow는 통과하고 Paper/Live는 거절 (+7 more)

### Community 319 - "IntelligenceArchitectureTest"
Cohesion: 0.18
Nodes (9): _imports(), IntelligenceArchitectureTest, Path, _python_files(), intelligence 계층 경계를 검증한다. data 도메인들과 같은 4계층 문법을 쓴다 — 저장소만 Supabase가 아니라 로컬…, 도메인 규칙이 저장소나 네트워크를 알면 규칙만 따로 시험할 수 없다., application은 infrastructure.sources와 domain만 안다. universe·market과 같은 이유로…, 따로 두면 정규화·언급 추출 규칙이 두 벌이 되고 조용히 갈라진다. (+1 more)

### Community 320 - "test_view_reachability.py"
Cohesion: 0.22
Nodes (7): MasterViewsHaveNoScopeTest, 코드가 실제로 부르는 모양으로 reporting 뷰를 읽을 수 있어야 한다. `ReportingQueries.read`는 이력 뷰가 통째로…, `f("some_view")` 꼴로 인자 하나만 준 호출을 모은다., 검사 대상을 못 찾으면 위 테스트는 공허하게 통과한다., 시간 컬럼이 없는 뷰에 scope를 걸면 범위로 풀 길이 없다 — 영구히 못 읽는다., _unfiltered_view_calls(), UnfilteredViewCallsAreReadableTest

### Community 321 - "TradingAgentsDecisionEngine"
Cohesion: 0.23
Nodes (7): AgentEngineResult, DecisionEngine, Any, Protocol, 투자 Agent 구현을 교체 가능한 인터페이스로 제한한다., AI Investor 판단 엔진 인터페이스 및 공통 경계., TradingAgentsDecisionEngine

### Community 322 - "test_workflow_storage_paths.py"
Cohesion: 0.22
Nodes (7): _job_env(), 워크플로가 주고받는 로컬 저장소 경로는 `storage_paths`와 같아야 한다. 로컬 저장소(DuckDB·Parquet)는 Actions…, job에 선언된 env. 여러 단계가 같은 자리를 보게 하는 정상적인 방법이다., 옛 자리를 가리키는 줄이 하나라도 남으면 그 워크플로가 조용히 빈손이 된다., 대상을 못 찾으면 위 검사는 공허하게 통과한다., _resolved_research_paths(), WorkflowArtifactPathsFollowStorageTest

### Community 323 - "30_execution.sql"
Cohesion: 0.29
Nodes (10): approvals, execution_control, fills, intents, order_attempts, order_events, order_manifests, orders (+2 more)

### Community 324 - "openfigi.py"
Cohesion: 0.21
Nodes (17): _api_key(), _batch_size(), _map_batch(), map_identifiers(), MappingResult, _normalize_identifier(), _normalize_ticker(), OpenFIGI의 CUSIP/CINS 식별자 매핑 어댑터. (+9 more)

### Community 325 - "OpenFigiIdentifierTest"
Cohesion: 0.13
Nodes (4): institutional 외부 데이터 source adapter 패키지., OpenFigiIdentifierTest, CUSIP/CINS OpenFIGI 조회의 식별자 타입·fallback 계약을 검증한다., _Response

### Community 326 - "IntelligenceReaderTest"
Cohesion: 0.17
Nodes (6): IntelligenceReaderTest, 읽기 계층에 쓰기 메서드 호출이 있으면 경계가 무너진 것이다., 화면이 쓰기 모드로 열면 수집 잡이 파일을 열지 못해 죽는다., 수집이 한 번도 안 돈 노트북에서 화면이 예외로 죽으면 안 된다., 저장은 원문, 화면으로 나갈 때 가린다. Reddit 본문에는 지시문처럼 읽히는 문장과 자격증명이 실제로 들어온다., 실행 기록의 message는 provider 오류 문구라 자유 텍스트다. 수집 실패 메시지에 URL과 API 키가 들어올 수 있다.

### Community 328 - "FiresBetweenTest"
Cohesion: 0.13
Nodes (5): CronMatchTest, FiresBetweenTest, cron 판정 — 여기가 틀리면 '미실행'을 거꾸로 보고한다., cron 요일은 일=0이다. 파이썬 weekday()(월=0)를 그대로 쓰면 하루씩 밀린다., market_daily는 전날 23:30 UTC다 — 구간을 24시간으로 잡아야 잡힌다.

### Community 329 - "_called_schemas"
Cohesion: 0.22
Nodes (11): _called_schemas(), CodeOnlyCallsDeclaredSchemasTest, _declared_schemas(), _imports_postgres_singleton(), Module, 코드가 부르는 Postgres 스키마는 선언에 실재해야 한다. 이 저장소의 단위 테스트는 DB를 때리지 않는다. 그래서 없는 스키마를 부르는…, 대상을 못 찾으면 위 테스트는 공허하게 통과한다., `sb`는 service-role Postgres 클라이언트다. 이것을 들여온 모듈만 대상이다. (+3 more)

### Community 330 - "store"
Cohesion: 0.18
Nodes (8): Any, DB에 적을 것 전부. 내용은 여기 없다., 근거를 파일로 내보내고 주소를 돌려준다., store(), StoredEvidence, 빈 근거를 저장하면 '근거가 있다'고 기록되면서 실제로는 없다., 한 파일로 합치면 목록 화면이 역할 의견까지 통째로 받는다., StoreTest

### Community 331 - "Fundamentals domain"
Cohesion: 0.05
Nodes (37): Fundamentals architecture, 계산과 reporting, 시점 정합성, 실패와 검증, 의존성 방향, 저장 책임, earnings / expectations, Fundamentals canonical columns (+29 more)

### Community 332 - "taxonomy/__init__.py"
Cohesion: 0.15
Nodes (18): assess_rows(), _base_quality(), _company_row(), _is_subset_sum(), _metric_method(), _number(), _overlapping_revenue_aggregates(), Any (+10 more)

### Community 333 - "main"
Cohesion: 0.25
Nodes (11): crons_for(), _emit(), main(), Path, 워크플로 파일의 schedule cron 목록(주석 처리된 줄은 제외)., workflow_run으로 이 워크플로를 깨우는 상류 워크플로 이름들., 카드 본문에 이모지가 들어가는데 Windows 콘솔 기본 코드페이지(cp949)로는 인코딩이 터진다 — 미리보기가 개발자 기계에서 죽으면…, _uncommented() (+3 more)

### Community 334 - "test_market_retention.py"
Cohesion: 0.20
Nodes (4): Market 고정 용량 보존 작업 계약., _Response, _Rpc, _Supabase

### Community 335 - "Macro 경제발표"
Cohesion: 0.14
Nodes (12): Macro 경제발표, reporting read model, 검증과 운영 전환, 변경과 시간, 시점과 발표 오차, 실행과 소비자, 저장과 계산 예시, 키와 저장 단위 (+4 more)

### Community 336 - "InstitutionalArchitectureTest"
Cohesion: 0.21
Nodes (8): _imports(), InstitutionalArchitectureTest, Path, _python_files(), institutional 계층 경계를 검증한다. universe·market의 test_architecture.py와 같은 패턴이다. 다섯…, 도메인 규칙이 저장소나 네트워크를 알면 규칙만 따로 시험할 수 없다., application은 infrastructure.sources와 domain만 안다. universe·market과 같은 이유로…, 평면 모듈이 하나라도 돌아오면 도메인마다 문법이 달라진다.

### Community 337 - "EconIcsTest"
Cohesion: 0.27
Nodes (3): 경제 발표 infrastructure adapter., EconIcsTest, 자연키·구독 UID·일정 변경을 보존하는 ECON ICS 테스트.

### Community 339 - "apply_downstream_api_key"
Cohesion: 0.17
Nodes (8): apply_downstream_api_key(), _llm_max_retries(), 지금 고른 후보의 키를 provider SDK가 읽는 환경변수에 **덮어쓴다**. setdefault를 쓰면 안 된다. 모델 풀이 후보를…, 429를 견딜 SDK 재시도 횟수. 대기 시간은 provider가 준 Retry-After를 따른다., ProviderKeyRotationTest, 후보를 갈아탈 때 앞 후보의 API 키가 남으면 다음 후보가 그 키로 호출된다. 실측 2026-09-03: Azure 시도가…, Azure 배포는 429에 Retry-After 10~15초를 준다. SDK 기본 2회로는 못 견딘다., RetryBudgetTest

### Community 340 - "CandidateFeatureReadTest"
Cohesion: 0.25
Nodes (4): CandidateFeatureReadTest, _feature_rows(), 후보 선정은 feature 창을 한 번만 읽는다. 전에는 tracked 종목마다 `features_for_ticker`를 불렀다 — 실측으로…, 시점 근거다 — cutoff 뒤에 들어온 값이 섞이면 미래를 보게 된다.

### Community 341 - "Research Features — 일간 기술지표와 PIT 학습 입력"
Cohesion: 0.15
Nodes (13): 0. 관련 문서 및 전체 위치, 1. 전체 데이터 파이프라인 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 주요 기술지표 및 계산 정의, 4. 관련 코드 및 데이터 흐름, 5. 실행 및 검증 가이드, 6. 수정할 때 확인할 곳, 7. 유용한 SQL 점검 쿼리 (+5 more)

### Community 342 - "Strategy — 팩터/룰 기반 자산배분 전략 6종 파이프라인"
Cohesion: 0.15
Nodes (13): 0. 관련 문서 및 전체 위치, 1. 전체 데이터 파이프라인 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 지원하는 6대 퀀트 자산배분 전략 ([`catalog.py`](catalog.py)), 4. 관련 코드 및 데이터 흐름, 5. 실행 및 검증 가이드, 6. 수정할 때 확인할 곳, 7. 유용한 SQL 점검 쿼리 (+5 more)

### Community 343 - "PITScalar"
Cohesion: 0.29
Nodes (5): PITScalar, 하나의 수치와 그것을 당시 알 수 있었음을 보이는 근거다., _inputs(), PITValuationTest, _scalar()

### Community 344 - "18. 검수 체크리스트"
Cohesion: 0.29
Nodes (7): 18. 검수 체크리스트, 사실성과 구현 계약, 색, 철학과 정보 구조, 카피, 컴포넌트와 접근성, 타이포와 숫자

### Community 345 - "_by_key"
Cohesion: 0.22
Nodes (6): _by_key(), InvestmentChannelsTest, 자동매매 보고 채널 선언 — 카드가 조용히 안 나가는 배치를 막는다., 판단 → 승인 → 체결이 한 카테고리에서 순서대로 읽히게 한다., private 채널에 봇 allow가 안 붙으면 카드가 에러 없이 사라진다., @everyone 채널 deny는 카테고리 private 처리로만 붙어야 한다.

### Community 346 - "CollectNewsTest"
Cohesion: 0.15
Nodes (7): CollectNewsTest, _payload(), 뉴스 수집 유스케이스. 네트워크를 타지 않는다 — fetch는 주입한다., 조회해서 받은 것은 '화제'가 아니다 — 등급을 남긴다., 저장한 뒤 다음 정리에서 지우면 그 사이 화면에 잠깐 나타난다., 파싱 실패를 중복으로 세면 '조용한 0건'을 못 알아본다., cap 소진은 provider 오류가 아니다 — 남은 종목을 계속 돌면 예약만 반복 소모한다.

### Community 347 - "earnings/__init__.py"
Cohesion: 0.07
Nodes (9): Dashboard와 실적 알림이 함께 소비하는 실적 read model 계약., EarningsMetricsTest, 실적 카드와 실적 화면이 공유하는 파생 지표·등급 계약., EarningsScheduleContractTest, 발표 예정 read model은 Reporting이 소유하고 알림은 그것을 재노출한다., EarningsValuationHistoryTest, 역사적 밸류에이션 계산은 카드와 화면이 같은 분포를 주장해야 한다., CalendarPreflightTests (+1 more)

### Community 348 - "application/service.py"
Cohesion: 0.29
Nodes (9): _filing_row(), InstitutionalRefreshResult, _position_rows(), Any, date, FilingSource, SEC 13F 원문을 v1 institutional 원장에 다시 적재하는 경로., 활성 manager별 13F를 독립 처리한다. 한 filing 실패는 재시도 대상으로 남는다. (+1 more)

### Community 349 - "test_segments_quality.py"
Cohesion: 0.17
Nodes (4): CompanyBaselineTest, 회사별 세그먼트 형식 보존과 품질 판정 규칙을 검증한다., SchemaContractTest, SegmentSnapshotReadTest

### Community 350 - "CardInstallGuardTest"
Cohesion: 0.21
Nodes (7): CardInstallGuardTest, PNG 카드 렌더 준비의 시간 상한을 지킨다. 설치는 이제 `.github/actions/card-render` composite 하나에…, 이 composite를 실제로 부르는 워크플로. 없으면 그 자체가 실패다., 상한이 **하나라도** 빠지면 실패해야 한다. `playwright install`은 두 번 나온다(install-deps, install…, `timeout ... sudo`는 신호가 자식에 닿지 않아 상한이 무력해진다., 폰트 없이 렌더하면 한글이 두부로 나가는데 예외는 안 난다. 여기서 멈춰야 한다., 안쪽 상한의 합이 부르는 잡의 상한을 넘으면 상한을 둔 의미가 없다. composite action의 스텝은 `timeout-minutes`를…

### Community 351 - "처음 보는 사람을 위한 시스템 지도"
Cohesion: 0.15
Nodes (13): Discord 알림은 어디에 있는가, 공개 독자가 읽을 상시 문서, 대시보드는 어디에 있는가, 데이터 적재는 어디에 있는가, 문서와 코드가 다르면, 쉬운 비유, 유지보수자·기록 자료, 전체 책임 경계 (+5 more)

### Community 352 - "HarnessReporter"
Cohesion: 0.07
Nodes (22): main(), Discord 승인 Gateway listener를 별도 lock으로 감싸는 로컬 서비스 entry., DuplicateProcessError, ProcessFileLock, Path, RuntimeError, 이미 같은 state 디렉터리를 소유한 프로세스가 있는 경우다., HarnessReporter (+14 more)

### Community 353 - "db_capacity.py"
Cohesion: 0.33
Nodes (12): cmd_reclaim(), cmd_report(), connect(), database_size(), main(), mb(), project_ref(), Supabase 용량을 실측하고, 회수 가능한 공간을 되찾는다. Supabase Free는 **database size 500MB를 넘기면… (+4 more)

### Community 354 - "Any"
Cohesion: 0.07
Nodes (18): chunk_values(), _LazyServiceClient, Any, 쿼리 빌더. 스키마를 반드시 함께 받는다 — 기본 스키마에 기대면 표를 옮길 때 어느 스키마를 읽고 있었는지 코드만 봐서는 알 수 없다., 1,000행 상한을 넘겨 끝까지 읽는다. `builder_factory`는 **호출마다 새 빌더**를 돌려줘야 한다. 빌더는 한 번 실행하면…, 긴 `in` 목록을 URL 한도와 행 상한 없이 읽는다., 충돌 키를 **명시적으로** 받아 나눠 넣는다. `on_conflict`를 생략할 수 있게 두지 않는 이유: 생략하면 PostgREST가…, 넣는 데 성공하면 True, 이미 있으면 False. **선점(claim)에 쓴다.** "먼저 조회해서 없으면 넣기"는 두 러너가 동시에… (+10 more)

### Community 355 - "social_normalize.py"
Cohesion: 0.36
Nodes (9): author_hash(), _posted_at(), Any, datetime, Reddit 응답을 저장 레코드로 바꾼다. ## 작성자는 해시로만 남긴다 필요한 것은 "같은 사람이 반복 게시하나"뿐이고 그것은 해시로 된다.…, 작성자 식별용 해시. 지워진 계정은 비운다., 게시물 한 건을 저장 레코드로 바꾼다. 식별할 수 없으면 `None`., _sha() (+1 more)

### Community 356 - "compute_all"
Cohesion: 0.17
Nodes (11): compute_all(), macd(), DataFrame, Series, src/investment_agent/research/features/compute.py — RSI·MACD 직접 계산. §5 공식 그대로:…, Wilder RSI. 첫 length-1행은 NaN., MACD line / signal. EMA는 adjust=False (전통 정의)., 단일 ticker 가격을 날짜당 한 행의 저장형 지표로 계산한다. 입력 컬럼: ticker · trade_date · close 출력 컬럼:… (+3 more)

### Community 357 - "model_pool.py"
Cohesion: 0.13
Nodes (14): _azure(), _azure_daily_requests(), gemini_candidate(), groq_candidate(), _ledger_key(), ModelCandidate, datetime, 여러 LLM provider를 하루 요청 한도 안에서 종목 단위로 회전한다. 단일 모델(예: Gemini 무료 등급)의 분당 토큰·일일 요청… (+6 more)

### Community 358 - "Notifications — 시각화 알림(Playwright PNG 카드 & Discord Embed) 서브시스템"
Cohesion: 0.15
Nodes (13): 0. 관련 문서 및 전체 위치, 1. 전체 알림 렌더링 & 라우팅 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 8대 알림 카드 명세 및 전송 포맷, 4. 관련 코드 및 디렉토리 구조, 5. 실행 및 로컬 테스트 가이드, 6. 수정할 때 확인할 곳, Notifications — 시각화 알림(Playwright PNG 카드 & Discord Embed) 서브시스템 (+5 more)

### Community 359 - "test_inputs.py"
Cohesion: 0.19
Nodes (7): FilingAvailabilityTest, _four_quarters(), _quarter(), PIT 밸류에이션 입력 조립과 적재 진입점의 시점 계약을 고정한다., 일자만 아는 공시를 그날 0시로 잡으면 실제보다 이르게 안다고 주장하게 된다., 나중 정정본을 쓰면 그 시점에 알 수 없던 값이 섞인다., TTMReconstructionTest

### Community 360 - "overwrites"
Cohesion: 0.22
Nodes (10): overwrites(), plan_everyone(), plan_overwrites(), plan_roles(), Any, 적용할 채널 오버라이트 선언 — (대상 이름, 역할 key, allow, deny). private 카테고리는 카테고리와 그 안의 채널에…, @everyone의 길드 권한이 선언과 다르면 그 차이. 같으면 None., 선언한 역할을 이름으로 대조한다 — 없으면 만들고, 권한이 다르면 고친다. 이름으로 찾는 이유는 채널과 같다: ID를 코드에 박으면 서버를… (+2 more)

### Community 361 - "FindTickersTest"
Cohesion: 0.20
Nodes (5): FindTickersTest, 본문 ticker 추출. 오탐을 막지 못하면 언급 표가 쓰레기가 된다., S&P 500에는 ALL·IT·ON·NOW 같은 평범한 단어가 티커로 있다., universe에 없는 심볼은 언급이 아니다 — fail-closed., _tickers()

### Community 362 - "context.py"
Cohesion: 0.18
Nodes (10): ContextRepository, _fundamentals_available_at(), _id(), _item(), _latest_iso(), Any, datetime, Protocol (+2 more)

### Community 363 - "ActualProviderTest"
Cohesion: 0.19
Nodes (3): ActualProviderTest, _fred_setting(), ECON actual provider의 unit/validation/fail-closed 계약.

### Community 364 - "investment/embeds.py"
Cohesion: 0.29
Nodes (13): candidate_embed(), _date(), _lines(), _percent(), portfolio_embed(), Any, 자동매매 판단·체결을 Discord embed로 조립한다. 여기서 하는 일은 조립뿐이다 — DB도 네트워크도 만지지 않으므로 그대로 단위…, 종목 하나의 심층 판단 카드. 근거와 '없는 근거'를 함께 적는다. (+5 more)

### Community 365 - "redact"
Cohesion: 0.32
Nodes (4): LogRecord, 알려진 비밀값 모양을 가린다. 값의 길이도 남기지 않는다., redact(), RedactTest

### Community 366 - "_service"
Cohesion: 0.22
Nodes (5): CandidateRunnerTest, PortfolioRunnerTest, 자동매매 보고서 러너 — v1 outbox 등록·디스패치 경계를 DB 없이 검증한다., _service(), TradeRunnerTest

### Community 367 - "application/backfill_history.py"
Cohesion: 0.17
Nodes (16): backfill_segment_history(), _company_backfill_targets(), _completed_segment_accessions(), date, 기업 재무 이력을 명시적으로 백필한다. 기업 전체 재무는 daily와 같은 companyfacts 원천을 쓰고, 세그먼트는 차원 데이터가…, 선택 CIK에서 완료된 전역 고유 accession_no 집합., 요청 구간을 보존 창 안으로 제한해 적재 직후 삭제되는 재처리를 막는다., 세그먼트 FSDS 분기 파일을 원본 파일 단위로 한 번씩 처리한다. (+8 more)

### Community 368 - "v1 현재 상태"
Cohesion: 0.22
Nodes (9): 2026-09-07 storage foundation 전환, v1 현재 상태, 데이터와 SQL, 소유 구조, 아직 실행하지 않은 것, 적용 상태, 현재 검증, 현재 결론 (+1 more)

### Community 369 - "cron.py"
Cohesion: 0.31
Nodes (9): _field(), fires_between(), matches(), parse(), datetime, 워크플로 cron이 특정 구간에 발화했어야 하는지 판정한다. croniter를 쓰지 않는다 — 이 저장소의 cron은 전부 5필드(`분 시 일…, cron 필드 하나를 허용 값 집합으로 편다., moment(UTC)가 이 cron의 발화 시각인지. (+1 more)

### Community 370 - "test_universe_sic.py"
Cohesion: 0.14
Nodes (4): EntitySchemaTest, EntitySelectionTest, EntitySourceTest, SEC entity metadata 원천 결측·TTL·CIK 중복 제거 회귀 테스트.

### Community 371 - "MACRO — v1 market-state pipeline"
Cohesion: 0.29
Nodes (7): Code structure, Execution, MACRO — v1 market-state pipeline, Operational boundary, Responsibility, Snapshot retention, Source adapters

### Community 372 - "test_ecos.py"
Cohesion: 0.22
Nodes (7): dict, v1 macro 원천 어댑터. 각 adapter는 원천별 실패를 series 단위 결과로 남기고 다른 원천 수집을 막지 않는다., EcosClientTest, _payload(), ECOS 클라이언트가 전체 행과 통계 계약을 보존하는지 검증한다., _Response, _row()

### Community 373 - "news_normalize.py"
Cohesion: 0.26
Nodes (12): canonical_url(), content_fingerprint(), _published_at(), Any, datetime, provider 응답을 저장 레코드로 바꾸고 중복 제거 키를 만든다. ## 왜 URL을 정규화하는가 같은 기사에 추적 파라미터만 다른 링크가…, 중복 제거에 쓸 URL 형태로 맞춘다., 제목·요약으로 만드는 내용 지문. 다른 provider가 같은 기사를 다른 URL로 줄 때 이 지문이 중복을 잡는다. (+4 more)

### Community 374 - "validate"
Cohesion: 0.36
Nodes (5): 각 kind에 정확히 하나의 Discord target 환경변수가 설정돼 있는지 확인한다., validate(), _config(), workflow용 subscription read-only validation을 검증한다., ValidateSubscriptionsTest

### Community 375 - "installation_files"
Cohesion: 0.11
Nodes (26): cmd_apply(), cmd_plan(), _connect(), _exposed_schemas(), main(), _project_ref(), 빈 Supabase에 application schema를 처음부터 세운다. `db/postgres/v1/*.sql`이 스키마의 단일 기준이다.…, application_schemas() (+18 more)

### Community 376 - "DependencyDeclarationTest"
Cohesion: 0.22
Nodes (5): _declared_groups(), DependencyDeclarationTest, 의존성을 선언하는 자리는 `pyproject.toml` 하나다. 전에는 `requirements/*.txt` 31개와 루트…, 안내가 가리키는 group이 그 패키지를 실제로 담고 있어야 한다., TradingAgents는 git 의존이라 lock에 넣지 않는다 — 그러면 모든 CI가 그 저장소의 가용성에 묶인다. 대신 검증된…

### Community 377 - "features/etl.py"
Cohesion: 0.22
Nodes (8): load_market_prices_since(), v1 market 봉을 현재 ticker 표기로 투영해 끝까지 읽는다., Core runner for technical indicators., load_prices(), DataFrame, date, 지표 계산에 필요한 만큼의 market.prices_daily 롤링 윈도우를 읽어 온다. Supabase 접근은 이 패키지의 db.py를…, 최근 rolling_days 거래일 분량의 prices_daily(전 종목) → DataFrame. 반환 컬럼: ticker ·…

### Community 378 - "Universe watchlists — 관심 기업 & 토스증권 보유종목 동기화"
Cohesion: 0.18
Nodes (11): 0. 관련 문서 및 전체 위치, 1. 전체 관심종목 파이프라인 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 관련 코드 및 데이터 흐름, 4. 관심종목 CLI 관리 명령어, 5. 토스증권 계좌 보유종목 동기화 (고정 IP 로컬 전용), 6. 수정할 때 확인할 곳, Multi-Source 관심종목 관리 (`sources = ['manual', 'toss']`) (+3 more)

### Community 379 - "Discord Admin — 코드 기반 선언적 Discord 서버 관리 (IaC)"
Cohesion: 0.17
Nodes (12): 0. 관련 문서 및 전체 위치, 1. 전체 서버 구조 및 카테고리 분류, 2. 핵심 개념 (초보자 가이드), 3. 채널 구조 및 역할 권한 매트릭스, 4. 관련 코드 및 디렉토리 구조, 5. 실행 및 동기화 가이드 (로컬 전용), 6. 수정할 때 확인할 곳, Discord Admin — 코드 기반 선언적 Discord 서버 관리 (IaC) (+4 more)

### Community 380 - "Tracked universe 후보 선정"
Cohesion: 0.33
Nodes (6): Tracked universe 후보 선정, 안전 경계, 예시 해석, 운영 확인, 점수 입력, 정렬 순서

### Community 381 - "AGENTS.md"
Cohesion: 0.40
Nodes (4): 스킬 — 그 영역을 만지기 전에 해당 SKILL.md를 읽으세요, 실행 환경 노트, 코드 지식 그래프 — graphify, 하지 말 것

### Community 382 - "KindsWiringTest"
Cohesion: 0.29
Nodes (3): KindsWiringTest, `--kind`가 실제로 존재하는 러너를 가리키는지 검증한다. 배선이 어긋나면 import 에러가 아니라 실행 시점에야 드러난다 — 그때는…, 가짜 케이스를 반환하던 패키지가 되살아나면 지어낸 분석이 발송된다.

### Community 383 - "10. 데이터 시각화"
Cohesion: 0.40
Nodes (5): 10.1 기본 원칙, 10.2 차트 색 배정, 10.3 차트별 규칙, 10.4 테마별 Plotly 기준, 10. 데이터 시각화

### Community 384 - "test_continuous_retrain_exit_code.py"
Cohesion: 0.14
Nodes (9): Research 명령 진입점 패키지. import는 명시적이며 부작용이 없다., _decision(), EmptyLedgerRaisesNotReadyTest, ExitCodeTest, NotReadyIsASafetyErrorTest, PromotionDecision, 재학습 진입점의 종료 코드가 "무엇이 잘못됐나"만 말하게 한다. 실측 2026-09-04: `continuous_learning` 잡이 매일…, 기존 호출부가 RLSafetyError로 잡고 있으므로 하위 타입이어야 한다. (+1 more)

### Community 385 - "FundamentalsArchitectureTest"
Cohesion: 0.30
Nodes (5): FundamentalsArchitectureTest, _imports(), Path, _python_files(), fundamentals 계층 경계와 기준 진입점을 검증한다.

### Community 386 - "_domain_precisions"
Cohesion: 0.33
Nodes (6): _declared_precisions(), _domain_precisions(), 일정 정확도의 목록은 도메인과 저장소가 같아야 한다. `domain/releases/schedule.py`의…, 반대 방향도 본다 — 쓰지 않는 값을 받아 두면 오타가 그대로 저장된다., 대상을 못 찾으면 위 두 검사는 공허하게 통과한다., SchedulePrecisionContractTest

### Community 387 - "test_operational_guardrails.py"
Cohesion: 0.16
Nodes (5): EmptySourceTest, LazySupabaseClientTest, 권한·빈 응답·지연 DB 초기화 같은 운영 안전장치 회귀 테스트., 추적 대상과 화면 해석은 코드 설정, SEC filing/position만 DB가 소유한다., SqlContractTest

### Community 388 - "test_macro_release_watch_dedup.py"
Cohesion: 0.09
Nodes (10): macro: 매크로 시장 지표 알림 묶음 (core·watch). 데이터 조회와 outbox 선점은 이 패키지의…, NotificationLedgerTest, 경제발표 사실과 v1 notifications outbox의 경계를 검증한다., _Config, CoreDedupTest, v1 macro core entrypoint의 중복 방지 계약., 경제 캘린더와 v1 macro watch의 dedup 의미를 검증한다., ReleaseDedupTest (+2 more)

### Community 389 - "report.py"
Cohesion: 0.19
Nodes (10): coverage_rows(), dossier_sections(), DossierSectionSpec, 대시보드와 문서가 공유하는 Evidence Dossier 준비 상태 보고서., 읽기 전용 DB 감사 시점의 coverage를 화면용 행으로 돌려준다., 목표 서류철의 섹션과 현재 소비 가능 상태를 고정한다., PIT 밸류에이션 계약의 사용자 검토용 요약이다., 서류철 한 섹션의 표시·소비 계약이다. (+2 more)

### Community 390 - "16. 구현 계약"
Cohesion: 0.40
Nodes (5): 16.1 CSS 변수 계약, 16.2 코드 SSOT, 16.3 명명 규칙, 16.4 구현 반영 시 확인할 항목, 16. 구현 계약

### Community 392 - "9. 핵심 컴포넌트"
Cohesion: 0.18
Nodes (11): 9.10 승인·주문·위험 행동, 9.1 버튼, 9.2 카드, 9.3 Metric, 9.4 Data row와 Table, 9.5 Chip, Badge, Status, 9.6 입력과 선택, 9.7 Navigation (+3 more)

### Community 393 - "split_dataset"
Cohesion: 0.33
Nodes (3): 뒤쪽 구간을 평가용으로 떼어낸다. 학습한 구간에서 채점하면 어떤 정책도 통과한다., split_dataset(), SplitDatasetTest

### Community 394 - "2. 핵심 결정과 우선순위"
Cohesion: 0.40
Nodes (5): 2.1 핵심 결정 요약, 2.2 충돌 시 우선순위, 2.3 규칙의 강도와 적용 단위, 2.4 매체별 적용 범위, 2. 핵심 결정과 우선순위

### Community 395 - "trading/contracts.py"
Cohesion: 0.06
Nodes (61): 시장 가격을 Dashboard용 regime read model로 투영한다., LLM 입출력과 저장 행을 검증하는 엄격한 계약., AnalystSignal, Event, MarketRegime, 네이티브 투자 판단 계층이 공유하는 작고 검증 가능한 계약., 종목별 판단보다 먼저 공유되는 시장 환경 snapshot이다., Market/Fundamental/Macro/Event desk가 공통으로 반환하는 신호. (+53 more)

### Community 396 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 397 - "3. 제품 철학"
Cohesion: 0.40
Nodes (5): 3.1 먼저 이해시키고, 그다음 행동시킨다, 3.2 사용자의 인지 부하를 대신 짊어진다, 3.3 단순함은 정보 삭제가 아니라 우선순위다, 3.4 차분하지만 모호하지 않다, 3. 제품 철학

### Community 398 - "retry_on_5xx"
Cohesion: 0.20
Nodes (13): _fred_slot(), fetch_batch(), fetch_release_dates(), date, FRED 발표 일정(release/dates) 어댑터. macro/clients/fred.py는 관측치(series/observations)를…, release_id 하나의 발표 예정일을 [start, end] 구간으로 잘라 반환한다.…, 릴리스 단위로 한 번씩만 호출한다. 지표 14종이 릴리스 9개를 공유하므로(CPI·Core CPI가 release 10 하나) 지표마다 부르면…, fetch_gdpnow() (+5 more)

### Community 399 - "Fundamentals"
Cohesion: 0.33
Nodes (6): canonical 저장 모델, Fundamentals, 소유 구조, 스냅샷 보존, 실행 진입점, 읽기 규칙

### Community 400 - "Universe v1"
Cohesion: 0.40
Nodes (5): 30초 예시: Alphabet, Universe v1, 실행 흐름, 안전 규칙, 저장 계약

### Community 401 - "is_earnings_item"
Cohesion: 0.32
Nodes (7): classify_8k_items(), extract_item_numbers(), is_earnings_item(), 8-K Item 번호를 외부 SDK 없이 분류한다., SEC metadata나 HTML 텍스트에서 중복 없는 Item 번호를 순서대로 뽑는다., 8-K를 실적·임원변동·기타 중 하나로 분류한다., 최초 Form 8-K의 Item 2.02인지 반환한다.

### Community 402 - "validate_series"
Cohesion: 0.39
Nodes (3): 지표별 수집 계약을 확인하고 명백한 단위·스파이크 오류를 차단한다. ``source_params.validation``은 원천값을 화면 단위로…, validate_series(), SeriesContractTest

### Community 403 - "HarnessModuleAllowlistTest"
Cohesion: 0.40
Nodes (3): HarnessModuleAllowlistTest, 등록만 하고 allowlist에 안 넣으면 런타임에서야 드러난다., allowlist에 실행할 수 없는 이름이 들어가면 그 단계는 런타임에야 죽는다. `python -m X`가 성립하는 경우는 둘이다 — 모듈이…

### Community 404 - "UniverseArchitectureTest"
Cohesion: 0.21
Nodes (8): _imports(), Path, _python_files(), universe 계층 경계를 검증한다. fundamentals의 test_architecture.py와 같은 패턴., application은 infrastructure.sources와 domain만 안다.…, repository.py/persistence.py/watchlists/*는 application·commands가 소비하는 쪽이다 — 거꾸로…, 이 계층화 작업에서 지운 옛 평면 구조 파일이 재도입 shim으로 다시 생기지 않았는지 본다. stale import를 "고친다"며 한 줄짜리…, UniverseArchitectureTest

### Community 405 - "test_filing_xbrl_fallback.py"
Cohesion: 0.15
Nodes (9): SEC EDGAR와 FSDS 외부 데이터 어댑터., CompanyFacts 최신 반영 지연 시 filing XBRL 변환 회귀 테스트., XbrlParserContractTests, _companyfacts_row(), _filing(), CompanyFacts가 덮는 공시는 문서를 받지 않는다. CompanyFacts는 XBRL **차원을 버린다.** 그래서 어떤 공시가…, CompanyFacts에 없다 = 차원이 있었다 = 문서를 봐야 클래스를 안다., 클래스를 나중에 만든 기업의 과거 기간이 사라지면 안 된다. 전에는 클래스가 하나라도 보이면 CompanyFacts를 통째로 버렸고, 게다가… (+1 more)

### Community 406 - "earnings/metrics.py"
Cohesion: 0.23
Nodes (15): _yoy(), as_float(), _cash(), derive(), _eps_diluted(), _fcf(), _margin(), _net_debt() (+7 more)

### Community 407 - "SourceBudgetTest"
Cohesion: 0.19
Nodes (7): Macro 외부 연동과 원천 adapter의 infrastructure 계층., _indicator(), 소스별 벽시계 예산 — 느린 출처 하나가 수집 전체를 삼키지 못하게 한다. ECOS가 응답하지 않던 날, 요청당 30초 타임아웃에 재시도…, clock_steps를 monotonic 반환값으로 흘려보내며 3개 지표를 수집한다., 예산이 잡 캡(20분)보다 크면 상한을 둔 의미가 없다., _series(), SourceBudgetTest

### Community 408 - "EconSnapshotShapeTest"
Cohesion: 0.14
Nodes (11): 무엇을 살지 정하는 계층. 흐름은 한 방향이다: **근거 → 판단 → 포트폴리오 → 위험 → (실행 의도)**. 마지막 한 걸음만…, EconSnapshotShapeTest, AI 경제 근거는 macro owner가 실제로 주는 행 모양 위에서 조립된다. 전에는 이 검사가 손으로 지어낸 `record_kind` 행을…, owner의 계약에 있는 키만으로 행 하나를 만든다., 자체 모델은 컨센서스가 없을 때의 대체지 같은 무게의 근거가 아니다., EconSnapshotSizeTest, 경제 근거가 evidence bundle을 삼키지 않게 한다. 실측(2026-09-03): 번들 202,724자 중…, release 그룹에 이미 있는 값을 평면 키로 또 담으면 프롬프트만 커진다. (+3 more)

### Community 409 - "validate_live_candidate_as_of"
Cohesion: 0.32
Nodes (3): 현재 universe·비버전 자식 데이터로 과거 후보를 재구성하지 못하게 한다., validate_live_candidate_as_of(), CandidateLiveCutoffTest

### Community 410 - "40_macro.sql"
Cohesion: 0.39
Nodes (11): forecast_keeper, macro.economic_observations, macro.forecast_snapshots, macro.market_observations, macro.measures, macro.prune_release_snapshots(), macro.release_events, macro.release_schedule_versions (+3 more)

### Community 411 - "5. 색 시스템"
Cohesion: 0.20
Nodes (10): 5.1 브랜드 원색, 5.2 라이트 모드 중성 원색, 5.3 다크 모드 중성 원색, 5.4 금융 방향 원색, 5.5 접근성 보정 방향 토큰, 5.6 상태색과 방향색의 분리, 5.7 라이트·다크 시맨틱 매핑, 5.8 색 사용 금지 (+2 more)

### Community 412 - "resolve_flash_period"
Cohesion: 0.29
Nodes (10): _as_date(), fiscal_calendar(), _next_period(), project_forward(), date, 8-K 실적 속보를 회사의 실제 회계분기에 붙인다. 달력 월로 분기를 매기면 안 된다. 1월 결산…, 8-K 공시일에 대응하는 (회계연도, 회계분기, 기간종료일)을 돌려준다. 실적 8-K는 그 분기가 끝난 직후에 나온다. 따라서 공시일…, financial_versions 행을 period_end 순 회계력으로 정리한다. (+2 more)

### Community 413 - "저장 계층 전면 개편 인계 메모"
Cohesion: 0.15
Nodes (12): PostgreSQL DDL과 canonical writer, Research와 Intelligence, `src/` 패키지 구조 정리 결과, Storage foundation 전환 결과, 다음 작업 순서, 로컬 Runtime, 새 세션 시작 지시문, 저장 계층 전면 개편 인계 메모 (+4 more)

### Community 414 - "_LabelRepository"
Cohesion: 0.20
Nodes (3): BuildLabelsEntryTest, _LabelRepository, label 생산 경로가 쓰는 조회만 흉내낸다.

### Community 415 - "test_research_store_read_paths.py"
Cohesion: 0.28
Nodes (6): Call, _offenders(), 읽기만 하는 경로는 research 저장소를 쓰기로 열지 않는다. DuckDB는 쓰기 연결에 배타 잠금을 건다. 읽으면서 쓰기로 열면 같은…, 호출이 없으면 아래 검사는 아무것도 보증하지 않는다., _read_only_kwarg(), ResearchStoreReadPathTest

### Community 416 - "WorkflowNameTest"
Cohesion: 0.40
Nodes (3): CLAUDE.md 관례 11 — name:이 파일명과 다르면 workflow_run이 발화하지 않는다., 이어 붙은 YAML은 파서가 뒤 키를 택해 앞쪽 결함을 조용히 숨길 수 있다., WorkflowNameTest

### Community 417 - "11. 라이트·다크 모드 운영"
Cohesion: 0.50
Nodes (4): 11.1 테마 선택, 11.2 동일하게 유지할 것, 11.3 테마마다 바꿀 것, 11. 라이트·다크 모드 운영

### Community 418 - "14. 보이스 앤 톤"
Cohesion: 0.50
Nodes (4): 14.1 기본 문체, 14.2 문장 순서, 14.3 데이터 확실성 문구, 14. 보이스 앤 톤

### Community 419 - "social_source.py"
Cohesion: 0.25
Nodes (7): fetch_finnhub_sentiment(), fetch_reddit_posts(), fetch_stocktwits_messages(), TradingAgents Social Analyst를 위한 소셜 미디어(StockTwits/Reddit) 센티먼트 데이터 소스 어댑터., StockTwits 최근 심볼 메시지 스트림을 수집한다., Reddit 토론 검색 피드를 수집한다., Finnhub 소셜 감성(Reddit/Twitter 멘션 및 긍부정 스코어) 정량 데이터를 수집한다.

### Community 420 - "2. 핵심 헬퍼 모듈 사용법"
Cohesion: 0.22
Nodes (9): 0. 관련 문서 및 전체 위치, 1) Supabase 클라이언트 및 대량 페이징 (`db/postgres.py`), 1. 주요 모듈 맵 및 역할, 2) JSON 구조화 로깅 (`logging.py`), 2. 핵심 헬퍼 모듈 사용법, 3. 수정할 때 확인할 곳, 3) 재시도 데코레이터 (`retry.py`), 4) 토스 OAuth 캐시 및 락 (`src/investment_agent/execution/brokers/toss/auth.py`) (+1 more)

### Community 421 - "download_monthly_close"
Cohesion: 0.22
Nodes (9): market read model을 전략 입력으로 변환한다., download_monthly_close(), _last_complete_month_end(), DataFrame, date, Timestamp, market owner가 적재한 일봉에서 전략용 월말 종가를 읽는다., 가장 최근에 끝난 달의 마지막 날 (KST 기준). (+1 more)

### Community 422 - "6. 타이포그래피"
Cohesion: 0.50
Nodes (4): 6.1 서체, 6.2 타입 스케일, 6.3 금융 숫자 표기, 6. 타이포그래피

### Community 423 - "8. 모양, 보더, 깊이"
Cohesion: 0.50
Nodes (4): 8.1 Radius, 8.2 보더, 8.3 그림자, 8. 모양, 보더, 깊이

### Community 424 - "lifecycle.py"
Cohesion: 0.23
Nodes (10): AutonomyCriteria, AutonomyEvidence, LifecycleDecision, LifecyclePromotionGate, LifecycleStage, Enum, str, BACKTEST→SHADOW→PAPER→LIVE_MANUAL→LIVE_AUTONOMOUS 운영 승격 경계. (+2 more)

### Community 425 - "SetMembershipTest"
Cohesion: 0.25
Nodes (4): 수집 게이트를 정하는 자리다. 여기서 틀리면 모든 하류가 조용히 더 돈다. 실제로 두 가지가 함께 틀려 있었다. * 과거 멤버 행에는…, `is_tracked` 키가 없는 행은 게이트에 대해 아무 말도 하지 않는다., 현재 멤버인데 마스터에 없으면 CIK를 모른다 — 지어내면 재무가 영영 안 붙는다., SetMembershipTest

### Community 426 - "Institutional — SEC 13F 원천·유효 포트폴리오"
Cohesion: 0.40
Nodes (5): Institutional — SEC 13F 원천·유효 포트폴리오, 거장을 한 명 늘리려면, 구조, 실행, 정확성 규칙

### Community 428 - "Market v1"
Cohesion: 0.50
Nodes (4): Market v1, 보존 정책, 실행 흐름, 저장 계약

### Community 429 - "valuation/engine.py"
Cohesion: 0.24
Nodes (8): build_pit_valuation(), _decimal(), _missing(), _ratio(), PIT 밸류에이션 입력과 관측값의 순수 계산 계약., 유한한 수치만 Decimal로 정규화한다., 미래 입력을 차단하고 의미 있는 밸류에이션 비율만 계산한다., ValuationInputsTest

### Community 430 - "earnings_report/__init__.py"
Cohesion: 0.17
Nodes (3): fundamentals: 관심종목 실적 공시(10-Q/10-K) 알림. 트리거: 펀더멘탈·세그먼트 ETL 이후 실행 — 관심종목의 미발송 신규…, HistoricalCardTest, 연 단위는 점이 다섯 개뿐이라 계절성도 이번 분기 위치도 안 보인다.

### Community 431 - "normalize_accession"
Cohesion: 0.38
Nodes (4): normalize_accession(), 공시 번호를 표준 모양으로. 읽을 수 없으면 `None`. 하이픈 없는 18자리로 오는 소스가 있다. 그대로 저장하면 같은 공시가 두 키로…, AccessionTest, 같은 공시가 두 키로 남으면 재처리가 영영 끝나지 않는다.

### Community 433 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 434 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 435 - "_submissions_document"
Cohesion: 0.25
Nodes (6): SEC submissions JSON -> 내부 공시 dict 매핑 계약. 여기서 어긋나면 예외가 아니라 **0건**으로 끝난다. 세그먼트…, SEC submissions 응답의 모양을 그대로 흉내 낸다(키 이름이 계약의 전부다)., 두 날짜가 뒤바뀌면 조회 창이 영원히 빗나가고 보존 삭제가 엉뚱한 행을 지운다., 보고기간이 아니라 제출일로 잘라야 '최근 N일에 들어온 공시'가 된다., _submissions_document(), SubmissionsMappingTest

### Community 436 - "VersionSelectionTest"
Cohesion: 0.18
Nodes (5): canonical 정책: 기간별 한 행만 있고, 정정 전 숫자는 복원하지 않는다 — 의도적 한계다(repository.py의…, PK에 accession_no가 없어도 기간별 최대 한 행이라는 계약은 지켜야 한다., canonical 정책에서는 '그때 우리가 알던 값'을 복원하지 않는다 — 그 시점에 아직 공시가 없었다는 사실만 반영해 행을 통째로 제외한다., canonical 정책은 정정 횟수를 재현하지 않는다 — 항상 빈 목록이다., VersionSelectionTest

### Community 437 - "10_universe.sql"
Cohesion: 0.53
Nodes (4): universe.entities, universe.index_memberships, universe.securities, universe.security_identifiers

### Community 438 - "run"
Cohesion: 0.47
Nodes (5): check(), main(), 실제 Supabase에 붙어 각 서브시스템의 조회 경로를 한 번씩 태워 보는 점검 도구. python…, 조회 하나를 태워 보고 결과를 모은다. ``target``이 ``(module, "attr")`` 이면 속성을 **호출 시점에** 찾는다.…, run()

### Community 439 - "LocalArtifactStore"
Cohesion: 0.24
Nodes (7): LocalArtifactStore, Any, Path, 같은 디렉터리에 임시 파일로 쓴 뒤 rename. 중간에 죽어도 반쪽 파일이 남지 않는다. 반쪽 파일이 남으면 지문이 맞지 않아 읽기가…, 작업 트리 밖의 디렉터리에 내용 주소로 쌓는다., canonical JSON으로 저장한다 — 같은 내용이 항상 같은 지문을 갖도록., _write_atomically()

### Community 440 - "_entrypoints"
Cohesion: 0.23
Nodes (8): _calls_start_cli(), CliEntrypointContractTest, _entrypoints(), Path, CLI 진입점은 전부 같은 준비 과정을 거친다. `configure_logging()`이 안 불리면 루트 로거에 처리기가 없고,…, `python -m ...`으로 실행되도록 만든 모듈 — `__main__` 블록이 그 표식이다., 수집 규칙이 어긋나면 이 파일의 모든 검사가 공허하게 통과한다., 이름만 바뀌고 로깅 설정이 빠지면 위 검사는 통과한 채 로그만 사라진다.

### Community 441 - "platform/artifacts.py"
Cohesion: 0.31
Nodes (8): _check_digest(), _check_namespace(), _parse_uri(), RuntimeError, 큰 산출물을 DB 밖에 두고, DB에는 주소와 지문만 남긴다. ## 왜 DB에서 뺐나 판단 근거 번들은 한 건에 수십 KB다. 그것을…, 저장물을 읽을 수 없거나 지문이 맞지 않는다., StorageError, 근거는 내용 주소로 쌓이고, 바뀌면 읽을 때 걸린다.

### Community 442 - "EntityMention"
Cohesion: 0.18
Nodes (9): EntityMention, 어떤 글이 어떤 종목을 언급했다는 사실. `match_kind`는 그 사실을 어떻게 알았는지를 남긴다 — 조회해서 받은 것과 본문에서 찾아낸…, _article(), _post(), 90일 보존 경계. 기준 시각은 수집 시각이 아니라 발행 시각이다., 오래된 글을 오늘 수집해도 오래된 글이다., source_id만으로 지우면 보존 기간 안의 mention이 함께 사라진다. news와 social의 id 문자열 공간은 서로…, 뉴스와 소셜이 한 색인을 쓰므로, 정리 조회를 종류로 좁히지 않으면 뉴스 차례에 소셜 행까지 지운다 — 개수는 0으로 보고되면서. (+1 more)

### Community 443 - "NewsSocialPageTest"
Cohesion: 0.27
Nodes (5): _imports(), NewsSocialPageTest, Path, News/Social 화면의 경계. 화면은 reporting 계약만 읽는다., 이 페이지는 새 경로가 실제로 성립하는지 보이는 증거다.

### Community 444 - "PriceTargetTest"
Cohesion: 0.33
Nodes (3): PriceTargetTest, 발표를 보고 조정된 목표가 섞이면 같은 시점 비교가 깨진다., 컨센서스가 없어도 목표주가만으로 '주가'에 녹일 게 있다.

### Community 445 - "decision_and_apply_dates"
Cohesion: 0.33
Nodes (5): decision_and_apply_dates(), DataFrame, date, 날짜 보조 함수 (기준일=decision·적용일=apply 계산)., 기준일(decision)=가장 최근 끝난 달의 마지막 날, 적용일(apply)=그 다음 달 1일. KST 기준.

### Community 446 - "releases/test_db.py"
Cohesion: 0.10
Nodes (5): AlfredParserTest, IdentityTest, IngestTest, ECON 자연키·원자료 단일 저장·시간 보존 경계의 오프라인 테스트., WriterTest

### Community 447 - "pending_filings"
Cohesion: 0.36
Nodes (5): pending_filings(), 완료 장부에 없는 XBRL 공시만 반환한다. A ticker with no stored fundamentals is seeded from…, _filing(), PendingFilingsTest, Fundamentals 일간 워터마크가 같은 날의 추가 공시를 놓치지 않는지 검증한다.

### Community 448 - "Native Autonomous Investment System"
Cohesion: 0.25
Nodes (7): Native Autonomous Investment System, Rollout 상태, 이 계층이 쓰는 테이블, 저장 경계, 학습 표본과 승격, 핵심 계약 흐름, 현재 구조

### Community 449 - "content_index"
Cohesion: 0.29
Nodes (4): content_index, entity_mentions, intelligence_freshness, ticker_mention_daily

### Community 450 - "discord_admin/guide.py"
Cohesion: 0.32
Nodes (7): Any, #시작하기·#서버-규칙에 붙는 안내문의 단일 기준(SSOT). 문구를 스크립트로 한 번 올리고 마는 대신 여기에 둔다 — 카드가 바뀌면…, #서버-규칙 — 참여 규칙과, 카드를 잘못 읽지 않기 위한 전제., #시작하기 — 여기가 무엇을 하는 곳이고, 어디를 열면 되고, 언제 오는가., rules(), _schedule_table(), welcome()

### Community 451 - "Path"
Cohesion: 0.21
Nodes (6): CodexSkillIndexTest, OpenSourceDocumentationTest, Path, 공개 저장소의 최소 문서 표면과 개인 환경정보 차단을 고정한다., Codex는 스킬을 자동 발견하지 않는다 — AGENTS.md가 전부 가리켜야 한다., 두 도구가 같은 규칙을 받아야 한다. 한쪽에만 스킬이 있으면 지침이 갈린다.

### Community 452 - "v1 내부 정리 로드맵"
Cohesion: 0.18
Nodes (9): Architecture test 보강 (위 항목과 별개로 계속 추가), P3. Dashboard `db.py` 해체 (약 104KB), P4. `research/strategies` → Yahoo 직접 접근 제거, P5. Market 과거 Daily 원본 보존, v1 내부 정리 로드맵, 배경, 우선순위, 이번 세션에서 하지 않은 것 (+1 more)

### Community 453 - "MarketArchitectureTest"
Cohesion: 0.26
Nodes (6): _imports(), MarketArchitectureTest, Path, _python_files(), market 계층 경계를 검증한다. universe의 test_architecture.py(최종 수정본)와 같은 패턴 — 이름이 실제로…, application은 infrastructure.sources와 domain만 안다. universe의 최종 리뷰에서 정착된 것과 같은…

### Community 454 - "retry.py"
Cohesion: 0.09
Nodes (22): HTTPError, HTTPStatusError, _is_retryable(), is_transient(), network_retry(), _policy(), Any, BaseException (+14 more)

### Community 456 - "news_social.py"
Cohesion: 0.15
Nodes (9): _freshness_frame(), Any, DataFrame, News/Social 수집 상태 화면. ## 왜 intelligence.py가 아닌가 `app_pages/intelligence.py`는 이미…, _render_runs(), 저장소별 읽기 경계. 파일 이름이 "어디서 오는가"를 말한다. reporting이 존재하는 이유가 그 질문을 화면과 알림에서 감추는 것이다 —…, NewsProviderTests, 뉴스 provider의 정규화와 fail-closed 정책을 검증한다. (+1 more)

### Community 457 - "InstitutionalSchemaContractTest"
Cohesion: 0.18
Nodes (5): InstitutionalSchemaContractTest, institutional v1 SQL이 §9의 세 표와 universe 매핑 경계를 지키는지 검증한다., manager(name/fund_name/is_active)는 SEC 사실이 아니라 우리가 고른 추적 대상이라 Supabase 표가 아니라…, SEC raw XML의 투표권·투자재량 상세는 더 이상 저장하지 않는다 — 사실 컬럼만 남기는 간소화다(파일 상단 주석 참고)., manager 사실(name/fund_name/is_active)과 화면 해석(strategy_group· signal_role 등)은…

### Community 458 - "strategies/catalog.py"
Cohesion: 0.29
Nodes (5): 공용 카탈로그(`investment_agent.research.strategies.catalog`)에서 파생한 알림용 전략 라벨 모음., ensure_registered_strategies(), 계산기와 알림이 공유하는 전략 메타데이터., Fail fast when compute registration and metadata drift apart., StrategyMeta

### Community 459 - ".bars"
Cohesion: 0.12
Nodes (9): configure(), Any, date, datetime, 전체 market에서 가장 최근 거래일. 수집 잡의 진행 상태 로그용이다., 전체 종목의 특정 날짜 이후 시세 원시 행. `DailyBar.from_row()` 검증을 거치지 않는다 — 일별 수집이 기존 값과 비교만…, 구간 봉. ``known_at``은 API 호환성을 위해 받지만 시장 가격에는 적용하지 않는다. 일별 가격의 공개 가능성은 거래 세션으로…, 그날 종가만. 횡단면 조회의 주 경로다. (+1 more)

### Community 460 - "releases/baseline.py"
Cohesion: 0.27
Nodes (11): _diffs(), drift_forecast(), _predict(), _quantile(), 자체 베이스라인 예상값 — 외부 의존 없는 순수 로직. 무료 컨센서스가 없는 지표(23종 중 22종)를 위한 최소한의 기준선이다. **이건…, 선형 보간 분위수. 표본이 작아 numpy를 끌어오지 않는다., 최근 points개 시점에서 그 방법을 실제로 걸어 봤을 때의 중앙 절대오차., 이 지표에 지금 맞는 방법('drift' 또는 'naive'). 증거가 뚜렷할 때만 추세를 좇는다(SELECT_MARGIN). 채점이 안… (+3 more)

### Community 461 - "_run_backfill"
Cohesion: 0.33
Nodes (7): main(), _parse_yyyymm(), date, 지정한 달부터 이번 달 직전까지, 매달의 결과를 다시 계산해 저장한다(이미 보낸 것으로 표시)., _run_backfill(), compute_all(), 6개 전략을 모두 계산한다. 하나라도 불완전하면 전체 실행을 실패시킨다.

### Community 462 - "FullPortfolioSchemaTest"
Cohesion: 0.23
Nodes (4): FullPortfolioSchemaTest, trading·execution 모두 Supabase가 아니라 실행 컴퓨터 로컬 runtime.sqlite3가 소유한다 — RLS로 지킬…, trading은 execution snapshot을 가리키되 FK로 계층 방향을 뒤집지 않는다., Postgres `approve_model_promotion` 함수의 FOR UPDATE 잠금을 대신해, 로컬 SQLite에서는…

### Community 463 - "operations_view.py"
Cohesion: 0.40
Nodes (5): operations_links(), Discord-first 운영 로그 위치와 확인 순서를 안내한다., 설정된 운영 링크만 안전한 HTTPS URL로 반환한다., DB 조회 없이 운영 기록의 단일 확인 경로를 보여준다., render_operations_guide()

### Community 464 - "SharedSetupTest"
Cohesion: 0.22
Nodes (4): 준비 단계는 composite action 하나로 모은다. 공통 설정을 한 곳에서 검증해 모든 workflow가 같은 Python·secret…, 로그는 공개될 수 있다. 없는 것의 이름만 말하고 값은 절대 찍지 않는다., 옮기고 나서 목록에 남겨두면 그 목록이 거짓말을 시작한다., SharedSetupTest

### Community 465 - "us_market_today"
Cohesion: 0.05
Nodes (28): Clock, completed_us_daily_bar_cutoff(), day_window(), FixedClock, date, datetime, Protocol, 뉴욕 시장이 관측하는 날짜를 반환한다. (+20 more)

### Community 466 - "actions_budget.py"
Cohesion: 0.43
Nodes (6): main(), _observed_minutes(), _parse_workflows(), GitHub Actions 월 사용량을 cron 빈도 × 실측 실행시간으로 추정한다. 무료 할당은 초과해도 경고가 오지 않고 그냥 잡이 돌지…, cron 한 줄이 한 달에 몇 번 도는지. 이 저장소가 쓰는 문법만 다룬다., _runs_per_month()

### Community 467 - "twap.py"
Cohesion: 0.20
Nodes (7): datetime, 대량 주문 시간 분할(TWAP) 집행 슬라이서. 단일 주문의 시장 충격(Market Impact)과 슬리피지를 최소화하기 위해, 지정된 시간…, 주문을 N개의 TWAP 슬라이스로 분할한다 (총 수량 보존)., TWAPOrderSlicer, TWAPSlice, TWAPOrderSlicer 단위 테스트., TWAPTests

### Community 468 - "main"
Cohesion: 0.33
Nodes (5): main(), build(), Any, Server Guide(온보딩)의 단일 기준(SSOT). 처음 들어온 사람이 보는 화면이다. 채널 16개를 한꺼번에 보여 주면 어디부터 열어야…, 채널·역할 key -> ID 표를 받아 Discord가 받는 온보딩 payload를 만든다. 서버에 없는 key는 조용히 빠진다 —…

### Community 469 - "SegmentSnapshotOrderTest"
Cohesion: 0.46
Nodes (3): _metrics(), 세그먼트 스냅샷이 고르는 20행은 조회 순서에 흔들리지 않는다. 정렬 기준이 매출 하나뿐이면 매출이 없는 행들이 전부 동점이고, 파이썬 정렬은…, SegmentSnapshotOrderTest

### Community 470 - "Operations — Discord-first 운영 관측과 로컬 하네스"
Cohesion: 0.29
Nodes (7): DB 기준, Discord 채널과 환경변수, Operations — Discord-first 운영 관측과 로컬 하네스, 기록 경계, 로컬 하네스 안전 제어, 장애를 확인하는 순서, 핵심 구성

### Community 471 - "discord_admin/sync.py"
Cohesion: 0.31
Nodes (9): _by_name(), env_updates(), plan(), Any, 매니페스트와 실제 서버를 대조해 할 일을 계산하는 순수 로직. 네트워크를 건드리지 않는다 — 픽스처로 검증할 수 있어야 '무엇을 만들지'를…, 매니페스트 기준으로 (생성할 카테고리, 생성할 채널, 이미 있는 것, 매니페스트에 없는 것)., 이미 있는 포럼 중 태그가 매니페스트와 다른 것. 태그는 이름 집합만 본다 — 순서까지 맞추려 들면 사람이 Discord에서 정렬만 바꿔도…, .env에 써 넣을 {변수: 채널ID}. (+1 more)

### Community 472 - "yahoo.py"
Cohesion: 0.08
Nodes (29): is_split_ratio(), normalize_split_adjusted_prices(), 주식분할 이벤트와 가격 보정을 정규화하는 공용 함수., 0보다 크고 1이 아닌 유효한 주식분할 비율인지 반환한다., 전체 재다운로드 가격이 액션일에서 다시 분할 점프하지 않는지 검증한다., Adj Close가 OHLC와 같은 잘못된 basis인지 연속성으로 판정한다., Normalize Yahoo's occasionally mixed pre/post-split price basis., _scale_adjusted_close_with_price() (+21 more)

### Community 473 - "build_valuations.py"
Cohesion: 0.21
Nodes (11): main(), _number(), _parse_args(), Any, Decimal, Namespace, 거래일마다 PIT 밸류에이션 관측값을 계산해 원장에 적재한다. Phase 0 감사 결론에 따라 **live_shadow만** 만든다. 과거…, Decimal을 JSON 직렬화 가능한 형태로 낮춘다. (+3 more)

### Community 474 - "process_segment_cik"
Cohesion: 0.33
Nodes (6): process_segment_cik(), Any, date, 세그먼트 공시 처리 상태를 저장소 행으로 만든다., CIK 한 건의 새 공시 문서를 파싱해 저장 전 결과를 만든다., segment_filing_row()

### Community 475 - "test_channel_names_are_declared.py"
Cohesion: 0.36
Nodes (5): _declared_names(), MentionedChannelsExistTest, _mentions(), 문서와 코드가 부르는 Discord 채널 이름은 선언에 실재해야 한다. 채널 구조는 `discord_admin/manifest.py`가…, 대상을 못 찾으면 이 테스트는 공허하게 통과한다.

### Community 476 - "change_manifest.py"
Cohesion: 0.53
Nodes (5): earliest_change_since(), manifest_path(), Path, Market 수집 변경 manifest. 가격 fact에 local ingestion timestamp를 중복 저장하지 않는다. feature…, record_change_dates()

### Community 479 - "10. Intelligence: Parquet로 옮길 때 필요한 운영 계약"
Cohesion: 0.29
Nodes (7): 10.1 현재 데이터 보존과 책임, 10.2 파일 구성과 시간, 10.3 Parquet 게시와 중복 제거, 10.4 조회 예시의 한계, 10.5 DuckDB 동시성 보완, 10.6 TTL과 장애 상태, 10. Intelligence: Parquet로 옮길 때 필요한 운영 계약

### Community 480 - "_complete_tail"
Cohesion: 0.50
Nodes (5): _complete_tail(), index_series(), Series, 최신 월을 포함한 연속 n개월 수익률만 반환한다., 수익률을 누적해 '가격 흐름' 곡선으로 바꾼다 (평균선 계산에 사용).

### Community 481 - "PostgresSchemaLayoutTest"
Cohesion: 0.22
Nodes (3): PostgresSchemaLayoutTest, PostgreSQL v1 SQL의 역할별 설치 순서를 고정한다., 선언이 수집된 행에 의존하면 빈 DB를 한 번에 세울 수 없다.

### Community 482 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 483 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 484 - "7. 간격과 레이아웃"
Cohesion: 0.33
Nodes (6): 7.1 4px 간격 사다리, 7.2 정보 밀도, 7.3 그리드, 7.4 반응형, 7.5 PNG의 크기와 가독성, 7. 간격과 레이아웃

### Community 486 - "test_segments_unmapped.py"
Cohesion: 0.43
Nodes (3): _fact(), 컬럼으로 매핑되지 않아 버려지는 세그먼트 concept을 보고하는지 검증한다. 매핑 실패 fact는 적재되지 않고 사라지는데, 무엇이 얼마나…, UnmappedConceptReporting

### Community 488 - "ExecutionPackageLayoutTest"
Cohesion: 0.20
Nodes (6): ExecutionPackageLayoutTest, _imports(), Path, execution의 폴더가 주문 lifecycle 순서를 그대로 말하게 한다. 승인 → 주문 → broker → 재조정 (그 옆에서)…, 루트에 모듈이 늘어나면 다시 "어디에 둘지 모르겠으면 여기" 가 된다., 게이트가 감시 대상을 import하면 그 대상 없이는 게이트를 켤 수 없다. `risk_snapshot`이 여기 있다가 걸렸다 — 그것은…

### Community 489 - "test_table_query_contracts.py"
Cohesion: 0.43
Nodes (4): declared_columns(), query_issues(), 정적으로 해석 가능한 조회를 스키마 합집합이 아닌 개별 테이블과 대조한다., TableQueryContractsTest

### Community 490 - "test_repo_conventions.py"
Cohesion: 0.20
Nodes (7): JsonLoggingTest, CLAUDE.md 핵심 관례를 기계로 강제한다. 문서에만 적힌 규칙은 지켜지는지 아무도 모르는 채로 드리프트한다. 여기 있는 것은 사람의 판단…, 호출처 없는 과거 연구 writer를 trading facade에 되살리지 않는다., 관례 3 — 라이브러리 코드는 `print()` 대신 JSON 로거를 쓴다. 사람이 눈으로 읽으라고 있는 CLI 출력만 예외다. 그 판정은…, CLAUDE.md 관례 2 — 각 저장소는 자신이 소유한 스키마만 직접 조회한다., RetiredWriterTest, SchemaOwnershipTest

### Community 491 - "PackagingContractTest"
Cohesion: 0.22
Nodes (3): PackagingContractTest, v1 Python packaging 계약 회귀 테스트., `__main__` 블록이 없는 진입점도 진입점이다. Streamlit 앱은 파일을 스크립트로 그냥 실행하므로 `if __name__ ==…

### Community 492 - "_payload_key_sets"
Cohesion: 0.31
Nodes (7): _conflict_columns(), ConflictColumnsAreSentTest, _payload_key_sets(), Module, upsert가 `on_conflict`로 부르는 컬럼은 payload에 있어야 한다. `earnings_results` 저장은 행에서 허용…, `*_keys = {...}` 꼴의 문자열 집합 상수., 대상을 못 찾으면 이 테스트는 공허하게 통과한다.

### Community 496 - "test_fundamentals_consensus.py"
Cohesion: 0.25
Nodes (3): PriceTrackTest, 공시 직전 컨센서스 선택·조립 회귀 테스트. 여기서 지키는 건 전부 "틀려도 카드는 그려지고 숫자만 거짓이 되는" 규칙이다., 목표가 52주 축 밖이면 끝에 눌려 '어디로 본다'가 안 읽힌다.

### Community 497 - "test_forum_kinds_are_wired.py"
Cohesion: 0.31
Nodes (7): _enqueued_kinds_without_thread(), _forum_envs(), _forum_kinds(), ForumKindsCarryAThreadNameTest, 포럼으로 선언된 목적지에는 스레드 제목을 함께 보내야 한다. Discord 포럼 채널은 `/channels/{id}/messages`를…, `enqueue(kind="x", ...)` 호출 중 `thread_name`이 없는 것., 대상을 못 고르면 위 테스트는 공허하게 통과한다.

### Community 498 - "DefaultPoolTest"
Cohesion: 0.20
Nodes (4): DefaultPoolTest, 기본 풀 구성 — 실제로 존재하는 모델 id만, 안전 우선순위로 나열한다., 예산이 큰 모델부터 시도해야 하루 처리량이 최대화된다., 실측(2026-09-03): gemini-2.5-flash-lite는 신규 계정에서 404, Gemini 3.x 계열은 벤더 클라이언트가…

### Community 500 - "V1ResetContractTest"
Cohesion: 0.33
Nodes (3): 빈 DB 재구축 도구가 구 스키마에 기대지 않는지 확인한다., trading·execution은 둘 다 로컬 runtime.sqlite3 소유라 물리적으로 같은 파일에 있지만, execution이…, V1ResetContractTest

### Community 503 - "anon_client"
Cohesion: 0.67
Nodes (3): Client, anon_client(), 공개 읽기용 anon client를 실제 첫 호출 시 한 번 만든다.

### Community 504 - "7. Fundamentals: canonical 수치와 과거 사용 가능성을 구분"
Cohesion: 0.33
Nodes (6): 7.1 목표 테이블, 7.2 financials 한 행의 의미, 7.3 공개 시각을 정정 전으로 소급하지 않기, 7.4 타입은 두 번째 단계, 7.5 Segment와 share class도 정책 일관성 확인, 7. Fundamentals: canonical 수치와 과거 사용 가능성을 구분

### Community 505 - "11. Research: 대용량 Wide와 불변 실행 metadata"
Cohesion: 0.67
Nodes (3): 11.1 목표 배치, 11.2 Strategy 관계형 구조, 11. Research: 대용량 Wide와 불변 실행 metadata

### Community 506 - "16. 구현 순서와 완료 기준"
Cohesion: 0.67
Nodes (3): 16.1 DDL·코드 변경 묶음, 16.2 Runtime 작업의 필수 정비 절차, 16. 구현 순서와 완료 기준

### Community 509 - "fundamentals/test_service.py"
Cohesion: 0.44
Nodes (5): _Batch, FundamentalsWriterTest, _prepared_db(), v1 CompanyFacts writer의 원천→원장→wide 경로., _ref()

### Community 510 - "12. Runtime: SQLite에 돈의 사실과 안전 상태를 보존"
Cohesion: 0.40
Nodes (5): 12.1 최소 원장은 현재 안전 제약을 포함한다, 12.2 ID와 exact 값, 12.3 transaction과 crash 복구, 12.4 broker raw artifact와 계좌 snapshot, 12. Runtime: SQLite에 돈의 사실과 안전 상태를 보존

### Community 511 - "institutional/db.py"
Cohesion: 0.05
Nodes (43): all_managers(), guru_display_name(), guru_tags(), guru_thread_topic(), presentation_for(), institutional 7인 레이더의 코드 상수. 추적 대상 manager(cik/name/fund_name/is_active)의 런타임…, 활성 여부와 무관한 전체 manager 사실 + 화면 해석. cik 오름차순., 관리자 사실에 붙일 화면용 해석. 미등록 manager도 수집은 가능하다. (+35 more)

### Community 513 - "StrategyWorkflowOrderingTest"
Cohesion: 0.29
Nodes (3): notify_strategy 워크플로의 단계 순서·산출물 계약을 검증한다., channel routing은 이제 DB가 아니라 각 워크플로의 env가 SSOT다 — validate_subscriptions는 그 env가…, StrategyWorkflowOrderingTest

### Community 514 - "15. Markdown 파일별 개정 지도"
Cohesion: 0.40
Nodes (5): 15.1 지금 할 문서 변경과 구현 후 할 변경, 15.2 CLAUDE.md 교체 문안, 15.3 docs/DATA.md의 교체용 PIT 표, 15.4 기존 Intelligence spec에서 교체할 문장, 15. Markdown 파일별 개정 지도

### Community 515 - "6. Market: 얇은 행 + 명시적인 공개·변경 계약"
Cohesion: 0.40
Nodes (5): 6.1 목표 저장 형태, 6.2 Market에 필요한 시간은 ingestion 한 종류가 아니다, 6.3 ingestion 삭제의 선행조건: 정정 전파, 6.4 archive와 보존 범위, 6. Market: 얇은 행 + 명시적인 공개·변경 계약

### Community 516 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 517 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 518 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 519 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 520 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 521 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 522 - "execution_view.py"
Cohesion: 0.39
Nodes (8): execution_summary(), _number(), Any, 실행 원장의 상태·체결 비용·정산 결과를 읽기 전용으로 요약한다., 운영 화면의 핵심 지표를 저장 사실만으로 계산한다., 한 execution intent에 연결된 승인·주문·체결·TCA 이벤트를 반환한다., _rows(), trace_for_intent()

### Community 523 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 524 - "8. Macro: fact를 분리하되 의미 metadata는 유지"
Cohesion: 0.40
Nodes (5): 8.1 목표 구조, 8.2 market_observations, 8.3 economic_observation_versions, 8.4 forecast와 schedule, 8. Macro: fact를 분리하되 의미 metadata는 유지

### Community 526 - "d_day_label"
Cohesion: 0.67
Nodes (3): d_day_label(), Any, Discord 예정 카드와 같은 방향으로 남은 날짜를 표시한다.

### Community 527 - "DangerFloorTest"
Cohesion: 0.47
Nodes (3): DangerFloorTest, CLAUDE.md와 AGENTS.md의 안전 바닥이 어긋나지 않는지 본다. 두 문서에 같은 블록을 두는 것은 SSOT 원칙의 예외다. 그럴…, 길어지면 아무도 안 읽는다. 늘리고 싶으면 스킬이나 CLAUDE.md 본문으로.

### Community 529 - "4. 500MB 예산을 올바르게 정의하기"
Cohesion: 0.50
Nodes (4): 4.1 중복 계산을 없앤 예산, 4.2 타입 변경만으로 얼마가 줄어드는지 확정하지 않기, 4.3 적용 전 실행할 읽기 전용 측정 SQL, 4. 500MB 예산을 올바르게 정의하기

### Community 530 - "test_entrypoint.py"
Cohesion: 0.25
Nodes (6): MacroRefreshResult, _indicator(), MacroRunTest, MacroTransformTest, macro v1 진입점의 범위·모드·종료코드 계약을 검증한다., _series()

### Community 531 - "5. Universe: identity를 보존하며 간소화"
Cohesion: 0.50
Nodes (4): 5.1 integer 전환, 5.2 index_memberships의 기간 계약, 5.3 watchlist와 tracking, 5. Universe: identity를 보존하며 간소화

### Community 532 - "migrate_local_storage.py"
Cohesion: 0.16
Nodes (27): copy_duckdb_snapshot(), copy_sqlite_snapshot(), _duckdb_snapshot(), LocalStorageConflict, main(), MigrationPlan, _plan_dict(), plan_migrations() (+19 more)

### Community 535 - "_imported_modules"
Cohesion: 0.40
Nodes (4): _imported_modules(), PresentationLayerDirectionTest, 모듈이 가져오는 절대 모듈 경로. 상대 import는 파일 위치로 풀어서 돌려준다. 상대 import를 그대로 두면 `from…, 대시보드는 도메인 구현 대신 공개된 읽기 계약만 소비한다. 아래 목록은 허용 목록이 아니라 아직…

### Community 537 - "evidence/cache.py"
Cohesion: 0.17
Nodes (8): canonicalize_url(), 같은 문서를 가리키는 URL을 한 모양으로. 읽을 수 없으면 `None`. 같은 기사에 tracking 파라미터만 달라진 URL이 붙어…, _normalized_content(), 뉴스·소셜 원문을 Supabase 밖의 재생성 가능한 DuckDB에 보관한다., _sha(), main(), 로컬 뉴스·소셜 DuckDB의 90일 retention을 적용한다., CanonicalizeUrlTest

### Community 540 - "EarningsFlashOutbox"
Cohesion: 0.33
Nodes (4): EarningsFlashOutbox, 속보는 전송 전에 outbox에 스냅샷을 등록한다., outbox 스냅샷 등록이 디스패치보다 먼저 일어난다., 디스패치 결과가 불명이어도 실행기는 성공으로 세지 않는다.

### Community 541 - "identifiers.py"
Cohesion: 0.14
Nodes (12): _cusip_char_value(), cusip_check_digit(), is_valid_identifier(), normalize_cusip(), 종목을 가리키는 이름들의 규칙. ## 왜 platform이 아니라 여기인가 ticker 정규화와 CUSIP 검증은 "투자 데이터"를 알아야만…, 앞 8자리로 검사숫자를 계산한다. 계산할 수 없으면 `None`. 13F 원문에는 자리가 밀리거나 문자가 빠진 CUSIP이 실제로 섞여 온다.…, CUSIP을 9자리 표기로. 모양이나 검사숫자가 틀리면 `None`., 저장소가 받아들일 모양인가. 넣기 전에 여기서 거른다. (+4 more)

### Community 544 - "test_evaluator.py"
Cohesion: 0.17
Nodes (8): evaluate_returns(), PortfolioMetrics, 목표 비중 경로의 비용 포함 포트폴리오 성과를 계산한다., EvaluatorTest, FakeRepository, PortfolioEvaluatorTest, date, 성과 평가가 거래일과 SPY 공통 날짜로만 계산되는지 검증한다.

### Community 550 - "test_calculations_facade.py"
Cohesion: 0.29
Nodes (3): TradingAgents 실시간 웹 대시보드 패키지., CalculationsFacadeTest, 화면이 계산 facade에서 가져오는 공개 이름과 일정 계약을 검증한다. 페이지 모듈은 import만으로 Streamlit·DB를 초기화할 수…

### Community 553 - "ReportingPackageLayoutTest"
Cohesion: 0.24
Nodes (5): _opens_a_store(), Path, Reporting의 배치를 못박는다. reporting이 존재하는 이유는 "이 값이 어느 저장소에서 오는가"를 화면과 알림에서 감추는 것이다.…, 저장소를 여는 자리가 늘어나면 reporting이 감추는 것이 없어진다., ReportingPackageLayoutTest

### Community 556 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 558 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 559 - "FilingRowAcceptsEveryShapeTest"
Cohesion: 0.20
Nodes (3): 외부 저장소와 무관한 fundamentals 도메인 모델과 계산 규칙., FilingRowAcceptsEveryShapeTest, 부모 `filings` 행을 만드는 일은 어떤 입력으로 와도 같아야 한다. `Filing`(저장 계약)과 `FilingRef`(원문 읽기 전…

### Community 560 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 571 - "20_market.sql"
Cohesion: 0.67
Nodes (3): market.dividend_events, market.prices_daily, universe.securities

### Community 574 - "40_notifications.sql"
Cohesion: 0.67
Nodes (3): notification_deliveries, notification_delivery_state, notification_outbox

### Community 579 - "CandidateCoverageRepositoryTest"
Cohesion: 0.33
Nodes (4): CandidateCoverageRepositoryTest, 후보 coverage는 로컬 runtime 판단 원장에서 읽는다. 전에는 Postgres `trading.security_decisions`를…, 실패한 판단을 coverage로 세면 그 종목이 다시 분석되지 않는다., as_of 이후의 판단이 보이면 그 시점 재현이 아니다.

### Community 586 - "test_fundamentals_integrity.py"
Cohesion: 0.07
Nodes (12): ColumnDriftTest, _fact(), ManifestTest, PersistedPayloadTest, fundamentals wide 적재의 의미 선택·출처 보존 계약을 검증한다., 저장 payload에 스키마에 없는 키가 섞이면 그 공시가 통째로 사라진다., 메모리 전용으로 떼어 내는 키는 스키마가 obsolete로 선언한 것과 같아야 한다., 스키마의 numeric 컬럼은 코드가 쓰는 wide 컬럼 전부와 같아야 한다. 한쪽만 고치면 라이브 스키마가 코드보다 넓거나 좁은 채로… (+4 more)

### Community 591 - "test_universe_names.py"
Cohesion: 0.13
Nodes (5): universe 수집·정합성 명령 패키지., KoreanNameRefreshTest, KoreanNameSelectionTest, Universe 핵심 갱신과 로컬 전용 한글명 보강의 경계 테스트., UniverseWorkflowBoundaryTest

### Community 592 - "ResearchStoreTest"
Cohesion: 0.11
Nodes (7): 저장 기술별 연결 경계. 각 파일이 하나의 DB만 안다. 이 패키지는 재수출하지 않는다. `platform.db`만 적으면 세 저장소 중…, DuckDBStoreTest, 로컬 DuckDB 파일을 여는 공통 경계의 계약., intelligence 본문은 이제 Parquet가 소유하고 DuckDB는 작은 catalog/index metadata만 갖는다 —…, 읽기 전용 연결이 파일을 만들면, 화면이 빈 DB를 만들어 놓고 수집 잡의 쓰기 잠금을 빼앗는다., 읽기 전용 Research 조회와 재실행의 발송 상태 보존을 확인한다., ResearchStoreTest

### Community 596 - "test_watchlist_toss.py"
Cohesion: 0.12
Nodes (6): 토스 보유종목 관심목록 동기화의 안전장치를 검증한다., 관심 원장을 따로 두면 "활성인가"의 정의가 두 곳에 생긴다., TossClientPayloadTest, TossHoldingsTransformTest, TossMacOnlyConfigurationTest, TossSyncWriteBoundaryTest

### Community 608 - "test_model_pool_providers.py"
Cohesion: 0.12
Nodes (8): AzureCandidateTest, GroqCandidateTest, PoolCapacityTest, 풀에 있는 후보가 실제로 호출 가능하고, 실제 프롬프트 크기를 견디는지 못박는다. 실측 2026-09-03 (도구 호출 2턴 + 실제…, 카탈로그에만 있는 이름을 넣으면 매번 404를 맞고 후보 하나를 낭비한다., 무료 TPM 8,000은 종목 하나의 프롬프트도 못 받는다 — 넣으면 매번 413이다., 왜 뺐는지 숫자로 남긴다 — 나중에 '한번 더 넣어보자'를 막는다., 단일화 결정(2026-09-03): 후보가 하나면 어느 키로 불렀는지가 항상 분명하다.

### Community 637 - "30_fundamentals.sql"
Cohesion: 0.23
Nodes (13): financials_canonical_guard, fundamentals.analyst_consensus_snapshots, fundamentals.earnings_results, fundamentals.filing_processing, fundamentals.filings, fundamentals.financials, fundamentals.guard_canonical_financials(), fundamentals.segment_metrics (+5 more)

### Community 664 - "KillSwitchTest"
Cohesion: 0.40
Nodes (3): KillSwitchTest, Path, 킬 스위치는 워크플로 레벨 게이트다 — Python 코드 안에서 검사하지 않는다.

### Community 670 - "RunnerImageTest"
Cohesion: 0.40
Nodes (3): 러너 라벨은 `ubuntu-latest` 하나로 둔다. 버전을 박으면 그 이미지가 만료된다. ubuntu-22.04가 그랬다 —…, 옮기고 나서 목록에 남겨두면 그 목록이 거짓말을 시작한다., RunnerImageTest

## Knowledge Gaps
- **613 isolated node(s):** `content_files`, `content_catalog_state`, `feature_sets`, `dataset_runs`, `local_job_state` (+608 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 5542 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **92 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_logger()` connect `logging.py` to `web.py`, `EarningsCalendarStore`, `auth.py`, `Outbox`, `live_worker.py`, `ExecutionIntent`, `actuals.py`, `finite_float`, `fsds.py`, `companyfacts.py`, `process_filing.py`, `retry_on_5xx`, `investment_harness.py`, `commands/common_shares.py`, `github_actions.py`, `strategies.py`, `map_fiscal_periods.py`, `rl/contracts.py`, `ExecutionSafetyError`, `collection.py`, `reserve_provider_call`, `readers/intelligence.py`, `test_historical_earnings_estimates.py`, `supabase_repository.py`, `safe_fetch`, `universe/persistence.py`, `ProductionInvestmentAdapters`, `continuous_retrain.py`, `build_events.py`, `DiscordApprovalClient`, `MacroRepository`, `postgres.py`, `filings.py`, `TransactionCostModel`, `build_labels.py`, `fundamentals/repository.py`, `notifications/macro.py`, `ResearchDataset`, `discord_admin/client.py`, `shadow_daily.py`, `openfigi.py`, `retry.py`, `create_execution_intent.py`, `market_daily.py`, `tradingagents_adapter.py`, `features/db.py`, `worker.py`, `us_market_today`, `Database`, `construct.py`, `yahoo.py`, `ensure_aware`, `application/etl.py`, `build_valuations.py`, `application/service.py`, `HarnessReporter`, `social_normalize.py`, `application/backfill_history.py`, `portfolio_shadow.py`, `monitoring/discord.py`, `news_normalize.py`, `backtest/cli.py`, `detect_earnings_events.py`, `features/etl.py`, `infrastructure/sources/yfinance.py`, `parse_shares.py`, `sec13f.py`, `institutional/db.py`?**
  _High betweenness centrality (0.136) - this node is a cross-community bridge._
- **Why does `parse_datetime()` connect `parse_datetime` to `EvidenceBundle`, `live_worker.py`, `ExecutionIntent`, `Outbox`, `backtest/contracts.py`, `execution/db.py`, `fit_baseline`, `trading/contracts.py`, `artifacts.py`, `.create`, `investment_harness.py`, `ExecutionRepository`, `portfolio/contracts.py`, `PITValuationInputs`, `rl/contracts.py`, `ExecutionSafetyError`, `MarketQuote`, `fusion.py`, `validate_live_candidate_as_of`, `evidence/cache.py`, `json_value`, `FeatureDataset`, `_LabelRepository`, `supabase_repository.py`, `continuous_retrain.py`, `ProductionInvestmentAdapters`, `src/investment_agent/research/rl/__init__.py`, `build_events.py`, `HarnessScheduler`, `AccountSnapshot`, `valuation/engine.py`, `MacroRepository`, `market_schedule.py`, `postgres.py`, `filings.py`, `TransactionCostModel`, `build_labels.py`, `candidate_ranker.py`, `fundamentals/repository.py`, `ResearchDataset`, `shadow_daily.py`, `app_pages/intelligence.py`, `inputs.py`, `toss/client.py`, `capture_toss_account_snapshot`, `create_execution_intent.py`, `tradingagents_adapter.py`, `FakeRepository`, `worker.py`, `construct.py`, `SupabaseRepository`, `canonical_json`, `export_dataset`, `.from_row`, `build_valuations.py`, `attribution.py`, `layer.py`, `snapshots.py`, `logging.py`, `context.py`, `promotion/gate.py`, `LocalEvidenceCache`, `portfolio_shadow.py`, `BacktestRequest`, `parse_external_payload`, `services/investment/__init__.py`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Why does `canonical_json()` connect `canonical_json` to `EvidenceBundle`, `live_worker.py`, `ExecutionIntent`, `Outbox`, `backtest/contracts.py`, `execution/db.py`, `fit_baseline`, `trading/contracts.py`, `artifacts.py`, `investment_harness.py`, `ExecutionRepository`, `dashboard/db.py`, `portfolio/contracts.py`, `json_value`, `rl/contracts.py`, `MarketQuote`, `switch.py`, `ExecutionSafetyError`, `PITValuationInputs`, `evidence/cache.py`, `FeatureDataset`, `supabase_repository.py`, `continuous_retrain.py`, `ProductionInvestmentAdapters`, `emergency.py`, `lifecycle.py`, `build_events.py`, `parse_datetime`, `HarnessScheduler`, `src/investment_agent/research/rl/__init__.py`, `valuation/engine.py`, `AccountSnapshot`, `TransactionCostModel`, `install_investment_harness.py`, `LocalArtifactStore`, `platform/artifacts.py`, `candidate_ranker.py`, `ResearchDataset`, `shadow_daily.py`, `TradingAgentsDecisionEngine`, `tradingagents_adapter.py`, `worker.py`, `construct.py`, `SupabaseRepository`, `attribution.py`, `layer.py`, `snapshots.py`, `HarnessReporter`, `context.py`, `portfolio_shadow.py`, `RunContext`, `services/investment/__init__.py`, `HarnessMode`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `parse_datetime()` (e.g. with `._validate_timing()` and `build_events()`) actually correct?**
  _`parse_datetime()` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 52 inferred relationships involving `FakeDatabase` (e.g. with `ConsensusTest` and `ProcessingTest`) actually correct?**
  _`FakeDatabase` has 52 INFERRED edges - model-reasoned connections that need verification._
- **Are the 55 inferred relationships involving `ExecutionSafetyError` (e.g. with `DiscordApprovalClient` and `._check_state()`) actually correct?**
  _`ExecutionSafetyError` has 55 INFERRED edges - model-reasoned connections that need verification._
- **What connects `content_files`, `content_catalog_state`, `feature_sets` to the rest of the system?**
  _613 weakly-connected nodes found - possible documentation gaps or missing edges._