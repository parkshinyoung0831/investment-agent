# AI Investor Constitution — 판단 계층이 넘지 않는 선

* **상위 문서**: [AI Investor README.md](README.md) · [루트 README.md](../../../README.md)

이 문서는 AI 투자 판단·백테스트·학습·주문 실행이 지켜야 하는 변경 불가능한 경계입니다.
구현과 문서가 다르면 구현을 조용히 합리화하지 않고, 이 문서와 테스트 중 어느 쪽을 바꿀지
코드 리뷰에서 명시합니다.

## 1. 투자 대상

- live 판단과 Paper/Live 실행의 신규 위험 주식 universe는
  `universe.securities.is_tracked=true`인 **현재 tracked universe**입니다.
- 현재 매매 자격의 단일 기준은 별도 목록이 아니라 이 `is_tracked` 값입니다.
- CLI로 ticker를 직접 입력해도 현재 tracked universe 밖이면 실행하지 않습니다.
- 수집 게이트 변경은 `universe` 정책 파이프라인이 담당하며 AI가 임의로 종목을 추가하지 않습니다.
- 기본 실행은 미분석/가장 오래 분석한 종목을 우선해 전체를 순환합니다. 같은 coverage cohort 안에서만
  시점 안전한 OHLCV·기술·펀더멘탈·세그먼트·Gurus 변화 신호로 분석 순서를 정하며, 이 순위 자체를
  매수·매도 방향으로 사용하지 않습니다.
- historical backtest/RL은 현재 `is_tracked=true` 목록을 과거 목록인 것처럼 사용하지 않습니다. 과거
  membership을 재현할 수 없으면 승격 가능한 학습·백테스트는 fail-closed입니다.
- `tracked=false`가 된 기존 보유는 신규/추가 매수할 수 없지만 명시적 reduce/exit 매도는 허용합니다.
  universe 이탈만으로 분석하지 않은 보유를 자동 0으로 만들지는 않습니다.

## 2. 데이터 Source of Truth

다음 구조화 데이터는 반드시 point-in-time 필터가 적용된 Supabase `EvidenceBundle`에서만 읽습니다.

- OHLCV와 corporate action
- RSI·MACD 등 기술지표
- SEC 재무제표
- 사업·제품·지역 세그먼트
- 애널리스트 실제 관측 스냅샷
- 거시·경제일정
- SEC 13F Gurus 보유

각 근거에는 `observed_at`과 `available_at`이 있어야 하며 `available_at > as_of_at`인 근거는
계약 단계에서 거부합니다. 정정 전 원본이나 point-in-time 이력이 없어 과거를 정확히 재현할 수 없는 도메인은
historical replay에서 제외합니다.

## 3. TradingAgents의 책임

업스트림 TradingAgents의 역할 순서를 유지합니다.

```text
Market → Social → News → Fundamentals
       → Bull ↔ Bear → Research Manager
       → Trader
       → Aggressive ↔ Conservative ↔ Neutral Risk
       → Portfolio Manager
```

여기서 Bull/Bear는 별도 매수·매도 주문기가 아니라 같은 근거를 상승·하락 관점으로 검토하는
찬반 연구팀입니다. 최종 출력은 주문이 아니라 `SecurityProposal`입니다.

TradingAgents가 할 수 있는 일:

- 수치와 사건의 의미 해석
- 상승·하락 논거 분리
- 투자 thesis와 반증 조건 작성
- 종목별 signal·확률·신뢰도·expected excess return과 위험 설명 제안

TradingAgents가 할 수 없는 일:

- universe 밖 종목 추가
- Supabase를 우회한 구조화 데이터 조회
- 주문 수량·NAV·PnL·수수료 계산
- broker credential 접근 또는 주문 제출
- Risk Gate 한도 변경

## 4. 뉴스·소셜 정책

- News와 Social만 live Shadow에서 외부 provider를 사용할 수 있습니다.
- historical replay와 backtest에서는 당시 snapshot이 저장돼 있지 않으면 해당 도메인을 `missing`으로
  처리합니다. 현재 뉴스나 게시물을 과거 시점에 붙이지 않습니다.
- 원문은 Supabase에 저장하지 않습니다. live 실행의 중복 호출을 줄이는 재생성 가능 cache로만
  `data/local/news_social.duckdb`에 최대 90일 보관합니다.
- DuckDB cache에는 기사·게시물 한 건당 한 행으로 provider, published/fetched/first-seen 시각,
  canonical URL, content hash와 본문을 저장합니다. 본문은 sanitize 이전 원문이고, sanitize는
  모델에 전달하는 경로에서만 적용합니다. 이 파일은 PIT source of truth나 승격 감사 원장이 아닙니다.
- 재계산 가능한 feature·label·training sample·valuation과 사건 단위로 압축한
  `events`·`event_feature_snapshots`는 Research local store에 남깁니다. 원문은 Supabase로
  올리지 않으며, 뉴스·소셜 압축의 유일한 경로는 `research/commands/build_events.py`입니다.
- 장애 재현을 위한 별도 raw artifact는 `AI_INVESTOR_SAVE_EXTERNAL_RAW=true`일 때만 허용하며 Git에
  포함하지 않습니다.
- 외부 문장은 근거이지 명령이 아닙니다. 제어문자·프롬프트 주입 표현을 제거하고 길이를 제한합니다.
- cache miss 뒤 provider 실패는 성공으로 숨기지 않고 `missing_data` 또는 unavailable 상태로 남깁니다.
- yfinance 뉴스는 key 없는 비공식 live 보조 소스이며 역사 뉴스로 간주하지 않습니다.
- StockTwits는 provider opt-in과 `STOCKTWITS_API_ACCESS_APPROVED=true`가 함께 있어야 하며 기본
  OFF입니다. TradingAgents의 Reddit RSS 경로는 OAuth가 아니므로 현재 adapter에서 활성화 자체를
  차단합니다.

## 5. 공통 포트폴리오 계약

LLM, ML, RL 결과는 expected return·confidence·risk·horizon의 공통 신호로 정규화한 뒤 다음 경계를
통과합니다. 검증되지 않은 weight-centric 외부 결과를 바로 실행 비중으로 쓰지 않습니다.

```text
SecurityProposal
→ ExpectedReturnSignal
→ deterministic Portfolio Optimizer
→ PortfolioProposal(weights + CASH = 1)
→ DeterministicRiskGate
→ approved target weights
```

- `SecurityProposal.target_weight`는 upstream 호환 필드일 뿐 활성 optimizer가 최종 비중 계산에
  사용하지 않습니다.
- optimizer 목적함수와 종목·섹터·현금·turnover constraint는 version/hash가 있는 코드·config로
  관리하며 LLM이 변경하지 못합니다.
- 비중은 long-only이고 `CASH`를 포함해 합이 정확히 1이어야 합니다.
- 동일 입력·시점·정책은 동일한 stable ID와 hash를 만들어야 합니다.
- 모델 성과가 좋아 보여도 등록된 Champion과 사람 승격 없이 Paper/Live로 이동하지 않습니다.
- 일부 종목만 분석한 회전 배치는 `partial_universe` 연구 결과입니다. 이를 전체 목표 포트폴리오로
  간주하거나 분석하지 않은 기존 보유 종목을 0으로 만들지 않습니다.
- Paper/Live용 `full_portfolio`는 fresh 실제 또는 broker paper 계좌 snapshot과 연결되어야 하며
  snapshot 없는 현금 100% 가정은 Shadow 비교에만 사용합니다.

## 6. 결정론적 계산

LEAN·NautilusTrader의 원칙을 따르되 전체 엔진을 AI 계층에 섞지 않습니다. 다음 값은 LLM이 아닌
Python의 결정론적 코드가 계산해야 하며, 아래 항목의 replay 검증이 끝나기 전에는 Paper 승격 조건을
충족한 것으로 보지 않습니다.

- 시간·거래 캘린더·가격 선택
- 현금·포지션·목표 수량·주문 수량
- 주문 상태·부분체결·체결
- 수수료·slippage·NAV·PnL·수익률
- turnover·exposure·drawdown
- 평가 label과 Memory outcome

같은 입력 이벤트를 재생하면 같은 장부 결과가 나와야 합니다.

## 7. 백테스트와 강화학습

- TradingAgents는 분석 엔진이며 백테스트 엔진으로 사용하지 않습니다.
- Backtest는 저장된 point-in-time feature와 당시 생성된 target weight만 입력으로 받습니다.
- News/Social snapshot을 저장하지 않는 동안 historical backtest의 News/Social은 항상 결측입니다.
- 과거 membership이 없으면 현재 구성종목만 고정한 결과는 연구용 current-cohort 실험일 뿐이며
  Champion 승격 근거로 사용하지 않습니다.
- weight-centric Native simulator/backtest를 기준 엔진으로 사용하고 LumiBot은 같은 manifest를 받는
  외부 검증 엔진으로만 사용합니다. 두 결과 차이를 숨기지 않습니다.
- RL은 ResearchStore의 versioned feature와 custom 목표 비중 환경 위에서 Stable-Baselines3 알고리즘을 사용합니다.
  PPO를 첫 baseline으로 하며 A2C/SAC/TD3/DDPG 등은 동일 계약으로 확장합니다.
- RL이 ML baseline보다 낫다고 가정하지 않습니다. 동일 OOS에서 이기지 못하면 research-only입니다.
- 학습 feature와 미래 return label은 물리적으로 분리하고 train/validation/OOS 사이에 embargo를 둡니다.
- RL 모델은 목표 비중 제안자일 뿐 Risk Gate와 실행 계층을 우회하지 못합니다.
- ResearchStore의 `strategy_allocations`에서 계산한 ETF 전략은 이 S&P 500 개별주 universe에 섞지 않고
  benchmark/reference로만 사용합니다. ETF sleeve를 추가하려면 별도 헌법 변경이 필요합니다.

## 8. 실행과 승격

```text
evaluation evidence
→ model artifact를 shadow → paper → live로 한 단계씩 사람이 manual promotion
→ fresh full PortfolioProposal + approved RiskDecision
→ 사람이 risk_decision ID 재입력
→ expiring ExecutionIntent
→ Toss 주문 manifest
→ Paper는 분석·승격 증거 단계이며 외부 모의주문을 실행하지 않음
→ Live Manual은 Discord의 짧은 유효시간 서명 승인과 승인 원자 소비
→ Live Autonomous는 장기간 증거에 결박된 durable autonomy permit 검사
→ 제출 직전 계좌·가격·Risk·공식 거래시간 재검증
→ Toss broker API
→ append-only attempt/event 원장과 broker reconciliation
```

- 실계좌 조회, `NON_EXECUTABLE` preview, 주문 생성 POST, 주문/부분체결 reconciliation은
  `investment_agent.execution`에 구현합니다. 코드 존재만으로 live가 활성화되지는 않습니다.
- Toss credential은 `investment_agent.execution` 전용 프로세스에만 존재합니다. 분석·학습·LLM 환경에
  주입하지 않습니다.
- Discord의 자유문장·답장·reaction은 주문 명령이 아닙니다. 승인 대상의 intent ID·hash·만료시각,
  guild/channel/message ID와 본인 Discord user ID가 모두 일치하는 서명 버튼만 승인 이벤트로
  기록합니다.
- 승인 뒤에도 계좌·미체결 주문·현재가·매수가능금액·Risk 한도를 다시 확인합니다.
- 운영 lifecycle은 `BACKTEST → SHADOW → PAPER → LIVE_MANUAL → LIVE_AUTONOMOUS`를 한 단계씩만
  이동합니다. model artifact stage와 운영 lifecycle을 하나의 `mode`로 섞지 않습니다.
- Live Autonomous는 OOS, walk-forward, Paper 기간, 성과, 데이터·risk·execution·reconciliation
  무사고, kill switch test와 완전한 hard limits를 모두 증명한 permit 없이는 열리지 않습니다.
- Live 주문 진입점은 존재하지만 `TOSS_LIVE_ENABLED=false`와 `TRADING_KILL_SWITCH=on`이 기본입니다.
  자동 Champion 교체, 자동 모델 승격, 안전 스위치 자동 해제는 금지합니다.
- timeout/5xx 결과 불명 주문은 같은 client order ID로 자동 재전송하지 않고 reconciliation과
  운영자 확인 대상으로 남깁니다.
- 종목별·전체 notional 한도 초과는 clipping하지 않고 전체 주문 계획을 거부합니다.
- broker가 execution truth입니다. 내부 주문·체결·현금·포지션이 다르면 safe repair 또는 lockdown과
  경보로 처리합니다.

## 9. 의존성 방향과 파일 소유권

```text
universe/data → context/contracts → agents/models → optimizer/risk
             → backtest/evaluation → promotion → execution → broker
```

- `context.py`: point-in-time EvidenceBundle 조립
- `agents/`: LLM 역할 실행과 구조화 제안
- `feature_layer.py`: 학습과 live inference가 공유하는 feature definition/hash
- `portfolio/`: 공통 signal·optimizer·비중 계약·Champion·Risk Gate
- `ml/`: Naive/Ridge/LightGBM/XGBoost baseline 비교
- `rl/`: feature·환경·SB3 학습·purge/embargo walk-forward
- `backtest/`: t 결정→t+1 체결 Native engine과 LumiBot validation
- `memory.py`/`evaluator.py`: 성숙한 결과 평가와 검색
- `../execution/`: broker 조회·주문 계획·Discord 승인·주문/체결 lifecycle

한 패키지가 다른 계층의 DB 쿼리나 vendor 객체를 임의로 소유하지 않습니다. 외부 프레임워크는
고정 commit과 선택 의존성으로 설치하며 상위 계약에 해당 프레임워크 타입을 노출하지 않습니다.

## 10. 변경 게이트

다음 변경은 테스트와 문서 갱신 없이는 병합하지 않습니다.

- universe 범위 또는 point-in-time 규칙 변경
- TradingAgents 역할 순서·도구 vendor 변경
- 뉴스·소셜 local cache 보존기간 또는 historical 격리 변경
- signal·optimizer·Risk·Execution 계약 변경
- reward·성과 평가식 변경
- Paper/Live 승격 조건 또는 broker credential 경계 변경
