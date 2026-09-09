# 저장 지도 — 무엇이 어디에 사는가

이 시스템의 저장소는 하나가 아니라 **넷**이다. 문서가 이것을 헷갈리면 읽는 사람이 없는
곳을 찾아간다 — 이름이 남아 있어도 그 대화·그 도구로는 **조회 자체가 불가능**해진다.

각 저장소의 단일 선언은 `db/` 아래에 있고, 이 문서는 그 선언을 한 장으로 본 것이다.
표 이름을 바꾸면 `python -m unittest tests.test_docs_consistency`가 문서와의 어긋남을 잡는다.

## 넷을 가르는 기준

| 저장소 | 무엇이 사는가 | 왜 거기인가 | 선언 |
|---|---|---|---|
| **Supabase Postgres** | 공개 데이터에서 온 금융 사실 | 여러 기계·GitHub Actions가 함께 읽는다 | `db/postgres/v1/*.sql` |
| **로컬 SQLite** | 실행·승인·알림 원장 | 실제 주문과 중복 방지는 **실행한 그 컴퓨터**의 사실이다 | `db/sqlite/runtime/v1/*.sql` |
| **로컬 DuckDB (research)** | 연구 lineage와 전략 배분 | 언제든 다시 만들 수 있다. 남길 것은 "무엇으로 만들었나" | `db/duckdb/research/v1/*.sql` |
| **로컬 DuckDB (intelligence)** | 뉴스·소셜 색인과 언급 | 원문은 Parquet, 여기는 작은 metadata만 | `db/duckdb/intelligence/v1/*.sql` |

대용량 본문·feature 행은 어느 DB에도 넣지 않고 **날짜 파티션 Parquet**가 소유한다. DB는
그 뿌리가 어디고 얼마나 최신인지만 안다.

## Supabase Postgres — 원장

```text
data/local/                     ← 여기 있는 것은 커밋하지 않는다
Supabase                        ← GitHub Actions가 읽고 쓰는 유일한 곳
```

| 스키마 | 표 |
|---|---|
| `universe` | `entities` · `securities` · `security_identifiers` · `index_memberships` |
| `market` | `prices_daily` · `split_events` · `dividend_events` |
| `fundamentals` | `filings` · `filing_processing` · `financials` · `share_class_snapshots` · `segment_metrics` · `earnings_results` · `earnings_estimates` · `earnings_schedule_versions` · `analyst_consensus_snapshots` |
| `macro` | `series` · `measures` · `market_observations` · `economic_observations` · `release_events` · `release_schedule_versions` · `forecast_snapshots` |
| `institutional` | `filings` · `positions` |

`reporting` 스키마에는 표가 없고 **뷰만** 있다(15개). 파생값을 저장하지 않고 읽는 시점에
만들기 때문이다 — 규칙이 바뀔 때 과거 행이 조용히 옛 규칙을 말하는 것을 막는다.

## 로컬 SQLite — 실행 원장

기본 경로 `data/local/runtime/runtime.sqlite3`. **별도 PostgreSQL execution 스키마는 없다.**

| 파일 | 표 |
|---|---|
| `00_init.sql` | `local_job_state` |
| `10_account.sql` | `account_snapshots` |
| `20_decisions.sql` | `policies` · `model_versions` · `model_promotions` · `decision_runs` · `security_decisions` · `decision_evidence` · `signal_runs` · `signals` · `portfolio_proposals` · `risk_decisions` · `portfolio_decisions` · `decision_evaluations` · `attribution_reports` |
| `30_execution.sql` | `execution_control` · `runtime_records` · `intents` · `approvals` · `order_manifests` · `order_attempts` · `order_events` · `orders` · `fills` · `reconciliation_runs` |
| `40_notifications.sql` | `notification_delivery_state` · `notification_outbox` · `notification_deliveries` |

알림 중복 방지가 여기 있는 이유: 보내기 **전에** 선점해야 하는데, 그 판단은 발송을 실행하는
기계의 사실이다. Supabase 왕복이 실패하면 중복 발송을 막을 수 없다.

## 로컬 DuckDB

| research | intelligence |
|---|---|
| `feature_sets` · `dataset_runs` | `content_files` · `content_catalog_state` |
| `datasets` · `experiments` · `models` · `backtests` | `content_index` |
| `strategy_runs` · `strategy_allocations` | `entity_mentions` |
| 뷰: `research_inventory` | 뷰: `ticker_mention_daily` · `intelligence_freshness` |

## 소비자는 이 차이를 모른다

화면과 알림은 네 저장소를 직접 열지 않고 `reporting`의 읽기 계약만 소비한다.
`reporting.*`라는 이름은 **논리적 계약**이지 Postgres 뷰 목록이 아니다 —
`ReportingQueries.VIEWS`의 절반은 SQL 뷰이고 나머지는 `readers/runtime.py`가 SQLite에서
만든다.

자세한 것은 [reporting/README.md](../src/investment_agent/reporting/README.md).

## 옮겨간 이름

과거 문서·프롬프트에 남아 있던 이름과 현재 자리다. 옛 이름으로 조회하면 **에러가 아니라
빈 결과**가 오는 경우가 있어 특히 조용히 틀린다.

| 옛 이름 | 지금 |
|---|---|
| `fundamentals.company_financials`, `fundamentals.financial_versions` | `fundamentals.financials` |
| `fundamentals.v_company_metrics`, `v_security_valuation`, `mv_company_ttm` | 없음 — 원장에서 읽는 시점에 계산 |
| `macro.observations`, `macro.observation_versions` | `macro.market_observations` · `macro.economic_observations` |
| `universe.memberships`, `universe.sp500_membership_snapshots` | `universe.index_memberships` |
| `notifications.outbox`, `notifications.deliveries` | SQLite `notification_outbox` · `notification_deliveries` |
| `notifications.subscriptions` | 없음 — `DISCORD_CHANNEL_*` env와 `subscriptions.py`의 `KIND_ENV` |
| `execution.control_state` | SQLite `execution_control` |
| `execution.approval_requests` | SQLite `approvals` |
| `trading.*` (model_versions·signals·proposals·risk_decisions) | SQLite 같은 이름 |
| `tech_indicators`, `gurus`, `strategy` 스키마 | 없음 — DuckDB research / `institutional` 스키마 |

## 고칠 때 함께 볼 곳

- 표를 늘리거나 이름을 바꾼다 → `db/` 선언 + 이 문서 + `prompts/`
- 노출 스키마 목록 → Supabase 설정. **없는 스키마가 남으면 Data API 전체가 `PGRST002` 503**
- 읽기 계약 → `reporting/readers/financial.py`의 `VIEWS`, `runtime.py`의 `LOCAL_VIEWS`
- 커밋하면 안 되는 경로 → `.gitignore`의 `data/local/**`
