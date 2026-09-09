# Macro — 시장 상태 관측과 경제발표

`investment_agent.data.macro`는 "지금 시장이 어떤 상태인가"에 답하는 시계열을 소유한다.
금리·스프레드·환율·원자재·변동성·심리·breadth가 여기 있다.

**두 가지를 함께 담지만 표는 나눠 둔다.** 시장 관측(`market_observations`)은 매일 관측되고,
경제발표(`economic_observations`)는 예정 시각이 있고 나중에 개정된다 — 갱신 규칙이 다르므로
한 표에 섞으면 개정 이력이 관측 이력을 오염시킨다.

## 저장 계약

| 사실 | v1 표 |
|---|---|
| 지표 마스터(이름·단위·시간대·출처) | `macro.series` |
| 발표 지표의 측정 항목 | `macro.measures` |
| 시장 상태 관측값 | `macro.market_observations` |
| 경제지표 실제값 | `macro.economic_observations` |
| 발표 사건(자연키) | `macro.release_events` |
| 예정 일정의 버전 | `macro.release_schedule_versions` |
| 발표 전 예상값 스냅샷 | `macro.forecast_snapshots` |

관측은 append-only 버전이다. 자연키는 series·기준기간·출처·유효시각·수집시각이므로,
**소비자는 as-of 스냅샷을 골라야 한다** — 날짜당 가변 행 하나를 가정하면 안 된다.

서프라이즈·개정·최신값 같은 파생값은 저장하지 않는다. `reporting.macro_release_summary`가
읽는 시점에 만든다.

## 구조

```text
catalog → fetch → validate → persist (append-only 버전)
```

```text
src/investment_agent/data/macro/
├── domain/
│   ├── catalog.py       # 출처·series 선언 (참조 데이터의 SSOT)
│   ├── quality.py       # series 계약과 환율 교차 검증
│   ├── revisions.py     # PIT 관측 규칙
│   └── releases/        # 경제발표 규칙과 고정 30개 지표 설정
├── application/
│   ├── refresh_market_state.py
│   └── release_calendar.py
├── infrastructure/
│   ├── fetch.py         # 경계 있는 fetch·정규화·공통 검증
│   ├── settings.py      # 출처별 호출 예산
│   └── sources/         # 외부·내부 어댑터
├── repository.py        # v1 읽기와 관측 쓰기 경계
├── commands/            # 실행 진입점
└── releases/            # 발표 적재와 출처 계약
```

| 어댑터 | 무엇을 가져오나 |
|---|---|
| `sources/fred.py` | 미국 금리·기대인플레이션·스프레드 |
| `sources/ecos.py` | 한국 금리·환율·자금흐름 |
| `sources/yfinance.py` | 지수·ETF·원자재·VIX/MOVE·크립토 |
| `sources/web.py` | 등록된 웹 파서 |
| `sources/market.py` | universe·market 저장소에서 파생한 breadth |

## 실행

```powershell
python -m investment_agent.data.macro.commands.macro_refresh --lookback-days 14
python -m investment_agent.data.macro.commands.macro_refresh --dry-run
python -m investment_agent.data.macro.commands.macro_refresh --dry-run --series BREADTH_200DMA
python -m investment_agent.data.macro.commands.macro_refresh --backfill-from 2016-01-01
```

진입점은 `MacroRepository`로 카탈로그를 읽고, 출처마다 **독립적으로** 가져온 뒤, series
검증과 교차 검증을 적용하고, `MacroService`로 버전을 남긴다. 한 출처가 실패해도 나머지
출처의 관측은 보존된다. `--dry-run`은 DB에 아무것도 쓰지 않는다.

경제발표 쪽 진입점은 [releases/README.md](releases/README.md)에 있다.

## 보존 정책

일정과 예상은 발표 전에는 변경 자체가 신호다. 그런데 실제치가 나오면
`reporting.macro_release_summary`가 쓰는 것은 둘뿐이다 — **확정된 마지막 일정**과
**실제치 직전의 예상(closing)**.

`macro.prune_release_snapshots()`는 실제치가 있는 ref_period만, 그것도 최근 180일 밖의
것만 그 한 건씩 남기고 정리한다. `release_calendar.run_daily`가 실패 없는 회차에만
호출한다 — 부분 실패한 회차에서 정리하면 아직 안 받은 예상을 지운다.

## 조용히 틀리는 것

- 날짜당 행 하나를 가정하고 읽기. 같은 날짜에 출처·수집시각이 다른 버전이 여럿 있다.
- 시장 관측과 경제발표를 같은 표로 묶어 생각하기. 개정 규칙이 다르다.
- 부분 실패한 수집 회차에서 스냅샷 정리를 돌리기.

스키마의 단일 선언은 `db/postgres/v1/40_macro.sql`이며, bootstrap은 이 파일을 사용한다.
DB 초기화·재수집·Discord 발송은 별개의 운영 행위이고 이 패키지가 수행하지 않는다.
