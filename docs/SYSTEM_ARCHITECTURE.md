# 시스템 아키텍처 — 계층, 경계와 다이어그램 지도

이 문서는 **전체 구조를 한 장으로 보는 자리**다. 각 계층이 무엇을 소유하고 무엇을 소유하지
않는지, 그리고 어떤 화살표가 허용되는지를 갖는다. 계층 안쪽의 동작은 각 주제 문서와
package README가 갖는다.

계층 사이의 화살표 규칙은 **`tests/investment_agent/test_architecture.py`가 강제**한다.
이 문서와 그 테스트가 다르면 테스트가 옳다.

## L0 — 전체 아키텍처

![시스템 전체 아키텍처](diagrams/svg/system-architecture.svg)

수집(공개 데이터) → 저장(네 저장소) → 연구(PIT feature·팩터·ML) → 판단(ALPHA·optimizer·RiskGate)
→ 승인 → 실행(Toss 단일 broker), 그리고 그 옆에서 reporting이 읽기 모델을 만들어 대시보드와
Discord 알림에 공급한다. 점선 경계는 사람 승인 없이는 넘지 못하는 자리다.

*소스: `docs/diagrams/src/system-architecture.architecture.json` — 그림을 고치려면 이 파일을 고치고 `python scripts/build_diagrams.py`. 본문 폭에서는 글자가 작다 — 이미지를 눌러 원본으로 보거나 `docs/diagrams/html/system-architecture.html`을 브라우저로 연다.*

## 계층과 소유

| 계층 | 패키지 | 소유하는 것 | 소유하지 않는 것 |
|---|---|---|---|
| 수집 | `data/` | universe·market·fundamentals·macro·institutional의 수집·PIT·적재 | 모델 신호, 주문 |
| 텍스트 | `intelligence/` | 뉴스·소셜 원문과 종목 언급 (로컬 DuckDB, 최대 90일) | 판단, 발송 |
| 연구 | `research/` | feature·dataset·팩터·모델·평가·backtest·PIT 읽기 조립 | 판단·실행·표시 |
| 판단 | `trading/` | 사건 우선순위·논지·ALPHA·optimizer·RiskGate·System Portfolio | credential, 주문 mutation |
| 실행 | `execution/` | 승인·permit·broker·주문·체결·대사·kill switch | 투자 thesis, LLM prompt |
| 읽기 | `reporting/` | 화면과 알림이 공유하는 read model (SELECT 전용) | 발송, 화면, 실행 |
| 알림 | `notifications/` | 중복 방지 원장·카드·embed·Discord 전송 | 판단·실행 구현 |
| 화면 | `dashboard/` | 읽기 전용 Streamlit 화면 | 저장소 접근, mutation |
| 운영 | `operations/` | 최외곽 조립·스케줄·감시·CLI 진입점 | 투자 판단 알고리즘 |
| 공통 | `platform/` | DB 연결·clock·logging·retry·serialization·cache·사용량 | 금융 도메인 지식 |

최상위 공유 모듈은 **정확히 넷**이다 — `bootstrap.py` `config.py` `forecasting.py`
`portfolio_weights.py`. 뒤 둘은 Research와 Trading이 **대칭으로** 쓰는 금융 계약이라 어느
한쪽에 둘 수 없어서 여기 있다. 목록은 `SharedTopLevelModulesTest`가 고정한다.

## 허용되는 화살표

```text
data / intelligence → research → trading → execution
                                   ↘ reporting → dashboard / notifications
operations = 최외곽 orchestration · composition · monitoring
platform   = 금융 도메인을 모르는 공통 기술 계층
```

이 방향은 façade나 alias로 우회하지 않는다. 경계를 넘는 import는 전부 **이름이 붙은 단일
예외**뿐이고, 그 외에는 테스트가 실패시킨다.

| 넘는 간선 | 통과하는 유일한 모듈 | 왜 |
|---|---|---|
| `trading` → `research` | `research/adapters/trading.py` | Research 내부 구현(feature 계산·저장소·모델 serving)을 좁은 공개 계약 뒤에 둔다 |
| `trading` → `execution` | `execution/contracts.py` | 판단은 안정된 실행 계약만 소비한다. 주문 mutation은 execution 안에서만 |
| `research` → `trading` | `research/system_validation/ablation.py` (지정된 6개 심볼) | 운영 Trading 엔진을 실제로 재생하는 단일 검증 모듈 |
| `data` → `operations` | `operations/monitoring/{incidents,github}.py` | 파이프라인 실패를 Discord ops에 알리는 운영 행위 |
| `data` → `execution` | `execution/brokers/toss/auth.py` | Toss OAuth는 프로세스 공용 singleton이고 broker 쪽이 소유자다 |

**방향은 대칭이 아니다.** `research → trading`은 금지(위 한 파일 예외)지만
`trading → research`는 adapter 하나를 통해 허용되고 실제로 널리 쓰인다. 둘을 같은 규칙으로
읽으면 잘못된 곳에 코드를 놓게 된다.

## 리팩터링이 확정한 경계

"합치면 깔끔한데 왜 안 합쳤는가"에 반복해서 닿는 자리들이다. 되돌리기 전에 이유가 아직
유효한지 확인하라.

- **증거 계약·조립기·통계와 PIT 읽기는 `research/evidence/`가 소유한다** — `trading/evidence`가
  아니다. Research feature와 Trading 판단이 **같은 사실**을 읽어야 하기 때문이고, Trading은
  `research/adapters/trading.py`로만 가져온다.
- **dashboard는 자기 DB 모듈을 갖지 않는다.** 저장소 접근은 `reporting/readers/`뿐이고
  **RPC 경로는 코드에 존재하지 않는다** — allowlist로 거르는 것이 아니라 아예 없다.
  화면 모듈이 DB 클라이언트를 import하면 `DashboardReportingBoundaryTest`가 실패시킨다.
- **broker 중립 계약은 만들지 않았다.** 시스템은 Toss 단일 broker다. 쓰지 않는 추상은
  실제 경계를 흐린다.
- **`ResearchStore`는 한 저장소로 유지했다.** `SupabaseRepository`는 `PitReader`와
  `CandidateSelection`을 합성한 Trading 원장 게이트웨이다.
- **Trading 원장을 다루는 CLI 진입점은 `operations/commands/`에 둔다.** Research에는 조립
  예외가 없다.
- **`notifications/channels/`와 engine이 Discord 구현과 분리돼 있다.** engine은 구체 전송
  구현을 import하지 않는다 *(테스트 강제)*.

## 저장소 넷

| 저장소 | 선언 | 무엇이 사는가 |
|---|---|---|
| Supabase Postgres | `db/postgres/v1/` | universe · market · fundamentals · macro · institutional · notifications · reporting |
| 로컬 SQLite runtime | `db/sqlite/runtime/v1/` | 계좌·판단·실행·성과·System Portfolio 원장 |
| 로컬 DuckDB research | `db/duckdb/research/v1/` | dataset·실험·모델·backtest |
| 로컬 DuckDB intelligence | `db/duckdb/intelligence/v1/` | 뉴스·소셜 원문과 종목 언급 |

무엇이 어디에 사는지 행 단위 지도는 [저장 지도](STORAGE_MAP.md)가 갖는다.

## 다이어그램 지도

canonical source는 `docs/diagrams/src/*.json`이고, `html/`과 `svg/`는 생성물이라 손으로
고치지 않는다. 폴더 계약과 빌드 방법, 현재 다이어그램 목록은
[다이어그램 README](diagrams/README.md)가 갖는다.

```bash
python scripts/build_diagrams.py     # JSON → validate → HTML → SVG
```

| Level | 다이어그램 | 답하는 질문 |
|---|---|---|
| L0 | `overview` | 수집에서 체결·성과까지 전체가 어떻게 이어지는가 (루트 README) |
| L0 | `system-architecture` | 패키지 단위로 무엇이 무엇을 알아도 되는가 (이 문서) |
| L1 | `pipeline` | 수집이 어디서 와서 어디로 가는가 |
| L2 | `trading-analysis` · `trading-target` | 근거가 어떻게 신호가 되고 목표 비중이 되는가 |
| L3 | `promotion-ladder` | 어느 단계까지 올라갈 수 있고 무엇이 막는가 |
| L3 | `execution-lifecycle` · `execution-runbook` · `earnings-pipeline` | 주문·승인·공시 각각이 어떤 단계를 지나는가 |

그림은 **지도**다. 왜 그런지와 지켜야 할 불변식은 그림이 아니라 각 문서 본문에 있다.

## 더 읽을 곳

| 주제 | 문서 |
|---|---|
| 폴더와 전체 흐름 | [문서 지도](README.md) |
| 수집·PIT·품질 | [데이터](DATA.md) |
| 무엇이 어느 저장소에 | [저장 지도](STORAGE_MAP.md) |
| 판단·ML/RL·optimizer·RiskGate | [투자 시스템](INVESTMENT_SYSTEM.md) |
| 자율 판단 계층의 패키지 경계 | [자율 판단 계층](AUTONOMOUS_SYSTEM.md) |
| 승인·broker·안전장치 | [실행과 안전](EXECUTION_AND_SAFETY.md) |
| 설치·Actions·하네스 | [운영](OPERATIONS.md) |
| 넘지 않는 선 | [Trading Constitution](../src/investment_agent/trading/CONSTITUTION.md) |
