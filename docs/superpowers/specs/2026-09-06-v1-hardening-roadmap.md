# v1 내부 정리 로드맵 — 2026-09-06 기록

> 후속 저장 검토: [저장 최소화 검토와 Markdown 개정안](2026-09-06-storage-minimization-review.md).
> 아래 P5의 archive 기반은 현재 `data/market/archive.py`에 구현되어 있으므로 새로 구축하지 않는다.
> 남은 보존 밀도·영속성·변경 전파·연구 snapshot 계약은 후속 검토의 §6·§16과 함께 판단한다.
> 원격 Supabase 설치 상태는 실제 적용 전에 다시 확인한다.

> 상태: 계획 문서 (코드 변경 없음). v2가 아니라 **아직 v1 안에서** 남은 구조 문제를
> 정리하는 작업이다 — Supabase에는 아직 v1 스키마도 설치되지 않았다. 이 문서에 적힌
> 작업이 실제로 끝나면 해당 섹션을 지우고 `V1_STATUS.md`에 결과만 남긴다. "무엇을
> 했는가"는 git이 갖는다.

## 배경

`pipelines/ai_investor/ops/common` → `data/research/trading/execution/
reporting/notifications/operations/platform` 구조 전환은 완료됐고 방향은 유효하다.
지금 필요한 것은 폴더를 더 쪼개거나 새 버전으로 넘어가는 것이 아니라, v1 안에서 이미
그어놓은 경계를 다시 무너뜨리는 **중앙 파일**과 **DB 계약 오류 1건**을 없애는 것이다.
아래 우선순위 항목이 그중 가장 중요하다 — 나머지 항목보다 먼저 끝내야 하는 이유는 각
섹션에 적었다.

## 우선순위

### P3. Dashboard `db.py` 해체 (약 104KB)

Dashboard가 universe/market/macro/trading/execution을 직접 조회·join·계산하고 있다.
Reporting을 이미 만들어 놓고도 Dashboard가 그 경계를 우회하는 것이 지금 가장 큰 단일
파일 문제다.

**목표 구조**: `Supabase → Reporting → Dashboard/Discord`. Dashboard는 `reporting`
read model만 읽고, `dashboard/calculations`에 남아있는 진짜 도메인 계산(RSI, PnL, risk
metric, surprise, 투자점수 등)은 각 owner(`research`, `trading/performance`,
`trading/risk`, `reporting`)로 옮긴다. Dashboard에는 %, 축, 카드 레이아웃 같은 순수
표현 계산만 남긴다.

### P4. `research/strategies` → Yahoo 직접 접근 제거

`research/strategies/sources/yfinance.py`가 `data/market`을 거치지 않고 직접
`yfinance`를 호출한다. `data/market`이 이미 Yahoo 가격의 canonical owner이므로
`Yahoo → data/market → Research Dataset → GEM/HAA/GTAA`로 경로를 통일한다.

### P5. Market 과거 Daily 원본 보존

`market_backfill → compact_price_rows()`가 최근 7년만 daily로 남기고 7~10년은 weekly,
10년 이전은 제거한다. DB에 넣은 뒤 삭제하는 문제(`prices_deleted = 0`)는 이미 고쳤지만,
**백필 시점부터 오래된 daily를 버리는 문제**는 남아있다. ML/RL/장기 백테스트를 계획한다면
compact 이전에 Yahoo full daily history를 Parquet archive로 먼저 영구 보존하고, Supabase는
운영에 필요한 범위만 유지한다.

## 후속 항목 (위 우선순위 이후)

우선순위는 낮지만 §24 순서를 그대로 유지한다.

6. **`TradingRepository` 분리** — Policy/Model/Promotion/DecisionRun/SecurityDecision/
   Signal/Portfolio/Risk/Evaluation/Performance를 한 클래스가 다루는 새 god repository가
   되고 있다(~26KB). `trading/{decision,signals,portfolio,risk,performance,models}/
   repository.py`로 나누고, 필요하면 `TradingStore` facade를 얇게 둔다.
7. **Operations 디커플링** — `operations/commands/macro_refresh.py`가
   `data.macro.collectors.fred/yfinance/web` 등 collector 구현을 직접 import한다.
   Operations는 "Macro Refresh 실행"까지만 알아야 하고, 실제 collector 순서는
   `data/macro/service.py`가 안다.
8. **Reporting → 외부 수집 우회 제거** — `reporting/news.py`가 `data.news.provider`로
   직접 연결돼 있다. `외부 News → data/news → Cache/Artifact/DB → reporting/news →
   Dashboard/Discord` 순서로 고친다.
9. **Execution 파일 배치 정리(로직 변경 없음)** — `execution/approval_*.py` 등 루트에
   흩어진 파일을 `execution/{approvals,orders,control,brokers,reconciliation,tca}/`로
   옮긴다. 기존 safety test가 이동 전후 100% 동일하게 통과해야 하며, 이 작업 중에는
   `harness_switch --maintenance on`을 먼저 건다.
10. **`platform` 재검토** — `research_store.py`는 Research 전용이면 `research/storage.py`로,
    범용 저장 엔진이면 `platform/analytics_store.py`로 이름을 바꾼다. `external_usage.py`도
    provider별 규칙을 알고 있다면 해당 data 도메인으로 돌려보낸다.

## Architecture test 보강 (위 항목과 별개로 계속 추가)

기존 테스트가 강제하는 방향(Platform→domain 금지, data pipeline 상호호출 금지,
Execution→Trading/Research/Data 금지 등)에 아래를 추가한다.

```text
Dashboard      → Reporting 외 domain 직접 조회 금지
Notifications  → Reporting + notification infrastructure 외 금지
Research       → Execution/Broker 금지
Reporting      → External API 직접 호출 금지
Operations     → data/*/collectors 직접 import 금지
```

## 이번 세션에서 하지 않은 것

`db/v1/` 설치나 Supabase 적용은 위 우선순위 코드 변경과 오프라인 검증이 끝난 뒤에만
한다(현재 Supabase는 비어 있음).
