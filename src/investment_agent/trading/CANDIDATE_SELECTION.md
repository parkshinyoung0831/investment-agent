# 후보 선정 — tracked universe에서 무엇을 볼까

* **상위 문서**: [AI Investor README.md](README.md) · [루트 README.md](../../../README.md)

TradingAgents를 tracked universe 전체에 한 번에 실행하면 모델 비용과 시간이 지나치게 커집니다. 후보 선정기는
주문을 결정하지 않고, `universe.securities.is_tracked=true`인 현재 tracked universe 전체에서 이번 회차에
Bull/Bear 토론을 먼저 받을 종목만 고릅니다.

> **현재 구현 상태**
>
> 정렬 알고리즘과 live-only 시간 제한은 코드·단위 테스트가 있는 현재 동작입니다. 최신 종목 수는 Supabase의
> `is_tracked=true` 결과를 사용합니다. Segment pipeline이 `unavailable`이면 신뢰 가능한 행이 없는
> 종목에서 해당 domain은 점수 계산에서 자동 제외됩니다.

## 정렬 순서

```text
is_tracked=true 전체
→ as_of 시점보다 뒤의 행 제거
→ 미분석 종목 / 가장 오래 분석한 종목 우선
→ 같은 coverage cohort 안에서 구조화 데이터의 변화·극단값 점수
→ 점수 동률이면 ticker 오름차순
→ 실행당 limit(1~500, 기본값 50)
```

coverage가 점수보다 항상 먼저입니다. 따라서 점수가 낮은 종목도 재선정이 일어나기 전에 한 번씩
분석되며, 구성종목 수를 `N`, 일일 한도를 `L`이라 하면 성공 판단이 정상적으로 저장된
`ceil(N/L)`개 batch 안에 현재 집합을 한 바퀴 돕니다. `decision_runs.candidate_tickers`는 시도 목록일
뿐 coverage 증명이 아닙니다. `cases.status`가 `completed` 또는 `abstained`인 종목만 분석 완료로
인정하므로 partial/failed batch의 실패 종목은 뒤로 밀리지 않고 다음 실행의 우선 후보로 남습니다.

## 점수 입력

| 도메인 | 후보용 신호 | 가중치 | 시점 차단 |
|---|---|---:|---|
| OHLCV | 20거래일 절대수익률, 최근 거래량의 20일 중앙값 대비 변화 | 30% | `trade_date`, `ingested_at <= as_of` |
| 기술 | RSI 50 이탈 폭, MACD-signal의 종가 대비 절대 간격 | 20% | `trade_date`, `ingested_at <= as_of` |
| 펀더멘탈 | 전년 동기 매출 성장률과 영업이익률의 절대 크기 | 25% | `filed_at`, `ingested_at <= as_of` |
| 세그먼트 | 사용 가능한 경우에만 parsed 공시의 집중도와 coverage | 10% | 현재 unavailable이면 domain 제외 |
| Gurus | 매니저별 최신 13F의 보유 매니저 수와 gross reported value | 15% | `accepted_at`, `ingested_at`, CUSIP mapping `updated_at <= as_of` |

서로 단위가 다른 값은 현재 cross-section의 dense percentile로 바꾼 뒤 결합합니다. 데이터가 없는
도메인은 0이라고 꾸며 넣지 않고 가중치 분모에서 제외하며, 사용 가능한 도메인 수가 적으면 coverage
multiplier로 점수를 낮춥니다. 모든 도메인이 비어도 coverage와 ticker tie-break로 결정론적으로
순환합니다.

절대 변화폭을 쓰는 이유는 이 단계가 매수 랭커가 아니기 때문입니다. 급등·실적 개선뿐 아니라
급락·마진 악화도 먼저 연구할 가치가 있으며, 이후 TradingAgents의 Bull/Bear 분리 토론과 Trader,
Risk, Portfolio Manager가 방향을 결정합니다. 이 점수로 주문 방향·수량·목표 비중을 만들지 않습니다.

뉴스와 소셜은 90일 로컬 cache만 있는 live-only 입력이므로 전체 universe 사전 랭킹에는 사용하지 않습니다.
구조화 데이터로 선정된 종목에 한해서만 TradingAgents 실행 중 호출해 API 호출량과 이용조건을
통제합니다.

## 안전 경계

- CLI에서 종목을 직접 지정해도 `is_tracked=true` 밖이면 즉시 거부합니다.
- 암묵적 후보 선정에는 timezone이 있는 `as_of_at`이 필수입니다.
- 이 후보 랭커와 두 live Shadow entry는 현재 `is_tracked=true`와 현재형 자식 테이블을 쓰므로
  ticker를 직접 지정한 경우도 포함해 `as_of_at`이 실행 시각보다
  24시간 넘게 오래된 historical 요청은 네트워크 조회 전에 거부합니다. `segment_metrics`에는 행별
  `ingested_at`이 없고 재파생 결과가 같은 PK에 upsert될 수 있어, 부모 filing 시각만으로 임의 과거를
  완전 재현한다고 주장하지 않습니다. 13F positions는 filing과 한 트랜잭션으로 교체되고 부모
  `ingested_at`도 갱신되지만 현재 후보 랭커 전체의 가장 약한 도메인에 맞춰 live-only로 둡니다.
- 데이터 조회 오류는 알파벳 순이나 외부 웹 데이터로 조용히 대체하지 않고 실행을 실패시킵니다.
- historical backtest/RL의 과거 universe는 이 현재 후보 선정기를 재사용하지 않고
  `sp500_membership_snapshots`를 사용합니다.
- 선택 ticker와 최종 점수는 실행 로그에 남고, 실제 분석 batch는 `decision_runs.candidate_tickers`에
  저장됩니다.

## 예시 해석

AAPL의 구조화 변화 점수가 높고 MSFT는 오랫동안 분석되지 않았다고 가정합니다. MSFT가 더 오래된
coverage cohort라면 MSFT가 먼저 선택됩니다. 두 종목의 마지막 성공 분석 시각이 같을 때만 변화 점수가
순서를 가릅니다. AAPL의 후보 점수가 0.9여도 상승 확률 90%나 목표 비중 9%라는 뜻은 아닙니다.

## 운영 확인

```powershell
# LLM 호출 없이 실제 AAPL context와 결측 상태 확인
python -m investment_agent.trading.decision.portfolio_shadow --ticker AAPL --dry-run

# 모델 설정 뒤 현재 universe에서 최대 5개 Shadow 분석
python -m investment_agent.trading.decision.shadow_daily --limit 5
```

오래된 `--as-of`를 주면 현재형 segment/13F child data를 과거처럼 재구성할 수 없기 때문에 24시간
제한에서 실패하는 것이 정상입니다. 과거 연구는 live candidate ranker가 아니라 versioned universe와
PIT feature dataset을 사용합니다.
