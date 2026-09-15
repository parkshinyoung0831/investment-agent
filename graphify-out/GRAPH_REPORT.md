# Graph Report - investment-agent-main  (2026-09-15)

## Corpus Check
- 1200 files · ~927,550 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 15985 nodes · 35234 edges · 690 communities (557 shown, 96 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 1766 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b6e156b7`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- web.py
- ml_challengers.py
- quant.py
- EvidenceBundle
- SupabaseRepository
- live_worker.py
- macro/core.py
- serialization.py
- parse_xbrl.py
- application/backfill_history.py
- evidence/artifacts.py
- app_pages/earnings.py
- companyfacts.py
- launcher.py
- watch_earnings.py
- investment_harness.py
- logging.py
- ExecutionRepository
- sec.py
- charts.py
- rl/contracts.py
- PortfolioRiskPolicy
- _posix
- src/investment_agent/data/fundamentals/application/__init__.py
- universe/persistence.py
- switch.py
- reserve_provider_call
- MacroArchitectureTest
- readers/intelligence.py
- continuous_retrain.py
- reconcile_toss.py
- TransactionCostModel
- select_all_paged
- test_historical_replay_pit.py
- incidents.py
- ablation.py
- 90_reporting.sql
- StrategyTests
- ProductionInvestmentAdapters
- company_financials.py
- _fetch
- event_intelligence.py
- dashboard/db.py
- FiscalPeriod
- FactorModel
- CaseMemory
- 디자인 시스템 — 알림 카드와 대시보드 UI의 단일 기준
- ContractError
- releases/db.py
- DailyBar
- SelectOnlyGatewayTests
- ReportingQueries
- experiment.py
- build_market_regime
- worker.py
- run_backtest
- ApprovalRequest
- TradingRepository
- normalize_ticker
- VersionKey
- yahoo_finance/consensus.py
- SystemPortfolioStore
- application/refresh_expectations.py
- local_mirror/sync.py
- investment/embeds.py
- ml_serving.py
- 개별 주식 심층 분석 — 외부 GPT용 질의 템플릿
- export_dataset.py
- LocalMirror
- calculations/__init__.py
- toss/client.py
- OptimizerPolicy
- BrokerAdapter
- _text
- identifiers.py
- factor_research.py
- tradingagents_adapter.py
- FakeRepository
- features/db.py
- reported_observations.py
- backtest/contracts.py
- econ_calendar.py
- universe/test_persistence.py
- parse_shares.py
- read_runtime_rows
- backtest/cli.py
- BacktestRequest
- harness/runtime.py
- Any
- build_training_samples.py
- SimpleNamespace
- process_company_facts
- market_risk.py
- market/domain/models.py
- release_catalog.py
- intelligence/repository.py
- SegmentSnapshotOrderTest
- main
- build_segment_metrics.py
- load_config
- renderers/text.py
- target.py
- provider.py
- is_transient
- earnings/schedule.py
- _markdown_files
- make_filing_record
- FeatureLayer
- parser.py
- TradingAgentsAdapterTest
- test_roles.py
- LocalEvidenceCache
- CLAUDE.md — 이 저장소의 개발 규칙
- FakeDatabase
- budget.py
- FakeQuery
- sec_entities.py
- 운영 — 설치, 자동 실행, 상태 확인과 장애 대응
- FeatureDataset
- TossOrderApiTest
- environment.py
- CompanyFilingSource
- normalize_segment_facts.py
- services/investment/__init__.py
- app_pages/intelligence.py
- src/investment_agent/operations/harness/__init__.py
- infrastructure/sources/yfinance.py
- releases/schedule.py
- holdings.py
- What You Must Do When Invoked
- auth.py
- _snap
- FundamentalsRepository
- filing_documents.py
- Topic
- build_features.py
- calendar.py
- FilingRef
- fit_baseline
- fsds.py
- extract_summary_financials
- emergency.py
- earnings_report/embeds.py
- strategies.py
- _Query
- DossierBuilder
- _wf
- CLAUDE.md
- earnings/metrics.py
- ControlCenter
- collection.py
- main
- test_watchlist_db.py
- SelectOnlyGateway
- _snap
- test_revisions.py
- Config
- main
- strategies/etl.py
- _run
- _modules
- PolicyAndModelRepositoryTest
- supabase/segment_metrics.py
- normalize.py
- deflated_sharpe.py
- main
- ExecutionSafetyError
- MarketRepository
- market/test_persistence.py
- app_pages/macro.py
- MacroRepository
- render_dsr_gauge
- ensure_aware
- validated_weights
- f
- ContextBuilder
- _run
- test_workflow_wiring.py
- _Repository
- MeasureCalculationTest
- RawPosition
- lifecycle.py
- install_investment_harness.py
- create_execution_intent.py
- _intent
- layer.py
- us_market_today
- TossTokenManagerTest
- What You Must Do When Invoked
- What You Must Do When Invoked
- decision/alpha.py
- _canonical_filing_focus
- TossAuthError
- Path
- _Query
- 자주 발생하는 문제
- _row
- inputs.py
- event_reanalysis.py
- decision/analysis.py
- Third-party data notice — `gaap_mappings.json`
- alfred.py
- OpenAICompatibleClient
- test_page_wiring.py
- valuation_history.py
- test_inputs.py
- domain/analysis.py
- application/etl.py
- PolicyConceptChoice
- Trading — 근거에서 포트폴리오까지의 판단 계층
- test_schema_alignment.py
- test_provider_fail_closed.py
- Event
- test_strategy_guardrails.py
- _row
- secret_scope.py
- openfigi.py
- approval/ledger.py
- IntelligenceRepository
- to_wide_tables
- DiscordTest
- managers.py
- 투자 시스템 — System Portfolio와 My Portfolio
- process_filing.py
- test_reporting_guards.py
- RunContext
- ManifestTest
- sources/toss_holdings.py
- filing_xbrl.py
- GuruRoutingTest
- stress.py
- DimensionPreservationTest
- test_secret_scoped_modules.py
- ResearchStore
- expectations_exit_code
- refresh_earnings_season.py
- build
- retry.py
- promotion/gate.py
- test_read_path_performance.py
- FullPortfolioSchemaTest
- row_event_key
- model_pool.py
- earnings_report/quickchart.py
- IntelligenceRepositoryTest
- test_watchlist_toss.py
- fundamentals_pending.py
- experiments
- validate_snapshot
- Investment Operations Harness — 로컬 상시 오케스트레이션 계층
- 20_decisions.sql
- json_value
- _CountingRepository
- ArtifactRef
- execution_view.py
- Execution — 주문 lifecycle과 안전 경계
- PriorityCandidateTest
- universe/infrastructure/sources/__init__.py
- FailureAlertTest
- test_logging.py
- classify_session
- parse_datetime
- AI Investor Constitution — 판단 계층이 넘지 않는 선
- fundamentals/test_repository.py
- build_decision_experiences.py
- BuildTest
- storage_paths.py
- _db
- ViewTest
- 데이터 — Supabase, PIT, 그리고 로컬 저장소
- test_edgartools_13f.py
- market_schedule.py
- SurpriseRowsTest
- edgartools_13f.py
- test_macro_notifications.py
- map_fiscal_periods.py
- object
- ActualProviderTest
- _Repository
- ChampionForecastTest
- test_segments_retention.py
- DashboardLauncherCliTest
- price_risk_profile
- SegmentHighlightsTest
- DiscordChannel
- Database
- compute_all
- _crons
- 적응형 정보 구조
- DeliverEditTest
- gdpnow_archive.py
- context.py
- QualityAssessmentTest
- institutional/card.py
- sec13f.py
- _FakeBuilder
- report.py
- 실행과 안전 — 주문·승인·Broker와 단계별 안전장치
- SignalBatch
- verify_postgres_sql_syntax.py
- load
- fomc_calendar.py
- canonical_json
- reconcile_orders
- EnvFileTest
- ProcessFileLock
- CollectSocialTest
- memory_context
- build_valuations
- strategy/embeds.py
- discord_admin/client.py
- ._history
- format_guidance_headline
- _Repository
- Filing13F
- _Query
- valuation_history
- Investment Agent — S&P 500 투자 분석 파이프라인과 Discord 알림
- InvestmentAdaptersTest
- IntelligenceArchitectureTest
- DropImplausibleSharesTest
- market_backfill.py
- DeliveryRejected
- 30_execution.sql
- test_entrypoint.py
- OpenFigiIdentifierTest
- ._snapshot
- harness_adapters.py
- FiresBetweenTest
- _called_schemas
- store
- Fundamentals domain — 저장소와 무관한 계산 규칙
- assess_segment_quality.py
- apply_downstream_api_key
- storable_share_rows
- Macro 경제발표 — 일정·예상·실제·개정
- InstitutionalArchitectureTest
- EconIcsTest
- counters.py
- _coherent_range
- news_normalize.py
- Research Features — 일간 기술지표와 PIT 학습 입력
- Strategy — 팩터/룰 기반 자산배분 전략 6종 파이프라인
- strategies/db.py
- 18. 검수 체크리스트
- _by_key
- CollectNewsTest
- InstitutionalRepository
- safe_fetch
- run_preflight
- CardInstallGuardTest
- 문서 지도 — 처음 보는 사람을 위한 시스템 안내
- backfill
- db_capacity.py
- MacroNotificationStore
- CompanyFinancialRepository
- _ops_webhook
- fundamental_statistics
- Notifications — 시각화 알림(Playwright PNG 카드 & Discord Embed) 서브시스템
- intelligence/domain/__init__.py
- TestFundamentalsFlash
- FindTickersTest
- candidate_ranker.py
- LocalTradingDatabase
- edgar_parser/__init__.py
- WebClientError
- _Client
- macro_indicator_rows
- overwrites
- test_continuous_retrain_exit_code.py
- discord_admin/sync.py
- LoadConfigTest
- test_ecos.py
- _date
- institutional/test_persistence.py
- installation_files
- DependencyDeclarationTest
- DerivedReadModelTest
- Universe watchlists — 관심 기업 & 토스증권 보유종목 동기화
- Discord Admin — 코드 기반 선언적 Discord 서버 관리 (IaC)
- 후보 선정 — tracked universe에서 무엇을 볼까
- AGENTS.md — 에이전트가 이 저장소에서 지킬 것
- Delivery
- 10. 데이터 시각화
- PendingFilingGroupsTest
- FundamentalsArchitectureTest
- test_fundamentals_integrity.py
- DiscordTargetTests
- test_backfill_scopes.py
- select_timed_targets
- 16. 구현 계약
- PITScalar
- 9. 핵심 컴포넌트
- score_cross_section
- 2. 핵심 결정과 우선순위
- PostgresNotificationLedger
- graphify reference: extra exports and benchmark
- 3. 제품 철학
- test_runners.py
- Fundamentals — 공시·재무·세그먼트·실적 이벤트
- Universe — 회사 identity, 상장 증권, 지수 구성
- filings.py
- IntelligenceReaderTest
- non_liability_claims
- UniverseArchitectureTest
- finite_float
- PlanVersionsTest
- SourceBudgetTest
- EconSnapshotShapeTest
- press_releases.py
- 40_macro.sql
- 5. 색 시스템
- test_segments_unmapped.py
- remap_runtime_securities.py
- normalize_positions
- ResearchStoreReadPathTest
- WorkflowNameTest
- 11. 라이트·다크 모드 운영
- 14. 보이스 앤 톤
- Actions Discord Notification Recovery — 구현 계획
- 2. 핵심 헬퍼 모듈 사용법
- sqlite.py
- 6. 타이포그래피
- 8. 모양, 보더, 깊이
- backtest/metrics.py
- factors.py
- _row
- .test_static_all_exports_are_unique
- Market — 일봉과 corporate action
- validate_series
- HistoricalCardTest
- .test_every_workflow_installs_what_its_entry_point_imports
- test_failure_reporter_deps.py
- graphify reference: extra exports and benchmark
- graphify reference: extra exports and benchmark
- test_filing_xbrl_fallback.py
- QlibPITAdapter
- 10_universe.sql
- _fact
- LocalArtifactStore
- _entrypoints
- platform/artifacts.py
- load_earnings_results
- NewsSocialPageTest
- PriceTargetTest
- news_social.py
- .from_row
- fetch_forum_threads
- 자율 판단 계층 — 근거 수집부터 승격까지
- content_index
- discord_admin/guide.py
- Path
- RetiredWriterTest
- MarketArchitectureTest
- actuals.py
- institutional/NOTICE.md
- institutional/db.py
- InstitutionalSchemaContractTest
- 저장 지도 — 무엇이 어디에 사는가
- main
- releases/baseline.py
- EarningsCalendarStore
- test_segments_quality.py
- KindsWiringTest
- SharedSetupTest
- EntrypointAttributeCallTest
- src/investment_agent/data/universe/__init__.py
- _Builder
- operations_view.py
- _submissions_document
- Operations — Discord-first 운영 관측과 로컬 하네스
- Reporting — 화면과 알림이 공유하는 읽기 모델
- download_monthly_close
- test_learning_stage_commands.py
- CandidateFeatureReadTest
- test_channel_names_are_declared.py
- main
- ExecutionBoundaryTest
- 60_notifications.sql
- load_prices
- freshness_for
- PostgresSchemaLayoutTest
- graphify reference: query, path, explain
- graphify reference: query, path, explain
- 7. 간격과 레이아웃
- DashboardLauncherPortTest
- build_membership_snapshots
- ResolveIdentifiersTest
- ExecutionPackageLayoutTest
- test_table_query_contracts.py
- test_repo_conventions.py
- PackagingContractTest
- _payload_key_sets
- test_edgar_parser.py
- EarningsScheduleContractTest
- Intelligence — 뉴스·소셜 텍스트를 종목 언급으로
- test_fundamentals_consensus.py
- OperationalRetentionTest
- LiveExecutionRepository
- RepositoryLayoutTest
- V1ResetContractTest
- runtime/v1/00_init.sql
- UniverseNamingContractTest
- HarnessModuleAllowlistTest
- detect_earnings_events.py
- EarningsMetricsTest
- test_forum_kinds_are_wired.py
- calibrator.py
- awaiting_message
- _SegmentRepository
- anon_client
- test_factor_research.py
- Research — PIT feature·dataset·모델·평가·승격
- StrategyWorkflowOrderingTest
- src/investment_agent/operations/commands/__init__.py
- pending_filings
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- graphify reference: add a URL and watch a folder
- graphify reference: commit hook and native CLAUDE.md integration
- graphify reference: incremental update and cluster-only
- .filings
- graphify reference: query, path, explain
- social_normalize.py
- Institutional — SEC 13F 원천·유효 포트폴리오
- audit_fx_cross_sources
- DangerFloorTest
- test_econ_calendar.py
- GuruNotificationTest
- ReleaseWatchTest
- transient_retry
- migrate_local_storage.py
- test_adapter_contracts.py
- HarnessReporter
- TechIndicatorAtomicUpsertTests
- _domain_precisions
- _series
- DataPackageLayoutTest
- test_subscription_routing_contract.py
- RetentionTest
- test_workflow_storage_paths.py
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- state_versions.py
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- .from_row
- strategies/catalog.py
- verify_data.py
- test_dashboard_readonly.py
- .claude/skills/graphify/references/extraction-spec.md
- .codex/skills/graphify/references/extraction-spec.md
- ReportingPackageLayoutTest
- releases/test_db.py
- intelligence/v1/00_init.sql
- graphify reference: add a URL and watch a folder
- RepositoryMemoTest
- graphify reference: commit hook and native CLAUDE.md integration
- StrategyLabelsTest
- graphify reference: incremental update and cluster-only
- src/investment_agent/data/fundamentals/infrastructure/__init__.py
- Macro — 시장 상태 관측과 경제발표
- investment-agent
- NotificationGuardsTest
- EarningsValuationHistoryTest
- src/investment_agent/data/__init__.py
- institutional/commands/__init__.py
- yahoo.py
- IntelligenceJobTest
- ECON 데이터 출처 계약 — 고정 30개 지표
- 20_market.sql
- UniverseSnapshot
- datetime
- Local mirror — Supabase 원본 창고의 로컬 계산용 사본
- test_managers.py
- redact
- Q: Audit trading decision learning approval and performance flow
- breadth_200dma
- CandidateCoverageRepositoryTest
- KillSwitches
- BoundaryTest
- src/investment_agent/__init__.py
- IcSummary
- entries/__init__.py
- RegistryInjectionTest
- test_strategy_progress.py
- SchemaContractTest
- date
- StorageLayoutTest
- PITValuationInputs
- 45_performance.sql
- DuckDBOpenRetryTest
- graphify reference: GitHub clone and cross-repo merge
- graphify reference: transcribe video and audio
- local_mirror/__init__.py
- 50_institutional.sql
- estimate_statistics
- src/investment_agent/research/valuation/__init__.py
- collect_integrity_facts
- src/investment_agent/trading/decision/llm/__init__.py
- src/investment_agent/trading/evidence/__init__.py
- .agents/skills/graphify/references/extraction-spec.md
- src/investment_agent/trading/portfolio/__init__.py
- test_model_pool_providers.py
- src/investment_agent/trading/risk/__init__.py
- change_manifest.py
- tests/__init__.py
- tests/investment_agent/data/fundamentals/application/__init__.py
- tests/investment_agent/data/fundamentals/domain/__init__.py
- tests/investment_agent/data/fundamentals/infrastructure/__init__.py
- tests/investment_agent/data/macro/releases/__init__.py
- fundamentals.earnings_estimates
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
- membership_snapshots
- 10_account.sql
- NotifyPackageShapeTest
- fundamentals.earnings_schedule_versions
- macro/domain/__init__.py
- src/investment_agent/data/macro/__init__.py
- supabase/__init__.py
- 30_fundamentals.sql
- spearman
- market.actions_daily
- _Response
- ExpectationsRepositoryPagingTest
- ColumnDriftTest
- components/__init__.py
- .current_model_stage
- src/investment_agent/data/fundamentals/__init__.py
- approval/__init__.py
- orders/__init__.py
- reconciliation/__init__.py
- safety/__init__.py
- src/investment_agent/intelligence/__init__.py
- src/investment_agent/operations/__init__.py
- src/investment_agent/platform/__init__.py
- KillSwitchTest
- DashboardLauncherSafetyStateTest
- RunnerImageTest
- 47_system_portfolio.sql
- src/investment_agent/trading/system/__init__.py
- tests/investment_agent/trading/system/__init__.py

## God Nodes (most connected - your core abstractions)
1. `parse_datetime()` - 260 edges
2. `get_logger()` - 181 edges
3. `SupabaseRepository` - 170 edges
4. `canonical_json()` - 169 edges
5. `ExecutionSafetyError` - 163 edges
6. `FakeDatabase` - 159 edges
7. `Database` - 122 edges
8. `ContractError` - 114 edges
9. `ExecutionRepository` - 110 edges
10. `load_config()` - 96 edges

## Surprising Connections (you probably didn't know these)
- `run()` --uses--> `PostgresNotificationLedger`  [INFERRED]
  scripts/verify_integration.py → src/investment_agent/notifications/db.py
- `run()` --uses--> `Database`  [INFERRED]
  scripts/verify_integration.py → src/investment_agent/platform/db/postgres.py
- `run()` --uses--> `SupabaseRepository`  [INFERRED]
  scripts/verify_integration.py → src/investment_agent/trading/supabase_repository.py
- `main()` --calls--> `load_config()`  [INFERRED]
  scripts/verify_notification_ledger.py → src/investment_agent/config.py
- `main()` --uses--> `PostgresNotificationLedger`  [INFERRED]
  scripts/verify_notification_ledger.py → src/investment_agent/notifications/db.py

## Import Cycles
- None detected.

## Communities (690 total, 96 thin omitted)

### Community 0 - "web.py"
Cohesion: 0.12
Nodes (36): _cboe_put_call(), _cboe_put_call_on(), _cboe_vix(), _cnn_fear_greed(), fetch_batch(), _get(), _month_starts(), _multpl() (+28 more)

### Community 1 - "ml_challengers.py"
Cohesion: 0.05
Nodes (58): Hashable, default_candidate_dir(), evaluate_candidates(), _icir(), _load_champion(), main(), Any, datetime (+50 more)

### Community 2 - "quant.py"
Cohesion: 0.06
Nodes (72): _allocation_items(), _allocation_summary(), _allocation_text(), _asset_label(), _assets_for_allocations(), _comparison_chart(), _is_equal_weight_allocation(), _metric_row() (+64 more)

### Community 3 - "EvidenceBundle"
Cohesion: 0.08
Nodes (32): EvidenceBundle, _estimates(), _external_live(), _find(), _fundamentals(), _macro_events(), _missing_reason(), _ownership() (+24 more)

### Community 4 - "SupabaseRepository"
Cohesion: 0.03
Nodes (71): normalize_ticker(), universe의 Yahoo식 표기(BRK-B)에 맞춘다., SecurityProposal의 생성 배치와 유효기간을 묶는다., SignalRecord, _feature_snapshot(), _finite(), _guru_candidate_signals(), _iso() (+63 more)

### Community 5 - "live_worker.py"
Cohesion: 0.04
Nodes (81): 저장소 표기(BRK-B)를 토스 표기(BRK.B)로 변환한다., to_toss_symbol(), TossUsRegularSession, _decimal(), _decimal_text(), parse_personal_order_event(), Any, datetime (+73 more)

### Community 6 - "macro/core.py"
Cohesion: 0.04
Nodes (84): Any, 발표 예정 카드 렌더 — HTML 템플릿 채우기 + 헤드리스 브라우저로 PNG 캡처. 알림 패키지는 자기 render와 templates를…, 예정 카드 템플릿에 ctx를 채워 HTML 문자열을 반환., HTML을 브라우저로 열어 PNG로 캡처하고 파일 경로를 반환., render(), shoot_png(), Any, 실적 카드 렌더 — HTML 템플릿 채우기 + 헤드리스 브라우저로 PNG 캡처. macro/render.py와 같은 경로지만 펀더멘탈 전용… (+76 more)

### Community 7 - "serialization.py"
Cohesion: 0.04
Nodes (55): Toss 인증·계좌 조회·주문 API client 패키지., Broker에 전달하기 전 주문 계획 계약., 로컬 SQLite 실행 원장과 canonical 종목 identity 조회 경계., ExecutionIntent, IntentError, datetime, ValueError, 판단 계층이 실행 계층에 넘길 수 있는 **유일한** 물건. ## 왜 execution이 이 모양을 소유하나 `trading`이 만든 것을… (+47 more)

### Community 8 - "parse_xbrl.py"
Cohesion: 0.16
Nodes (32): _clean_number(), _concept_local(), _concept_qname(), _context_ref(), _deep_first_local(), _dimension_path(), _dimensions_hash(), _duration_days() (+24 more)

### Community 9 - "application/backfill_history.py"
Cohesion: 0.05
Nodes (53): backfill_company_history(), backfill_segment_history(), _company_backfill_targets(), _completed_segment_accessions(), prune_segment_history(), date, 기업 재무 이력을 명시적으로 백필한다. 기업 전체 재무는 daily와 같은 companyfacts 원천을 쓰고, 세그먼트는 차원 데이터가…, 선택 CIK에서 완료된 전역 고유 accession_no 집합. (+45 more)

### Community 10 - "evidence/artifacts.py"
Cohesion: 0.11
Nodes (24): archive_case_evidence(), ArchivedCaseEvidence, _bounded_texts(), build_evidence_digest(), EvidenceArtifactError, EvidenceArtifactManifest, EvidenceArtifactStore, _latest_timestamp() (+16 more)

### Community 11 - "app_pages/earnings.py"
Cohesion: 0.04
Nodes (135): _frame_from_prices(), _latest(), Any, DataFrame, 저장된 AI 투자 판단을 선택한 깊이만큼 읽기 전용으로 검토한다., 선택된 가격 뷰 안에서만 저장된 OHLCV를 읽고 지표를 계산한다., 주문·체결 페이지가 탭 하나로 불러 쓴다. 페이지 단독 진입점은 아니다. 스크립트였을 때의 st.stop()은 return으로 바꿨다 — 탭…, render() (+127 more)

### Community 12 - "companyfacts.py"
Cohesion: 0.08
Nodes (43): _accession_coverage(), _affected_fiscal_years(), all_financial_filings(), _annual_fiscal_year(), _available_daily_index_urls(), companyfacts(), companyfacts_to_facts(), _corroborated_source_accessions() (+35 more)

### Community 13 - "launcher.py"
Cohesion: 0.14
Nodes (28): clear_screen(), configure_console(), developer_tools_menu(), find_available_port(), harness_switch_command(), interactive_menu(), is_port_available(), main() (+20 more)

### Community 14 - "watch_earnings.py"
Cohesion: 0.09
Nodes (26): fetch_reported_earnings(), _optional_float(), Yahoo Finance에서 발표 실적과 EPS 서프라이즈를 읽는 어댑터., 발표 일자별 EPS 예상·실제·서프라이즈를 반환한다., main(), main(), note_problem(), Problem (+18 more)

### Community 15 - "investment_harness.py"
Cohesion: 0.06
Nodes (63): build_registry(), _emit(), main(), 항상 켜진 로컬 장비용 투자 분석 운영 하네스. 인자 없이 실행하면 상태 파일이나 외부 서비스에 손대지 않고 계획만 출력한다., JobDefinition, StageDefinition, HealthReport, inspect_health() (+55 more)

### Community 16 - "logging.py"
Cohesion: 0.02
Nodes (162): 프로세스로 시작한 CLI만 거치는 자리. 여기서 두 가지를 한다 — 로컬 `.env`를 읽는 것과, 루트 로거를 JSON 한 줄로 맞추는 것.…, 프로세스 진입점 준비. `__main__` 블록에서만 부른다., start_cli(), main(), _parse_args(), Namespace, Yahoo 발표 이력으로 EPS 예상치를 재구성해 저장하는 수동 백필 진입점., 명시적으로만 수행하는 역사 EPS 예상치 백필. (+154 more)

### Community 17 - "ExecutionRepository"
Cohesion: 0.04
Nodes (32): _approval(), ExecutionRepository, funding_followup_allowed(), _intent(), latest_order(), latest_paper_account_snapshot(), latest_reconciliation_run(), datetime (+24 more)

### Community 18 - "sec.py"
Cohesion: 0.09
Nodes (32): earnings_8k_filings(), current submissions와 필요한 과거 fragment에서 Item 2.02를 찾는다., filing_archive_base(), filing_archive_items(), filing_document_url(), filing_homepage_url(), filings_filed_since(), _headers() (+24 more)

### Community 19 - "charts.py"
Cohesion: 0.06
Nodes (55): _as_date(), _axis_money(), _bridge_parts(), cashflow_bridge(), cashflow_quarters(), combo(), _div(), dividend_trend() (+47 more)

### Community 20 - "rl/contracts.py"
Cohesion: 0.04
Nodes (66): 일간 기술지표 ETL과 PIT feature layer (RSI·MACD → local ResearchStore). 시세 입력은 v1…, 도메인 유무와 무관하게 항상 같은 컬럼 집합을 만든다. 결측을 여기서 0으로 채우지 않는다 — RSI 0은 극도 과매도라는 실제 값이라 관측…, 단일 horizon label을 구간 종료가 확정된 뒤에만 만든다. `label_available_at`을 넘기면 실제 적재 시각을 근거로…, 1/5/20 거래일 종료 뒤에만 label을 생성한다., ResearchStore의 PIT feature snapshot을 Qlib research workflow에만 연결한다., 외부 RL 의존성 없이 재현 가능한 선형 challenger 정책., FeatureSnapshot, _finite() (+58 more)

### Community 21 - "PortfolioRiskPolicy"
Cohesion: 0.04
Nodes (59): 내용 기반의 결정론적 식별자를 만든다., stable_id(), 투자 Agent 구현을 교체 가능한 인터페이스로 제한한다., follow_weights(), FollowOutcome, FollowPolicy, order_gaps(), plan_follow() (+51 more)

### Community 22 - "_posix"
Cohesion: 0.17
Nodes (10): DatabaseNameConstantsTest, FutureAnnotationsTest, _modules(), _posix(), PresentationLayerDirectionTest, 관례 4 — 모든 모듈의 첫 import는 `from __future__ import annotations`., 관례 17 — 스키마·테이블·RPC 이름은 모듈 상수로만 부른다. 문자열을 직접 쓰면 오타가 import 에러가 아니라 런타임 PGRST…, 로거 이름은 항상 `__name__` — 고정 문자열은 어느 모듈이 냈는지 지운다. (+2 more)

### Community 23 - "src/investment_agent/data/fundamentals/application/__init__.py"
Cohesion: 0.05
Nodes (27): backfill_historical_eps_estimates(), Any, ExpectationsRepository, 과거 8-K 실적 속보에 EPS 예상치 재구성값을 채운다., 기존 실적 속보에만 Yahoo의 과거 EPS 예상치를 재구성해 저장한다., build_historical_eps_estimates(), _finite_number(), HistoricalEpsEstimateBatch (+19 more)

### Community 24 - "universe/persistence.py"
Cohesion: 0.09
Nodes (42): 추적 종목의 누락 한글명을 토스증권으로 보강한다. 토스 IP 허용목록에 등록된 로컬 환경에서만 별도 실행한다. 기존…, refresh_korean_names(), append_memberships(), apply_entity_results(), apply_toss_names(), _db(), _listing_payload(), _placeholder() (+34 more)

### Community 25 - "switch.py"
Cohesion: 0.07
Nodes (44): interactive_loop(), main(), print_status_dashboard(), Path, 투자 하네스 ON/OFF 스위치 및 제어판 CLI 진입점. 사용 예시: # 1. 종합 상태 조회 python -m…, _safe_print(), ATLAS 로컬 제어센터. 대시보드는 관측 전용으로 유지하고, 하네스 시작·정지처럼 로컬 프로세스를 변경하는 작업만 이 창에서 명시적으로…, clear_maintenance_hold() (+36 more)

### Community 26 - "reserve_provider_call"
Cohesion: 0.06
Nodes (42): RuntimeError, 뉴스 provider가 data 계층에서 반환하는 결과 계약., Reddit 자격증명이 없다. 오류가 아니라 아직 켜지지 않은 상태다., 오늘 provider 한도를 다 썼다. 수집 유스케이스와 reddit 어댑터가 함께 쓰는 계약이라 둘 중 어느 계층에도 두지 않는다.…, SocialCredentialsMissing, SocialQuotaExhausted, fetch_ticker_news(), NewsQuotaExhausted (+34 more)

### Community 27 - "MacroArchitectureTest"
Cohesion: 0.10
Nodes (18): ImportFrom, _application_code_files(), _command_code_files(), _domain_code_files(), _import_from_modules(), _importing_package(), _imports(), _infrastructure_code_files() (+10 more)

### Community 28 - "readers/intelligence.py"
Cohesion: 0.12
Nodes (32): default_database_path(), 이번 실행이 쓸 Intelligence DB 경로., connect(), ddl_statements(), DuckDBStoreError, _open_with_retry(), Any, Path (+24 more)

### Community 29 - "continuous_retrain.py"
Cohesion: 0.06
Nodes (34): adopt_candidate(), default_spec(), _last_trained_period(), main(), _parse_args(), Any, datetime, Namespace (+26 more)

### Community 30 - "reconcile_toss.py"
Cohesion: 0.09
Nodes (20): ApprovalStatusClient, ApprovalStatusPublishSummary, ApprovalStatusRepository, publish_reconciliation_statuses(), Protocol, 재조정 결과를 원래 Discord 승인 카드에만 best-effort로 되돌린다., 허용한 broker 축약 상태만 사람용 문구로 바꾼다., 원장 변경 뒤 exact approval/message에만 PATCH하며 실패를 전파하지 않는다. 승인봇 설정이 아직 없으면 조용히… (+12 more)

### Community 31 - "TransactionCostModel"
Cohesion: 0.05
Nodes (41): ChallengerComparison, ChallengerPolicy, compare_challenger(), Any, Champion과 Challenger의 비교 결과를 수동 승격 입력으로 만든다., OOS·shadow·paper 증거를 평가하되 자동 운영 승격은 항상 금지한다., _non_negative(), Any (+33 more)

### Community 32 - "select_all_paged"
Cohesion: 0.07
Nodes (47): _filings_for(), fiscal_periods(), _fundamental_rows(), observed_consensus_as_of(), _project_fundamental_rows(), datetime, 시장 예상치·발표 일정·애널리스트 커버리지 저장소 구현. 세 표 모두 상태가 바뀔 때만 새 버전을…, 상태가 바뀐 행만 넣고, 같은 상태는 기존 버전의 last_seen_at만 옮긴다. 돌려주는 수는 이번에 관측해 반영한 상태 수(새 버전 +… (+39 more)

### Community 33 - "test_historical_replay_pit.py"
Cohesion: 0.12
Nodes (8): _MembershipRepository, PriceAvailabilityTest, 과거 재현 학습이 조용히 부풀거나 비지 않게 하는 시점·단위 계약., 가격 저장소의 봉에는 적재 시각이 없다. 그것을 요구하면 모든 시가총액이 빈다., 저장 종가는 이미 현재 분할 기준이다(market이 새 분할마다 전체 이력을 다시 받는다)., 2021년 공시 주식 수에 이후 4:1·10:1 분할을 곱해야 분할 기준 종가와 시가총액이 맞는다., ReplayUniverseTest, SplitBasisTest

### Community 34 - "incidents.py"
Cohesion: 0.09
Nodes (27): _integer(), _jobs(), main(), GitHub Actions 실패 위치를 찾아 Discord 시스템 로그에 한 장으로 보낸다., Actions API의 짧은 반영 지연만 제한적으로 재시도한다., classify_incident(), _clip(), extract_error_summary() (+19 more)

### Community 35 - "ablation.py"
Cohesion: 0.07
Nodes (31): AblationVariant, _default_feature_rows(), default_variants(), ml_artifact_lookahead(), Any, date, datetime, Path (+23 more)

### Community 36 - "90_reporting.sql"
Cohesion: 0.09
Nodes (39): reporting.company_financials_latest, reporting.earnings_outlook, reporting.earnings_schedule, reporting.earnings_surprise, reporting.earnings_surprises, reporting.economic_calendar, reporting.financial_statements, reporting.institutional_filings (+31 more)

### Community 37 - "StrategyTests"
Cohesion: 0.04
Nodes (32): EarningsAndGuruTests, HarnessTests, PortfolioAndRoleTests, DataFrame, 대시보드 읽기 전용 계산의 결측 보존과 핵심 수식을 검증한다., 어닝 수식과 13F 비교가 완전한 입력에서만 작동하는지 검증한다., 과거 분기별 실적과 사전 컨센서스를 매칭하여 서프라이즈 % 및 연속 비트 streak을 계산해야 한다., 비교 테스트용 실제 long-equity 형태의 최소 행을 만든다. (+24 more)

### Community 38 - "ProductionInvestmentAdapters"
Cohesion: 0.10
Nodes (29): _metadata_id(), ProductionInvestmentAdapters, ID를 metadata로 넘기고 모든 주문 mutation은 execution entry에만 맡긴다., 따라갈 System 목표를 고른다. 같은 목표로는 한 번만 승인을 묻는다., 새 Toss 계좌 스냅샷으로 `System 목표 − 실제 계좌` 제안을 기록한다. 주문은 아직 없다., 발표 예정 시각 창에서 관심종목 공시를 훑고 알림을 바로 보낸다. 거래 창(risk_window)으로 막지 않는다 — 주문이 아니라 공시…, PIT 밸류에이션 관측값을 원장에 적재한다. live_shadow만 만든다 — 과거 시점은 가격 적재시각과 TTM vintage를 증명할 수…, tracked universe의 PIT feature snapshot을 ResearchStore에 적재한다. 주문이 아니라 데이터 생산이라… (+21 more)

### Community 39 - "company_financials.py"
Cohesion: 0.06
Nodes (45): filing_row(), 어떤 모양으로 오든 canonical `filings` 행 하나로 바꾼다. `Filing`(저장 계약)과 `FilingRef`(원문 읽기 전…, ciks_for_tickers(), ciks_missing_financials(), _ensure_filings(), filing_accessions(), _filing_state_row(), gating_universe() (+37 more)

### Community 40 - "_fetch"
Cohesion: 0.10
Nodes (16): AnalystSnapshot, ConsensusSnapshots, _earnings_estimate(), _FakeTicker, _fetch(), FiscalPeriodNormalization, _history(), DataFrame (+8 more)

### Community 41 - "event_intelligence.py"
Cohesion: 0.07
Nodes (44): canonicalize_url(), 같은 문서를 가리키는 URL을 한 모양으로. 읽을 수 없으면 `None`. 같은 기사에 tracking 파라미터만 달라진 URL이 붙어…, build_events(), EventRepository, main(), _normalized(), _parse_args(), Any (+36 more)

### Community 42 - "dashboard/db.py"
Cohesion: 0.04
Nodes (138): P, R, AI·강화학습(ML/RL) 자율진화 관제 랩 대시보드 페이지. 하네스 7대 전자동 잡의 실제 실행 상태, PPO 강화학습 챔피언 정책…, show(), _active_watchlist_rows(), _as_datetime(), _attach_entity_profiles(), _canonical_financial_rows() (+130 more)

### Community 43 - "FiscalPeriod"
Cohesion: 0.06
Nodes (29): derive_fourth_quarter(), FiscalPeriod, parse_period(), period_end_is_plausible(), PeriodError, date, ValueError, 회계기간의 규칙. ## 달력 분기가 아니다 회사마다 회계연도 끝이 다르다(애플은 9월, 마이크로소프트는 6월). `period_end`가… (+21 more)

### Community 44 - "FactorModel"
Cohesion: 0.20
Nodes (9): IC를 잴 신호들: 방향을 맞춘 개별 factor, category 점수, 종합 점수., signal_values(), FactorModel, load_factor_model_from_ic_report(), Path, category 가중치와 품질 기준. 버전은 가중치를 바꿀 때마다 올린다., IC 연구 산출물의 특정 기간 제안을 명시적인 새 모델 버전으로 읽는다. 기간과 버전을 호출자가 반드시 고르게 해 `latest.json`이…, SignalDirectionTest (+1 more)

### Community 45 - "CaseMemory"
Cohesion: 0.15
Nodes (9): CaseMemory, MemoryRepository, datetime, Protocol, 평가가 끝난 과거 판단과, 결과를 아직 모르는 직전 판단을 구분해 다음 판단에 제공한다. 평가된 사례는 "무엇이 맞았나"를 가르치고, 직전…, 미평가 판단은 배제해 자기확증 메모리가 생기지 않게 한다., CaseMemoryTest, 다음 판단에 넘기는 기억: 평가된 사례와, 결과를 모르는 직전 판단을 섞지 않는다. (+1 more)

### Community 46 - "디자인 시스템 — 알림 카드와 대시보드 UI의 단일 기준"
Cohesion: 0.22
Nodes (9): 12. 모션, 13. 접근성, 15. 아이콘과 일러스트, 17. 컴포넌트 상태 매트릭스, 19. 절대 하지 않는 것, 1. 한 문장 정의, 20. 설계 근거, 4. 토큰 구조 (+1 more)

### Community 47 - "ContractError"
Cohesion: 0.07
Nodes (30): PositionSnapshot, AccountSnapshot, _nonnegative_number(), Any, datetime, 현금과 보유 평가액을 합친 스냅샷 기준 순자산., CASH를 포함해 합이 1인 현재 포트폴리오 비중., 계좌와 freshness가 맞지 않으면 전체 포트폴리오 생성을 막는다. (+22 more)

### Community 48 - "releases/db.py"
Cohesion: 0.18
Nodes (41): 미래 발표의 예상값을 매번 확인하고, 달라진 상태만 DB가 원자적으로 저장한다., snapshot_forecasts(), split_event_key(), append_forecasts(), append_observations(), calendar_window(), counts(), _db() (+33 more)

### Community 49 - "DailyBar"
Cohesion: 0.04
Nodes (44): adjust(), dividend_factors(), _previous_close(), date, 분할·배당으로 과거 가격을 조정한다. ## 왜 저장하지 않고 계산하는가 조정가를 저장하면 **분할이 하나 새로 들어올 때마다 과거 행 전체를…, 거래일마다 곱할 분할 계수. 분할 당일(`action_date`)의 가격은 이미 분할 후 가격이다. 따라서 조정 대상은 **그 전날까지**다.…, 거래일마다 곱할 배당 계수(총수익 기준). 배당락일 전날 종가를 기준으로 `1 - 배당/종가`를 누적한다. 종가를 모르면 그 배당은 건너뛴다…, 배당락일 **직전 거래일**의 종가. 휴장을 건너뛰어야 하므로 목록을 거슬러 찾는다. (+36 more)

### Community 50 - "SelectOnlyGatewayTests"
Cohesion: 0.05
Nodes (17): DashboardStaticBoundaryTests, _FakeBuilder, _FakeClient, _FakeFunction, _FakeSchema, OfflineBoundaryTests, Any, manager_cik/name/fund_name/is_active는 코드 설정이 SSOT이므로 `institutional.managers`를… (+9 more)

### Community 51 - "ReportingQueries"
Cohesion: 0.06
Nodes (23): load_released(), parse_time(), Any, datetime, 경제 발표 알림의 reporting reader 경계. 보낼지 말지는 원장(엔진)이 판단한다., 최근 first actual이 확인된 발표. 같은 발표를 여러 번 읽어도 원장이 한 번만 보낸다., 화면과 알림에 같은 DataResult를 반환한다. 실패를 빈 결과로 숨기지 않는다., ReportingQueries (+15 more)

### Community 52 - "experiment.py"
Cohesion: 0.07
Nodes (25): PPOAllocationTimingSpec, Any, PPO의 초기 범위를 allocation·timing으로 제한한다., PPO가 broker나 종목 수량을 직접 만들지 않는 연구 명세., Python·NumPy의 seed를 함께 고정하고 지역 RNG를 반환한다., set_deterministic_seed(), make_gym_environment(), FinRL/Stable-Baselines3가 요구하는 Gymnasium 환경을 지연 생성한다. (+17 more)

### Community 53 - "build_market_regime"
Cohesion: 0.09
Nodes (28): 시장 가격을 Dashboard용 regime read model로 투영한다., MarketRegime, 종목별 판단보다 먼저 공유되는 시장 환경 snapshot이다., build_market_regime(), _clamp(), _drawdown_fraction(), MarketRegimeCalculator, _number() (+20 more)

### Community 54 - "worker.py"
Cohesion: 0.05
Nodes (35): from_toss_symbol(), 토스의 미국 종목 표기를 저장소 표기로 변환한다., _attempt_event(), OrderAttemptEvent, 시도에 붙는 사건 하나. 상태는 덮어쓰지 않고 쌓는다., 사람이나 재동기화가 확인해야 하는 상태인가. `outcome_unknown`을 실패로 다루면 다시 보내게 되고, 그것이 중복 체결의 가장 흔한…, OrderFill, PositionBaseline (+27 more)

### Community 55 - "run_backtest"
Cohesion: 0.29
Nodes (8): BacktestConfig, 동일 입력에서 체결 결과를 바꾸는 엔진 설정이다., 작은 호출 경계를 제공해 향후 entry·FinRL adapter가 엔진 타입에 결합되지 않게 한다., run_backtest(), BacktestEngineTest, market_bar(), request(), weight_point()

### Community 56 - "ApprovalRequest"
Cohesion: 0.07
Nodes (20): ApprovalRequest, 특정 주문 계획 하나에만 유효한 건별 사람 승인., ApprovalRepository, Protocol, _Repository, ApprovalSchemaTest, 새 설치는 execution_control 행을 자동으로 채우지 않는다. Postgres 시절에는 스키마 적용이…, _config() (+12 more)

### Community 57 - "TradingRepository"
Cohesion: 0.09
Nodes (12): Any, 승인 전 제안·거절 audit만 기록한다. 승인은 수동 게이트를 거친다., 현재 단계를 잠근 뒤 승인 audit만 추가한다., 이미 계산된 회차 상태를 v1 원장에 기록한다., 완전성 배치와 immutable 종목 신호를 함께 기록한다., 승인·매수 여부와 무관한 원본 완료 판단을 읽는다., 판단 한 건. `final_decision`과 `failure_reason`은 배타적이다., 위험 판정. 거절이면 승인 비중이 없어야 한다. (+4 more)

### Community 58 - "normalize_ticker"
Cohesion: 0.07
Nodes (23): normalize_ticker(), 밖에서 온 종목 표기를 우리 표기로. 읽을 수 없으면 `None`. 점을 하이픈으로 바꾸는 이유: 같은 종목을 SEC은 `BRK.B`,…, Entity, Any, ValueError, 더 깊이 볼 회사. 알림 여부는 여기서 정하지 않는다(notifications의 몫). 관심의 identity는 `cik`다.…, 출처가 하나라도 남아 있으면 계속 본다. 토스 보유가 빠져도 수동 등록이 남아 있으면 활성이다. 저장소도 같은 식으로 `is_active`를…, 저장소 행이 universe의 계약을 어겼다. (+15 more)

### Community 59 - "VersionKey"
Cohesion: 0.10
Nodes (20): latest(), latest_known_at(), datetime, 여러 버전 중 "그 시점의 최신"을 고르는 규칙. ## 왜 고르는 일이 따로 있어야 하나 v1은 정정공시가 원본을 덮지 않는다. 같은…, 버전 하나를 고르는 데 필요한 것 전부., PostgREST는 timestamptz를 **문자열**로 준다. 그대로 두면 비교하는 순간에야 터지는데, 그 자리는 저장소에서 한참 떨어져…, 지금 기준 최신. 제출일이 늦은 것, 같으면 나중에 손에 넣은 것. 제출일이 같은 정정이 실제로 있다(같은 날 두 번 낸다). 그때…, `as_of` 시점에 우리가 알고 있던 것 중 최신. 이것이 v1이 정정 이력을 남기는 이유 그 자체다 — "2026년 3월에 우리가 알던… (+12 more)

### Community 60 - "yahoo_finance/consensus.py"
Cohesion: 0.14
Nodes (35): _add_quarter(), _analyst_snapshot(), _as_date(), fetch_consensus(), _frame(), _int(), _next_quarter_end(), _next_report() (+27 more)

### Community 61 - "SystemPortfolioStore"
Cohesion: 0.05
Nodes (37): main(), advance(), DailyMark, first_session_after(), _gross(), performance_summary(), datetime, System Portfolio의 비중 기반 회계. 가상 현금·수량·주문·체결이 없다. 한 거래일을 넘기는 계산은 둘뿐이다. 1. **평가**:… (+29 more)

### Community 62 - "application/refresh_expectations.py"
Cohesion: 0.06
Nodes (30): build_earnings_estimates(), ConsensusBatch, date, 시장 원천의 상대 기간을 표준 회계기간 스냅샷으로 변환한다., 예상치 수집 한 번에서 만들어진 정규화 결과., 컨센서스와 발표 예정일을 같은 회계기간 키에 맞춘다., ConsensusSource, date (+22 more)

### Community 63 - "local_mirror/sync.py"
Cohesion: 0.07
Nodes (22): _frame(), MirrorSource, _preferred_ids(), Any, DataFrame, datetime, timedelta, Supabase(원본 창고) → 로컬 사본(계산 작업장) 동기화. ``` universe.securities · entities ─┐… (+14 more)

### Community 64 - "investment/embeds.py"
Cohesion: 0.08
Nodes (31): candidate_embed(), _date(), _lines(), _percent(), portfolio_embed(), Any, 자동매매 판단·체결을 Discord embed로 조립한다. 여기서 하는 일은 조립뿐이다 — DB도 네트워크도 만지지 않으므로 그대로 단위…, System Portfolio 목표 카드. RiskGate 판정과 비중이 바뀐 이유가 중심이다. (+23 more)

### Community 65 - "ml_serving.py"
Cohesion: 0.05
Nodes (43): AdoptionCheck, check_adoptable(), main(), _parse_args(), Any, Namespace, 학습된 ML artifact를 판단 경로가 읽는 채택 모델로 올린다. `ml_serving`은 `active_ml_model.json`이…, impute_cross_section() (+35 more)

### Community 66 - "개별 주식 심층 분석 — 외부 GPT용 질의 템플릿"
Cohesion: 0.06
Nodes (31): 1. 공통 시스템 프롬프트 (그대로 복사), 2-1. 표준 수집 스크립트 (yfinance · 키 불필요), 2-2. 동종/벤치마크 ETF 비교 스크립트 (3단계에서 출력), 2-3. 역사적 PER/PBR 재구성 스크립트 (접근 C · edgartools · SEC 실측 · API 키 불필요), ETF 분석 하네스 — 세팅 팩 (US v1), prompts/ — 외부 GPT용 질의 템플릿, 사용, 스키마를 바꿀 때 (+23 more)

### Community 67 - "export_dataset.py"
Cohesion: 0.13
Nodes (14): export_dataset(), main(), _parse_args(), Any, Namespace, Path, 저장된 feature snapshot과 forward label을 학습용 dataset JSON으로 내보낸다.…, 원장을 읽어 label이 확정된 행만 학습 dataset으로 결합한다. (+6 more)

### Community 68 - "LocalMirror"
Cohesion: 0.11
Nodes (17): LocalMirror, mirror_root(), MirrorManifest, Any, DataFrame, date, datetime, Path (+9 more)

### Community 69 - "calculations/__init__.py"
Cohesion: 0.03
Nodes (121): covariance_to_correlation(), finite_number(), parse_date_safe(), parse_datetime_safe(), Any, datetime, 대시보드 계산 기본 파싱·변환 유틸리티., DataFrame 또는 매핑 시퀀스를 복사된 레코드 목록으로 정규화한다. (+113 more)

### Community 70 - "toss/client.py"
Cohesion: 0.05
Nodes (48): access_token(), _authorized_headers(), fetch_accounts(), fetch_buying_power(), fetch_exchange_rate(), fetch_holdings(), fetch_open_orders(), fetch_prices() (+40 more)

### Community 71 - "OptimizerPolicy"
Cohesion: 0.08
Nodes (29): optimizer가 거래 **전에** 비용을 뺄 수 있도록 종목별로 추정한 편도 반스프레드. 따라가는 실계좌가 수천 달러 규모라 주문이 시장…, TradingCostInputs, ExpectedReturnSignal, OptimizationResult, OptimizerPolicy, ndarray, 종목 기대수익을 결정적 convex portfolio 비중으로 변환한다. ## 비중은 여기서만 정해진다 ALPHA는 종목마다 기대수익과,…, cvxpy가 infeasible/미설치면 주문 가능한 비중을 만들지 않고 실패한다. (+21 more)

### Community 72 - "BrokerAdapter"
Cohesion: 0.11
Nodes (15): BrokerAccount, BrokerAdapter, BrokerError, BrokerFill, BrokerOrder, BrokerOutcomeUnknown, BrokerPosition, BrokerQuote (+7 more)

### Community 73 - "_text"
Cohesion: 0.13
Nodes (9): EconCalendarChainTest, ExpectationsWorkflowTest, NotificationWorkflowTest, NotifyChainTest, 무관한 CIK 하나로 ETL이 exit 1 하는 일이 잦다 — success로 잠그면 알림이 묻힌다., watcher가 같은 러너에서 이미 보내므로 여기에 workflow_run을 걸지 않는다. 걸면 watch가 도는 족족 러너가 한 번 더…, 미국 지표 발표 시각대에만 깨어난다. 24시간 `*/5`는 한 달 8,766번이고 저장소 할당은 2,000분이라, 이 워크플로 하나가 예산을…, _text() (+1 more)

### Community 74 - "identifiers.py"
Cohesion: 0.11
Nodes (15): _cusip_char_value(), cusip_check_digit(), is_valid_identifier(), normalize_cik(), normalize_cusip(), 종목을 가리키는 이름들의 규칙. ## 왜 platform이 아니라 여기인가 ticker 정규화와 CUSIP 검증은 "투자 데이터"를 알아야만…, 저장소가 받아들일 모양인가. 넣기 전에 여기서 거른다., CIK를 10자리 0채움 문자열로. 읽을 수 없으면 `None`. SEC은 같은 회사를 `320193`, `0000320193`,… (+7 more)

### Community 75 - "factor_research.py"
Cohesion: 0.15
Nodes (16): forward_returns(), group_snapshots(), horizon_dates(), main(), overlap_factor(), date, quantile_spread(), 과거 재현 시점들의 factor 점수가 실제로 앞으로의 수익률 순위를 맞혔는지(IC) 잰다. python -m… (+8 more)

### Community 76 - "tradingagents_adapter.py"
Cohesion: 0.05
Nodes (77): _date_ok(), _domain_payload(), fetch_fundamentals(), fetch_macro_indicators(), fetch_statement(), TradingAgents Fundamentals Analyst를 위한 SEC 재무제표·Gurus·거시지표 데이터 소스 어댑터., 재무제표, 밸류에이션, 세그먼트, 13F 기관 대가 지분을 시점 일치 번들에서 읽는다., 손익계산서/대차대조표/현금흐름표를 시점 일치 번들에서 읽는다. (+69 more)

### Community 77 - "FakeRepository"
Cohesion: 0.06
Nodes (34): plan_with_funding(), 지금 가진 현금으로 매수를 다 못 대면 이번 승인은 **매도만** 담는다. 아직 체결되지 않은 매도대금은 현금이 아니다(worker의 연쇄…, S&P 500 미국주식 sleeve의 읽기 전용 계좌 스냅샷., TossManualSnapshot, approval(), FakeApi, FakeRepository, funding_handoff() (+26 more)

### Community 78 - "features/db.py"
Cohesion: 0.10
Nodes (32): main(), Daily technical indicators entrypoint., changed_indicators(), delete_before(), earliest_market_change_since(), existing_indicators_since(), features_for_ticker(), features_since() (+24 more)

### Community 79 - "reported_observations.py"
Cohesion: 0.09
Nodes (46): _clone(), _credible_total_equity(), _date_s(), _derive_mezzanine_from_balance_totals(), _derive_mezzanine_from_components(), _derive_minority_interest_from_total_equity(), _derive_spac_mezzanine_from_trust(), _duration_days() (+38 more)

### Community 80 - "backtest/contracts.py"
Cohesion: 0.12
Nodes (26): BacktestSafetyError, CashEvent, CorporateActionApplication, FillEvent, MarketBar, NavPoint, OrderEvent, PositionSnapshot (+18 more)

### Community 81 - "econ_calendar.py"
Cohesion: 0.10
Nodes (39): dialog, _as_date(), _calendar_query_window(), _country_emoji(), _event_card(), _expected_number(), _korean_time(), _number() (+31 more)

### Community 82 - "universe/test_persistence.py"
Cohesion: 0.06
Nodes (17): ListingSyncDoesNotOwnTheGateTest, PersistenceDotTickerNormalizationTest, PersistenceSecurityProfilesTrackedOnlyTest, PersistenceSecurityQueriesTest, persistence.py의 조회 함수가 UniverseRepository로 위임한 뒤에도 같은 값을 주는지 굳힌다. 리팩터 전 특성화 테스트…, 수집 게이트를 정하는 자리다. 여기서 틀리면 모든 하류가 조용히 더 돈다. 실제로 두 가지가 함께 틀려 있었다. * 과거 멤버 행에는…, `is_tracked` 키가 없는 행은 게이트에 대해 아무 말도 하지 않는다., 현재 멤버인데 마스터에 없으면 CIK를 모른다 — 지어내면 재무가 영영 안 붙는다. (+9 more)

### Community 83 - "parse_shares.py"
Cohesion: 0.09
Nodes (31): aggregate_company_share_history(), _clean_member_title(), drop_implausible_share_rows(), _is_preferred_or_derivative(), _match_class_ticker(), _normalize_class_key(), parse_common_shares_from_companyfacts(), parse_common_shares_from_xbrl_document() (+23 more)

### Community 84 - "read_runtime_rows"
Cohesion: 0.09
Nodes (32): load_alpha_lab_data(), 투자 엔진의 최근 입력·모델·신호·위험 심사 사실을 한 번에 읽는다. 표마다 적재 주기가 다르므로 한 표의 실패가 전체 화면을 가리지 않게…, latest_analysis_run_id(), latest_portfolio(), Any, 자동매매 보고서의 로컬 판단·실행 원장 조회 경계., 가장 최근 System Portfolio 목표와 그 risk 판정·실행을 로컬 원장에서 묶는다. 실계좌 추종…, 종목 판단이 기록된 가장 최근 분석 회차. System 목표 회차와 달리 종목 논지를 갖는다. (+24 more)

### Community 85 - "backtest/cli.py"
Cohesion: 0.25
Nodes (11): _atomic_json(), load_backtest_input(), main(), _mapping(), Any, Path, 완전한 오프라인 JSON 입력을 결정론적 백테스트 artifact로 변환한다., CorporateAction (+3 more)

### Community 86 - "BacktestRequest"
Cohesion: 0.12
Nodes (17): BacktestRequest, BacktestResult, 네트워크나 DB 없이 재생할 수 있는 완전한 백테스트 입력이다., 입력 hash와 모든 장부를 포함하는 재현 가능한 결과 artifact다., 시장 이벤트를 순서대로 적용해 동일 입력에 동일 장부를 만든다., WeightBacktestEngine, 목표 비중을 가격 이벤트 위에서 재생하는 결정론적 백테스트., BacktestComparison (+9 more)

### Community 87 - "harness/runtime.py"
Cohesion: 0.06
Nodes (22): _idempotency_key(), datetime, job 등록, 일정 판정, stage 전이를 담당하는 단일 프로세스 scheduler., _run_id(), 상태·로그·설치 미리보기에 비밀값이 섞이지 않게 정리한다., HarnessState, JobRuntime, Any (+14 more)

### Community 88 - "Any"
Cohesion: 0.07
Nodes (20): date, 전체 재처리 뒤 현재 매핑 버전이 아닌 행과 보관 기간 밖의 행을 제거한다. 같은 공시를 현재 매핑 버전으로 다시 처리했을 때만 부른다. 옛…, reconcile_wide_history(), delete_history_before(), 보존 하한 이전의 지표와 공시 상태를 외래키 순서대로 제거한다. ``segment_metrics``가 ``filings``를 참조하므로 자식…, chunk_filter_values(), chunk_values(), _LazyServiceClient (+12 more)

### Community 89 - "build_training_samples.py"
Cohesion: 0.09
Nodes (29): _benchmark_close_at(), build_labels(), _closes_by_date(), _label_symbols(), main(), _parse_args(), Any, date (+21 more)

### Community 90 - "SimpleNamespace"
Cohesion: 0.09
Nodes (10): SimpleNamespace, PressReleaseDocument, 8-K 실적 보도자료에서 안전하게 읽을 수 있는 원천값 묶음., _EarningsRepository, LoadReleasedTest, EarningsConsensusReaderTest, 실적 consensus reader와 v1 필드 계약을 검증한다., TradingCostEstimateTest (+2 more)

### Community 91 - "process_company_facts"
Cohesion: 0.12
Nodes (13): process_company_facts(), Any, 표준 fact를 기업 전체 재무로 만들고 저장한다., build_company_financials(), CompanyFinancialBatch, 표준 공시 fact에서 기업 전체 재무 결과를 만든다., fact 선택·기간 파생·wide 생성·검증을 한 번만 수행한다., 한 번에 원자적으로 저장할 기업 전체 재무 결과. (+5 more)

### Community 92 - "market_risk.py"
Cohesion: 0.12
Nodes (22): _aligned_returns(), calculate_market_covariance(), calculate_market_risk(), _close_by_date(), estimate_betas(), historical_tail_losses(), ledoit_wolf_constant_correlation(), MarketCovariance (+14 more)

### Community 93 - "market/domain/models.py"
Cohesion: 0.07
Nodes (26): action_rows(), attach_security_ids(), changed_prices(), clean_price_row(), collect_prices(), CollectedPrices, 일봉·기업행위 수집의 공통 절차. daily와 backfill은 대상과 기간만 다르다. ## 종목 신원은 수집을 시작할 때 고정한다 요청할…, 새 키이거나 저장된 값과 다른 가격 행만 돌려준다. (+18 more)

### Community 94 - "release_catalog.py"
Cohesion: 0.11
Nodes (22): enrich_series(), measure_definitions(), Any, 고정 30개 지표의 수집기 설정. API 옵션·라이선스 설명은 사실표에 반복하지 않는다., 경제 발표 계산에 필요한 고정 measure 정의를 반환한다., 호출자가 고정 설정을 수정하지 못하도록 복사해 반환한다., DB의 표시·단위 master와 코드의 수집 계약을 실행 시점에 결합한다., 빈 DB의 경제지표 master를 재현할 수 있는 코드 catalog. (+14 more)

### Community 95 - "intelligence/repository.py"
Cohesion: 0.09
Nodes (31): FetchNews, FetchPosts, collect_news(), _mention(), datetime, 관심종목 뉴스 수집 유스케이스. ## fetch를 주입받는다 provider 호출을 이 모듈이 직접 하면 테스트가 네트워크를 타야 한다.…, 조회해서 받은 기사의 언급. 등급은 결정론적이다., 관심종목별로 뉴스를 가져와 저장하고 실행 기록을 남긴다. (+23 more)

### Community 96 - "SegmentSnapshotOrderTest"
Cohesion: 0.46
Nodes (3): _metrics(), 세그먼트 스냅샷이 고르는 20행은 조회 순서에 흔들리지 않는다. 정렬 기준이 매출 하나뿐이면 매출이 없는 행들이 전부 동점이고, 파이썬 정렬은…, SegmentSnapshotOrderTest

### Community 97 - "main"
Cohesion: 0.13
Nodes (26): _as_datetime(), _failure(), ingest_raw(), Any, date, datetime, ISO UTC/aware datetime와 datetime 객체를 동일하게 비교한다., 원자료를 한 번만 저장한다. 최초 관측 판정은 계산 결과의 전후 차이로 얻는다. (+18 more)

### Community 98 - "build_segment_metrics.py"
Cohesion: 0.07
Nodes (51): 차원이 있는 공시 fact에서 세그먼트 지표를 만든다., _build_wide(), _drop_aggregate_rows(), _init_row(), _is_better(), _period_parts(), 파싱한 세그먼트 fact를 영구 저장 가능한 지표 wide 행으로 조립한다., column_key·period_kind가 부여된 candidate fact를 wide 행으로 피벗한다. (+43 more)

### Community 99 - "load_config"
Cohesion: 0.03
Nodes (154): Renderer, default_config(), load_config(), Path, 설정을 명시적으로 읽는 자리. 실제 환경변수가 `.env`보다 우선하고, 필수 값은 호출 시점에 검증하며, 비밀값은 로그에 기록하지 않는다., 설정을 한 번 읽는다. **진입점에서만** 부른다. `use_dotenv=False`는 테스트용이다 — 로컬 `.env`가 테스트 결과를…, 진입점이 매번 넘기기 번거로운 자리를 위한 캐시. 라이브러리 코드에서는 쓰지 않는다 — 쓰면 그 함수는 프로세스 환경에 묶여 테스트에서 격리할…, ForumThread (+146 more)

### Community 100 - "renderers/text.py"
Cohesion: 0.10
Nodes (34): build(), _number(), Any, 경제발표 결과를 survey/nowcast/own_model과 혼동 없이 Discord에 표시한다., build_filing(), build_quarterly(), _matrix(), _move_label() (+26 more)

### Community 101 - "target.py"
Cohesion: 0.06
Nodes (48): ChampionForecast, champion 모델 한 번의 예측. 쓸 수 없으면 `expected_excess_returns`가 비고 이유가 남는다., estimate_trading_costs(), point-in-time 일봉만으로 20일 평균 거래대금과 반스프레드를 추정한다., FactorExposureLimit, mandatory_base_weights(), 신호 종목 비중으로 가중평균한 factor 노출의 범위. 종합 점수만 최대화하면 점수에 가장 크게 기여하는 한 factor(보통 모멘텀)에…, 한도 준수에 **반드시** 필요한 매도만 먼저 반영한 출발 비중이다. turnover 한도는 재량 매매의 비용을 묶는 장치다. 청산 명령과… (+40 more)

### Community 102 - "provider.py"
Cohesion: 0.12
Nodes (21): NewsResult, Any, provider 호출 결과와 실패 원인을 data 계층 안에서 보존한다., 표시할 뉴스가 준비된 결과인지 반환한다., _canonical_url(), load_live_news(), _news_enabled(), _news_time() (+13 more)

### Community 103 - "is_transient"
Cohesion: 0.13
Nodes (13): HTTPError, HTTPStatusError, _is_retryable(), is_transient(), BaseException, 구 공통 API의 private 테스트 계약을 최종 platform 정책으로 연결한다., _status_is_transient(), CommonRetryTests (+5 more)

### Community 104 - "earnings/schedule.py"
Cohesion: 0.08
Nodes (36): d_day_label(), Any, date, 선택한 지평을 실제 날짜 구간으로 바꾼다. 반환값은 ``(시작일, 종료일, 기간별 분리 여부)``다. 모르는 라벨은 예외 대신 기본 창으로…, Discord 예정 카드와 같은 방향으로 남은 날짜를 표시한다., schedule_window(), build(), _day_label() (+28 more)

### Community 105 - "_markdown_files"
Cohesion: 0.12
Nodes (16): _declared_relations(), DeclaredRelationTest, DocumentShapeTest, _markdown_files(), MarkdownLinkTest, Path, 문서가 말하는 것이 저장소에 실제로 있는지 본다. 문서는 코드와 달리 틀려도 아무도 알려주지 않는다. import 오류도 테스트 실패도 없이…, 문서가 부르는 표 이름은 선언에 있어야 한다. (+8 more)

### Community 106 - "make_filing_record"
Cohesion: 0.13
Nodes (15): SEC Summary와 직접 파싱 결과가 완전히 일치하는지 검증한다., _validate_filing(), make_filing_record(), make_position(), Position, gurus 테스트용 FilingRecord/Position 팩토리. 외부 의존성 없음., edgar.py가 만들어내는 것과 동일한 형태의 검증 통과용 레코드., 13F 적재 전 검증 계약. SEC 요약(tableEntryTotal)이 세는 것은 informationTable의 **원시 행**이다.… (+7 more)

### Community 107 - "FeatureLayer"
Cohesion: 0.08
Nodes (18): FeatureLayer, EvidenceBundle 외의 SQL 접근을 모델에서 금지하는 단일 feature 경계다., EvidenceItem, FeatureLayerTest, _bars(), BuildLabelsEntryTest, _bundle(), FeatureColumnStabilityTest (+10 more)

### Community 108 - "parser.py"
Cohesion: 0.19
Nodes (20): _amendment_type(), _boolean(), _child(), _child_text(), _date(), identifier_type(), _integer(), local_name() (+12 more)

### Community 109 - "TradingAgentsAdapterTest"
Cohesion: 0.08
Nodes (11): _bundle(), _Client, _ExternalClient, _ExternalRunner, LocalEvidencePersistenceTest, TradingAgents가 활성 Supabase bundle 밖으로 나가지 않는지 검증한다., 뉴스·소셜 원문이 기사 단위로 남아야 사건 추출이 그것을 읽을 수 있다., 호출마다 정해 둔 인용 ID를 돌려준다. 재요청 본문은 JSON 뒤에 위반 설명이 붙는다. (+3 more)

### Community 110 - "test_roles.py"
Cohesion: 0.04
Nodes (21): EveryoneTest, GrantTest, OnboardingGateTest, PlanTest, PrivateCategoryTest, 역할·권한 선언이 조용히 잘못 열리거나 잘못 닫히지 않는지 지킨다. 권한은 틀려도 아무것도 실패하지 않는 종류다. 너무 열면 아무 일도 안…, 공개 채널을 실수로 숨기면 사람들은 그 채널이 있는 줄도 모른다. ai_investor는 보유종목·비중·체결가가 드러나므로 숨긴다., 이 설계의 전제. @everyone에 쓰기 권한이 붙으면 모든 카드 채널이 한 번에 열린다. (+13 more)

### Community 111 - "LocalEvidenceCache"
Cohesion: 0.04
Nodes (45): _clean(), _parse_bracketed_messages(), parse_external_payload(), _parse_markdown_articles(), Any, provider 응답 blob을 기사·게시물 단위 ExternalContent로 쪼갠다. upstream TradingAgents는 항목…, `시각 · @작성자 · 태그` 머리말을 시각·작성자·감성으로 나눈다., 대괄호 머리말이 붙은 게시물을 항목별로 나눈다. 이어지는 줄은 앞 글에 붙인다. (+37 more)

### Community 112 - "CLAUDE.md — 이 저장소의 개발 규칙"
Cohesion: 0.11
Nodes (19): CI / GitHub Actions, CLAUDE.md — 이 저장소의 개발 규칙, `prompts/` — 코드가 아닙니다, 대시보드 ([src/investment_agent/dashboard/](src/investment_agent/dashboard/README.md)), 데이터·연구 owner (`src/investment_agent/`), 런타임 한계 (넘기면 조용히 틀립니다), 로컬 실행 스크립트, 아키텍처 (+11 more)

### Community 113 - "FakeDatabase"
Cohesion: 0.03
Nodes (49): MembershipSnapshot, 그날 지수에 무엇이 있었는가. 이것이 없으면 backtest가 생존 편향에 걸린다 — 지금 살아남은 종목만 과거에 넣게 되기 때문이다. 그래서…, ActiveManagerQueryTest, manager_cik/name/fund_name/is_active의 SSOT는 코드 설정이다 — DB는 전혀 관여하지 않으므로…, MacroWriterTest, v1 macro writer는 원천 날짜를 가용 시각으로 가장하지 않는다., ActionsTest, BadRowTest (+41 more)

### Community 114 - "budget.py"
Cohesion: 0.09
Nodes (25): _macro_exposure(), Any, datetime, 시장·거시 입력을 오늘의 위험 한도로 바꾼다. 종목을 고르지 않고 한도만 조인다. ``` SPY 가격 → 시장…, 가격 시장 상태와 거시 노출 규칙을 모두 반영한 위험 정책과 그 근거 metadata., risk_budget(), assess_macro_exposure(), MacroExposureState (+17 more)

### Community 115 - "FakeQuery"
Cohesion: 0.07
Nodes (11): 승인·계획·원장·broker를 격리하는 v1 실행 경계., 주문을 쓰기 전에 universe identity를 결박하고 승인 표기를 보존한다., TossOnlyTest, FakeClient, FakeQuery, FakeRpc, Any, 테스트가 쓰는 가짜 PostgREST. ## 왜 patch가 아니라 가짜 객체인가 `Database`를 인자로 받는 구조에서는 가짜 연결을… (+3 more)

### Community 116 - "sec_entities.py"
Cohesion: 0.09
Nodes (30): classify_security_type(), norm_ticker(), S&P500 원천 데이터의 표준화와 PIT snapshot 계산., 종목코드 표기 통일. 예: 'BRK.B' → 'BRK-B'. 빈 값도 안전 처리., 4자리 SIC 코드 → 대분류(division) 명. SIC 표준 11개 대분류(10 division + 미분류). 세부…, Classify security into data-driven security types. Allowed types: common_stock,…, sic_division(), _download() (+22 more)

### Community 117 - "운영 — 설치, 자동 실행, 상태 확인과 장애 대응"
Cohesion: 0.10
Nodes (21): Discord-first 운영 기록, GitHub Actions, Maintenance hold, Research Actions 산출물과 로컬 운용, Secret 관리, Supabase 접근과 스키마, TradingAgents는 lock 밖에 있다, 기본 검증 (+13 more)

### Community 118 - "FeatureDataset"
Cohesion: 0.04
Nodes (55): BaselinePolicyConfig, BaselinePolicyModel, DurablePolicyArtifact, load_baseline_policy(), Any, ndarray, Path, 현재 tracked mask가 false인 종목에는 반드시 0 비중을 준다. (+47 more)

### Community 119 - "TossOrderApiTest"
Cohesion: 0.20
Nodes (8): command(), controls(), FakeResponse, permit(), remote_order(), risk_state(), TossOrderApiTest, TossOrderCommandTest

### Community 120 - "environment.py"
Cohesion: 0.04
Nodes (41): ContinuousLearner, PolicyEvaluationScore, PromotionDecision, Any, 같은 독립 평가 구간에서 연구 후보의 수동 채택 자격을 판정한다., 신규 챌린저 모델과 기존 챔피언 모델의 성과를 대조하여 승격 여부를 결정한다., 주어진 모델을 FeatureDataset 환경에서 롤아웃 시뮬레이션하여 성과 및 DSR을 산출한다., RewardConfig (+33 more)

### Community 121 - "CompanyFilingSource"
Cohesion: 0.14
Nodes (9): CompanyFilingSource, EarningsFilingSource, Any, date, Protocol, 기업 전체 재무 공시 탐색과 Company Facts 원천., 세그먼트 재무용 SEC FSDS 원천., Item 2.02 실적 발표 공시 원천. (+1 more)

### Community 122 - "normalize_segment_facts.py"
Cohesion: 0.11
Nodes (21): bulk_frames_to_filings_and_facts(), _dimension_path(), _dimensions_hash(), _int_to_date(), parse_dimensions(), _period_is_usable(), Any, date (+13 more)

### Community 123 - "services/investment/__init__.py"
Cohesion: 0.09
Nodes (36): _bounded_counts(), _bounded_text(), _bounded_texts(), _bounded_timestamps(), build_decision_case_read_model(), build_decision_cases_read_model(), _claim_summaries(), _mapping() (+28 more)

### Community 124 - "app_pages/intelligence.py"
Cohesion: 0.07
Nodes (61): _engine_snapshot(), _engine_steps(), _list(), _mapping(), _merge_execution_payload(), _normalise_article(), _provider_payload(), Any (+53 more)

### Community 125 - "src/investment_agent/operations/harness/__init__.py"
Cohesion: 0.09
Nodes (28): _format_terminal_output(), main(), 투자 하네스 보안 및 런타임 안전 감사 CLI. 사용 예시: python -m…, _safe_print(), HarnessMode, Enum, str, 운영 하네스 job·stage의 실행 계약. (+20 more)

### Community 126 - "infrastructure/sources/yfinance.py"
Cohesion: 0.16
Nodes (25): _extract_batch_close(), fetch_batch(), _fetch_info_ratio(), _fetch_many(), _fetch_one(), _market_today(), DataFrame, date (+17 more)

### Community 127 - "releases/schedule.py"
Cohesion: 0.16
Nodes (25): _add_months(), _first_business_day(), _month_start(), _months(), official_calendar_dates(), Any, date, datetime (+17 more)

### Community 128 - "holdings.py"
Cohesion: 0.14
Nodes (14): portfolio_weights(), Position, 13F 보유 신고를 읽는 규칙. ## 정정이 원본을 대체하는 방식이 두 가지다 13F 정정(13F-HR/A)에는 두 종류가 있고, 처리가…, 주식 보유인가. 옵션과 섞으면 풋이 매수로 둔갑한다., 주식 보유만. 옵션은 성격이 달라 같은 목록에 두지 않는다., CUSIP별 비중. 합이 0이면 빈 결과 — 0으로 나누지 않는다. 비중은 신고된 시장가치 기준이다. 주식수 기준으로 하면 가격이 다른 종목을…, 신고서의 한 줄. `identifier`는 CUSIP이라 종목 매핑은 universe가 한다., share_positions() (+6 more)

### Community 129 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 130 - "auth.py"
Cohesion: 0.13
Nodes (23): _access_token(), _fetch_chunk(), fetch_korean_names(), toss.py — 토스증권 Open API에서 미국 종목의 한글명을 보강한다. OAuth2 client_credentials로 access…, 공용 token을 반환하고 실패는 미시도 상태로 호출자에게 전달한다., 우리 표기(BRK-B) → 토스 표기(BRK.B)., 종목코드 목록 → (찾은 {ticker: 한글명}, 실제로 조회한 ticker 목록). 두 번째 값(attempted)은 '실제로 토스에…, _to_toss_symbol() (+15 more)

### Community 131 - "_snap"
Cohesion: 0.16
Nodes (7): NextQuarterTest, PickSnapshotTest, eps_trend 소급분은 수집 시점의 target을 달고 있어 과거 분기에 못 붙인다., 발표 뒤 갱신된 값을 섞으면 '그때의 기대'가 아니라 지금 기대가 된다., 발표 뒤 값은 '기대'가 아니라 결과를 반영한 값이다., 회계기간 식별자는 날짜 근사치 대신 저장된 절대 기간 키로 맞춘다., _snap()

### Community 132 - "FundamentalsRepository"
Cohesion: 0.08
Nodes (16): Filing, 공시가 존재한다는 사실. 우리가 그것을 어떻게 처리했는지는 여기 없다., FundamentalsRepository, Any, date, 발표 시점 이전 **마지막** 컨센서스. 최신 컨센서스를 쓰면 과거 서프라이즈가 매일 조금씩 달라진다. 그러면 "그때 놀라운 실적이었나"에…, 그날 발표 예정. 관측일마다 행이 쌓이므로 종목·기간별 **마지막 관측**만 남긴다., 관심종목의 발표 예정 스냅샷을 전부 읽는다(마지막 관측 선택은 reader가 한다). (+8 more)

### Community 133 - "filing_documents.py"
Cohesion: 0.12
Nodes (29): _archive_cik(), _available_daily_index_urls(), fetch_xbrl_document(), _filing_section(), filings_filed_since(), _filings_from_document(), _find_xbrl_document(), _get_bytes_optional() (+21 more)

### Community 134 - "Topic"
Cohesion: 0.21
Nodes (7): Topic, _notice(), PublishEngineTest, datetime, 알림 발행 엔진의 계약 — 같은 알림은 몇 번을 불러도 사람에게 한 번 닿는다. 원장은 SQL 함수와 같은 규칙을 따르는…, 원장 도입 전에 옛 경로가 보낸 상태를 전환 다음 날 다시 알리지 않는다., _render()

### Community 135 - "build_features.py"
Cohesion: 0.05
Nodes (29): main(), date, start부터 every_days 간격의 평일 판단 시각. 주말에 걸리면 직전 금요일로 당긴다., replay_dates(), build_features(), default_workers(), main(), _parse_args() (+21 more)

### Community 136 - "calendar.py"
Cohesion: 0.10
Nodes (24): bar_available_at(), completed_bar_cutoff(), market_today(), overlap_window(), date, datetime, 미국 시장의 시간 규칙. ## 왜 platform이 아니라 여기인가 "장이 언제 끝나는가"는 시장 도메인 지식이다.…, 시장이 보는 오늘 날짜. UTC 자정 근처에서 한국 시각과 뉴욕 날짜가 하루 어긋나므로, 날짜가 필요한 자리에서는 반드시 이것을 쓴다. (+16 more)

### Community 137 - "FilingRef"
Cohesion: 0.11
Nodes (8): FilingRef, 원천 수집기가 넘기는 SEC 공시 참조. ``Filing``은 v1 저장 계약이고, 이 타입은 아직 원문을 읽기 전의 최소 식별자다. 둘을…, BackfillScopeTest, _CompanyRepository, _CompanySource, date, 기업 전체 재무 백필이 쓰는 companyfacts 원천의 최소 대역., FilingXbrlFallbackTest

### Community 138 - "fit_baseline"
Cohesion: 0.06
Nodes (33): BaselineEvaluation, _dataset_hash(), _evaluate(), fit_baseline(), _LightGBMModel, ModelArtifact, _NaiveModel, _period() (+25 more)

### Community 139 - "fsds.py"
Cohesion: 0.13
Nodes (30): BulkFrames, discover_batches(), ensure_data(), _ensure_segment_data(), _expected_quarters(), iter_batches(), load_batch(), _missing_quarters() (+22 more)

### Community 140 - "extract_summary_financials"
Cohesion: 0.15
Nodes (17): extract_summary_financials(), _label_at(), _labels_in_row(), normalize_table(), _normalized_label(), parse_amount(), Any, SEC HTML 표를 병합 셀·표시 단위까지 반영해 읽는 경량 파서. (+9 more)

### Community 141 - "emergency.py"
Cohesion: 0.11
Nodes (25): main(), 투자 하네스 비상 긴급 정지(Emergency Stop) 및 재활성화(Re-arm) CLI 도구. 사용 예시: # 1. 상태 및 Durable…, _safe_print(), check_runtime_status(), emergency_stop(), get_lockdown_path(), is_execution_locked_down(), _is_process_alive() (+17 more)

### Community 142 - "earnings_report/embeds.py"
Cohesion: 0.11
Nodes (26): _axis_embed(), build_segments(), _f(), _footnote(), _join(), _lines(), _period_text(), _profit_field() (+18 more)

### Community 143 - "strategies.py"
Cohesion: 0.11
Nodes (35): _adm(), _complete_tail(), compute_all(), compute_one(), cum_ret(), defensive(), _dmsr(), _gem() (+27 more)

### Community 145 - "DossierBuilder"
Cohesion: 0.10
Nodes (21): DossierBuilder, bundle 하나와 선택적 밸류에이션 관측값으로 서류철을 만든다., _format_number(), Any, 서류철을 LLM 프롬프트용 Markdown으로 줄인다. 원본 서류철은 그대로 보존하고, 여기서만 분량 예산을 적용한다. 예산을 넘으면 잘라내되…, 구조화 호출용. 본문과 근거 ID를 분리해 모델이 인용을 지어내지 못하게 한다., 근거 ID를 함께 적은 사람이 읽을 수 있는 서류철을 만든다., _render_mapping() (+13 more)

### Community 146 - "_wf"
Cohesion: 0.13
Nodes (14): EvaluateTest, 일일 점검 요약 — 무엇을 문제로 셀지가 이 카드의 전부다., 합이 총수와 맞아야 카드가 무엇을 안 보고 있는지 드러난다., 링크가 없으면 원인을 보려고 GitHub에서 그 실행을 손으로 찾아야 한다., 타임아웃은 conclusion이 cancelled로 찍힌다 — 이걸 놓쳐서 알림이 안 갔었다. 실패와 색은 나누되(원인도 대응도 다르다)…, 인프라가 끊은 것과 코드가 깨진 것을 같은 줄에 두면 매일 훑고 넘기게 된다., 아침에 깨졌다가 고쳐 다시 돌린 것을 지금도 깨진 것과 같이 읽으면 안 된다., 마지막 실행이 실패로 끝난 것은 계속 빨강이어야 한다. (+6 more)

### Community 148 - "earnings/metrics.py"
Cohesion: 0.23
Nodes (15): _yoy(), as_float(), _cash(), derive(), _eps_diluted(), _fcf(), _margin(), _net_debt() (+7 more)

### Community 149 - "ControlCenter"
Cohesion: 0.10
Nodes (13): range, control_command(), ControlCenter, dashboard_command(), dashboard_url(), Any, Path, 실행 중인 로컬 Streamlit만 찾아 URL을 반환한다. (+5 more)

### Community 150 - "collection.py"
Cohesion: 0.10
Nodes (28): _missing_sec_get_json(), Any, SEC·S&P500·Toss 수집 흐름을 조율한다., 수집 게이트를 현재 멤버 집합에 맞춘다. 고친 종목 수를 돌려준다., 현재 S&P 집합을 비교하고 실제 변경 또는 월간 감사 때만 저장한다. `is_tracked`는 범용 gate이므로, 과거 멤버 전체를…, SEC 거래소 master와 시세 기준 ETF를 동기화하고 새 CIK의 entity 이름만 seed한다. ETF는 매번 함께 넘긴다. 빠지면…, CIK별 SEC submissions metadata를 증분 보강한다., reconcile_membership() (+20 more)

### Community 151 - "main"
Cohesion: 0.06
Nodes (57): crons_for(), _emit(), main(), Path, 워크플로 파일의 schedule cron 목록(주석 처리된 줄은 제외)., workflow_run으로 이 워크플로를 깨우는 상류 워크플로 이름들., 카드 본문에 이모지가 들어가는데 Windows 콘솔 기본 코드페이지(cp949)로는 인코딩이 터진다 — 미리보기가 개발자 기계에서 죽으면…, _uncommented() (+49 more)

### Community 152 - "test_watchlist_db.py"
Cohesion: 0.13
Nodes (9): ActiveMembersTest, AddRemoveMemberTest, _entity(), watchlists/db.py의 공개 함수가 injectable Database로도 같은 값을 주는지 굳힌다. 관심은 발행사(CIK) 단위로…, 보유는 종목 단위로 오지만 관심 기업은 하나여야 한다., 해제 이력조차 없는 회사까지 내면 전 종목이 목록에 들어온다., 관심 갱신이 SEC metadata 수집 결과를 덮어쓰면 회사 이름이 사라진다., _security() (+1 more)

### Community 153 - "SelectOnlyGateway"
Cohesion: 0.23
Nodes (9): DashboardDataError, _membership_chunks(), RuntimeError, 읽기 결과의 구조가 계약과 다를 때 사용하는 안전한 오류., 허용된 PostgREST SELECT 연산만 조합하는 좁은 게이트웨이. v1 관심 기업은 공개 읽기 전용인…, SELECT와 허용된 필터·정렬·범위만 사용해 행을 읽는다., allowlist에 있는 읽기 전용 SQL 함수의 결과 행만 읽는다. 비공개 스키마(`alerts`)의 사실에 닿는 유일한 경로다. 이름과…, `in` 목록을 URL 한도 안에 들어가는 조각들의 조합으로 나눈다. 조각 크기는 platform이 정한 것 하나를 쓴다 — 여기서 따로… (+1 more)

### Community 154 - "_snap"
Cohesion: 0.13
Nodes (8): CardTest, ConfidenceTest, CustomWindowTest, PriorFilingTest, 발표 예정 카드의 주 선택·불확실성 표기 회귀 테스트., 대시보드가 쓰는 임의 구간 조회가 Discord 주간 규칙을 바꾸지 않아야 한다., _snap(), WeekWindowTest

### Community 155 - "test_revisions.py"
Cohesion: 0.12
Nodes (18): latest_known_at(), date, datetime, `as_of` 시점에 알고 있던 것 중 가장 최근에 유효해진 값., 그 시점에 보이던 **시계열 전체**. 기간마다 그때의 최신 버전을 고른다. 기간별로 따로 고르는 것이 핵심이다. 시계열 하나를 통째로 최신…, `as_of` 시점에 이 값을 알 수 있었는가. **두 경계를 모두 넘어야 한다.** 유효해졌더라도 우리가 아직 손에 넣지 못했으면 쓸 수…, series_as_of(), KnownAtTest (+10 more)

### Community 156 - "Config"
Cohesion: 0.05
Nodes (48): Config, 이 실행이 쓰는 설정. 값은 프로세스 환경에서 온다., 필요한 값을 지금 확인한다. 없으면 **이름만** 말하고 멈춘다., 켜짐/꺼짐 값. 모르는 값은 **꺼진 것으로 읽는다**(fail-closed). 안전 플래그가 오타 하나로 켜지면 안 된다. 그래서 참으로…, build_directory(), guild_directory(), GuildChannel, GuildDirectory (+40 more)

### Community 157 - "main"
Cohesion: 0.13
Nodes (22): bot_user_id(), fetch_channels(), fetch_guild(), fetch_roles(), 길드의 모든 역할. @everyone은 ID가 길드 ID와 같다., 다른 봇 토큰의 사용자 ID를 그 토큰으로 묻는다. 카드 봇에게 역할을 붙이려면 그 봇의 사용자 ID가 필요하다. 관리형 역할에서 역추적할…, 길드 메타(이름·features). 포럼을 만들 수 있는지는 features의 COMMUNITY가 정한다., main() (+14 more)

### Community 158 - "strategies/etl.py"
Cohesion: 0.14
Nodes (18): _compute_available_for_backfill(), main(), _parse_yyyymm(), DataFrame, date, 전체 과정을 순서대로 실행하는 '시작 파일'(진입점). 사용법: python -m…, 과거 시점에 실제 데이터가 준비된 전략만 계산한다. 월간 운영 실행은 계속 6개 전략 완결성을 강제한다. 반면 과거 백필에서는 아직 상장되지…, 지정한 달부터 이번 달 직전까지, 매달의 결과를 다시 계산해 저장한다(이미 보낸 것으로 표시). (+10 more)

### Community 159 - "_run"
Cohesion: 0.11
Nodes (15): AccountingTest, ChainTest, CountersTest, EmbedTest, 체인 감시·연속 일수·심각도 색 — 전부 '조용히 틀리는' 자리다., 원장이 Supabase에 있으므로 GitHub runner도 로컬과 같은 대기 수를 읽는다., 카운터 하나가 실패했다고 점검이 사라지면 점검이 없는 것보다 나쁘다., cron이 없는 워크플로는 상류 성공 말고는 '돌았어야 함'을 알 길이 없다. (+7 more)

### Community 160 - "_modules"
Cohesion: 0.08
Nodes (23): DashboardReportingBoundaryTest, DataBoundaryTest, _imported_names(), LayerDirectionTest, LiveFlagTest, _modules(), PackageImportTest, PlatformBoundaryTest (+15 more)

### Community 161 - "PolicyAndModelRepositoryTest"
Cohesion: 0.06
Nodes (10): DecisionTest, PolicyAndModelRepositoryTest, 부분 성공을 성공으로 승격하지 않고, 거절이 주문으로 새지 않는다., System 논지는 판단 시점으로 유효를 가른다. 24시간 신호 만료가 지난 논지도 창 안이면 읽는다., 판단하지 않음'도 판단이다. 근거가 없으면 나중에 되짚을 수 없다., 거절인데 비중이 남아 있으면 그것을 주문으로 읽는 길이 열린다., 둘 다 있으면 나중에 읽는 사람이 어느 쪽을 믿을지 모른다., completed로 적으면 빠진 종목이 '신호 없음'으로 보인다. (+2 more)

### Community 162 - "supabase/segment_metrics.py"
Cohesion: 0.06
Nodes (40): _compact_row(), compact_rows(), _company_metrics_for(), _dedupe(), delete_stale_metrics_for_accessions(), existing_accessions(), fetch_metric_years(), filing_accessions() (+32 more)

### Community 163 - "normalize.py"
Cohesion: 0.19
Nodes (18): calculate_family(), calculate_measure(), finite(), _lag_period(), MeasureValidationError, _percentage_change(), _previous_observation(), Any (+10 more)

### Community 164 - "deflated_sharpe.py"
Cohesion: 0.21
Nodes (9): DeflatedSharpeRatio, DeflatedSharpeResult, _norm_cdf(), _norm_ppf(), Marcos Lopez de Prado 교수의 Deflated Sharpe Ratio (DSR) 과적합 검정 엔진. 다중 가설…, Deflated Sharpe Ratio 검정 결과., 수익률 시계열과 시도 횟수를 바탕으로 DSR 확률을 계산한다., DeflatedSharpeTests (+1 more)

### Community 165 - "main"
Cohesion: 0.13
Nodes (20): _ensure_community(), main(), Any, 포럼을 만들기 전에 길드가 Community인지 확인하고, 아니면 바꾼다., 카테고리와 채널을 매니페스트 선언 순서대로 다시 세운다. 이미 있던 채널은 자기 자리에 있지 않다 — 새로 만든 것만 position을…, _reorder(), Path, values의 키를 갱신하고, 없으면 끝에 덧붙인다. 바뀐 키 이름 목록을 돌려준다. (+12 more)

### Community 166 - "ExecutionSafetyError"
Cohesion: 0.02
Nodes (104): build_approval_card(), button_components(), Any, 토스 비실행 주문표를 Discord 건별 승인 카드로 바꾼다., 자유문장 대신 서명된 승인/거절 버튼 두 개만 만든다., Discord message create API에 바로 전달할 안전한 payload를 만든다., _ticket_lines(), DiscordApprovalClient (+96 more)

### Community 167 - "MarketRepository"
Cohesion: 0.07
Nodes (57): _backfill_prices(), 계획을 한 번 고정한 뒤 받아 archive → 기업행위 병합 → 가격 저장 순으로 반영한다., main(), merge_corporate_actions(), 분리 저장한 배당·분할 이벤트를 가격 행에 읽기 전용으로 결합한다., 가격 행의 grain을 바꾸지 않고 같은 거래일의 이벤트만 붙인다., actions_for_securities(), bars_for_securities() (+49 more)

### Community 168 - "market/test_persistence.py"
Cohesion: 0.12
Nodes (8): LatestPriceDateTest, _price(), PricesSinceTest, PriceWriteTest, persistence.py의 조회 함수가 MarketRepository로 위임한 뒤에도 같은 값을 주는지 굳힌다. 리팩터 전 특성화 테스트., 증분 비교는 수집 계획의 security_id로 한다. ticker로 되돌리면 개명 뒤 비교가 어긋난다., 저장 직전에 ticker로 신원을 다시 풀지 않는다., UniverseMissingPricesTest

### Community 169 - "app_pages/macro.py"
Cohesion: 0.08
Nodes (50): _allocation_text(), _close_prices(), _econ_table(), _expected_value(), _market_snapshot(), _market_value(), _mode_text(), _page_link() (+42 more)

### Community 170 - "MacroRepository"
Cohesion: 0.06
Nodes (24): Observation, 관측 한 버전. 같은 `(series_id, ref_period)`에 여러 개가 있을 수 있다., MacroRepository, Any, date, datetime, 코드 catalog의 measure를 물리 series_key로 변환해 적재한다., 수집 설정은 코드 catalog가 소유한다. DB는 display metadata만 보관한다. (+16 more)

### Community 171 - "render_dsr_gauge"
Cohesion: 0.18
Nodes (8): Figure, _load_real_active_policy(), Any, 실제 강화학습 승격 정책 메타데이터 로드 (없으면 None)., DSR 과적합 검정 반원형 게이지 차트 생성., render_dsr_gauge(), MlRlLabDashboardTests, ml_rl_lab 대시보드 페이지 단위 테스트.

### Community 172 - "ensure_aware"
Cohesion: 0.06
Nodes (37): SeriesValidator, SourceFetcher, Any, date, datetime, v1 macro 원천 결과를 revision-safe observation 원장에 적재한다., source별 결과를 독립 수집해 원천 수집 시각으로만 버전을 남긴다., refresh_macro() (+29 more)

### Community 173 - "validated_weights"
Cohesion: 0.18
Nodes (7): Any, 비중을 검증하고 현금을 포함한 정렬 사본을 돌려준다. **현금을 포함한 합이 1이어야 한다.** 이것이 이 함수의 핵심이다 — 없으면 "10%…, validated_weights(), 10%만 적힌 의도가 통과하면 나머지 90%를 아무도 말하지 않은 채 계획이 결정한다., 0으로 바꾸면 데이터 오류가 매도 주문이 된다., float(True)는 1.0이라 플래그가 100% 비중이 된다., WeightContractTest

### Community 174 - "f"
Cohesion: 0.09
Nodes (34): f(), financial_versions 한 행에서 값을 읽는 순수 함수. DB에 접근하지 않으므로 조회 경계(reporting)와 카드 계산…, 숫자로 바꿀 수 없으면 None. Decimal·문자열·None이 섞여 들어온다., _as_date(), build(), _next_fiscal_period(), pick_next_quarter(), pick_price_target() (+26 more)

### Community 175 - "ContextBuilder"
Cohesion: 0.12
Nodes (7): ContextBuilder, feature 적재: 종목과 무관한 조회는 한 번만, 계산은 쌓이는 대로 저장한다., SharedContextTest, ContextPointInTimeTest, historical replay에서 point-in-time 이력이 없는 데이터를 차단한다., 1/2 제출 공시를 1/2 저녁(1/3 00:00 UTC)에 이미 안 것으로 만들지 않는다., _Repository

### Community 176 - "_run"
Cohesion: 0.06
Nodes (29): _check(), evaluate(), date, 적재 결과의 불변조건을 점검해 조용히 썩는 실패를 드러낸다. 순수 판정만 여기 둔다. 조회는 repository가 하고, 이 함수는 숫자를…, 조회한 데이터 사실을 판정한다. 운영 오류는 DB에 기록하지 않는다., 조회 결과를 점검 항목 목록으로 바꾼다., verify_integrity(), BalanceIdentityBaseline (+21 more)

### Community 177 - "test_workflow_wiring.py"
Cohesion: 0.16
Nodes (17): _declared_flags(), _direct_module_imports(), EntryPointOptionTest, _imported_names(), _invocations(), _module_path(), AST, 워크플로 배선 회귀 테스트 — 어긋나도 조용히 실패하는 것들만 지킨다. 여기 걸린 규칙은 전부 "틀려도 CI가 초록이고, 알림만 안 온다"… (+9 more)

### Community 178 - "_Repository"
Cohesion: 0.15
Nodes (8): BuildTrainingSamplesTest, _features(), datetime, 과거 편출 종목 BBB를 조회 범위에서 빼면 학습 표본이 조용히 사라진다., +0.1% 판단은 비용 후 손실이다. 그 개수가 보고돼야 한다., 최소 수수료가 있으면 비율이 주문 금액에 따라 달라져 계산할 수 없다., 적재 첫 며칠은 horizon이 안 지나 label이 0건이다. 여기서 실패시키면 5거래일 내내 job이 실패로 뜨고, 그 사이 정상 적재된…, _Repository

### Community 179 - "MeasureCalculationTest"
Cohesion: 0.08
Nodes (6): MeasureCalculationTest, 30-family ECON schedule/measure source contract의 오프라인 회귀 테스트., The 2026-08-29 CCSA print was published on 2026-09-10, not 2026-09-03., ReferencePeriodTest, ScheduleTimezoneTest, SeedContractTest

### Community 180 - "RawPosition"
Cohesion: 0.18
Nodes (12): PositionKey, SEC Information Table 원본 행의 분석·감사 필수 필드., RawPosition, _aggregate(), compare(), errored(), KeyMismatch, 운영 파서와 edgartools shadow 파서의 13F 결과를 대조한다. 순수 비교 로직이라 외부 의존성이 없다. 입력은 양쪽 파서가 만든… (+4 more)

### Community 181 - "lifecycle.py"
Cohesion: 0.23
Nodes (10): AutonomyCriteria, AutonomyEvidence, LifecycleDecision, LifecyclePromotionGate, LifecycleStage, Enum, str, BACKTEST→SHADOW→PAPER→LIVE_MANUAL→LIVE_AUTONOMOUS 운영 승격 경계. (+2 more)

### Community 182 - "install_investment_harness.py"
Cohesion: 0.16
Nodes (14): main(), _plans(), 로컬 운영 하네스의 OS 서비스 등록 계획을 만들고 선택적으로 적용한다., _require_apply_environment(), _absolute(), apply_install_plan(), macos_launchd_plan(), Any (+6 more)

### Community 183 - "create_execution_intent.py"
Cohesion: 0.14
Nodes (13): ExecutionRepository, create_execution_intent(), main(), datetime, 승격된 full portfolio RiskDecision을 paper/live intent로 발행한다., 승격·snapshot을 재검증해 저장한 intent의 안정적 ID를 직접 반환한다., 부분 분석이나 실제 계좌 기준이 없는 목표 비중을 주문으로 승격하지 않는다., validate_paper_scope() (+5 more)

### Community 184 - "_intent"
Cohesion: 0.18
Nodes (6): ExecutabilityTest, _intent(), 실행 의도가 받아들이는 모양. 여기서 막지 못한 것은 주문이 된다., 며칠 전 승인이 오늘 주문으로 나가면 안 된다., 부르는 쪽이 자기가 어느 경로인지 명시해야 한다., ShapeTest

### Community 185 - "layer.py"
Cohesion: 0.22
Nodes (19): _close_returns(), FeatureBundle, _fundamental(), _gurus(), _macro(), _momentum(), _number(), Any (+11 more)

### Community 186 - "us_market_today"
Cohesion: 0.11
Nodes (14): compact_price_rows(), date, Market history retention policy. Supabase에는 연속된 일봉만 남기고, 전체 Yahoo 일봉은 Parquet…, Supabase 보관 범위 안의 연속 일봉만 남긴다., _years_ago(), completed_us_daily_bar_cutoff(), day_window(), date (+6 more)

### Community 187 - "TossTokenManagerTest"
Cohesion: 0.14
Nodes (6): FakeResponse, 토스 OAuth 공용 token manager의 동시성·보안 경계를 검증한다., 모듈 이동이 worker 간 OAuth cache 공유 경로를 바꾸면 안 된다., token_response(), TossSharedClientIntegrationTest, TossTokenManagerTest

### Community 188 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 189 - "What You Must Do When Invoked"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 190 - "decision/alpha.py"
Cohesion: 0.06
Nodes (36): build_alpha_policy_read_model(), build_optimizer_policy_read_model(), build_risk_policy_read_model(), Any, 투자 정책을 화면용 bounded read model로 투영한다., 현재 ALPHA 기대초과수익 정책을 변경 없이 직렬화한다., 현재 optimizer 기본 정책을 변경 없이 직렬화한다., 현재 portfolio risk 기본 한도를 변경 없이 직렬화한다. (+28 more)

### Community 191 - "_canonical_filing_focus"
Cohesion: 0.17
Nodes (9): _canonical_filing_focus(), _quarter_from_annual_distance(), 인접 10-K 기간말과의 거리로 10-Q의 분기 번호를 복원한다., SEC unit의 오염된 ``fy``/``fp`` 대신 filing 기간으로 회계키를 만든다. CompanyFacts는 일부 등록인에서 과거…, 같은 CIK 안의 새 회계력이 대체하는 이전 accession을 반환한다., superseded_filing_accessions(), CanonicalFilingFocusTest, _filing() (+1 more)

### Community 192 - "TossAuthError"
Cohesion: 0.13
Nodes (14): Any, Path, RuntimeError, 운영 점검용 캐시 경로. 파일 내용은 외부로 노출하지 않는다., 유효한 공용 token을 반환하고 없을 때만 잠금 안에서 발급한다., 401을 낸 token이 여전히 최신일 때만 잠금 안에서 한 번 갱신한다., 인증 요청을 보내고 401이면 공용 갱신 후 정확히 한 번만 다시 보낸다., 비밀값을 로그에 넣지 않고 network·429·5xx만 제한적으로 재시도한다. (+6 more)

### Community 193 - "Path"
Cohesion: 0.31
Nodes (6): DashboardLauncherPreflightTest, Path, `.venv`에 의존성만 있고 이 저장소가 안 깔린 상태가 실제로 있었다. 서드파티만 세면 사전 점검이 "이상 없음"이라 말한 뒤 앱이…, 모듈 이름만 알려주면 무엇을 실행해야 하는지 알 수 없다., _runtime(), _touch()

### Community 194 - "_Query"
Cohesion: 0.11
Nodes (5): _Client, GatewayInChunkTest, Any, _Query, 대시보드 게이트웨이도 `in` 목록의 URL 한도를 지킨다. PostgREST는 `in` 값을 URL에 그대로 싣는다. 행 상한과 **다른…

### Community 195 - "자주 발생하는 문제"
Cohesion: 0.12
Nodes (16): CVXPY 또는 NumPy 충돌, Discord 승인이 거절됨, DuckDB import 또는 cache 오류, Historical macro/fundamentals가 비어 있음, Live가 실행되지 않음, Optimizer가 infeasible, Reconciliation mismatch, RiskGate가 Shadow는 통과하고 Paper/Live는 거절 (+8 more)

### Community 196 - "_row"
Cohesion: 0.09
Nodes (15): JudgeTest, ManifestDriftTest, 채널 도착 확인 — '워크플로 초록인데 카드 없음'을 잡는 유일한 장치다. 여기가 틀리면 조용히 틀린다: 거짓 경보를 내면 며칠 만에 아무도…, 포럼의 글은 메시지가 아니라 스레드라 셀 수 없다 — 없는 수를 지어내지 않는다., 워크플로가 전부 초록이어도 채널이 비었으면 '이상 없음'이라고 하면 안 된다., `env`(시크릿) 아니면 `name`(봇이 길드에서 찾음) 중 하나는 있어야 한다., 여기만 따로 두면 채널을 옮길 때 한쪽만 고치게 된다., 감시 목록에서 빠진 채널은 죽어도 아무도 모른다. 랩은 제외한다. (+7 more)

### Community 197 - "inputs.py"
Cohesion: 0.17
Nodes (23): build_valuation_inputs(), _decimal(), _evidence_id(), filing_available_at(), _missing(), price_scalar(), Any, date (+15 more)

### Community 198 - "event_reanalysis.py"
Cohesion: 0.08
Nodes (29): main(), Any, datetime, 새 공시·고영향 사건·검증된 글로벌 사건이 생긴 보유 종목을 정기 주기를 기다리지 않고 다시 분석한다. python -m…, 로컬 뉴스·소셜 원문을 사건으로 다시 압축한다. 실패해도 공시 기반 재분석은 계속한다., _refresh_events(), run_event_reanalysis(), merge_priority_lane() (+21 more)

### Community 199 - "decision/analysis.py"
Cohesion: 0.05
Nodes (37): analysis_limit(), _case_key(), main(), _model_pool_ledger_path(), _parse_args(), datetime, Namespace, Path (+29 more)

### Community 200 - "Third-party data notice — `gaap_mappings.json`"
Cohesion: 0.25
Nodes (7): 5.36.0 -> 5.53.0에서 바뀐 것, MIT License, Third-party data notice — `gaap_mappings.json`, 무결성 확인, 업데이트와 검증 절차, 출처와 현재 스냅샷, 프로젝트에서 사용하는 방식

### Community 201 - "alfred.py"
Cohesion: 0.15
Nodes (26): AlfredDataError, _failure_reason(), fetch_batch(), fetch_first_prints(), fetch_revisions(), _http_error_message(), _is_empty_vintage_window(), _observations() (+18 more)

### Community 202 - "OpenAICompatibleClient"
Cohesion: 0.06
Nodes (25): _attempt_case(), `apply_candidate`가 이미 활성화된 상태에서 실제 TradingAgents 호출 한 건을 한다., AgentEngineResult, DecisionEngine, Any, Protocol, AI Investor 판단 엔진 인터페이스 및 공통 경계., TradingAgentsDecisionEngine (+17 more)

### Community 203 - "test_page_wiring.py"
Cohesion: 0.10
Nodes (14): CalendarAssetTest, EconSeriesScopeTest, HomeMarketWiringTest, _page_files(), PageRenderTest, Path, 화면이 실제로 그려지는지, 그리고 화면이 요구하는 것을 reader가 받아 주는지. 2,500개 테스트 중 **화면을 한 번도 렌더하지…, macro.series에는 시장 관측 지표가 함께 산다. 걸러지지 않은 채 발표 카탈로그로 넘어가면 domain이 `unknown ECON… (+6 more)

### Community 204 - "valuation_history.py"
Cohesion: 0.15
Nodes (19): _asof(), compute(), daily_series(), downsample_weekly(), _f(), _positive_den_ratio(), Any, date (+11 more)

### Community 205 - "test_inputs.py"
Cohesion: 0.19
Nodes (7): FilingAvailabilityTest, _four_quarters(), _quarter(), PIT 밸류에이션 입력 조립과 적재 진입점의 시점 계약을 고정한다., 일자만 아는 공시를 그날 0시로 잡으면 실제보다 이르게 안다고 주장하게 된다., 나중 정정본을 쓰면 그 시점에 알 수 없던 값이 섞인다., TTMReconstructionTest

### Community 206 - "domain/analysis.py"
Cohesion: 0.12
Nodes (23): _authoritative_filings(), build_snapshot(), _change_rows(), _combined_positions(), _consensus_rows(), _coverage_status(), _filing_order(), _instrument() (+15 more)

### Community 207 - "application/etl.py"
Cohesion: 0.05
Nodes (60): AllGuruManagersFailedError, GuruConfigurationError, GuruEtlError, GuruProviderError, _make_filing_error_sink(), _make_shadow_sink(), Any, Exception (+52 more)

### Community 208 - "PolicyConceptChoice"
Cohesion: 0.06
Nodes (12): CashFlowConceptChoice, ConflictRejection, PolicyConceptChoice, PolicyUnitGate, 컬럼 매핑 정책 — 단위 게이트와 동률 처리. 적재 결과 실측에서, 정책이 없는 컬럼은 동률일 때 태그 이름의 알파벳 순으로 값을 골랐고 그…, 정책이 없는 wide 컬럼도 기대 단위가 아니면 받지 않는다., 정책이 없어도 동률이면 임의로 고르지 않고 비워둔다., 현금흐름표 계열 — 총계 자리에 라인아이템이 들어오지 않는지. (+4 more)

### Community 209 - "Trading — 근거에서 포트폴리오까지의 판단 계층"
Cohesion: 0.11
Nodes (18): 1. Universe와 후보 선정, 2. Context와 PIT 경계, 3. Feature layer, 4. TradingAgents, 5. System Portfolio와 My Portfolio, 6. Optimizer와 RiskGate, 7. Backtest, ML, RL, Qlib, 8. 평가와 승격 (+10 more)

### Community 210 - "test_schema_alignment.py"
Cohesion: 0.06
Nodes (29): v1 알림 전달 계층의 최상위 패키지., _Database, declared_columns(), declared_functions(), LedgerAdapterContractTest, Any, _Query, Supabase 원장 어댑터가 선언 SQL과 같은 이름을 부르는지 본다. RPC 인자 이름이 하나라도 어긋나면 PostgREST는 "함수를… (+21 more)

### Community 211 - "test_provider_fail_closed.py"
Cohesion: 0.07
Nodes (12): Any, v1 시장 거시지표의 선언형 원천 카탈로그. 카탈로그는 DB seed와 같은 계약을 코드에서 재현한다. 수집 시에는 DB에 실제로 seed된…, _row(), 원시 매크로 관측치에 붙일 표시 메타데이터 읽기 계약., ActiveSeedContractTest, ActualsFailClosedTest, MarketBreadthFailClosedTest, 활성 provider의 오프라인 fail-closed 계약 테스트. (+4 more)

### Community 212 - "Event"
Cohesion: 0.09
Nodes (19): Popen, CommandExecutionError, CommandResult, ModuleCommandRunner, Path, Protocol, RuntimeError, shell 없이 고정된 Python entry만 실행하는 하네스 command 경계. (+11 more)

### Community 213 - "test_strategy_guardrails.py"
Cohesion: 0.11
Nodes (9): DatetimeIndex, _complete_prices(), _monthly_index(), MonthlyEntrypointGuardrailTest, DataFrame, 월간 전략이 stale/부분 데이터를 정상 신호로 저장하지 않는지 검증한다., StrategyCalculationGuardrailTest, StrategyRetentionTest (+1 more)

### Community 214 - "_row"
Cohesion: 0.21
Nodes (5): FailOpenTest, fast path 시즌 게이트 — 특히 fail-open 규칙 회귀 테스트. 이 게이트가 잘못 "시즌 아님"을 내면 관심종목 공시 알림이…, 근거가 없으면 언제나 수집을 돌린다 — 놓치는 쪽이 훨씬 비싸다., _row(), SeasonWindowTest

### Community 215 - "secret_scope.py"
Cohesion: 0.12
Nodes (12): current_scope(), environ_for_scope(), is_analysis_scope(), RuntimeError, 프로세스별 비밀값 범위. 판단·학습 프로세스는 broker·승인 비밀을 갖지 않는다. 하네스가 자식 프로세스를 띄울 때 범위를 정하고, 자식은…, 판단 범위 프로세스가 실행 전용 자원에 닿으려 했다., 자식 프로세스에 넘길 환경. 판단 범위면 실행 비밀을 뺀다., broker 인증처럼 실행 범위에서만 열려야 하는 자원의 입구에서 부른다. (+4 more)

### Community 216 - "openfigi.py"
Cohesion: 0.21
Nodes (17): _api_key(), _batch_size(), _map_batch(), map_identifiers(), MappingResult, _normalize_identifier(), _normalize_ticker(), OpenFIGI의 CUSIP/CINS 식별자 매핑 어댑터. (+9 more)

### Community 217 - "approval/ledger.py"
Cohesion: 0.09
Nodes (26): ApprovalInteraction, create_approval_id(), issue_live_execution_permit(), LiveExecutionPermit, parse_button_interaction(), Any, datetime, timedelta (+18 more)

### Community 218 - "IntelligenceRepository"
Cohesion: 0.15
Nodes (12): 저장 시도의 결과. 중복은 실패가 아니라 정상이다., StoreResult, IntelligenceRepository, Any, date, datetime, Path, 이전 v1 DuckDB 본문 table을 한 번만 Parquet로 옮긴다. (+4 more)

### Community 219 - "to_wide_tables"
Cohesion: 0.26
Nodes (5): core wide 행과 매핑 이상 행을 반환한다. FY는 저장하지 않는다. `periodize`가 이미 FY에서 Q4 단독값을 복원했으므로…, to_wide_tables(), ConsolidatedEquityScope, _fact(), 연결 자본 범위와 비지배지분 파생 규칙의 회귀 테스트.

### Community 220 - "DiscordTest"
Cohesion: 0.15
Nodes (8): 이 어댑터의 text/embed 계약과 Discord 길이 한도를 전송 전에 검사한다., validate_message(), DiscordTest, Discord 계약과 renderer를 가짜 HTTP로 검증한다. 실제 메시지는 보내지 않는다., 거장 카드는 제목을 SEC 원문으로 잇는다. `url`이 허용 목록에 없던 동안 그 카드 6장이 매번 거절됐고, 실패는…, 전략 카드 2종(dmsr·gtaa5)이 QuickChart를 thumbnail로 건다. 허용 목록에 없던 동안 그 두 장은 매번 거절됐고,…, producer가 넣은 문자열이 그대로 링크가 되는 자리다., response()

### Community 221 - "managers.py"
Cohesion: 0.21
Nodes (11): all_managers(), guru_display_name(), guru_tags(), guru_thread_topic(), presentation_for(), institutional 7인 레이더의 코드 상수. 추적 대상 manager(cik/name/fund_name/is_active)의 런타임…, 활성 여부와 무관한 전체 manager 사실 + 화면 해석. cik 오름차순., 관리자 사실에 붙일 화면용 해석. 미등록 manager도 수집은 가능하다. (+3 more)

### Community 222 - "투자 시스템 — System Portfolio와 My Portfolio"
Cohesion: 0.05
Nodes (37): Ablation — 모듈이 실제로 성과를 개선하는가, ALPHA — 기대초과수익과 논지, Dataset split과 재현성, DeterministicRiskGate, EvidenceBundle 도메인 구성, factor IC 연구, factor 기반 후보 선정, Feature Layer (+29 more)

### Community 223 - "process_filing.py"
Cohesion: 0.12
Nodes (24): current_segment_facts(), derive_segment_rows(), process_segment_cik(), date, 공시 한 건의 기업 전체·세그먼트 결과를 처리한다., 세그먼트 공시 처리 상태를 저장소 행으로 만든다., CIK 한 건의 새 공시 문서를 파싱해 저장 전 결과를 만든다., 저장된 연도 지표와 이번 YTD 관측값으로 discrete 분기를 계산한다. (+16 more)

### Community 224 - "test_reporting_guards.py"
Cohesion: 0.18
Nodes (9): assert_boundary(), assert_contract(), HumanViewTest, 읽기 경계와 SQL 공개 계약. 각 가드에 위반을 하나씩 주입해 실패도 검증한다., reporting 전체가 읽기 전용인지 본다 — 한 파일만 빠져도 그 경로로 쓰기가 샌다., LOCAL_VIEWS는 실제 Postgres 뷰가 아니라 로컬 runtime.sqlite3 읽기라 90_reporting.sql에 선언되지…, 사람이 여는 뷰는 이름을 영문으로 두고 뜻을 한국어 COMMENT로 적는다., ReportingGuardsTest (+1 more)

### Community 225 - "RunContext"
Cohesion: 0.05
Nodes (33): content_hash(), Any, 내용 지문(sha256 hex). 근거 번들이 바뀌었는지 판정하는 유일한 기준., case_key(), context_hash(), is_reproducible(), Any, datetime (+25 more)

### Community 226 - "ManifestTest"
Cohesion: 0.06
Nodes (19): _existing(), ForumTagTest, ManifestTest, PlanTest, PositionTest, 매니페스트 ↔ 서버 대조 — 여기가 틀리면 채널이 중복 생성된다., 발송 코드가 아는 태그 이름과 서버에 만드는 태그가 어긋나면 태그 없이 나간다., 전략 태그 선언과 발송 routing 대응표가 일치해야 한다. (+11 more)

### Community 227 - "sources/toss_holdings.py"
Cohesion: 0.15
Nodes (22): access_token(), _authorized_headers(), fetch_accounts(), fetch_holdings(), _get_json(), Any, RuntimeError, 토스증권 Open API의 계좌·보유종목 조회 클라이언트. 관심종목 API는 아직 제공되지 않으므로 공식 ``accounts``와… (+14 more)

### Community 228 - "filing_xbrl.py"
Cohesion: 0.16
Nodes (22): normalize_form(), 수정 공시 표기를 원 공시 유형으로 정규화한다., is_excluded_tag(), policy_accepts(), 원시 us-gaap 태그에 대응하는 프로젝트 컬럼명을 반환한다., 투자 지표 의미가 불명확해 자동 적재하지 않을 SEC 태그인지 반환한다., 정책이 태그와 단위를 허용하는지 반환한다. 정책이 있는 컬럼은 화이트리스트 + 단위로 판정하고, 없는 wide 컬럼은 단위만 검사한다(금액…, to_column_key() (+14 more)

### Community 229 - "GuruRoutingTest"
Cohesion: 0.09
Nodes (14): BuildDirectoryTest, _config(), GuildDirectoryCacheTest, GuruRoutingTest, 채널을 이름으로 찾는 경로를 굳힌다. 거장 채널 ID를 시크릿으로 들고 있던 것을 봇 조회로 바꿨다. 그 조회가 틀리면 카드가 엉뚱한 채널로…, 이름이 없는 거장은 태그도 스레드 제목도 만들 수 없다., 태그 하나 때문에 그 분기 공시를 통째로 막지 않는다., 분기마다 새 스레드를 만들면 7명 × 4분기 = 연 28개가 되어 흐름이 끊긴다. (+6 more)

### Community 230 - "stress.py"
Cohesion: 0.14
Nodes (13): Any, 대표 ETF 충격을 보유 비중의 손실로 옮기는 결정론적 스트레스 시나리오. ## 왜 변동성·베타만으로는 부족한가 종목 여러 개를 나눠 담아도…, 시나리오 이름 → 종목 → 대표 ETF 민감도. 대표 ETF나 종목 이력이 없으면 `estimate_betas`가 실패한다., 시나리오별 포트폴리오 손실(양수 = 손실). 민감도가 없는 보유 종목이 있으면 실패한다., scenario_losses(), scenario_sensitivities(), StressScenario, GateStressLimitTest (+5 more)

### Community 233 - "ResearchStore"
Cohesion: 0.06
Nodes (34): load_prev_alloc(), load_recent_allocations(), Research 로컬 전략 결과를 알림용 모양으로 읽는 저장소 경계. 보낼지 말지는 알림 원장이 판단한다., 최근 적용월의 전략 배분을 오래된 순서로 읽는다., _store(), 저장 기술별 연결 경계. 각 파일이 하나의 DB만 안다. 이 패키지는 재수출하지 않는다. `platform.db`만 적으면 세 저장소 중…, _decode_allocation(), _decode_json() (+26 more)

### Community 234 - "expectations_exit_code"
Cohesion: 0.17
Nodes (8): expectations_exit_code(), 부분 성공은 성공, 붕괴한 실행만 실패로 돌린다. `failures`는 로그·판단 근거로만 받는다 — 게이트는 적재량이 정한다., ExpectationsExitCodeTest, 부분 성공을 실패로 올리면 알림이 매일 울리고 진짜 고장을 못 가린다. 실측 2026-09-04: Yahoo 레이트리밋으로 503종목 중…, 레이트리밋은 상시 조건이다 — 대부분 적재됐으면 성공이다., 행이 하나도 안 들어갔는데 성공이라고 하면 조용히 비어 간다., 행이 거의 안 들어갔으면 실패 수와 무관하게 붕괴한 실행이다., 실패는 (종목 × 단계) 단위라 종목 수와 단위가 다르다 — 게이트는 적재량이 정한다.

### Community 235 - "refresh_earnings_season.py"
Cohesion: 0.15
Nodes (20): _as_date(), _env_int(), evaluate_earnings_season(), github_output_lines(), lag_days(), lead_days(), date, 발표 예정일을 기준으로 관심종목 fast path 실행 여부를 판정한다. (+12 more)

### Community 236 - "build"
Cohesion: 0.13
Nodes (20): _beat_color(), _big(), build(), _expectation_view(), _inconsistent_7d(), _period_text(), 실적 PNG 카드 — 템플릿 컨텍스트(ctx)와 Discord 캡션 조립. candidates.load_pending() 항목 +…, 항목(+extras) → (템플릿 ctx, Discord 캡션). (+12 more)

### Community 237 - "retry.py"
Cohesion: 0.16
Nodes (18): _fred_slot(), fetch_batch(), fetch_release_dates(), date, FRED 발표 일정(release/dates) 어댑터. macro/clients/fred.py는 관측치(series/observations)를…, release_id 하나의 발표 예정일을 [start, end] 구간으로 잘라 반환한다.…, 릴리스 단위로 한 번씩만 호출한다. 지표 14종이 릴리스 9개를 공유하므로(CPI·Core CPI가 release 10 하나) 지표마다 부르면…, fetch_gdpnow() (+10 more)

### Community 238 - "promotion/gate.py"
Cohesion: 0.08
Nodes (21): _args(), main(), Namespace, aggregate_evaluations(), _covered_days(), EvaluationSummary, _incident_count(), ManualPromotionGate (+13 more)

### Community 239 - "test_read_path_performance.py"
Cohesion: 0.14
Nodes (7): _FakeMarketRepository, LatestFeaturesBatchTest, PriceWindowTest, date, 읽기 경로 최적화가 결과를 바꾸지 않는지: 가격 창 조회·종목 ID 기억·저장소 기억·기술지표 일괄·병렬 feature 적재., SecurityIdCacheTest, _weekday_bars()

### Community 240 - "FullPortfolioSchemaTest"
Cohesion: 0.23
Nodes (4): FullPortfolioSchemaTest, trading·execution 모두 Supabase가 아니라 실행 컴퓨터 로컬 runtime.sqlite3가 소유한다 — RLS로 지킬…, trading은 execution snapshot을 가리키되 FK로 계층 방향을 뒤집지 않는다., Postgres `approve_model_promotion` 함수의 FOR UPDATE 잠금을 대신해, 로컬 SQLite에서는…

### Community 241 - "row_event_key"
Cohesion: 0.21
Nodes (17): event_key(), Any, date, 경제발표의 자연키를 화면·알림·적재에서 동일하게 읽고 만든다., row_event_key(), build(), _escape(), _event_lines() (+9 more)

### Community 242 - "model_pool.py"
Cohesion: 0.07
Nodes (30): apply_candidate(), _azure(), _azure_daily_requests(), gemini_candidate(), groq_candidate(), _ledger_key(), ModelCandidate, datetime (+22 more)

### Community 243 - "earnings_report/quickchart.py"
Cohesion: 0.20
Nodes (14): axis_chart(), _blue(), _color(), composition_donut(), 세그먼트 embed에 붙일 QuickChart 이미지 URL을 조립한다. 여기서 그림을 그리지 않는다 — Chart.js 설정을 URL에 실어…, 매출 규모 가로 막대 — 비중을 낼 수 없는 축(partial)의 대체 그림. 합계를 모르니 '전체 중 얼마'는 말하지 않고 '서로 얼마나…, 축 하나의 그림 — 비중을 낼 수 있으면 도넛, 아니면 매출 막대., 매출 구성 도넛. 가운데가 비어 있어 집중도가 링 두께로 읽힌다. 비중을 낼 수 있는 행이 둘 미만이면 원 하나가 되어 정보가 없다 →… (+6 more)

### Community 244 - "IntelligenceRepositoryTest"
Cohesion: 0.14
Nodes (9): _article(), IntelligenceRepositoryTest, _post(), datetime, intelligence.duckdb 저장 경계의 계약., 다른 provider가 같은 기사를 줘도 한 행이어야 한다., 같은 배치 안에서 서로 충돌하는 경우 — 기존 행과의 충돌과 다른 경로다. `executemany`는 행 단위로 실행되므로 두 번째 레코드가…, 같은 배치 안에서 서로 충돌하는 경우 — 기존 행과의 충돌과 다른 경로다. `SocialPostRecord`는 `content_hash`가… (+1 more)

### Community 245 - "test_watchlist_toss.py"
Cohesion: 0.12
Nodes (6): 토스 보유종목 관심목록 동기화의 안전장치를 검증한다., 관심 원장을 따로 두면 "활성인가"의 정의가 두 곳에 생긴다., TossClientPayloadTest, TossHoldingsTransformTest, TossMacOnlyConfigurationTest, TossSyncWriteBoundaryTest

### Community 246 - "fundamentals_pending.py"
Cohesion: 0.08
Nodes (17): universe 관심종목 멤버십과 Toss 보유 출처 동기화., 이번 주 실적 발표 예정 카드. 발표 예정일 스냅샷을 읽어 관심종목의 다음 발표를 미리 알린다. 예정일은 자주 바뀌고 틀리기도 하므로 카드는…, _cutoff(), load_flash_candidates(), _lookback_days(), 8-K 실적 속보 알림 대상 후보 선정., 관심종목의 최근 8-K 실적 속보. 등록일 이전 공시는 뺀다 — 이미 보냈는지는 원장이 가른다., fundamentals: 관심종목 실적 공시(10-Q/10-K) 알림. 트리거: 펀더멘탈·세그먼트 ETL 이후 실행 — 관심종목의 미발송 신규… (+9 more)

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

### Community 251 - "json_value"
Cohesion: 0.16
Nodes (4): json_value(), JSON에 실을 수 있는 모양으로 바꾼다. 손실이 생기는 변환은 하지 않는다., Any, Any

### Community 252 - "_CountingRepository"
Cohesion: 0.18
Nodes (3): _CountingRepository, IncrementalSaveTest, ParallelFeatureBuildTest

### Community 253 - "ArtifactRef"
Cohesion: 0.11
Nodes (9): ArtifactRef, ArtifactStore, Protocol, DB에 적는 것 전부. 내용은 여기 없다., `trading.decision_evidence`가 받는 모양., 저장 백엔드. 지금은 로컬 파일뿐이지만, 나중에 객체 저장소로 바꿔도 DB에 적힌 URI는 그대로여야 한다., LocalArtifactStoreTest, canonical JSON으로 저장하지 않으면 같은 근거가 두 지문을 갖는다. (+1 more)

### Community 254 - "execution_view.py"
Cohesion: 0.39
Nodes (7): execution_summary(), Any, 실행 원장의 상태·체결 비용·정산 결과를 읽기 전용으로 요약한다., 운영 화면의 핵심 지표를 저장 사실만으로 계산한다., 한 execution intent에 연결된 승인·주문·체결 이벤트를 반환한다., _rows(), trace_for_intent()

### Community 255 - "Execution — 주문 lifecycle과 안전 경계"
Cohesion: 0.17
Nodes (12): Durable safety, Execution — 주문 lifecycle과 안전 경계, Live Manual 흐름, Reconciliation, Toss 단일 실행 경로, 분석·검증, 주문 결과가 불명확할 때, 주요 CLI (+4 more)

### Community 256 - "PriorityCandidateTest"
Cohesion: 0.32
Nodes (3): _event(), PriorityCandidateTest, datetime

### Community 257 - "universe/infrastructure/sources/__init__.py"
Cohesion: 0.14
Nodes (9): CompanyFactsKeyContractTest, _document(), 공용 SEC submissions 파서의 키 매핑 계약. `src/investment_agent/data/universe/sec.py`는…, fundamentals 일별 경로가 읽는 SEC 키 계약. `src/investment_agent/data/universe/sec.py`와…, Company Facts unit entry도 원본 이름 `form`을 쓴다., SEC submissions 응답의 모양(키 이름이 계약의 전부다)., 두 날짜가 뒤바뀌면 조회 창이 빗나가고 보존 삭제가 엉뚱한 행을 지운다., 13F 운용사는 10년치가 페이지로 나뉜다 — 최근 페이지만 보면 이력이 통째로 빈다. (+1 more)

### Community 258 - "FailureAlertTest"
Cohesion: 0.13
Nodes (7): FailureAlertTest, 실패 알림은 timeout 취소(cancelled) 상태도 포착해야 한다. GitHub Actions는 timeout 초과 시 결론을…, CI는 읽기 전용이므로 새 push가 대기 검증을 취소할 이유가 없다., 분기 실패가 연간 백필까지 막아 세그먼트 공백을 남기면 안 된다., source workflow가 공통 리포터를 건너뛰면 조용한 장애가 생긴다., 비싼 설치 앞에 게이트가 있어야 한다 — preflight를 없애면 안 된다., 보낼 카드가 없는 날 Chromium과 61MB 폰트를 받으면 그 시간은 그냥 사라진다. 설치가 composite로 옮겨갔으므로 게이트도 그…

### Community 259 - "test_logging.py"
Cohesion: 0.21
Nodes (6): JsonFormatterTest, LogFieldsTest, 로그는 한 줄 JSON이고, 비밀값은 나가지 않는다., 로그는 관측이다. 직렬화 때문에 프로그램이 죽으면 안 된다., logging이 나중에 KeyError를 던지는 것보다 여기서 막는 편이 낫다., _render()

### Community 260 - "classify_session"
Cohesion: 0.11
Nodes (22): classify_session(), collect_window(), is_placeholder_time(), is_within_collect_window(), datetime, time, 발표 예정 시각을 거래 세션 구간(BMO/AMC)으로 분류한다. 발표 '날짜'만으로는 언제 수집을 걸어야 하는지 알 수 없다. 같은 날짜라도…, 지금이 그 세션의 수집 창 안인지 판정한다. (+14 more)

### Community 261 - "parse_datetime"
Cohesion: 0.04
Nodes (51): 로컬 사본(Parquet)의 읽기·쓰기. Supabase 조회 함수와 같은 모양의 결과를 돌려준다. ``` data/local/mirror/…, MarketQuote, MarketState, _number(), Any, datetime, 실시간 quote를 보관하는 단일 프로세스 RAM Hot State., 최신값만 덮어쓰는 RAM cache. source of truth나 주문 ledger가 아니다. (+43 more)

### Community 262 - "AI Investor Constitution — 판단 계층이 넘지 않는 선"
Cohesion: 0.18
Nodes (11): 10. 변경 게이트, 1. 투자 대상, 2. 데이터 Source of Truth, 3. TradingAgents의 책임, 4. 뉴스·소셜 정책, 5. 공통 포트폴리오 계약, 6. 결정론적 계산, 7. 백테스트와 강화학습 (+3 more)

### Community 263 - "fundamentals/test_repository.py"
Cohesion: 0.15
Nodes (10): _as_of(), datetime, 정정이 원본을 덮지 않고, as-of 조회가 그때의 값을 준다., 예정일은 자주 바뀐다. 관측이 쌓인 채로 세면 같은 발표가 여러 번 잡힌다., 정정 공시가 원본을 지우지 않고, cutoff마다 그때 알 수 있던 버전 하나를 고른다., SEC 제출일(6/1)이 지났어도 우리가 받은 것은 6/3이다 — 운영 재현은 원본을 쓴다., 6/1 제출 공시는 6/2 00:00 UTC(뉴욕 6/1 저녁)에는 아직 쓰지 않는다 — 장 마감 뒤 공시일 수 있다., 공시는 받았어도 재처리한 버전 행이 cutoff 뒤에 생겼으면 그때는 몰랐던 값이다. (+2 more)

### Community 264 - "build_decision_experiences.py"
Cohesion: 0.08
Nodes (24): build_experience(), main(), datetime, 원본 판단의 당시 신호와 독립적인 비용 반영 가상 성과를 연결한다., 다음 날 이후 종가 진입과 완전히 지난 거래일만 사용한다. 보유 비중을 추측하지 않는 단위 노출 실험이다. open/increase는 1 단위…, 이미 관측한 경험은 덮어쓰지 않고 신규 성숙 판단만 추가한다., run(), main() (+16 more)

### Community 265 - "BuildTest"
Cohesion: 0.20
Nodes (4): BuildTest, estimates 커버리지가 100%가 아니다 — 없으면 블록이 통째로 빠져야 한다., GAAP 계산값과 조정 컨센서스를 빼면 없는 서프라이즈가 생긴다., 컨센서스 스냅샷이 없어도 서프라이즈 이력만으로 블록을 낼 수 있다.

### Community 266 - "storage_paths.py"
Cohesion: 0.16
Nodes (23): parquet_root(), Path, Intelligence의 DuckDB catalog와 Parquet archive 위치. 표 이름을 문자열 리터럴로 흩뿌리면 이름을 바꿀 때…, 본문 Parquet 루트. 기본 production 경로는 명시적으로 고정한다. 테스트나 별도 profile에서 DuckDB 경로를 주면 그…, _configured_path(), evidence_cache_path(), intelligence_database_path(), intelligence_parquet_root() (+15 more)

### Community 267 - "_db"
Cohesion: 0.11
Nodes (11): _db(), _FakeClient, _FakeTable, Database, 조용히 잘리거나 빠지는 읽기를 막는지 본다., 정렬 없는 range 읽기는 페이지 경계로 행이 빠질 수 있다. 조용히 두지 않는다., 권한·제약 오류를 '이미 있음'으로 삼키면 알림이 조용히 사라진다., SelectInChunksTest (+3 more)

### Community 268 - "ViewTest"
Cohesion: 0.20
Nodes (3): 7일은 30일에 포함되므로 넘을 수 없다 — 넘으면 출처가 따로 갱신한 것이다. 실측: UBER 상향 7일 7 대 30일 6, TSLA 하향…, 카드에 GAAP EPS도 함께 있으므로 무엇을 비교했는지 밝혀야 한다., ViewTest

### Community 269 - "데이터 — Supabase, PIT, 그리고 로컬 저장소"
Cohesion: 0.11
Nodes (19): Cache와 중복 제거, Feature 소비 경계, Fundamentals cutoff 조회, Macro historical replay, PIT의 핵심 시각, Retention과 복구, Segment metrics, Source of truth와 편의용 최신 표 (+11 more)

### Community 270 - "test_edgartools_13f.py"
Cohesion: 0.11
Nodes (7): skipUnless, EdgartoolsWrapperTest, edgartools shadow 파서 wrapper와 운영 파서의 결과 일치(parity) 테스트. edgartools가 설치되어 있지 않으면…, edgartools 미설치/지연 import 경로. 설치 여부와 무관하게 동작해야 한다., edgartools 출력 컬럼을 운영 모델로 정규화하는 순수 헬퍼. 의존성 불필요., WrapperNormalizerTest, WrapperUnavailableTest

### Community 271 - "market_schedule.py"
Cohesion: 0.16
Nodes (13): get_us_market_phase(), is_us_market_holiday(), MarketPhaseInfo, date, datetime, Enum, str, 미국 정규장 시간표(뉴욕 시간 기준)를 인식하여 하네스 동작 국면과 주기를 계산한다. (+5 more)

### Community 272 - "SurpriseRowsTest"
Cohesion: 0.20
Nodes (4): 공시 시점에는 아직 모르는 분기를 카드에 실으면 안 된다., 관측된 실제 사례(GOOGL +214%/+92%, UBER -82%)를 서프라이즈로 단정하지 않는다., 정상 범위(AAPL 3~7%, TSLA -38%)까지 잘라내면 블록이 쓸모없어진다., SurpriseRowsTest

### Community 273 - "edgartools_13f.py"
Cohesion: 0.26
Nodes (10): EdgartoolsUnavailable, parse_information_table(), _position_kind(), RuntimeError, _quantity_type(), edgartools 기반 13F information table shadow 파서. 운영…, edgartools가 설치되어 있지 않을 때 발생한다., edgartools로 information table을 파싱해 운영 모델(`RawPosition`)로 정규화한다.… (+2 more)

### Community 274 - "test_macro_notifications.py"
Cohesion: 0.27
Nodes (4): macro: 매크로 시장 지표 알림 묶음 (core·watch). 데이터 조회와 알림 조립은 이 패키지의…, _marker_tier(), 매크로 알림 — 경보는 상태가 바뀔 때만, 오늘의 시장은 내용이 바뀔 때만 사람에게 닿는다., WatchStateTest

### Community 275 - "map_fiscal_periods.py"
Cohesion: 0.16
Nodes (21): 외부 I/O 없이 재무 관측값을 변환하고 검증하는 서비스., _add_months(), _annual_period(), _as_date(), _as_datetime(), _calendar_by_ticker(), _latest_reported_quarters(), _nearest_period() (+13 more)

### Community 276 - "object"
Cohesion: 0.07
Nodes (23): object, 외부 저장소와 무관한 fundamentals 도메인 모델과 계산 규칙., 키가 설정된 후보마다 실행 환경을 확인하고, 통과한 첫 후보 이름을 돌려준다. 예산은 쓰지 않는다., 풀에서 남은 후보를 하나씩 예약·시도해 이 종목의 분석을 완주한다. 한 후보가 실패하면(예약 자체가 없거나 호출 도중 429/404 등) 다음…, _select_and_run(), verify_runtime(), 판단을 시작하기 전에 확인한 실행 환경이 망가져 있다. 종목 실패로 기록하면 안 되는 종류다., TradingAgents가 실제로 쓰는 import·SDK·TLS 경로로 요금이 없는 호출 하나를 보낸다. 환경이 깨지면(패키지가 `uv… (+15 more)

### Community 277 - "ActualProviderTest"
Cohesion: 0.19
Nodes (3): ActualProviderTest, _fred_setting(), ECON actual provider의 unit/validation/fail-closed 계약.

### Community 278 - "_Repository"
Cohesion: 0.13
Nodes (6): _filing(), FilingRowCapTest, 프롬프트에 실리는 원자료 양을 못박는다. Azure gpt-5-mini 배포 실측(2026-09-03): 50,000 토큰/분, 50…, as_of(2026-09-03)보다 과거인 분기 공시. 최신이 index 0이다., 자른 것을 숨기면 모델이 '이게 전부'라고 읽는다., _Repository

### Community 279 - "ChampionForecastTest"
Cohesion: 0.15
Nodes (7): _artifact(), ChampionForecastTest, FakeRepository, datetime, _row(), SignalHorizonContractTest, TrainingRecordsAlphaTest

### Community 280 - "test_segments_retention.py"
Cohesion: 0.14
Nodes (4): fundamentals 수집·검증 명령 패키지., 세그먼트 8년 보존 정책과 외래키 안전 삭제 순서를 검증한다., SegmentsRetentionTest, _Supabase

### Community 281 - "DashboardLauncherCliTest"
Cohesion: 0.15
Nodes (3): DashboardLauncherCliTest, 모든 .bat은 CRLF여야 하고, 시스템 python이 아니라 프로젝트 .venv를 쓴다. LF로 저장되면 cmd.exe가 마지막 줄을 삼켜…, 루트에는 run.bat 하나만 둔다 — 나머지는 목적별 scripts/ 하위에 있다.

### Community 282 - "price_risk_profile"
Cohesion: 0.07
Nodes (36): _annual_points(), AnnualPoint, _bars_oldest_first(), _cagr(), fundamental_trend(), _gap_profile(), _number(), _percentile() (+28 more)

### Community 283 - "SegmentHighlightsTest"
Cohesion: 0.08
Nodes (13): EarningsCardTest, EarningsExtrasTest, 실적 알림에 붙는 세그먼트 요약의 기간·중복 방지 규칙을 검증한다., 세그먼트 공시가 끝나기 전에는 빈 축 카드로 선점하지 않는다., 기한이 없으면 "늦게 보낸다"가 아니라 "영영 안 보낸다"가 된다. 세그먼트는 SEC의 분기 데이터셋에서 오고 그것은 한 분기 늦게 공개된다.…, 접수일을 모르면 기한을 잴 수 없다. 그때는 보내지 않는 쪽이 안전하다., 후속 알림 잡도 processing/failed 공시를 원장에 맡기지 않는다., 블록 하나 = 질문 하나. 제목이 '뭐와 뭐'면 두 주제가 섞였다는 뜻이다. (+5 more)

### Community 284 - "DiscordChannel"
Cohesion: 0.09
Nodes (18): DiscordChannel, 목적지 ID와 고정 API 경로만 사용한다. webhook URL을 받거나 기록하지 않는다., _config(), DuplicateThreadResolutionTest, ForumDeliveryTest, ForumThreadsAreReusedTest, 포럼 채널로 카드를 보내는 경로를 굳힌다. Discord는 포럼 채널의 `/messages`를 **400으로 거절한다** — 첫 글이 곧…, 분기마다 오는 공시 사이에 스레드는 보관 상태가 된다. (+10 more)

### Community 285 - "Database"
Cohesion: 0.02
Nodes (136): fundamentals 스키마를 읽고 쓰는 유일한 자리. ## 재무는 CIK 사실이다 SEC CompanyFacts는 등록인(CIK) 단위로…, institutional 스키마를 읽고 쓰는 유일한 자리. ## CUSIP은 여기서 종목으로 바꾸지 않는다 13F는 CUSIP으로만 온다.…, MarketPriceReader, 저장된 market 가격으로 일별 breadth를 계산한다., Macro breadth가 소비하는 최소 Market 저장 interface., Macro canonical reader/writer. 코드는 안정적인 ``series_id``라는 이름을 계속 사용하지만 DB fact는…, market 스키마를 읽고 쓰는 유일한 자리. ## 시장 가격의 PIT 경계 일별 종가는 거래일 종료 뒤 공개된 사실이다. 로컬 적재 시각은…, configure() (+128 more)

### Community 286 - "compute_all"
Cohesion: 0.14
Nodes (12): compute_all(), macd(), DataFrame, Series, src/investment_agent/research/features/compute.py — RSI·MACD 직접 계산. §5 공식 그대로:…, Wilder RSI. 첫 length-1행은 NaN., MACD line / signal. EMA는 adjust=False (전통 정의)., 단일 ticker 가격을 날짜당 한 행의 저장형 지표로 계산한다. 입력 컬럼: ticker · trade_date · close 출력 컬럼:… (+4 more)

### Community 287 - "_crons"
Cohesion: 0.13
Nodes (8): _crons(), MacroChainTest, 매크로 알림 3종. 상류가 둘(macro_etl / macro_etl_monday)이라 한쪽만 들으면 요일이 빈다., ECOS 키 하나가 만료돼도 ETL은 exit 1 한다 — success로 잠그면 카드가 묻힌다., workflow_run이 발화하지 않아도 스스로 한 번은 돈다., 워치가 볼 수 있는 새 관측치는 macro ETL이 넣어주는 것뿐이다. `macro.observation_versions`는…, 워크플로의 schedule cron 목록(주석 처리된 줄은 제외)., UniverseCadenceTest

### Community 288 - "적응형 정보 구조"
Cohesion: 0.12
Nodes (16): 13F 비중은 '보고된 장부 안에서의 비중'이다, Dashboard — ATLAS 읽기 전용 투자 터미널, Discord 알림 대응표, 데이터 출처 설계표, 매크로와 지표 발표는 분리한다, 사이드바는 세 갈래다, 상세를 여는 방식은 고를 수 있다, 선택은 카드 클릭만이 아니다 (+8 more)

### Community 289 - "DeliverEditTest"
Cohesion: 0.17
Nodes (4): _config(), DeliverEditTest, 원장 기반 전송(`deliver`)과 정정(`edit`)이 Discord에 어떤 요청을 보내는지 굳힌다., _Response

### Community 290 - "gdpnow_archive.py"
Cohesion: 0.30
Nodes (13): _as_date(), fetch_rows(), fetch_workbook(), _frame_rows(), parse_workbook(), Any, date, _quarter_start() (+5 more)

### Community 291 - "context.py"
Cohesion: 0.12
Nodes (17): filing_available_at(), date, datetime, 공시와 회계기간을 식별하는 순수 값 객체., 일자 정밀도 SEC 제출일을 **다음 날 0시(뉴욕)**부터 알 수 있던 것으로 본다. `filing_date`는 시각이 없는 ET 날짜다.…, ContextRepository, _fundamentals_available_at(), _id() (+9 more)

### Community 292 - "QualityAssessmentTest"
Cohesion: 0.21
Nodes (3): QualityAssessmentTest, 회사 지표가 0이면 커버리지 비율을 낼 수 없다. None인 채로 임계값 비교에 들어가면 TypeError로 그 배치의 분기 파일 전체가…, _row()

### Community 293 - "institutional/card.py"
Cohesion: 0.15
Nodes (33): blind_spot_caveat(), blind_spots 코드 목록을 운용사별 한국어 caveat 한 줄로 만든다., _activity_rows(), build_filing(), build_quarterly(), _co_held(), _conflicts(), _instrument_rows() (+25 more)

### Community 294 - "sec13f.py"
Cohesion: 0.16
Nodes (15): FilingErrorSink, ShadowSink, FilingRecord, 13F 수집·저장 경계에서 사용하는 명시적 데이터 모델., RPC에 넘기는 원천 포지션 배열. DB 컬럼 계약과 1:1로 맞춘다., 검증을 마친 13F 공시와 합산 포지션 묶음., _information_table_xml(), iter_filings() (+7 more)

### Community 295 - "_FakeBuilder"
Cohesion: 0.11
Nodes (8): accessions_by_source(), 지정 source로 적재된 accession_no을 CIK별로 반환한다., 긴 `in` 목록을 나누고 각 묶음을 페이지네이션한다., select_in_chunks(), _FakeBuilder, Any, PostgREST 빌더 체인 흉내. 실제로 호출된 range/order/in_을 기록한다., _Result

### Community 296 - "report.py"
Cohesion: 0.19
Nodes (10): coverage_rows(), dossier_sections(), DossierSectionSpec, 대시보드와 문서가 공유하는 Evidence Dossier 준비 상태 보고서., 읽기 전용 DB 감사 시점의 coverage를 화면용 행으로 돌려준다., 목표 서류철의 섹션과 현재 소비 가능 상태를 고정한다., PIT 밸류에이션 계약의 사용자 검토용 요약이다., 서류철 한 섹션의 표시·소비 계약이다. (+2 more)

### Community 297 - "실행과 안전 — 주문·승인·Broker와 단계별 안전장치"
Cohesion: 0.14
Nodes (14): Broker-independent contract, Credential 격리, Discord Live Manual 승인, Idempotency와 결과불명 주문, Kill switch와 Lockdown, Model 승격 최소 증거와 Live Autonomous Permit, Reconciliation, 분석·검증 단계 (+6 more)

### Community 298 - "SignalBatch"
Cohesion: 0.22
Nodes (5): Any, 한 분석 회차에서 요청·성공·실패·미완료 종목을 고정한다., 모든 요청이 성공한 배치만 실행 후보가 될 수 있다., SignalBatch, SignalBatchTest

### Community 299 - "verify_postgres_sql_syntax.py"
Cohesion: 0.30
Nodes (9): check_all(), check_file(), main(), Path, `db/postgres/v1/*.sql`이 유효한 PostgreSQL 구문인지 오프라인으로 검증한다. `v1_schema_probe.py`는…, 구문 오류가 있으면 사람이 읽을 오류 메시지를, 없으면 None을 돌려준다., sql_files(), PostgresSqlSyntaxTest (+1 more)

### Community 300 - "load"
Cohesion: 0.17
Nodes (9): EvidenceError, load(), ValueError, 판단 근거를 파일로 내보내고 DB에는 주소만 남긴다. ## 왜 DB에 넣지 않는가 근거 번들은 한 건에 수십 KB다. `jsonb`에 넣었더니…, 저장된 근거를 되읽는다. 지문이 다르면 예외 — 조용히 다른 근거를 주지 않는다., IntegrityTest, 근거는 DB 밖에 있고, 조용히 바뀌면 읽을 때 걸려야 한다., 그때 본 근거'가 조용히 바뀌면 판단 기록 전체가 거짓이 된다. (+1 more)

### Community 301 - "fomc_calendar.py"
Cohesion: 0.22
Nodes (13): _current_dates(), _fetch(), fetch_dates(), FomcCalendarError, _historical_dates(), _meeting_end_date(), date, ValueError (+5 more)

### Community 302 - "canonical_json"
Cohesion: 0.05
Nodes (46): canonical_json(), 같은 내용이면 항상 같은 문자열. 해시와 중복 판정의 기준이다., DatasetManifest, FeatureRecord, LabelRecord, _period(), 연구 산출물의 provenance와 PIT 경계를 표현하는 계약., dataset hash·기간·PIT cutoff을 모델 artifact와 함께 추적한다. (+38 more)

### Community 303 - "reconcile_orders"
Cohesion: 0.23
Nodes (9): LocalOrder, Protocol, 우리 원장과 broker 상태를 다시 맞춘다. ## broker_order_id로만 맞춘다 종목·수량·시각이 비슷하다고 같은 주문으로 묶지…, broker 응답에서 이 모듈이 요구하는 최소한., 양쪽 목록을 `broker_order_id`로만 맞춘다., reconcile_orders(), ReconciliationResult, RemoteOrder (+1 more)

### Community 304 - "EnvFileTest"
Cohesion: 0.27
Nodes (4): EnvFileTest, Path, .env 갱신 — 비밀값 파일을 다루므로 손실이 나면 안 된다., 사람이 적어둔 메모가 날아가면 안 된다.

### Community 305 - "ProcessFileLock"
Cohesion: 0.10
Nodes (13): main(), DuplicateProcessError, ProcessFileLock, Path, RuntimeError, 한 장비에서 하네스 프로세스가 하나만 실행되게 하는 OS file lock., 이미 같은 state 디렉터리를 소유한 프로세스가 있는 경우다., HarnessService (+5 more)

### Community 306 - "CollectSocialTest"
Cohesion: 0.15
Nodes (7): CollectSocialTest, NormalizeSocialTest, _payload(), Reddit 수집 유스케이스와 저장 형태., 작성자 원문을 90일 들고 있을 이유가 없다., 언급이 없다고 게시물을 버리면 나중에 규칙을 고쳐도 다시 못 찾는다., cap 소진은 provider 오류가 아니다 — 남은 채널을 계속 돌면 예약만 반복 소모한다.

### Community 307 - "memory_context"
Cohesion: 0.12
Nodes (11): PendingStateTest, memory_context(), datetime, 모든 topic의 baseline을 과거로 둔 메모리 원장과 가짜 채널., CalendarTest, _flash(), FlashTest, CLI와 하네스는 목적지를 넘기지 않는다. 해석된 포럼이 곧 목적지다. (+3 more)

### Community 308 - "build_valuations"
Cohesion: 0.10
Nodes (9): build_valuations(), datetime, 종목별 가격·발행주식수·TTM 재무를 하나의 PIT 관측값으로 만든다., HistoricalValuationTest, _ValuationRepository, BuildValuationsEntryTest, 근거가 모자란 날도 기록한다 — 왜 못 만들었는지가 나중에 필요하다., DB CHECK 제약과 같은 불변식을 코드 쪽에서도 지킨다. (+1 more)

### Community 309 - "strategy/embeds.py"
Cohesion: 0.05
Nodes (79): analyze_allocation_change(), Allocation change analysis for strategy notifications., _as_card(), _as_row(), build_card(), build_summary(), _generic_layout(), _layout_for() (+71 more)

### Community 310 - "discord_admin/client.py"
Cohesion: 0.10
Nodes (40): add_member_role(), admin_user_id(), create_channel(), create_role(), create_webhook(), delete_channel(), edit_channel(), edit_everyone() (+32 more)

### Community 311 - "._history"
Cohesion: 0.18
Nodes (5): ComboOverlayTest, EpsBlendTest, 수염이 축 밖으로 잘리면 '기대보다 훨씬 위'가 안 보인다., GAAP 선 범위 밖의 조정값이 잘리면 간극이 안 보인다., 이력이 이번 분기까지 못 왔으면 직전 분기 쌍을 올리지 않는다.

### Community 312 - "format_guidance_headline"
Cohesion: 0.08
Nodes (23): Pattern, build_flash_embed(), compute_surprise(), format_eps(), format_money(), Any, 8-K 실적 속보 Discord Embed 빌더., 실제값과 예상값으로부터 서프라이즈 비율(%)을 동적으로 계산한다. (+15 more)

### Community 313 - "_Repository"
Cohesion: 0.23
Nodes (5): _feature_row(), _label_row(), LoadTrainingSetTest, 원장 행에서 RL 학습용 FeatureDataset을 조립하는 경로를 검증한다., _Repository

### Community 314 - "Filing13F"
Cohesion: 0.19
Nodes (11): effective_filings(), Filing13F, 한 매니저·한 분기에서 **실제로 유효한** 신고들. `RESTATEMENT`가 있으면 그것 하나만, 없으면 원본과 `NEW HOLDINGS`…, effective_portfolio_state(), _filing_row(), Any, v1 원천 표에서 accepted-at 이전의 현재·직전 포트폴리오를 만든다., EffectiveFilingsTest (+3 more)

### Community 315 - "_Query"
Cohesion: 0.08
Nodes (10): _feature(), _label(), _model_version(), _Query, signal_runs는 decision_runs를 FK로 참조한다 — 둘 다 최소한으로 심는다., _Response, RLRepositoryTest, _Schema (+2 more)

### Community 316 - "valuation_history"
Cohesion: 0.12
Nodes (18): _gauge(), _log(), _multiple(), 배수 축은 로그다 — 곱셈 척도이기도 하고, 이익이 0에 가까워지면 발산하기 때문. TSLA는 실제로 PER 5~95분위가…, PER 스파크라인 좌표 + 중앙선/축 라벨 (history.downsample_weekly 결과를 받음). top은 축 라벨이 앉는 자리다 —…, 값 → 트랙 위치(%). 양끝 2~98%로 클램프해 마커가 트랙 밖으로 안 나가게., 배수 표기 — 1000배가 넘으면 소수점을 버려야 칸에 들어간다., valuation_history.compute() 결과 → 역사 밸류에이션 표 행 + PER 스파크라인(색 기준 적용). 트랙은 백분위 축이… (+10 more)

### Community 317 - "Investment Agent — S&P 500 투자 분석 파이프라인과 Discord 알림"
Cohesion: 0.13
Nodes (15): 1. 데이터 수집과 Supabase, 2. Evidence와 Feature, 3. 후보 선정과 AI 분석, 4. 모델과 포트폴리오, 5. 검증과 실행, Investment Agent — S&P 500 투자 분석 파이프라인과 Discord 알림, Repository 구조, 각 계층이 하는 일 (+7 more)

### Community 318 - "InvestmentAdaptersTest"
Cohesion: 0.11
Nodes (8): context(), FakeApprovalRepository, FakeDecisionRepository, FakeRunner, FakeSystemStore, InvestmentAdaptersTest, 거절·만료도 물은 것이다. 같은 System 목표로 다시 승인을 묻지 않는다., 수집은 거래 창과 무관하다 — 창으로 자르면 BMO·AMC 발표를 통째로 놓친다.

### Community 319 - "IntelligenceArchitectureTest"
Cohesion: 0.18
Nodes (9): _imports(), IntelligenceArchitectureTest, Path, _python_files(), intelligence 계층 경계를 검증한다. data 도메인들과 같은 4계층 문법을 쓴다 — 저장소만 Supabase가 아니라 로컬…, 도메인 규칙이 저장소나 네트워크를 알면 규칙만 따로 시험할 수 없다., application은 infrastructure.sources와 domain만 안다. universe·market과 같은 이유로…, 따로 두면 정규화·언급 추출 규칙이 두 벌이 되고 조용히 갈라진다. (+1 more)

### Community 320 - "DropImplausibleSharesTest"
Cohesion: 0.24
Nodes (7): DropImplausibleSharesTest, SEC 원본의 이상값은 그 행만 버린다 — 그 기업 전체를 버리지 않는다. 발행주식수는 시가총액과 주당 지표의 분모다. 틀린 값을 담느니 없는…, 실측: benchmark=1,000 대 실제 1,071,666,977 — 진짜 값이 걸렸었다., 클래스 B가 A보다 훨씬 작은 것은 정상이다 — 섞어 재면 B가 이상값이 된다., 전부 자리표시자면 그 클래스에 대해 아는 것이 없다 — 지어내지 않는다., _row(), _values()

### Community 321 - "market_backfill.py"
Cohesion: 0.06
Nodes (28): main(), _parse_args(), Namespace, 일봉·기업행위 과거 이력 복구. daily와 같은 수집 절차를 쓰고 대상·기간만 다르다., prune_history(), v1 market 계약은 append-only 관측 원장만 정의하므로 삭제하지 않는다., archive_daily_rows(), archive_root() (+20 more)

### Community 322 - "DeliveryRejected"
Cohesion: 0.24
Nodes (9): DeliveryRejected, DeliveryUnknown, _file_name(), Any, RuntimeError, 새 메시지를 보낸다. 포럼이면 스레드에 이어 붙이거나 스레드를 새로 만든다. `known_thread_id`는 원장이 기억하는 스레드다.…, 전송되지 않았음이 명확한 응답. 재시도 가능한 거절만 다시 예약한다., 이미 보낸 메시지의 내용을 바꾼다. 첨부가 있으면 옛 첨부를 새 것으로 갈아 끼운다. (+1 more)

### Community 323 - "30_execution.sql"
Cohesion: 0.29
Nodes (10): approvals, execution_control, fills, intents, order_attempts, order_events, order_manifests, orders (+2 more)

### Community 324 - "test_entrypoint.py"
Cohesion: 0.25
Nodes (6): MacroRefreshResult, _indicator(), MacroRunTest, MacroTransformTest, macro v1 진입점의 범위·모드·종료코드 계약을 검증한다., _series()

### Community 325 - "OpenFigiIdentifierTest"
Cohesion: 0.13
Nodes (4): institutional 외부 데이터 source adapter 패키지., OpenFigiIdentifierTest, CUSIP/CINS OpenFIGI 조회의 식별자 타입·fallback 계약을 검증한다., _Response

### Community 326 - "._snapshot"
Cohesion: 0.24
Nodes (3): InstrumentBreakdownTest, ManagerGroupsSnapshotTest, 13F의 옵션·전환사채(PRN)를 주식과 분리해 보존하는지 검증한다.

### Community 327 - "harness_adapters.py"
Cohesion: 0.12
Nodes (17): ApprovalRepositoryPort, _clock(), DecisionRepositoryPort, follow_system_target(), _positive_float(), _positive_int(), Any, datetime (+9 more)

### Community 328 - "FiresBetweenTest"
Cohesion: 0.13
Nodes (5): CronMatchTest, FiresBetweenTest, cron 판정 — 여기가 틀리면 '미실행'을 거꾸로 보고한다., cron 요일은 일=0이다. 파이썬 weekday()(월=0)를 그대로 쓰면 하루씩 밀린다., market_daily는 전날 23:30 UTC다 — 구간을 24시간으로 잡아야 잡힌다.

### Community 329 - "_called_schemas"
Cohesion: 0.22
Nodes (11): _called_schemas(), CodeOnlyCallsDeclaredSchemasTest, _declared_schemas(), _imports_postgres_singleton(), Module, 코드가 부르는 Postgres 스키마는 선언에 실재해야 한다. 이 저장소의 단위 테스트는 DB를 때리지 않는다. 그래서 없는 스키마를 부르는…, 대상을 못 찾으면 위 테스트는 공허하게 통과한다., `sb`는 service-role Postgres 클라이언트다. 이것을 들여온 모듈만 대상이다. (+3 more)

### Community 330 - "store"
Cohesion: 0.18
Nodes (8): Any, DB에 적을 것 전부. 내용은 여기 없다., 근거를 파일로 내보내고 주소를 돌려준다., store(), StoredEvidence, 빈 근거를 저장하면 '근거가 있다'고 기록되면서 실제로는 없다., 한 파일로 합치면 목록 화면이 역할 의견까지 통째로 받는다., StoreTest

### Community 331 - "Fundamentals domain — 저장소와 무관한 계산 규칙"
Cohesion: 0.05
Nodes (37): Fundamentals 아키텍처 — 계층 경계와 소유 규칙, 계산과 reporting, 시점 정합성, 실패와 검증, 의존성 방향, 저장 책임, earnings / expectations, Fundamentals canonical 컬럼 — 이름과 의미 (+29 more)

### Community 332 - "assess_segment_quality.py"
Cohesion: 0.25
Nodes (14): assess_rows(), _base_quality(), _company_row(), _is_subset_sum(), _metric_method(), _number(), _overlapping_revenue_aggregates(), Any (+6 more)

### Community 333 - "apply_downstream_api_key"
Cohesion: 0.17
Nodes (8): apply_downstream_api_key(), _llm_max_retries(), 지금 고른 후보의 키를 provider SDK가 읽는 환경변수에 **덮어쓴다**. setdefault를 쓰면 안 된다. 모델 풀이 후보를…, 429를 견딜 SDK 재시도 횟수. 대기 시간은 provider가 준 Retry-After를 따른다., ProviderKeyRotationTest, 후보를 갈아탈 때 앞 후보의 API 키가 남으면 다음 후보가 그 키로 호출된다. 실측 2026-09-03: Azure 시도가…, Azure 배포는 429에 Retry-After 10~15초를 준다. SDK 기본 2회로는 못 견딘다., RetryBudgetTest

### Community 334 - "storable_share_rows"
Cohesion: 0.26
Nodes (7): Any, 저장 계약이 받는 서식만 남기고, 버린 서식 이름을 함께 돌려준다. CompanyFacts의 fact에는 `10-KT`(회계연도 변경 전환기…, storable_share_rows(), 발행주식수 수집은 저장 계약이 받는 서식만 보낸다. CompanyFacts의 fact에는 `10-KT`(회계연도 변경 전환기 보고서)처럼 우리…, 한 건 때문에 그 기업 전체를 잃지 않는다 — 그것이 전에 일어난 일이다., _row(), StorableShareRowsTest

### Community 335 - "Macro 경제발표 — 일정·예상·실제·개정"
Cohesion: 0.22
Nodes (9): Macro 경제발표 — 일정·예상·실제·개정, reporting read model, 검증과 운영 전환, 변경과 시간, 시점과 발표 오차, 실행과 소비자, 저장과 계산 예시, 키와 저장 단위 (+1 more)

### Community 336 - "InstitutionalArchitectureTest"
Cohesion: 0.21
Nodes (8): _imports(), InstitutionalArchitectureTest, Path, _python_files(), institutional 계층 경계를 검증한다. universe·market의 test_architecture.py와 같은 패턴이다. 다섯…, 도메인 규칙이 저장소나 네트워크를 알면 규칙만 따로 시험할 수 없다., application은 infrastructure.sources와 domain만 안다. universe·market과 같은 이유로…, 평면 모듈이 하나라도 돌아오면 도메인마다 문법이 달라진다.

### Community 337 - "EconIcsTest"
Cohesion: 0.27
Nodes (3): 경제 발표 infrastructure adapter., EconIcsTest, 자연키·구독 UID·일정 변경을 보존하는 ECON ICS 테스트.

### Community 338 - "counters.py"
Cohesion: 0.26
Nodes (11): as_dict(), _calendar(), collect(), _fundamentals(), _gurus(), _ledger(), Any, 각 알림이 '지금 보낼 게 있다고 보는지'를 그대로 읽어 온다. **게이트가 정상적으로 0건을 낼 때가 제일 위험하다.**… (+3 more)

### Community 339 - "_coherent_range"
Cohesion: 0.21
Nodes (7): _coherent_range(), Any, 추정 구간이 말이 될 때만 싣는다. yfinance가 `low > high`인 구간을 주는 일이 있다(실측: eps_low 1.24 >…, CoherentRangeTest, 추정 구간이 뒤집혀 오면 구간만 버리고 평균은 남긴다. yfinance가 `low > high`인 구간을 준다(실측: eps_low 1.24…, 한쪽만 있는 구간은 저장소가 받는다 — 버릴 이유가 없다., 원천 한 칸이 이상하다고 그 종목 전체를 잃지 않는다.

### Community 340 - "news_normalize.py"
Cohesion: 0.26
Nodes (12): canonical_url(), content_fingerprint(), _published_at(), Any, datetime, provider 응답을 저장 레코드로 바꾸고 중복 제거 키를 만든다. ## 왜 URL을 정규화하는가 같은 기사에 추적 파라미터만 다른 링크가…, 중복 제거에 쓸 URL 형태로 맞춘다., 제목·요약으로 만드는 내용 지문. 다른 provider가 같은 기사를 다른 URL로 줄 때 이 지문이 중복을 잡는다. (+4 more)

### Community 341 - "Research Features — 일간 기술지표와 PIT 학습 입력"
Cohesion: 0.15
Nodes (13): 0. 관련 문서 및 전체 위치, 1. 전체 데이터 파이프라인 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 주요 기술지표 및 계산 정의, 4. 관련 코드 및 데이터 흐름, 5. 실행 및 검증 가이드, 6. 수정할 때 확인할 곳, 7. 유용한 SQL 점검 쿼리 (+5 more)

### Community 342 - "Strategy — 팩터/룰 기반 자산배분 전략 6종 파이프라인"
Cohesion: 0.15
Nodes (13): 0. 관련 문서 및 전체 위치, 1. 전체 데이터 파이프라인 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 지원하는 6대 퀀트 자산배분 전략 ([`catalog.py`](catalog.py)), 4. 관련 코드 및 데이터 흐름, 5. 실행 및 검증 가이드, 6. 수정할 때 확인할 곳, 7. 유용한 SQL 점검 쿼리 (+5 more)

### Community 343 - "strategies/db.py"
Cohesion: 0.29
Nodes (12): allocation_strategy_ids(), delete_allocations_before(), latest_allocation_per_strategy(), mark_allocations_sent(), date, 전략 계산 결과를 Research 로컬 저장소에 기록하는 경계., _store(), upsert_allocation() (+4 more)

### Community 344 - "18. 검수 체크리스트"
Cohesion: 0.29
Nodes (7): 18. 검수 체크리스트, 사실성과 구현 계약, 색, 철학과 정보 구조, 카피, 컴포넌트와 접근성, 타이포와 숫자

### Community 345 - "_by_key"
Cohesion: 0.22
Nodes (6): _by_key(), InvestmentChannelsTest, 자동매매 보고 채널 선언 — 카드가 조용히 안 나가는 배치를 막는다., 판단 → 승인 → 체결이 한 카테고리에서 순서대로 읽히게 한다., private 채널에 봇 allow가 안 붙으면 카드가 에러 없이 사라진다., @everyone 채널 deny는 카테고리 private 처리로만 붙어야 한다.

### Community 346 - "CollectNewsTest"
Cohesion: 0.16
Nodes (7): CollectNewsTest, _payload(), 뉴스 수집 유스케이스. 네트워크를 타지 않는다 — fetch는 주입한다., 조회해서 받은 것은 '화제'가 아니다 — 등급을 남긴다., 저장한 뒤 다음 정리에서 지우면 그 사이 화면에 잠깐 나타난다., 파싱 실패를 중복으로 세면 '조용한 0건'을 못 알아본다., cap 소진은 provider 오류가 아니다 — 남은 종목을 계속 돌면 예약만 반복 소모한다.

### Community 347 - "InstitutionalRepository"
Cohesion: 0.10
Nodes (14): InstitutionalRepository, Any, 추적 대상 manager 목록. manager_cik/name/fund_name/is_active의 SSOT는 코드…, 이미 원장에 있는 SEC accession. 신규 수집만 원천에 요청할 때 쓴다., _filing_row(), ManagerTest, OptionsTest, PointInTimeTest (+6 more)

### Community 348 - "safe_fetch"
Cohesion: 0.19
Nodes (15): normalize_tz(), Logger, Series, 출처 함수들이 공통으로 쓰는 도우미 모음(성공값 + 실패목록 함께 반환)., 날짜의 timezone 정보를 떼어 형식 통일(yfinance 등 tz 표기 제각각 대응)., 지표를 하나씩 fetch. 하나 실패해도 멈추지 않고 성공값+실패목록을 함께 반환. budget_sec를 넘기면 그 시점부터 남은 지표는…, safe_fetch(), _api_error() (+7 more)

### Community 349 - "run_preflight"
Cohesion: 0.20
Nodes (13): build_preflight_report(), load_effective_environment(), PreflightReport, probe_venv_runtime(), Path, 파일을 바꾸지 않고 `.env`와 현재 환경의 유효값을 합친다., `.venv` 프로세스에서 버전과 import 가용성만 확인한다., 외부 호출 없이 파일·환경·런타임 점검 결과를 조립한다. (+5 more)

### Community 350 - "CardInstallGuardTest"
Cohesion: 0.21
Nodes (7): CardInstallGuardTest, PNG 카드 렌더 준비의 시간 상한을 지킨다. 설치는 이제 `.github/actions/card-render` composite 하나에…, 이 composite를 실제로 부르는 워크플로. 없으면 그 자체가 실패다., 상한이 **하나라도** 빠지면 실패해야 한다. `playwright install`은 두 번 나온다(install-deps, install…, `timeout ... sudo`는 신호가 자식에 닿지 않아 상한이 무력해진다., 폰트 없이 렌더하면 한글이 두부로 나가는데 예외는 안 난다. 여기서 멈춰야 한다., 안쪽 상한의 합이 부르는 잡의 상한을 넘으면 상한을 둔 의미가 없다. composite action의 스텝은 `timeout-minutes`를…

### Community 351 - "문서 지도 — 처음 보는 사람을 위한 시스템 안내"
Cohesion: 0.17
Nodes (12): Discord 알림은 어디에 있는가, 공개 독자가 읽을 상시 문서, 대시보드는 어디에 있는가, 데이터 적재는 어디에 있는가, 문서 지도 — 처음 보는 사람을 위한 시스템 안내, 문서와 코드가 다르면, 쉬운 비유, 전체 책임 경계 (+4 more)

### Community 352 - "backfill"
Cohesion: 0.07
Nodes (15): BackfillWindow, backfill(), Any, datetime, 시점마다 밸류에이션 → feature 순서로 적재한다. 이미 있는 시점은 건너뛴다., main(), _parse_args(), Namespace (+7 more)

### Community 353 - "db_capacity.py"
Cohesion: 0.33
Nodes (12): cmd_reclaim(), cmd_report(), connect(), database_size(), main(), mb(), project_ref(), Supabase 용량을 실측하고, 회수 가능한 공간을 되찾는다. Supabase Free는 **database size 500MB를 넘기면… (+4 more)

### Community 354 - "MacroNotificationStore"
Cohesion: 0.12
Nodes (16): check(), main(), 실제 Supabase에 붙어 각 서브시스템의 조회 경로를 한 번씩 태워 보는 점검 도구. python…, 조회 하나를 태워 보고 결과를 모은다. ``target``이 ``(module, "attr")`` 이면 속성을 **호출 시점에** 찾는다.…, run(), MacroNotificationStore, Any, 원천 관측을 카드가 소비하는 최신값+파생지표 행으로 접는다. `history`에는 최근 관측마다 경보 판정에 필요한 값(현재·직전 값과… (+8 more)

### Community 355 - "CompanyFinancialRepository"
Cohesion: 0.12
Nodes (3): CompanyFinancialRepository, Any, date

### Community 356 - "_ops_webhook"
Cohesion: 0.23
Nodes (8): _ops_webhook(), (webhook, origin, 사용한 env 이름). Actions 실패와 로컬 하네스 실패는 고치는 방법이 다르다 — 전자는 재실행이나…, OpsWebhookOriginTest, OriginTravelsWithTheMessageTest, 운영 알림은 **실행된 곳**으로 목적지를 가른다. Actions 워크플로 실패와 로컬 하네스 실패는 고치는 방법이 완전히 다르다 — 전자는…, 갈라 두기 전에 알림이 먼저 조용해지는 것이 더 나쁘다., 전용 webhook이 아직 없으면 둘이 한 채널로 떨어진다 — 그때도 구분돼야 한다., _with()

### Community 357 - "fundamental_statistics"
Cohesion: 0.13
Nodes (9): 판단 하나를 가리키는 키와 재현 지문. 키를 계산해서 만드는 이유는 같은 판단이 두 행으로 갈라지지 않게 하기 위해서다., fundamental_statistics(), 공시 원시값에서 최신 수익성·성장·재무안전 지표를 계산한다., FundamentalGrowthTest, AnalysisPathTest, RL 정책은 ALPHA 분석 경로에 섞이지 않는다. RL은 오프라인 연구·평가로만 남는다., 분석은 논지만 남긴다. RL 목표비중·포트폴리오 제안을 다시 만들지 않게 한다., FundamentalStatisticsTest (+1 more)

### Community 358 - "Notifications — 시각화 알림(Playwright PNG 카드 & Discord Embed) 서브시스템"
Cohesion: 0.15
Nodes (13): 0. 관련 문서 및 전체 위치, 1. 전체 알림 렌더링 & 라우팅 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 8대 알림 카드 명세 및 전송 포맷, 4. 관련 코드 및 디렉토리 구조, 5. 실행 및 로컬 테스트 가이드, 6. 수정할 때 확인할 곳, Notifications — 시각화 알림(Playwright PNG 카드 & Discord Embed) 서브시스템 (+5 more)

### Community 359 - "intelligence/domain/__init__.py"
Cohesion: 0.12
Nodes (6): 텍스트 정규화와 언급 추출 규칙. 외부 호출도 저장소도 모른다., CanonicalUrlTest, 추적 파라미터만 다른 같은 기사가 두 행이 되면 안 된다., URL이 없으면 중복 제거를 할 수 없다 — 저장하지 않는다., PIT 계산은 coalesce(available_at, first_seen_at)을 쓴다 — 빈칸을 수집 시각으로 채우면 그 계약이 거짓이…, ToRecordTest

### Community 360 - "TestFundamentalsFlash"
Cohesion: 0.07
Nodes (25): _first_table_amount(), _html_table_priority(), _normalize_text(), _normalized_label(), parse_earnings_release(), 실적 보도자료 HTML에서 실제 매출과 가이던스 문장을 추출한다., 보도자료에서 ``(revenue_actual, guidance_summary)``를 반환한다. 통화 단위가 명시된 headline 매출을 우선…, HTML에서 읽은 공백과 글머리표를 비교 가능한 한 줄로 정리한다. (+17 more)

### Community 361 - "FindTickersTest"
Cohesion: 0.20
Nodes (5): FindTickersTest, 본문 ticker 추출. 오탐을 막지 못하면 언급 표가 쓰레기가 된다., S&P 500에는 ALL·IT·ON·NOW 같은 평범한 단어가 티커로 있다., universe에 없는 심볼은 언급이 아니다 — fail-closed., _tickers()

### Community 362 - "candidate_ranker.py"
Cohesion: 0.06
Nodes (45): normalize_ticker(), 종목 심볼을 대문자 및 표준 dash 형태로 정규화한다., assemble_candidate_features(), CandidateFeatures, CandidateRank, _dense_percentiles(), FactorCandidate, _group_by_ticker() (+37 more)

### Community 363 - "LocalTradingDatabase"
Cohesion: 0.20
Nodes (3): LocalTradingDatabase, 관계형 판단 원장의 원자 쓰기와 페이지 제한 없는 로컬 조회., QueueTest

### Community 364 - "edgar_parser/__init__.py"
Cohesion: 0.10
Nodes (25): is_earnings_8k(), 정확한 Form 8-K Item 2.02 공시만 허용한다., parse_8k_earnings(), 8-K 실적 발표에서 저장 가능한 요약값을 조립한다., 내재화한 표·본문 파서로 8-K 실적값을 한 번에 추출한다., clean_html_to_markdown(), _document_score(), extract_guidance_text() (+17 more)

### Community 365 - "WebClientError"
Cohesion: 0.29
Nodes (6): Exception, RuntimeError, 웹 원천 수집 계약 위반의 공통 기반 예외., 외부 페이지 호출 또는 응답 파싱이 실패했다., WebClientError, WebProviderError

### Community 366 - "_Client"
Cohesion: 0.19
Nodes (5): _Client, Any, 스키마 client를 표 하나 열 때마다 새로 만들지 않는다. supabase-py의 ``schema()``는 부를 때마다 PostgREST…, _Schema, SchemaClientReuseTest

### Community 367 - "macro_indicator_rows"
Cohesion: 0.23
Nodes (8): macro_indicator_rows(), `reporting.macro_observations` 원값을 지표별 최신 상태 + 경보 등급으로 접는다. 반환 각 행:…, market_metadata_by_series(), Any, 대시보드·알림이 공통 카탈로그 메타데이터를 series_id로 조회한다., MacroIndicatorRowsTest, 홈 화면이 부르는 매크로 지표 스트립 계산. 실측 2026-09-04: 홈 페이지가 NameError로 통째로 죽었다 — macro.py가…, _window()

### Community 368 - "overwrites"
Cohesion: 0.22
Nodes (10): overwrites(), plan_everyone(), plan_overwrites(), plan_roles(), Any, 적용할 채널 오버라이트 선언 — (대상 이름, 역할 key, allow, deny). private 카테고리는 카테고리와 그 안의 채널에…, @everyone의 길드 권한이 선언과 다르면 그 차이. 같으면 None., 선언한 역할을 이름으로 대조한다 — 없으면 만들고, 권한이 다르면 고친다. 이름으로 찾는 이유는 채널과 같다: ID를 코드에 박으면 서버를… (+2 more)

### Community 369 - "test_continuous_retrain_exit_code.py"
Cohesion: 0.14
Nodes (9): Research 명령 진입점 패키지. import는 명시적이며 부작용이 없다., _decision(), EmptyLedgerRaisesNotReadyTest, ExitCodeTest, NotReadyIsASafetyErrorTest, PromotionDecision, 재학습 진입점의 종료 코드가 "무엇이 잘못됐나"만 말하게 한다. 실측 2026-09-04: `continuous_learning` 잡이 매일…, 기존 호출부가 RLSafetyError로 잡고 있으므로 하위 타입이어야 한다. (+1 more)

### Community 370 - "discord_admin/sync.py"
Cohesion: 0.31
Nodes (9): _by_name(), env_updates(), plan(), Any, 매니페스트와 실제 서버를 대조해 할 일을 계산하는 순수 로직. 네트워크를 건드리지 않는다 — 픽스처로 검증할 수 있어야 '무엇을 만들지'를…, 매니페스트 기준으로 (생성할 카테고리, 생성할 채널, 이미 있는 것, 매니페스트에 없는 것)., 이미 있는 포럼 중 태그가 매니페스트와 다른 것. 태그는 이름 집합만 본다 — 순서까지 맞추려 들면 사람이 Discord에서 정렬만 바꿔도…, .env에 써 넣을 {변수: 채널ID}. (+1 more)

### Community 371 - "LoadConfigTest"
Cohesion: 0.12
Nodes (9): ConfigError, RuntimeError, 설정이 없거나 모양이 틀렸다. 값 자체는 담지 않는다., LoadConfigTest, PackageImportTest, 설정은 명시적으로 읽고, 안전 플래그는 fail-closed다., 테스트가 개발자 기계의 .env에 물들지 않아야 한다., 안전 플래그가 오타 하나로 켜지면 안 된다. (+1 more)

### Community 372 - "test_ecos.py"
Cohesion: 0.22
Nodes (7): dict, v1 macro 원천 어댑터. 각 adapter는 원천별 실패를 series 단위 결과로 남기고 다른 원천 수집을 막지 않는다., EcosClientTest, _payload(), ECOS 클라이언트가 전체 행과 통계 계약을 보존하는지 검증한다., _Response, _row()

### Community 373 - "_date"
Cohesion: 0.31
Nodes (4): _date(), _finite(), 달력 날짜를 정규 ISO 문자열로 검증한다., _symbol()

### Community 374 - "institutional/test_persistence.py"
Cohesion: 0.15
Nodes (5): 13F 유스케이스 계층. 수집·적재·정리 흐름을 조립한다., InstitutionalRetentionTest, MappingCacheTest, institutional v1 저장소 경계를 검증한다., OpenFIGI의 ticker는 지금 표기다. 상장이 끝났으면 다른 회사가 재사용했을 수 있다.

### Community 375 - "installation_files"
Cohesion: 0.11
Nodes (26): cmd_apply(), cmd_plan(), _connect(), _exposed_schemas(), main(), _project_ref(), 빈 Supabase에 application schema를 처음부터 세운다. `db/postgres/v1/*.sql`이 스키마의 단일 기준이다.…, application_schemas() (+18 more)

### Community 376 - "DependencyDeclarationTest"
Cohesion: 0.22
Nodes (5): _declared_groups(), DependencyDeclarationTest, 의존성을 선언하는 자리는 `pyproject.toml` 하나다. 전에는 `requirements/*.txt` 31개와 루트…, 안내가 가리키는 group이 그 패키지를 실제로 담고 있어야 한다., TradingAgents는 git 의존이라 lock에 넣지 않는다 — 그러면 모든 CI가 그 저장소의 가용성에 묶인다. 대신 검증된…

### Community 377 - "DerivedReadModelTest"
Cohesion: 0.12
Nodes (9): AsOfLookupTest, DerivedReadModelTest, _quarters(), 카드가 쓰는 파생 read model이 실제로 값을 만드는지 지킨다. 이 다섯은 한동안 `return {}`으로 박혀 있었다("v1에…, 8분기치 최소 재무. TTM(4분기)과 전년 동기 비교가 성립하는 최소 크기다., 분기 영업이익을 연간 자산과 견주면 항이 1/4로 줄어 우량 기업이 위험으로 나온다., 스냅샷의 기준일은 공시 접수일이다 — 그 전 거래일에 이 숫자를 쓰면 미래를 본다., 네 분기가 안 되면 합치지 않는다. 부분 합은 틀린 TTM이다. (+1 more)

### Community 378 - "Universe watchlists — 관심 기업 & 토스증권 보유종목 동기화"
Cohesion: 0.18
Nodes (11): 0. 관련 문서 및 전체 위치, 1. 전체 관심종목 파이프라인 아키텍처, 2. 핵심 개념 (초보자 가이드), 3. 관련 코드 및 데이터 흐름, 4. 관심종목 CLI 관리 명령어, 5. 토스증권 계좌 보유종목 동기화 (고정 IP 로컬 전용), 6. 수정할 때 확인할 곳, Multi-Source 관심종목 관리 (`sources = ['manual', 'toss']`) (+3 more)

### Community 379 - "Discord Admin — 코드 기반 선언적 Discord 서버 관리 (IaC)"
Cohesion: 0.17
Nodes (12): 0. 관련 문서 및 전체 위치, 1. 전체 서버 구조 및 카테고리 분류, 2. 핵심 개념 (초보자 가이드), 3. 채널 구조 및 역할 권한 매트릭스, 4. 관련 코드 및 디렉토리 구조, 5. 실행 및 동기화 가이드 (로컬 전용), 6. 수정할 때 확인할 곳, Discord Admin — 코드 기반 선언적 Discord 서버 관리 (IaC) (+4 more)

### Community 380 - "후보 선정 — tracked universe에서 무엇을 볼까"
Cohesion: 0.33
Nodes (6): 안전 경계, 예시 해석, 운영 확인, 점수 입력, 정렬 순서, 후보 선정 — tracked universe에서 무엇을 볼까

### Community 381 - "AGENTS.md — 에이전트가 이 저장소에서 지킬 것"
Cohesion: 0.40
Nodes (5): AGENTS.md — 에이전트가 이 저장소에서 지킬 것, 스킬 — 그 영역을 만지기 전에 해당 SKILL.md를 읽으세요, 실행 환경 노트, 코드 지식 그래프 — graphify, 하지 말 것

### Community 382 - "Delivery"
Cohesion: 0.23
Nodes (5): Delivery, 보낸 메시지가 사는 곳. 수정하려면 location_id와 message_id가 둘 다 필요하다., FakeChannel, 보낸 메시지를 기록한다. failures에 넣은 예외를 차례로 던진다., FakeChannel

### Community 383 - "10. 데이터 시각화"
Cohesion: 0.40
Nodes (5): 10.1 기본 원칙, 10.2 차트 색 배정, 10.3 차트별 규칙, 10.4 테마별 Plotly 기준, 10. 데이터 시각화

### Community 385 - "FundamentalsArchitectureTest"
Cohesion: 0.30
Nodes (5): FundamentalsArchitectureTest, _imports(), Path, _python_files(), fundamentals 계층 경계와 기준 진입점을 검증한다.

### Community 386 - "test_fundamentals_integrity.py"
Cohesion: 0.15
Nodes (6): PersistedPayloadTest, fundamentals wide 적재의 의미 선택·출처 보존 계약을 검증한다., 저장 payload에 스키마에 없는 키가 섞이면 그 공시가 통째로 사라진다., 메모리 전용으로 떼어 내는 키는 스키마가 obsolete로 선언한 것과 같아야 한다., ValidationTest, ViewContractTest

### Community 387 - "DiscordTargetTests"
Cohesion: 0.21
Nodes (7): RuntimeError, 알림 종류에 대해 전송 가능한 Discord 채널이 구성되지 않았다., SubscriptionConfigurationError, _config(), DiscordTargetTests, notifications.subscriptions 읽기 계약을 검증한다., 테스트·CLI가 채널을 직접 지정하는 자리. env가 비어도 통과해야 한다.

### Community 388 - "test_backfill_scopes.py"
Cohesion: 0.22
Nodes (5): BulkFilingContractTest, FilingSchemaContractTest, 기업 전체·세그먼트 재무가 같은 백필 범위 의미를 사용하는지 검증한다., 세그먼트 백필은 secfsdstools 파케이를 직접 읽는다. `sub` 컬럼 이름이 어긋나면 공시를 전부 걸러 내고도 성공으로 끝나므로 실물…, 가짜 프레임이 실물과 어긋나면 이 테스트만 초록이고 운영은 0건이 된다. 실제로 그랬다 — 목이 `form_type`을 쓰는 동안…

### Community 389 - "select_timed_targets"
Cohesion: 0.08
Nodes (27): _as_date(), _as_datetime(), _is_date_only_anchor(), latest_schedule_by_ticker(), date, datetime, 지금 이 시각에 발표가 예정된 관심종목만 골라 낸다. 관심종목 50개를 매번 다 훑으면 SEC 호출이 낭비되고, 하루 한 번만 훑으면 장전…, 발표 예정 시각의 신뢰도에 맞춰 지금 SEC를 조회할 종목만 고른다. 정확 시각은 발표 직전부터 짧게, Yahoo 추정·자리표시는 넓게,… (+19 more)

### Community 390 - "16. 구현 계약"
Cohesion: 0.40
Nodes (5): 16.1 CSS 변수 계약, 16.2 코드 SSOT, 16.3 명명 규칙, 16.4 구현 반영 시 확인할 항목, 16. 구현 계약

### Community 391 - "PITScalar"
Cohesion: 0.13
Nodes (15): build_pit_valuation(), _decimal(), _missing(), PITScalar, PITValuationObservation, _ratio(), PIT 밸류에이션 입력과 관측값의 순수 계산 계약., PIT 입력에서 계산된 저장 후보 관측값이다. (+7 more)

### Community 392 - "9. 핵심 컴포넌트"
Cohesion: 0.18
Nodes (11): 9.10 승인·주문·위험 행동, 9.1 버튼, 9.2 카드, 9.3 Metric, 9.4 Data row와 Table, 9.5 Chip, Badge, Status, 9.6 입력과 선택, 9.7 Navigation (+3 more)

### Community 393 - "score_cross_section"
Cohesion: 0.32
Nodes (5): 같은 시점 종목들의 feature로 category 점수·종합 점수·품질 기준 통과 여부를 계산한다., score_cross_section(), factor 점수: 방향·결측·업종 상대·품질 기준·결정적 순위., _row(), ScoreTest

### Community 394 - "2. 핵심 결정과 우선순위"
Cohesion: 0.40
Nodes (5): 2.1 핵심 결정 요약, 2.2 충돌 시 우선순위, 2.3 규칙의 강도와 적용 단위, 2.4 매체별 적용 범위, 2. 핵심 결정과 우선순위

### Community 395 - "PostgresNotificationLedger"
Cohesion: 0.05
Nodes (29): main(), _observed_minutes(), _parse_workflows(), GitHub Actions 월 사용량을 cron 빈도 × 실측 실행시간으로 추정한다. 무료 할당은 초과해도 경고가 오지 않고 그냥 잡이 돌지…, cron 한 줄이 한 달에 몇 번 도는지. 이 저장소가 쓰는 문법만 다룬다., _runs_per_month(), _count(), _keys() (+21 more)

### Community 396 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 397 - "3. 제품 철학"
Cohesion: 0.40
Nodes (5): 3.1 먼저 이해시키고, 그다음 행동시킨다, 3.2 사용자의 인지 부하를 대신 짊어진다, 3.3 단순함은 정보 삭제가 아니라 우선순위다, 3.4 차분하지만 모호하지 않다, 3. 제품 철학

### Community 398 - "test_runners.py"
Cohesion: 0.19
Nodes (6): _Base, CandidateRunnerTest, PortfolioRunnerTest, 자동매매 보고서 러너 — 원장을 거쳐 한 번씩 닿는지 DB·네트워크 없이 검증한다., _trade(), TradeRunnerTest

### Community 399 - "Fundamentals — 공시·재무·세그먼트·실적 이벤트"
Cohesion: 0.33
Nodes (6): canonical 저장 모델, Fundamentals — 공시·재무·세그먼트·실적 이벤트, 소유 구조, 실행 진입점, 예상치·일정은 바뀔 때만 새 행이다, 읽기 규칙

### Community 400 - "Universe — 회사 identity, 상장 증권, 지수 구성"
Cohesion: 0.40
Nodes (5): 30초 예시: Alphabet, Universe — 회사 identity, 상장 증권, 지수 구성, 실행 흐름, 안전 규칙, 저장 계약

### Community 401 - "filings.py"
Cohesion: 0.07
Nodes (21): _as_datetime(), base_form(), FilingError, is_amendment(), is_periodic(), normalize_accession(), Any, datetime (+13 more)

### Community 402 - "IntelligenceReaderTest"
Cohesion: 0.17
Nodes (7): _article(), IntelligenceReaderTest, 읽기 계층에 쓰기 메서드 호출이 있으면 경계가 무너진 것이다., 화면이 쓰기 모드로 열면 수집 잡이 파일을 열지 못해 죽는다., 수집이 한 번도 안 돈 노트북에서 화면이 예외로 죽으면 안 된다., 저장은 원문, 화면으로 나갈 때 가린다. Reddit 본문에는 지시문처럼 읽히는 문장과 자격증명이 실제로 들어온다., 실행 기록의 message는 provider 오류 문구라 자유 텍스트다. 수집 실패 메시지에 URL과 API 키가 들어올 수 있다.

### Community 403 - "non_liability_claims"
Cohesion: 0.25
Nodes (8): non_liability_claims(), Any, 자본 범위를 구분해 회계항등식의 비부채 청구권을 계산한다., 선택된 common_equity 태그의 포함 범위를 반환한다., 총자산에서 총부채를 제외한 청구권 합계를 계산한다., source_scope(), _derive_missing_liabilities(), 정확한 총부채 태그가 없을 때만 회계항등식 잔여값을 채운다. 부분 부채 태그를 총부채로 승격하지 않는다. 총자산과 보통주자본이 모두 보고됐고…

### Community 404 - "UniverseArchitectureTest"
Cohesion: 0.21
Nodes (8): _imports(), Path, _python_files(), universe 계층 경계를 검증한다. fundamentals의 test_architecture.py와 같은 패턴., application은 infrastructure.sources와 domain만 안다.…, repository.py/persistence.py/watchlists/*는 application·commands가 소비하는 쪽이다 — 거꾸로…, 이 계층화 작업에서 지운 옛 평면 구조 파일이 재도입 shim으로 다시 생기지 않았는지 본다. stale import를 "고친다"며 한 줄짜리…, UniverseArchitectureTest

### Community 405 - "finite_float"
Cohesion: 0.12
Nodes (22): finite_float(), 유한한 float만. NaN·Infinity·bool·읽을 수 없는 값은 `default`. bool을 막는 이유: 파이썬에서…, _gross_profit(), price_statistics(), Any, quality_statistics(), _quarters_desc(), _ratio() (+14 more)

### Community 406 - "PlanVersionsTest"
Cohesion: 0.20
Nodes (8): PlanVersionsTest, 예상치·일정·커버리지를 바뀔 때만 버전으로 남기는 규칙과, 그 버전을 읽는 비교 뷰의 계약., A→B→A. 전체 DISTINCT로 줄이면 되돌아온 사건이 사라진다., 비교 뷰가 발표 뒤에 만든 값이나 다른 단위를 서프라이즈에 쓰지 않는다., 발표 전 예상 이력은 다시 받을 수 없다. 버전 저장이라 지울 반복도 없다., _row(), _stored(), SurpriseViewContractTest

### Community 407 - "SourceBudgetTest"
Cohesion: 0.19
Nodes (7): Macro 외부 연동과 원천 adapter의 infrastructure 계층., _indicator(), 소스별 벽시계 예산 — 느린 출처 하나가 수집 전체를 삼키지 못하게 한다. ECOS가 응답하지 않던 날, 요청당 30초 타임아웃에 재시도…, clock_steps를 monotonic 반환값으로 흘려보내며 3개 지표를 수집한다., 예산이 잡 캡(20분)보다 크면 상한을 둔 의미가 없다., _series(), SourceBudgetTest

### Community 408 - "EconSnapshotShapeTest"
Cohesion: 0.14
Nodes (11): 무엇을 살지 정하는 계층. 흐름은 한 방향이다: **근거 → 판단 → 포트폴리오 → 위험 → (실행 의도)**. 마지막 한 걸음만…, EconSnapshotShapeTest, AI 경제 근거는 macro owner가 실제로 주는 행 모양 위에서 조립된다. 전에는 이 검사가 손으로 지어낸 `record_kind` 행을…, owner의 계약에 있는 키만으로 행 하나를 만든다., 자체 모델은 컨센서스가 없을 때의 대체지 같은 무게의 근거가 아니다., EconSnapshotSizeTest, 경제 근거가 evidence bundle을 삼키지 않게 한다. 실측(2026-09-03): 번들 202,724자 중…, release 그룹에 이미 있는 값을 평면 키로 또 담으면 프롬프트만 커진다. (+3 more)

### Community 409 - "press_releases.py"
Cohesion: 0.23
Nodes (8): _decode_html(), press_release_document(), SEC archive에서 8-K 실적 보도자료와 요약 재무값을 읽는 어댑터., SEC 문서의 흔한 인코딩을 숫자 손실 없이 문자열로 바꾼다., SEC archive 목록에서 EX-99 보도자료를 선택해 HTML과 실제값을 반환한다., _selected_name(), PressReleaseAdapterTest, SEC archive 8-K 보도자료 어댑터의 네트워크 없는 계약 테스트.

### Community 410 - "40_macro.sql"
Cohesion: 0.45
Nodes (10): macro.economic_observations, macro.forecast_snapshots, macro.market_observations, macro.measure_value(), macro.measures, macro.raw_value(), macro.release_events, macro.release_schedule_versions (+2 more)

### Community 411 - "5. 색 시스템"
Cohesion: 0.20
Nodes (10): 5.1 브랜드 원색, 5.2 라이트 모드 중성 원색, 5.3 다크 모드 중성 원색, 5.4 금융 방향 원색, 5.5 접근성 보정 방향 토큰, 5.6 상태색과 방향색의 분리, 5.7 라이트·다크 시맨틱 매핑, 5.8 색 사용 금지 (+2 more)

### Community 412 - "test_segments_unmapped.py"
Cohesion: 0.43
Nodes (3): _fact(), 컬럼으로 매핑되지 않아 버려지는 세그먼트 concept을 보고하는지 검증한다. 매핑 실패 fact는 적재되지 않고 사라지는데, 무엇이 얼마나…, UnmappedConceptReporting

### Community 413 - "remap_runtime_securities.py"
Cohesion: 0.23
Nodes (12): apply_remap(), main(), plan_remap(), Connection, Path, Supabase 종목 ID가 다시 매겨진 뒤, 로컬 판단 원장의 옛 security_id를 새 ID로 옮긴다. python -m…, 옮길 (표, case_key, 옛 ID, 새 ID) 목록과 풀리지 않은 행. 원장은 읽기만 한다., _ticker_from_case_key() (+4 more)

### Community 414 - "normalize_positions"
Cohesion: 0.20
Nodes (10): Position, SEC 원본 한 행을 USD로 정규화한 DB 저장 단위. Combination Report의 중복 보유를 Python에서 먼저 합치면 sub-…, normalize_positions(), Position, 원본 행을 USD로 환산하되 SEC 행 단위로 보존한다., detect_value_scale(), _fallback_scale(), date (+2 more)

### Community 415 - "ResearchStoreReadPathTest"
Cohesion: 0.24
Nodes (6): Call, _offenders(), 읽기만 하는 경로는 research 저장소를 쓰기로 열지 않는다. DuckDB는 쓰기 연결에 배타 잠금을 건다. 읽으면서 쓰기로 열면 같은…, 호출이 없으면 아래 검사는 아무것도 보증하지 않는다., _read_only_kwarg(), ResearchStoreReadPathTest

### Community 416 - "WorkflowNameTest"
Cohesion: 0.33
Nodes (3): CLAUDE.md 관례 11 — name:이 파일명과 다르면 workflow_run이 발화하지 않는다., 이어 붙은 YAML은 파서가 뒤 키를 택해 앞쪽 결함을 조용히 숨길 수 있다., WorkflowNameTest

### Community 417 - "11. 라이트·다크 모드 운영"
Cohesion: 0.50
Nodes (4): 11.1 테마 선택, 11.2 동일하게 유지할 것, 11.3 테마마다 바꿀 것, 11. 라이트·다크 모드 운영

### Community 418 - "14. 보이스 앤 톤"
Cohesion: 0.50
Nodes (4): 14.1 기본 문체, 14.2 문장 순서, 14.3 데이터 확실성 문구, 14. 보이스 앤 톤

### Community 419 - "Actions Discord Notification Recovery — 구현 계획"
Cohesion: 0.22
Nodes (8): Actions Discord Notification Recovery — 구현 계획, File map, Task 1: Make CI execute the intended offline suite, Task 2: Give hosted notification jobs a durable initialized runtime ledger, Task 3: Preserve the parent CIK for SEC filing rows, Task 4: Quarantine one malformed Yahoo bar without accepting incomplete symbols, Task 5: Repair baseline offline-test isolation exposed by fixed CI, Task 6: Verify the full recovery and prepare operations follow-up

### Community 420 - "2. 핵심 헬퍼 모듈 사용법"
Cohesion: 0.22
Nodes (9): 0. 관련 문서 및 전체 위치, 1) Supabase 클라이언트 및 대량 페이징 (`db/postgres.py`), 1. 주요 모듈 맵 및 역할, 2) JSON 구조화 로깅 (`logging.py`), 2. 핵심 헬퍼 모듈 사용법, 3. 수정할 때 확인할 곳, 3) 재시도 데코레이터 (`retry.py`), 4) 토스 OAuth 캐시 및 락 (`src/investment_agent/execution/brokers/toss/auth.py`) (+1 more)

### Community 421 - "sqlite.py"
Cohesion: 0.20
Nodes (13): _apply_schema(), _columns(), _migrate_legacy_decision_tables(), _migrate_legacy_execution_tables(), Connection, RuntimeError, 로컬 실행 원장의 SQLite 연결 경계. 실제 주문·승인·알림 중복 방지는 네트워크 DB가 아니라 실행 컴퓨터의 단일 파일에 기록한다.…, 기존 주문을 새 원장으로 검증해 옮겨야 한다. (+5 more)

### Community 422 - "6. 타이포그래피"
Cohesion: 0.50
Nodes (4): 6.1 서체, 6.2 타입 스케일, 6.3 금융 숫자 표기, 6. 타이포그래피

### Community 423 - "8. 모양, 보더, 깊이"
Cohesion: 0.50
Nodes (4): 8.1 Radius, 8.2 보더, 8.3 그림자, 8. 모양, 보더, 깊이

### Community 424 - "backtest/metrics.py"
Cohesion: 0.23
Nodes (8): BacktestMetrics, calculate_metrics(), Any, 백테스트 NAV·체결 장부에서 성과와 위험을 계산한다., 초기 현금을 첫 기준점으로 포함해 일별 수익과 비용 지표를 계산한다., _sample_std(), BacktestMetricsTest, nav()

### Community 425 - "factors.py"
Cohesion: 0.20
Nodes (9): _factor_ranks(), feature_rows_by_ticker(), percentile_ranks(), rank_candidates(), 중장기 선별 factor 점수: 같은 시점 종목들 사이의 순위로 품질·건전성·성장·가치·기대·모멘텀을 잰다. ## 왜 순위(백분위)인가 ROE…, 값이 있는 종목만 0~1 백분위. 동률은 평균 순위. 한 종목뿐이면 가운데(0.5)., 품질 기준을 통과한 종목 중 종합 점수 순. 점수가 같으면 ticker 순으로 결정적으로 자른다., snapshot 저장 행들을 ticker → feature dict로. 같은 ticker가 여럿이면 마지막 행을 쓴다. (+1 more)

### Community 426 - "_row"
Cohesion: 0.24
Nodes (3): CompareTest, shadow 대조 로직(shadow_diff.compare) 단위 테스트. 외부 의존성 없음., _row()

### Community 428 - "Market — 일봉과 corporate action"
Cohesion: 0.50
Nodes (4): Market — 일봉과 corporate action, 보존 정책, 실행 흐름, 저장 계약

### Community 429 - "validate_series"
Cohesion: 0.16
Nodes (7): 지표별 수집 계약을 확인하고 명백한 단위·스파이크 오류를 차단한다. ``source_params.validation``은 원천값을 화면 단위로…, validate_series(), MacroEconBoundaryTest, MacroSqlContractTest, 매크로 단위 계약, 환율 교차검증 및 정합성/품질 안전장치를 검증한다., catalog seed는 이제 SQL이 아니라 코드가 소유한다(repository.py의 ``upsert_series`` 진입점이 정상…, SeriesContractTest

### Community 431 - ".test_every_workflow_installs_what_its_entry_point_imports"
Cohesion: 0.18
Nodes (8): _entry_modules(), _group_requirements(), pyproject의 dependency group을 include-group까지 펼친다., company 동기화는 8-K 보도자료와 Yahoo 발표 실적도 함께 처리한다., 진입점이 import하는 서드파티가 그 워크플로 dependency group에 다 있어야 한다. 파이프라인별 dependency…, 워크플로가 실제로 실행하는 `python -m investment_agent....` 진입점들., composite action과 인라인 uv 설치가 요청하는 의존성 그룹., _workflow_groups()

### Community 433 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 434 - "graphify reference: extra exports and benchmark"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 435 - "test_filing_xbrl_fallback.py"
Cohesion: 0.15
Nodes (9): SEC EDGAR와 FSDS 외부 데이터 어댑터., CompanyFacts 최신 반영 지연 시 filing XBRL 변환 회귀 테스트., XbrlParserContractTests, _companyfacts_row(), _filing(), CompanyFacts가 덮는 공시는 문서를 받지 않는다. CompanyFacts는 XBRL **차원을 버린다.** 그래서 어떤 공시가…, CompanyFacts에 없다 = 차원이 있었다 = 문서를 봐야 클래스를 안다., 클래스를 나중에 만든 기업의 과거 기간이 사라지면 안 된다. 전에는 클래스가 하나라도 보이면 CompanyFacts를 통째로 버렸고, 게다가… (+1 more)

### Community 436 - "QlibPITAdapter"
Cohesion: 0.23
Nodes (6): Any, DataFrame, QlibPITAdapter, QlibSegments, Qlib data vendor를 쓰지 않고 StaticDataLoader로 우리 snapshot만 전달한다., QlibAdapterTest

### Community 437 - "10_universe.sql"
Cohesion: 0.47
Nodes (3): universe.entities, universe.securities, universe.security_identifiers

### Community 438 - "_fact"
Cohesion: 0.24
Nodes (3): _fact(), ManifestTest, SemanticPolicyTest

### Community 439 - "LocalArtifactStore"
Cohesion: 0.24
Nodes (7): LocalArtifactStore, Any, Path, 같은 디렉터리에 임시 파일로 쓴 뒤 rename. 중간에 죽어도 반쪽 파일이 남지 않는다. 반쪽 파일이 남으면 지문이 맞지 않아 읽기가…, 작업 트리 밖의 디렉터리에 내용 주소로 쌓는다., canonical JSON으로 저장한다 — 같은 내용이 항상 같은 지문을 갖도록., _write_atomically()

### Community 440 - "_entrypoints"
Cohesion: 0.23
Nodes (8): _calls_start_cli(), CliEntrypointContractTest, _entrypoints(), Path, CLI 진입점은 전부 같은 준비 과정을 거친다. `configure_logging()`이 안 불리면 루트 로거에 처리기가 없고,…, `python -m ...`으로 실행되도록 만든 모듈 — `__main__` 블록이 그 표식이다., 수집 규칙이 어긋나면 이 파일의 모든 검사가 공허하게 통과한다., 이름만 바뀌고 로깅 설정이 빠지면 위 검사는 통과한 채 로그만 사라진다.

### Community 441 - "platform/artifacts.py"
Cohesion: 0.31
Nodes (8): _check_digest(), _check_namespace(), _parse_uri(), RuntimeError, 큰 산출물을 DB 밖에 두고, DB에는 주소와 지문만 남긴다. ## 왜 DB에서 뺐나 판단 근거 번들은 한 건에 수십 KB다. 그것을…, 저장물을 읽을 수 없거나 지문이 맞지 않는다., StorageError, 근거는 내용 주소로 쌓이고, 바뀌면 읽을 때 걸린다.

### Community 442 - "load_earnings_results"
Cohesion: 0.20
Nodes (10): load_earnings_results(), load_fiscal_calendar(), Any, 실적 속보 행을 자연키 기준으로 멱등 저장한다., 종목의 실제 회계력. 8-K를 올바른 회계분기에 붙이는 유일한 근거다. 달력 월로 분기를 매기면 1월 결산 유통사가 통째로 어긋난다 —…, 수집 게이트를 지난 종목만 CIK별 ticker 목록으로 묶는다. 같은 CIK에는 우선주·채권·자리표시 종목도 있다. 그 ticker로…, 역사 예상치 재구성에 필요한 실적 속보 회계키만 읽는다. 행은 수집 대상 보통주마다 하나다., tracked_tickers_by_cik() (+2 more)

### Community 443 - "NewsSocialPageTest"
Cohesion: 0.27
Nodes (5): _imports(), NewsSocialPageTest, Path, News/Social 화면의 경계. 화면은 reporting 계약만 읽는다., 이 페이지는 새 경로가 실제로 성립하는지 보이는 증거다.

### Community 444 - "PriceTargetTest"
Cohesion: 0.33
Nodes (3): PriceTargetTest, 발표를 보고 조정된 목표가 섞이면 같은 시점 비교가 깨진다., 컨센서스가 없어도 목표주가만으로 '주가'에 녹일 게 있다.

### Community 445 - "news_social.py"
Cohesion: 0.15
Nodes (9): _freshness_frame(), Any, DataFrame, News/Social 수집 상태 화면. ## 왜 intelligence.py가 아닌가 `app_pages/intelligence.py`는 이미…, _render_runs(), 저장소별 읽기 경계. 파일 이름이 "어디서 오는가"를 말한다. reporting이 존재하는 이유가 그 질문을 화면과 알림에서 감추는 것이다 —…, NewsProviderTests, 뉴스 provider의 정규화와 fail-closed 정책을 검증한다. (+1 more)

### Community 446 - ".from_row"
Cohesion: 0.33
Nodes (5): MacroDataError, Any, ValueError, ObservationRowTest, 모르는 정밀도를 기본값으로 삼키면 PIT 경계가 조용히 헐거워진다.

### Community 447 - "fetch_forum_threads"
Cohesion: 0.20
Nodes (8): fetch_forum_threads(), 스레드를 다시 찾을 때 쓰는 안정된 키. 제목 전체를 키로 쓰면 표시명이 바뀌는 순간 같은 대상의 이력이 조용히 갈라진다. 실제로 한글명을…, 포럼 채널의 스레드 매칭 키(`_thread_match_key`) -> 스레드 ID (활성 + 공개 보관). 포럼은 "종목 1개 = 스레드…, 생성 시각이 없을 때 쓰는 순서. snowflake는 시간순으로 커진다., (POST 대상 채널 ID, 새 스레드를 만들어야 하는가). 같은 스레드가 이미 있으면 그 안에 이어 붙인다. 없을 때만 만든다 —…, 같은 실행 안에서 두 번째 카드가 방금 만든 스레드를 다시 찾게 한다., _snowflake_order(), _thread_match_key()

### Community 448 - "자율 판단 계층 — 근거 수집부터 승격까지"
Cohesion: 0.25
Nodes (7): Rollout 상태, 이 계층이 쓰는 테이블, 자율 판단 계층 — 근거 수집부터 승격까지, 저장 경계, 학습 표본과 승격, 핵심 계약 흐름, 현재 구조

### Community 449 - "content_index"
Cohesion: 0.29
Nodes (4): content_index, entity_mentions, intelligence_freshness, ticker_mention_daily

### Community 450 - "discord_admin/guide.py"
Cohesion: 0.32
Nodes (7): Any, #시작하기·#서버-규칙에 붙는 안내문의 단일 기준(SSOT). 문구를 스크립트로 한 번 올리고 마는 대신 여기에 둔다 — 카드가 바뀌면…, #서버-규칙 — 참여 규칙과, 카드를 잘못 읽지 않기 위한 전제., #시작하기 — 여기가 무엇을 하는 곳이고, 어디를 열면 되고, 언제 오는가., rules(), _schedule_table(), welcome()

### Community 451 - "Path"
Cohesion: 0.16
Nodes (9): CodexSkillIndexTest, DocumentHygieneTest, Path, 문서에 개인 환경정보가 새지 않게 한다., 레퍼런스에 경위 서술과 실측 날짜를 남기지 않는다., Codex는 스킬을 자동 발견하지 않는다 — AGENTS.md가 전부 가리켜야 한다., 두 도구가 같은 규칙을 받아야 한다. 한쪽에만 스킬이 있으면 지침이 갈린다., CLAUDE.md 관례 2 — 각 저장소는 자신이 소유한 스키마만 직접 조회한다. (+1 more)

### Community 453 - "MarketArchitectureTest"
Cohesion: 0.26
Nodes (6): _imports(), MarketArchitectureTest, Path, _python_files(), market 계층 경계를 검증한다. universe의 test_architecture.py(최종 수정본)와 같은 패턴 — 이름이 실제로…, application은 infrastructure.sources와 domain만 안다. universe의 최종 리뷰에서 정착된 것과 같은…

### Community 454 - "actuals.py"
Cohesion: 0.12
Nodes (35): ActualConfigurationError, ActualDataError, ActualNotAvailableYetError, ActualProviderError, ActualsError, _canonical_period(), _contract(), _ecos() (+27 more)

### Community 456 - "institutional/db.py"
Cohesion: 0.53
Nodes (5): _all(), _identifier_map(), load_analysis_source(), 13F 알림이 읽는 institutional·universe 원천. 보낼지 말지는 알림 원장이 판단한다., v1 원천 표를 카드 분석 함수가 소비하는 형태로 조립한다.

### Community 457 - "InstitutionalSchemaContractTest"
Cohesion: 0.18
Nodes (5): InstitutionalSchemaContractTest, institutional v1 SQL이 §9의 세 표와 universe 매핑 경계를 지키는지 검증한다., manager(name/fund_name/is_active)는 SEC 사실이 아니라 우리가 고른 추적 대상이라 Supabase 표가 아니라…, SEC raw XML의 투표권·투자재량 상세는 더 이상 저장하지 않는다 — 사실 컬럼만 남기는 간소화다(파일 상단 주석 참고)., manager 사실(name/fund_name/is_active)과 화면 해석(strategy_group· signal_role 등)은…

### Community 458 - "저장 지도 — 무엇이 어디에 사는가"
Cohesion: 0.29
Nodes (7): Supabase Postgres — 원장, 고칠 때 함께 볼 곳, 넷을 가르는 기준, 로컬 DuckDB, 로컬 SQLite — 실행 원장, 소비자는 이 차이를 모른다, 저장 지도 — 무엇이 어디에 사는가

### Community 459 - "main"
Cohesion: 0.48
Nodes (6): _item(), main(), datetime, 알림 원장 SQL 함수가 `MemoryLedger`와 같은 규칙으로 동작하는지 실DB에서 확인한다. 단위 테스트는 DB를 때리지 않으므로 엔진…, 두 구현에 똑같이 태울 단계. 각 단계의 관찰값을 돌려준다., scenario()

### Community 460 - "releases/baseline.py"
Cohesion: 0.27
Nodes (11): _diffs(), drift_forecast(), _predict(), _quantile(), 자체 베이스라인 예상값 — 외부 의존 없는 순수 로직. 무료 컨센서스가 없는 지표(23종 중 22종)를 위한 최소한의 기준선이다. **이건…, 선형 보간 분위수. 표본이 작아 numpy를 끌어오지 않는다., 최근 points개 시점에서 그 방법을 실제로 걸어 봤을 때의 중앙 절대오차., 이 지표에 지금 맞는 방법('drift' 또는 'naive'). 증거가 뚜렷할 때만 추세를 좇는다(SELECT_MARGIN). 채점이 안… (+3 more)

### Community 461 - "EarningsCalendarStore"
Cohesion: 0.33
Nodes (4): _default_store(), EarningsCalendarStore, Any, 카드에 필요한 행만 읽는다. 보낼지 말지는 알림 원장이 판단한다.

### Community 462 - "test_segments_quality.py"
Cohesion: 0.13
Nodes (6): CompanyBaselineTest, DerivedQuartersCarryNoBalances, 회사별 세그먼트 형식 보존과 품질 판정 규칙을 검증한다., 파생 분기는 잔액(instant)을 들고 오지 않는다. Q4는 FY에서 Q1~Q3를 빼서 만든다. 그 차감은 유량에만 뜻이 있고 잔액에는…, SchemaContractTest, SegmentSnapshotReadTest

### Community 463 - "KindsWiringTest"
Cohesion: 0.29
Nodes (3): KindsWiringTest, `--kind`가 실제로 존재하는 러너를 가리키는지 검증한다. 배선이 어긋나면 import 에러가 아니라 실행 시점에야 드러난다 — 그때는…, 가짜 케이스를 반환하던 패키지가 되살아나면 지어낸 분석이 발송된다.

### Community 464 - "SharedSetupTest"
Cohesion: 0.18
Nodes (5): 준비 단계는 composite action 하나로 모은다. 공통 설정을 한 곳에서 검증해 모든 workflow가 같은 Python·secret…, 로그는 공개될 수 있다. 없는 것의 이름만 말하고 값은 절대 찍지 않는다., 옮기고 나서 목록에 남겨두면 그 목록이 거짓말을 시작한다., tests 패키지가 src 패키지를 가리는 300여 import 오류를 막는다., SharedSetupTest

### Community 465 - "EntrypointAttributeCallTest"
Cohesion: 0.36
Nodes (4): EntrypointAttributeCallTest, missing_class_attributes(), Path, 진입점이 import한 클래스에 없는 속성을 부르면 실행 시점에야 죽는다. 실주문 CLI가 존재하지 않는…

### Community 466 - "src/investment_agent/data/universe/__init__.py"
Cohesion: 0.06
Nodes (10): universe 수집·정합성 명령 패키지., 무엇을 다룰 것인가 — 회사·증권 identity와 지수 membership. 여기 없는 종목은 수집도 판단도 하지 않는다. 다른 모든…, KoreanNameRefreshTest, KoreanNameSelectionTest, Universe 핵심 갱신과 로컬 전용 한글명 보강의 경계 테스트., UniverseWorkflowBoundaryTest, EntitySchemaTest, EntitySelectionTest (+2 more)

### Community 467 - "_Builder"
Cohesion: 0.15
Nodes (3): _Supabase, _Builder, _Response

### Community 468 - "operations_view.py"
Cohesion: 0.40
Nodes (5): operations_links(), Discord-first 운영 로그 위치와 확인 순서를 안내한다., 설정된 운영 링크만 안전한 HTTPS URL로 반환한다., DB 조회 없이 운영 기록의 단일 확인 경로를 보여준다., render_operations_guide()

### Community 469 - "_submissions_document"
Cohesion: 0.25
Nodes (6): SEC submissions JSON -> 내부 공시 dict 매핑 계약. 여기서 어긋나면 예외가 아니라 **0건**으로 끝난다. 세그먼트…, SEC submissions 응답의 모양을 그대로 흉내 낸다(키 이름이 계약의 전부다)., 두 날짜가 뒤바뀌면 조회 창이 영원히 빗나가고 보존 삭제가 엉뚱한 행을 지운다., 보고기간이 아니라 제출일로 잘라야 '최근 N일에 들어온 공시'가 된다., _submissions_document(), SubmissionsMappingTest

### Community 470 - "Operations — Discord-first 운영 관측과 로컬 하네스"
Cohesion: 0.29
Nodes (7): DB 기준, Discord 채널과 환경변수, Operations — Discord-first 운영 관측과 로컬 하네스, 기록 경계, 로컬 하네스 안전 제어, 장애를 확인하는 순서, 핵심 구성

### Community 471 - "Reporting — 화면과 알림이 공유하는 읽기 모델"
Cohesion: 0.25
Nodes (7): readers — 어디서 오는가, Reporting — 화면과 알림이 공유하는 읽기 모델, 계산을 저장하지 않는 이유, 고칠 때 함께 볼 곳, 세 계층, 이력 뷰는 범위를 요구한다, 조용히 틀리는 것

### Community 472 - "download_monthly_close"
Cohesion: 0.22
Nodes (9): market read model을 전략 입력으로 변환한다., download_monthly_close(), _last_complete_month_end(), DataFrame, date, Timestamp, market owner가 적재한 일봉에서 전략용 월말 종가를 읽는다., 가장 최근에 끝난 달의 마지막 날 (KST 기준). (+1 more)

### Community 473 - "test_learning_stage_commands.py"
Cohesion: 0.24
Nodes (5): _context(), LearningStageCommandTest, 학습 원장 단계가 실행 가능한 명령 계약을 유지하는지 검증한다. 각 단계는 allowlist에 있는 모듈 하나를 호출하고, 문자열 인자 튜플과…, `--as-of`는 context.now여야 한다 — 벽시계를 쓰면 재시도가 다른 날을 본다., RecordingRunner

### Community 474 - "CandidateFeatureReadTest"
Cohesion: 0.25
Nodes (4): CandidateFeatureReadTest, _feature_rows(), 후보 선정은 feature 창을 한 번만 읽는다. 전에는 tracked 종목마다 `features_for_ticker`를 불렀다 — 실측으로…, 시점 근거다 — cutoff 뒤에 들어온 값이 섞이면 미래를 보게 된다.

### Community 475 - "test_channel_names_are_declared.py"
Cohesion: 0.36
Nodes (5): _declared_names(), MentionedChannelsExistTest, _mentions(), 문서와 코드가 부르는 Discord 채널 이름은 선언에 실재해야 한다. 채널 구조는 `discord_admin/manifest.py`가…, 대상을 못 찾으면 이 테스트는 공허하게 통과한다.

### Community 476 - "main"
Cohesion: 0.33
Nodes (5): main(), build(), Any, Server Guide(온보딩)의 단일 기준(SSOT). 처음 들어온 사람이 보는 화면이다. 채널 16개를 한꺼번에 보여 주면 어디부터 열어야…, 채널·역할 key -> ID 표를 받아 Discord가 받는 온보딩 payload를 만든다. 서버에 없는 key는 조용히 빠진다 —…

### Community 478 - "60_notifications.sql"
Cohesion: 0.31
Nodes (5): notifications.deliveries, notifications.notices, notifications.reserve(), notifications.threads, notifications.topics

### Community 479 - "load_prices"
Cohesion: 0.33
Nodes (6): load_market_prices_since(), v1 market 봉을 현재 ticker 표기로 투영해 끝까지 읽는다., load_prices(), DataFrame, date, 최근 rolling_days 거래일 분량의 prices_daily(전 종목) → DataFrame. 반환 컬럼: ticker ·…

### Community 480 - "freshness_for"
Cohesion: 0.25
Nodes (7): freshness_for(), kst_today(), date, 매크로 관측값의 기준일과 지연 상태를 일관되게 계산한다., 실행 위치와 관계없이 한국 시간의 오늘을 반환한다., 관측 기준일의 나이와 UI/알림용 freshness 상태를 반환한다. 일간 시세와 감시 지표의 지연 상태에 사용한다., MacroFreshnessTest

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

### Community 486 - "build_membership_snapshots"
Cohesion: 0.16
Nodes (8): build_membership_snapshots(), build_reconcile_rows(), DataFrame, 현재 명단에서 변경 이력을 역재생해 날짜별 S&P 500 명단을 복원한다. 가장 오래된 변경일 이전은 알 수 없으므로 행을 만들지 않는다.…, 현재 멤버 표 + 편입/탈락 기록 → 저장용 목록을 생성한다. 반환: current_rows : 현재 S&P 500 종목 (~503개,…, MembershipHistoryTransformTest, MembershipReconcileTest, 멤버십이 그대로여도 게이트가 그대로라는 뜻은 아니다. 상류의 거래소 master 동기화가 게이트를 통째로 껐고, 이 경로가 조기 반환하는…

### Community 488 - "ExecutionPackageLayoutTest"
Cohesion: 0.20
Nodes (6): ExecutionPackageLayoutTest, _imports(), Path, execution의 폴더가 주문 lifecycle 순서를 그대로 말하게 한다. 승인 → 주문 → broker → 재조정 (그 옆에서)…, 루트에 모듈이 늘어나면 다시 "어디에 둘지 모르겠으면 여기" 가 된다., 게이트가 감시 대상을 import하면 그 대상 없이는 게이트를 켤 수 없다. `risk_snapshot`이 여기 있다가 걸렸다 — 그것은…

### Community 489 - "test_table_query_contracts.py"
Cohesion: 0.43
Nodes (4): declared_columns(), query_issues(), 정적으로 해석 가능한 조회를 스키마 합집합이 아닌 개별 테이블과 대조한다., TableQueryContractsTest

### Community 490 - "test_repo_conventions.py"
Cohesion: 0.20
Nodes (11): _has_main_guard(), _imported_modules(), JsonLoggingTest, Module, CLAUDE.md 핵심 관례를 기계로 강제한다. 문서에만 적힌 규칙은 지켜지는지 아무도 모르는 채로 드리프트한다. 여기 있는 것은 사람의 판단…, 모듈이 가져오는 절대 모듈 경로. 상대 import는 파일 위치로 풀어서 돌려준다. 상대 import를 그대로 두면 `from…, `if __name__ == "__main__":` 블록이 있으면 CLI로 직접 실행되는 모듈이다., 관례 3 — 라이브러리 코드는 `print()` 대신 JSON 로거를 쓴다. 사람이 눈으로 읽으라고 있는 CLI 출력만 예외다. 그 판정은… (+3 more)

### Community 491 - "PackagingContractTest"
Cohesion: 0.22
Nodes (3): PackagingContractTest, v1 Python packaging 계약 회귀 테스트., `__main__` 블록이 없는 진입점도 진입점이다. Streamlit 앱은 파일을 스크립트로 그냥 실행하므로 `if __name__ ==…

### Community 492 - "_payload_key_sets"
Cohesion: 0.31
Nodes (7): _conflict_columns(), ConflictColumnsAreSentTest, _payload_key_sets(), Module, upsert가 `on_conflict`로 부르는 컬럼은 payload에 있어야 한다. `earnings_results` 저장은 행에서 허용…, `*_keys = {...}` 꼴의 문자열 집합 상수., 대상을 못 찾으면 이 테스트는 공허하게 통과한다.

### Community 493 - "test_edgar_parser.py"
Cohesion: 0.18
Nodes (4): ExhibitExtractorTest, ItemClassifierTest, PressReleaseArchiveAdapterTest, 내재화한 SEC 8-K 파서의 표·EX-99·Item 계약을 네트워크 없이 검증한다.

### Community 495 - "Intelligence — 뉴스·소셜 텍스트를 종목 언급으로"
Cohesion: 0.29
Nodes (7): Intelligence — 뉴스·소셜 텍스트를 종목 언급으로, 고칠 때 함께 볼 곳, 구조, 보존은 90일, 기준은 발행 시각, 실행, 저장 계약, 조용히 틀리는 것

### Community 496 - "test_fundamentals_consensus.py"
Cohesion: 0.25
Nodes (3): PriceTrackTest, 공시 직전 컨센서스 선택·조립 회귀 테스트. 여기서 지키는 건 전부 "틀려도 카드는 그려지고 숫자만 거짓이 되는" 규칙이다., 목표가 52주 축 밖이면 끝에 눌려 '어디로 본다'가 안 읽힌다.

### Community 498 - "LiveExecutionRepository"
Cohesion: 0.05
Nodes (23): _order_attempt(), PostgREST numeric 직렬화 차이(``5``/``5.0``)를 충돌로 오인하지 않는다., _same_planned_value(), make_attempt_id(), OrderAttempt, OrderAttemptReservation, payload_digest(), Any (+15 more)

### Community 500 - "V1ResetContractTest"
Cohesion: 0.33
Nodes (3): 빈 DB 재구축 도구가 구 스키마에 기대지 않는지 확인한다., trading·execution은 둘 다 로컬 runtime.sqlite3 소유라 물리적으로 같은 파일에 있지만, execution이…, V1ResetContractTest

### Community 503 - "HarnessModuleAllowlistTest"
Cohesion: 0.40
Nodes (3): HarnessModuleAllowlistTest, 등록만 하고 allowlist에 안 넣으면 런타임에서야 드러난다., allowlist에 실행할 수 없는 이름이 들어가면 그 단계는 런타임에야 죽는다. `python -m X`가 성립하는 경우는 둘이다 — 모듈이…

### Community 504 - "detect_earnings_events.py"
Cohesion: 0.07
Nodes (34): detect_earnings_events(), detect_earnings_events_for_ticker(), determine_fiscal_period(), _parse_release_html(), Any, date, 8-K Item 2.02를 감지해 실적 속보를 만든다., 구조화 결과가 없는 보도자료 HTML에서 누락 필드를 보완한다. (+26 more)

### Community 506 - "test_forum_kinds_are_wired.py"
Cohesion: 0.33
Nodes (6): _forum_topics(), ForumTopicsBuildAThreadTest, _packages(), 포럼으로 선언된 목적지에 보내는 topic은 스레드를 함께 그려야 한다. Discord 포럼 채널은…, 패키지 -> {선언한 topic 이름: 패키지 안에서 ForumThread를 만드는가}., 대상을 못 고르면 위 테스트는 공허하게 통과한다.

### Community 508 - "awaiting_message"
Cohesion: 0.24
Nodes (6): awaiting_data(), awaiting_message(), 비어 있는 화면에 붙일 안내 문구를 만든다. 빈 화면만으로는 "코드가 죽었다"와 "아직 안 쌓였다"를 구분할 수 없다. 무엇이 없는지와 언제…, `awaiting_message`를 화면에 표시한다., AwaitingMessageTest, 빈 화면이 고장인지 데이터가 없는 건지 구분되게 한다. 지금까지는 그냥 비어 있어서, 코드가 죽은 것(호출자 0)과 아직 안 쌓인 것을 화면만…

### Community 509 - "_SegmentRepository"
Cohesion: 0.18
Nodes (4): 최신 SEC 벌크 파일에 아직 공시가 반영되지 않은 상태를 재현한다., 최신 분기 벌크 파일의 지연은 실시간 수집이 보충하므로 장애가 아니다., _SegmentRepository, _SegmentSource

### Community 510 - "anon_client"
Cohesion: 0.67
Nodes (3): Client, anon_client(), 공개 읽기용 anon client를 실제 첫 호출 시 한 번 만든다.

### Community 511 - "test_factor_research.py"
Cohesion: 0.31
Nodes (6): ForwardWindowTest, GroupSnapshotsTest, date, factor IC 연구: 순위 상관·기간 날짜·겹침 보정·가중치 제안·세대 분리., ResearchTest, _weekdays()

### Community 512 - "Research — PIT feature·dataset·모델·평가·승격"
Cohesion: 0.29
Nodes (6): Research — PIT feature·dataset·모델·평가·승격, 고칠 때 함께 볼 곳, 실행, 저장 계약, 조용히 틀리는 것, 흐름

### Community 513 - "StrategyWorkflowOrderingTest"
Cohesion: 0.29
Nodes (3): notify_strategy 워크플로의 단계 순서·산출물 계약을 검증한다., channel routing은 이제 DB가 아니라 각 워크플로의 env가 SSOT다 — validate_subscriptions는 그 env가…, StrategyWorkflowOrderingTest

### Community 514 - "src/investment_agent/operations/commands/__init__.py"
Cohesion: 0.18
Nodes (5): 운영 점검과 하네스 실행 명령 패키지., LongHorizonCadenceTest, 중장기 보유 전략의 실행 주기: 분석·System 목표 갱신이 분 단위 매매 주기로 되돌아가지 않는다., 공통 Actions 실패 리포터가 원문을 안전한 사건 카드로 바꾸는지 검증한다., WorkflowFailureReporterTest

### Community 515 - "pending_filings"
Cohesion: 0.36
Nodes (5): pending_filings(), 완료 장부에 없는 XBRL 공시만 반환한다. A ticker with no stored fundamentals is seeded from…, _filing(), PendingFilingsTest, Fundamentals 일간 워터마크가 같은 날의 추가 공시를 놓치지 않는지 검증한다.

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

### Community 522 - ".filings"
Cohesion: 0.24
Nodes (5): date, 정정 규칙을 적용한 뒤 남는 신고들. 보유를 셀 때는 반드시 이것을 쓴다., 그 분기 포트폴리오 비중(CUSIP 기준). `effective_filings`를 거치므로 정정이 이중 계산되지 않는다., 보존 기간 밖 신고를 지우고 FK cascade로 원천 행도 함께 정리한다., 신고 목록. `known_at`을 주면 그날까지 **제출된** 것만 준다. 분기말이 아니라 제출일로 자르는 것이 핵심이다 — 13F는 45일…

### Community 523 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 524 - "social_normalize.py"
Cohesion: 0.36
Nodes (9): author_hash(), _posted_at(), Any, datetime, Reddit 응답을 저장 레코드로 바꾼다. ## 작성자는 해시로만 남긴다 필요한 것은 "같은 사람이 반복 게시하나"뿐이고 그것은 해시로 된다.…, 작성자 식별용 해시. 지워진 계정은 비운다., 게시물 한 건을 저장 레코드로 바꾼다. 식별할 수 없으면 `None`., _sha() (+1 more)

### Community 525 - "Institutional — SEC 13F 원천·유효 포트폴리오"
Cohesion: 0.40
Nodes (5): Institutional — SEC 13F 원천·유효 포트폴리오, 거장을 한 명 늘리려면, 구조, 실행, 정확성 규칙

### Community 526 - "audit_fx_cross_sources"
Cohesion: 0.20
Nodes (9): audit_fx_cross_sources(), _comparison(), date, Series, 매크로 원천 시계열의 단위·범위와 환율 교차검증을 담당한다., BOK 환율을 독립적인 연준/FRED 관측치와 교차검증한다. ECOS를 주 원천으로 유지한다. FRED의 DEXKOUS(원/달러)와…, FxCrossSourceTest, date (+1 more)

### Community 527 - "DangerFloorTest"
Cohesion: 0.47
Nodes (3): DangerFloorTest, CLAUDE.md와 AGENTS.md의 안전 바닥이 어긋나지 않는지 본다. 두 문서에 같은 블록을 두는 것은 SSOT 원칙의 예외다. 그럴…, 길어지면 아무도 안 읽는다. 늘리고 싶으면 스킬이나 CLAUDE.md 본문으로.

### Community 528 - "test_econ_calendar.py"
Cohesion: 0.26
Nodes (5): datetime, 경제 발표 알림 — 발표 하나가 묶음 전송과 반복 실행을 거쳐도 사람에게 한 번 닿는다., ReleaseNoticeTest, ReleasePublishTest, _row()

### Community 529 - "GuruNotificationTest"
Cohesion: 0.44
Nodes (3): _filing(), GuruNotificationTest, 거장 13F 알림 — 제출은 사람 스레드에 한 번, 분기 요약은 한 장을 고쳐 가며 닿는다.

### Community 530 - "ReleaseWatchTest"
Cohesion: 0.10
Nodes (7): Macro application orchestration boundary., Macro domain의 실행 가능한 명령 진입점., HistoricalForecastTest, ALFRED forecast reconstruction이 measure/PIT 계약을 지키는지 검사한다., ECON release-time watcher의 due/filter/pending/idempotency 계약., _release(), ReleaseWatchTest

### Community 531 - "transient_retry"
Cohesion: 0.24
Nodes (8): fetch_batch(), _fetch_one(), date, Series, 연결 오류 + 429/5xx + Postgres 일시 오류를 재시도. 외부 API 읽기의 기본값., transient_retry(), tenacity가 감싸면 부르는 쪽의 except 절이 안 잡힌다., TransientRetryTest

### Community 532 - "migrate_local_storage.py"
Cohesion: 0.16
Nodes (27): copy_duckdb_snapshot(), copy_sqlite_snapshot(), _duckdb_snapshot(), LocalStorageConflict, main(), MigrationPlan, _plan_dict(), plan_migrations() (+19 more)

### Community 534 - "HarnessReporter"
Cohesion: 0.12
Nodes (12): HarnessReporter, NoopOpsAlert, OpsAlertAdapter, Any, Protocol, 구조화 로그와 Discord 운영 webhook 사이의 좁은 adapter., Any, 민감한 key의 값은 타입과 무관하게 고정 문자열로 바꾼다. (+4 more)

### Community 535 - "TechIndicatorAtomicUpsertTests"
Cohesion: 0.27
Nodes (3): _frame(), DataFrame, TechIndicatorAtomicUpsertTests

### Community 536 - "_domain_precisions"
Cohesion: 0.33
Nodes (6): _declared_precisions(), _domain_precisions(), 일정 정확도의 목록은 도메인과 저장소가 같아야 한다. `domain/releases/schedule.py`의…, 반대 방향도 본다 — 쓰지 않는 값을 받아 두면 오타가 그대로 저장된다., 대상을 못 찾으면 위 두 검사는 공허하게 통과한다., SchedulePrecisionContractTest

### Community 537 - "_series"
Cohesion: 0.33
Nodes (4): 관측마다 등급 표식을 심어 둔 지표 한 줄. 등급 판정은 표식을 그대로 돌려준다., 관측일 하나로 원장을 치면 늦게 들어온 다른 지표의 새 경보가 버려진다., _series(), WatchPublishTest

### Community 540 - "RetentionTest"
Cohesion: 0.21
Nodes (7): _article(), _post(), 90일 보존 경계. 기준 시각은 수집 시각이 아니라 발행 시각이다., 오래된 글을 오늘 수집해도 오래된 글이다., source_id만으로 지우면 보존 기간 안의 mention이 함께 사라진다. news와 social의 id 문자열 공간은 서로…, 뉴스와 소셜이 한 색인을 쓰므로, 정리 조회를 종류로 좁히지 않으면 뉴스 차례에 소셜 행까지 지운다 — 개수는 0으로 보고되면서., RetentionTest

### Community 541 - "test_workflow_storage_paths.py"
Cohesion: 0.22
Nodes (7): _job_env(), 워크플로가 주고받는 로컬 저장소 경로는 `storage_paths`와 같아야 한다. 로컬 저장소(DuckDB·Parquet)는 Actions…, job에 선언된 env. 여러 단계가 같은 자리를 보게 하는 정상적인 방법이다., 옛 자리를 가리키는 줄이 하나라도 남으면 그 워크플로가 조용히 빈손이 된다., 대상을 못 찾으면 위 검사는 공허하게 통과한다., _resolved_research_paths(), WorkflowArtifactPathsFollowStorageTest

### Community 544 - "state_versions.py"
Cohesion: 0.39
Nodes (8): _as_datetime(), _normalized(), plan_versions(), datetime, 상태가 바뀔 때만 새 버전을 남기는 판정. 예상치·발표 일정·애널리스트 커버리지가 쓴다. 같은 논리 키(종목·대상 기간·원천 등)의 **직전…, 새로 넣을 버전과 last_seen_at만 옮길 기존 버전을 가른다., same_state(), VersionPlan

### Community 547 - ".from_row"
Cohesion: 0.31
Nodes (5): HoldingsError, Any, ValueError, FilingRowTest, 13F는 분기말 뒤에 낸다. 뒤집혀 있으면 그 행은 미래를 보고한 것이다.

### Community 548 - "strategies/catalog.py"
Cohesion: 0.22
Nodes (6): 공용 카탈로그(`investment_agent.research.strategies.catalog`)에서 파생한 알림용 전략 라벨 모음., ensure_registered_strategies(), 계산기와 알림이 공유하는 전략 메타데이터., Fail fast when compute registration and metadata drift apart., StrategyMeta, 전략 계산용 상수 모음 (매매 대상 종목·계산 기간).

### Community 550 - "test_dashboard_readonly.py"
Cohesion: 0.22
Nodes (4): TradingAgents 실시간 웹 대시보드 패키지., CalculationsFacadeTest, 화면이 계산 facade에서 가져오는 공개 이름과 일정 계약을 검증한다. 페이지 모듈은 import만으로 Streamlit·DB를 초기화할 수…, 대시보드 데이터 계층의 읽기 전용 경계를 오프라인으로 검증한다.

### Community 553 - "ReportingPackageLayoutTest"
Cohesion: 0.24
Nodes (5): _opens_a_store(), Path, Reporting의 배치를 못박는다. reporting이 존재하는 이유는 "이 값이 어느 저장소에서 오는가"를 화면과 알림에서 감추는 것이다.…, 저장소를 여는 자리가 늘어나면 reporting이 감추는 것이 없어진다., ReportingPackageLayoutTest

### Community 554 - "releases/test_db.py"
Cohesion: 0.08
Nodes (8): AlfredParserTest, IdentityTest, IngestTest, ECON 자연키·원자료 단일 저장·시간 보존 경계의 오프라인 테스트., 짧은 감사 구간에 개정이 없다는 것은 외부 원천 장애가 아니다., API 키·URL은 숨기되, 데이터 계약 오류는 Actions에서 진단할 수 있어야 한다., ALFRED가 빈 vintage 구간을 400으로 표현해도 개정 없음으로 처리한다., WriterTest

### Community 556 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 558 - "graphify reference: commit hook and native CLAUDE.md integration"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 560 - "graphify reference: incremental update and cluster-only"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 562 - "Macro — 시장 상태 관측과 경제발표"
Cohesion: 0.29
Nodes (7): Macro — 시장 상태 관측과 경제발표, 구조, 보존 정책, 비교는 measure 단위로만, 실행, 저장 계약, 조용히 틀리는 것

### Community 564 - "NotificationGuardsTest"
Cohesion: 0.43
Nodes (3): assert_boundary(), NotificationGuardsTest, 알림의 도메인/DB/HTTP 경계. 위반 주입도 함께 실행한다.

### Community 568 - "yahoo.py"
Cohesion: 0.07
Nodes (31): is_split_ratio(), normalize_split_adjusted_prices(), 주식분할 이벤트와 가격 보정을 정규화하는 공용 함수., 0보다 크고 1이 아닌 유효한 주식분할 비율인지 반환한다., 전체 재다운로드 가격이 액션일에서 다시 분할 점프하지 않는지 검증한다., Adj Close가 OHLC와 같은 잘못된 basis인지 연속성으로 판정한다., Normalize Yahoo's occasionally mixed pre/post-split price basis., _scale_adjusted_close_with_price() (+23 more)

### Community 569 - "IntelligenceJobTest"
Cohesion: 0.28
Nodes (4): _context(), IntelligenceJobTest, 하네스 Intelligence 잡. 한 단계 실패가 나머지를 멈추지 않는다., 정리는 뒷정리다. 실패해도 그날 수집 결과를 되돌리지 않는다.

### Community 570 - "ECON 데이터 출처 계약 — 고정 30개 지표"
Cohesion: 0.50
Nodes (3): ECON 데이터 출처 계약 — 고정 30개 지표, Survey와 실시간·PIT 제공 범위, 제공처 참고 문서

### Community 572 - "UniverseSnapshot"
Cohesion: 0.36
Nodes (4): 해당 날짜부터 신규·추가 매수가 허용된 point-in-time 종목 집합이다., UniverseSnapshot, BacktestContractsTest, bar()

### Community 573 - "datetime"
Cohesion: 0.22
Nodes (4): datetime, 기록 시각이 창 안인 종목 의견 전부(만료 여부와 무관). System 논지는 만료가 아니라 판단 시점으로 유효를 가른다., 판단 시점 직전의 완료된 판단 하나. 결과 평가 여부와 무관하다(시점 이전 사실만 읽는다)., 회차를 닫는다. 상태와 사유의 짝이 맞지 않으면 여기서 막는다. 저장소도 같은 것을 CHECK로 막지만, 거기서 걸리면 배치 전체가 죽는다.

### Community 574 - "Local mirror — Supabase 원본 창고의 로컬 계산용 사본"
Cohesion: 0.40
Nodes (4): Local mirror — Supabase 원본 창고의 로컬 계산용 사본, 규칙, 사본에 담는 것, 실행

### Community 575 - "test_managers.py"
Cohesion: 0.22
Nodes (3): BlindSpotCaveatTest, RadarCodeContractTest, 7인 레이더 코드 계약 + manager_groups 스냅샷 + active 수집 기준 테스트. 외부 의존성 없음(DB/네트워크 미접근).…

### Community 576 - "redact"
Cohesion: 0.32
Nodes (4): LogRecord, 알려진 비밀값 모양을 가린다. 값의 길이도 남기지 않는다., redact(), RedactTest

### Community 577 - "Q: Audit trading decision learning approval and performance flow"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: Audit trading decision learning approval and performance flow, Source Nodes

### Community 578 - "breadth_200dma"
Cohesion: 0.29
Nodes (7): breadth_200dma(), fetch_batch(), Any, date, Series, market 스키마 입력을 사용하는 MACRO series를 수집한다., S&P 500 현재 구성종목 중 200일선 위에 있는 비율을 반환한다. RPC가 실패해도 같은 가격 테이블을 REST로 계산한다. 두 경로…

### Community 579 - "CandidateCoverageRepositoryTest"
Cohesion: 0.25
Nodes (5): CandidateCoverageRepositoryTest, 후보 coverage는 로컬 runtime 판단 원장에서 읽는다. 전에는 Postgres `trading.security_decisions`를…, 판단 원장은 security_id를 저장한다. 조회기 없이 부르면 실제 reader는 매번 실패한다., 실패한 판단을 coverage로 세면 그 종목이 다시 분석되지 않는다., as_of 이후의 판단이 보이면 그 시점 재현이 아니다.

### Community 580 - "KillSwitches"
Cohesion: 0.32
Nodes (4): KillSwitches, 전역 거래·job별 kill switch 해석., 알 수 없는 값은 안전하게 ON으로 해석한다., _switch()

### Community 581 - "BoundaryTest"
Cohesion: 0.22
Nodes (6): BoundaryTest, Path, System과 ALPHA는 실계좌·승인·주문 코드도, 연구 후보(ML challenger·RL) 코드도 import하지 않는다., 검사 대상이 사라지면 아래 검사는 공허하게 통과한다., RL은 Research다. 운영 경로(trading·execution·operations)가 RL 정책을 읽어 비중을 바꾸지 않는다., optimizer와 RiskGate 판정은 System 목표 생성 한 곳에서만 부른다 — 두 번째 비중 결정자가 없다.

### Community 583 - "IcSummary"
Cohesion: 0.43
Nodes (5): IcSummary, Any, 평균 IC가 양수이고 겹침 보정 t가 기준 이상인 category만 IC 비례 가중치. 없으면 동일가중 유지., suggest_category_weights(), SummaryTest

### Community 585 - "RegistryInjectionTest"
Cohesion: 0.27
Nodes (5): 가짜 adapters로 한 tick 돌리고, 실제로 불린 adapter 이름을 돌려준다., 하나라도 안 불리면 그 자리에 진짜 provider가 들어와 있다는 뜻이다., 아무것도 안 불리는 tick이면 위 검사는 공허하게 통과한다., System Portfolio는 승인 흐름 밖에서 돈다 — 분석 전용 모드에서도 불려야 한다., RegistryInjectionTest

### Community 586 - "test_strategy_progress.py"
Cohesion: 0.33
Nodes (4): 월간 전략 알림 — 적용월마다 요약 한 장과 전략별 카드가 한 번씩 닿는다., 한 달의 실패가 다음 달을 막거나 같은 실행에서 무한히 다시 돌지 않는다., _row(), StrategyNotificationTest

### Community 592 - "DuckDBOpenRetryTest"
Cohesion: 0.13
Nodes (6): DuckDBOpenRetryTest, DuckDBStoreTest, 로컬 DuckDB 파일을 여는 공통 경계의 계약., intelligence 본문은 이제 Parquet가 소유하고 DuckDB는 작은 catalog/index metadata만 갖는다 —…, 읽기 전용 연결이 파일을 만들면, 화면이 빈 DB를 만들어 놓고 수집 잡의 쓰기 잠금을 빼앗는다., 다른 프로세스가 파일을 잡고 있으면 즉시 죽지 않고 제한 시간 동안 기다린다.

### Community 601 - "estimate_statistics"
Cohesion: 0.33
Nodes (3): estimate_statistics(), 컨센서스 최신값과 관측 스냅샷 변화만 계산한다., FactorFeatureTest

### Community 603 - "collect_integrity_facts"
Cohesion: 0.33
Nodes (6): _as_date(), collect_integrity_facts(), _db_columns(), date, PostgREST가 노출하는 canonical financials 컬럼 집합. 한 행만 읽어 키를 본다. information_schema는…, 판정에 필요한 숫자만 모은다. 등급 매기기는 use case가 한다.

### Community 608 - "test_model_pool_providers.py"
Cohesion: 0.12
Nodes (8): AzureCandidateTest, GroqCandidateTest, PoolCapacityTest, 풀에 있는 후보가 실제로 호출 가능하고, 실제 프롬프트 크기를 견디는지 못박는다. 실측 2026-09-03 (도구 호출 2턴 + 실제…, 카탈로그에만 있는 이름을 넣으면 매번 404를 맞고 후보 하나를 낭비한다., 무료 TPM 8,000은 종목 하나의 프롬프트도 못 받는다 — 넣으면 매번 413이다., 왜 뺐는지 숫자로 남긴다 — 나중에 '한번 더 넣어보자'를 막는다., 단일화 결정(2026-09-03): 후보가 하나면 어느 키로 불렀는지가 항상 분명하다.

### Community 610 - "change_manifest.py"
Cohesion: 0.53
Nodes (5): earliest_change_since(), manifest_path(), Path, Market 수집 변경 manifest. 가격 fact에 local ingestion timestamp를 중복 저장하지 않는다. feature…, record_change_dates()

### Community 628 - "membership_snapshots"
Cohesion: 0.33
Nodes (5): membership_snapshots(), Any, date, S&P 500 멤버십 구간 행을 시점별 스냅샷으로 펼치는 순수 규칙. Supabase 조회(`universe.persistence`)와 로컬…, 구간 행(`security_id`·`ticker`·`valid_from`·`valid_to`)을 시작일과 변경일마다의 스냅샷으로 만든다.

### Community 636 - "supabase/__init__.py"
Cohesion: 0.14
Nodes (7): fundamentals 스키마용 Supabase 저장소 모음., Fundamentals 품질 이슈 기록의 실패 전파 계약., CompanyFinancialsUpsertTest, 기업 전체 재무가 공시 버전(financial_versions)으로 적재되는지 검증한다., 충돌 키에 공시와 매핑 버전이 있어야 정정 공시가 원본 수치를 지우지 않는다., 예상치 상태 저장이 돌려주는 수는 관측한 상태 수다., WriteVersionsCountTest

### Community 637 - "30_fundamentals.sql"
Cohesion: 0.31
Nodes (11): fundamentals.analyst_consensus_snapshots, fundamentals.earnings_results, fundamentals.filing_processing, fundamentals.filings, fundamentals.financial_versions, fundamentals.financials, fundamentals.segment_metrics, fundamentals.share_class_snapshots (+3 more)

### Community 638 - "spearman"
Cohesion: 0.47
Nodes (3): 두 값 사전의 공통 종목 순위 상관. 종목이 모자라거나 한쪽이 전부 같으면 None., spearman(), SpearmanTest

### Community 664 - "KillSwitchTest"
Cohesion: 0.40
Nodes (3): KillSwitchTest, Path, 킬 스위치는 워크플로 레벨 게이트다 — Python 코드 안에서 검사하지 않는다.

### Community 670 - "RunnerImageTest"
Cohesion: 0.40
Nodes (3): 러너 라벨은 `ubuntu-latest` 하나로 둔다. 버전을 박으면 그 이미지가 만료된다. ubuntu-22.04가 그랬다 —…, 옮기고 나서 목록에 남겨두면 그 목록이 거짓말을 시작한다., RunnerImageTest

## Knowledge Gaps
- **603 isolated node(s):** `content_files`, `content_catalog_state`, `feature_sets`, `dataset_runs`, `notifications.threads` (+598 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 5923 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **96 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_logger()` connect `logging.py` to `web.py`, `ml_challengers.py`, `SupabaseRepository`, `live_worker.py`, `macro/core.py`, `serialization.py`, `application/backfill_history.py`, `companyfacts.py`, `social_normalize.py`, `watch_earnings.py`, `investment_harness.py`, `PortfolioRiskPolicy`, `HarnessReporter`, `src/investment_agent/data/fundamentals/application/__init__.py`, `universe/persistence.py`, `reserve_provider_call`, `readers/intelligence.py`, `continuous_retrain.py`, `reconcile_toss.py`, `select_all_paged`, `incidents.py`, `ablation.py`, `company_financials.py`, `event_intelligence.py`, `yahoo.py`, `application/refresh_expectations.py`, `local_mirror/sync.py`, `ml_serving.py`, `export_dataset.py`, `toss/client.py`, `factor_research.py`, `tradingagents_adapter.py`, `features/db.py`, `parse_shares.py`, `read_runtime_rows`, `backtest/cli.py`, `build_training_samples.py`, `intelligence/repository.py`, `load_config`, `target.py`, `budget.py`, `sec_entities.py`, `infrastructure/sources/yfinance.py`, `auth.py`, `build_features.py`, `fsds.py`, `strategies.py`, `collection.py`, `main`, `Config`, `strategies/etl.py`, `supabase/segment_metrics.py`, `ExecutionSafetyError`, `ensure_aware`, `create_execution_intent.py`, `us_market_today`, `event_reanalysis.py`, `decision/analysis.py`, `alfred.py`, `application/etl.py`, `openfigi.py`, `process_filing.py`, `refresh_earnings_season.py`, `retry.py`, `fundamentals_pending.py`, `parse_datetime`, `build_decision_experiences.py`, `map_fiscal_periods.py`, `Database`, `sec13f.py`, `discord_admin/client.py`, `market_backfill.py`, `harness_adapters.py`, `counters.py`, `news_normalize.py`, `safe_fetch`, `remap_runtime_securities.py`, `actuals.py`, `detect_earnings_events.py`?**
  _High betweenness centrality (0.159) - this node is a cross-community bridge._
- **Why does `parse_datetime()` connect `parse_datetime` to `ml_challengers.py`, `EvidenceBundle`, `SupabaseRepository`, `live_worker.py`, `serialization.py`, `build_decision_experiences.py`, `build_features.py`, `fit_baseline`, `PITScalar`, `evidence/artifacts.py`, `investment_harness.py`, `logging.py`, `filings.py`, `ExecutionRepository`, `market_schedule.py`, `rl/contracts.py`, `PortfolioRiskPolicy`, `continuous_retrain.py`, `TransactionCostModel`, `select_all_paged`, `ablation.py`, `context.py`, `ExecutionSafetyError`, `ProductionInvestmentAdapters`, `event_intelligence.py`, `ensure_aware`, `canonical_json`, `ContractError`, `build_market_regime`, `worker.py`, `create_execution_intent.py`, `layer.py`, `VersionKey`, `SystemPortfolioStore`, `.from_row`, `decision/alpha.py`, `ml_serving.py`, `export_dataset.py`, `LocalMirror`, `inputs.py`, `toss/client.py`, `event_reanalysis.py`, `harness_adapters.py`, `decision/analysis.py`, `OptimizerPolicy`, `tradingagents_adapter.py`, `PITValuationInputs`, `backtest/contracts.py`, `BacktestRequest`, `harness/runtime.py`, `approval/ledger.py`, `build_training_samples.py`, `target.py`, `candidate_ranker.py`, `FeatureLayer`, `promotion/gate.py`, `LocalEvidenceCache`, `LiveExecutionRepository`, `FeatureDataset`, `environment.py`, `services/investment/__init__.py`, `app_pages/intelligence.py`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `canonical_json()` connect `canonical_json` to `ml_challengers.py`, `EvidenceBundle`, `SupabaseRepository`, `live_worker.py`, `parse_datetime`, `serialization.py`, `build_decision_experiences.py`, `PITScalar`, `fit_baseline`, `evidence/artifacts.py`, `emergency.py`, `investment_harness.py`, `logging.py`, `rl/contracts.py`, `PortfolioRiskPolicy`, `HarnessReporter`, `switch.py`, `remap_runtime_securities.py`, `continuous_retrain.py`, `TransactionCostModel`, `ablation.py`, `context.py`, `ExecutionSafetyError`, `ProductionInvestmentAdapters`, `event_intelligence.py`, `dashboard/db.py`, `CaseMemory`, `ContractError`, `experiment.py`, `lifecycle.py`, `worker.py`, `install_investment_harness.py`, `LocalArtifactStore`, `platform/artifacts.py`, `layer.py`, `SystemPortfolioStore`, `DeliveryRejected`, `event_reanalysis.py`, `decision/analysis.py`, `OptimizerPolicy`, `OpenAICompatibleClient`, `tradingagents_adapter.py`, `PITValuationInputs`, `backtest/contracts.py`, `harness/runtime.py`, `market_risk.py`, `RunContext`, `load_config`, `target.py`, `ResearchStore`, `candidate_ranker.py`, `services/investment/__init__.py`, `LocalEvidenceCache`, `LiveExecutionRepository`, `FeatureDataset`, `json_value`, `src/investment_agent/operations/harness/__init__.py`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `parse_datetime()` (e.g. with `._validate_timing()` and `build_events()`) actually correct?**
  _`parse_datetime()` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `SupabaseRepository` (e.g. with `run()` and `ProductionInvestmentAdapters`) actually correct?**
  _`SupabaseRepository` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 64 inferred relationships involving `ExecutionSafetyError` (e.g. with `DiscordApprovalClient` and `._check_state()`) actually correct?**
  _`ExecutionSafetyError` has 64 INFERRED edges - model-reasoned connections that need verification._
- **What connects `content_files`, `content_catalog_state`, `feature_sets` to the rest of the system?**
  _603 weakly-connected nodes found - possible documentation gaps or missing edges._