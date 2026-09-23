# Investment Decision Engine Design — 자동매매 판단 엔진 13단계의 현재 수식·비평·대체안·검증 기준 SSOT

> **문서 역할**: Factor → ML → AI 판단 계층 → Alpha → 공분산 → Optimizer → Regime → No-trade band → Tail risk → RiskGate → TCA → RL → 평가 구간 전체의 **현재 수식(코드 대조), 비평, 대체 수식, 검증 설계, 판정**을 소유한다.
> **기준 SHA**: `d9bb5a3` (main)
> **기준일**: 2026-09-23
> **상위 문서**: 불변 원칙·P0·구현 순서는 [SYSTEM_UPGRADE_MASTER.md](SYSTEM_UPGRADE_MASTER.md)가 갖는다.
> **구성**: Part I(§1~§19) 수치 엔진, Part II(§41~§58) AI 판단 계층과 토큰 비용, Part III(§59~§60) 데이터 사용 감사와 기관 수준까지의 거리. §20~§40은 비워 둔다 — Part II 번호를 코드 주석(`llm/usage.py`, `analysis.py`의 §50)이 참조하므로 바꾸지 않는다.

---

## 1. 판정 체계와 표기

| 판정 | 의미 |
|---|---|
| **KEEP** | 현행 유지 |
| **REFINE** | 구조는 유지하고 내부 계산만 개선 |
| **CHALLENGER** | Champion을 유지한 채 비교 후보를 추가 |
| **PARTIAL REPLACE** | 일부 계산 또는 계약만 교체 |
| **RESEARCH** | 검증에 필요한 표본이 아직 없다. Production 반영 금지 |
| **DO NOT IMPLEMENT** | 이 시스템의 제약에서 위험 대비 가치가 낮다 |

검증 가능성은 따로 적는다.

| 표기 | 의미 |
|---|---|
| **OOS-NOW** | 지금 있는 데이터(가격 7년, 주간 feature 스냅샷 260개)만으로 out-of-sample 검증 가능. LLM 판단이 필요 없다 |
| **WAIT(n)** | 표본 n이 쌓여야 검증 가능. n과 예상 도달 시점을 함께 적는다 |

숫자의 출처는 반드시 붙인다.

| 표기 | 의미 |
|---|---|
| **[실측]** | 이 저장소의 원장·artifact·재현에서 직접 잰 값 |
| **[재구성]** | 저장된 artifact로 호출 payload를 다시 만들어 토크나이저로 센 값. 호출 당시 계측은 아니다 |
| **[추정]** | 가정을 명시한 계산 |
| **[문헌]** | 외부 연구값. 그 연구의 유니버스·기간·비용 가정이 이 시스템과 어떻게 다른지 함께 적는다 |

> **Challenger가 존재한다고 Champion이 폐기되는 것은 아니다.** 그리고 문서에 적힌 수식은 구현의 증거가 아니다.

---

## 2. Master Decision Matrix

| 단계 | 현재 | 판정 | 우선 후보 | 검증 |
|---|---|---|---|---|
| 1 Factor 결측 | 가용 category 재정규화 + coverage 문턱 0.5 | REFINE | 신뢰도 가중 중립 수축(§5.3) | OOS-NOW |
| 1 Factor 가중 | equal weight | CHALLENGER | 경험적 Bayes 수축 IC 가중(§5.5) | OOS-NOW |
| 1 balance_sheet 결측 | 게이트 검사를 건너뜀 | REFINE (feature 정의) | 무차입·음(-)자본을 feature에서 정의(§5.4) | OOS-NOW |
| 2 ML 채택 | **채택된 모델 없음 → 운영 ML 몫 0** | — | 채택 여부는 사람의 결정(§6.1) | — |
| 2 ML 신뢰도 | `min(0.8, 10·IC)` | PARTIAL REPLACE | OOS 스태킹 회귀 계수(§6.3) | OOS-NOW |
| 2 ML 검증 | 단일 분할(`splits[0]`) | REFINE | 모든 walk-forward 창 사용(§6.5) | OOS-NOW |
| 2 `probability_up` | 전체 적중률 복사, 소비자 0 | DO NOT IMPLEMENT (보정) | 소비자가 생길 때까지 계약에서 뺀다(§6.4) | — |
| 2.5 AI 판단 계층 | 14호출 순차, gpt-5-mini 단일 | KEEP 구조 + REFINE payload | §56 로드맵 | 일부 지금, 일부 WAIT |
| 3 Alpha 스케일 | IC 0.04 고정, z ±2.05 clip | REFINE | 측정 IC·Blom z(§7.2·§7.3) | OOS-NOW |
| 3 factor·ML 결합 | 선형 보간 `(1-c)·prior + c·ml` | PARTIAL REPLACE | OOS 스태킹(§7.4) | OOS-NOW |
| 3 LLM tilt | `0.25 × LLM 자칭 confidence` | REFINE | 상수 → 검증된 R_L(§7.5) | WAIT(채점 200건) |
| 3 confidence 곱 | 방향 일치 비율 {0, ½, 1…} | PARTIAL REPLACE | 기대수익에서 떼고 불확실성 항으로(§9.3) | OOS-NOW(ML/factor), WAIT(LLM) |
| 3 Black-Litterman | 없음 | DO NOT IMPLEMENT | τ·Ω를 추정할 근거 없음(§7.6) | — |
| 4 공분산 | LW 상수상관, 일별×20 | KEEP | EWMA 수축 challenger, 분산비 점검(§8) | OOS-NOW |
| 5 **현금 편향** | 초과수익 μ vs 현금 대안, λ=5 | **PARTIAL REPLACE** | 노출 분리 + SPY 대비 active 목적함수(§9.2) | OOS-NOW |
| 5 factor 노출 제약 | 실패 시 통째 제거 | REFINE | slack + 쌍대가격 기반 벌점(§9.5) | OOS-NOW |
| 5 미분류 섹터 | optimizer 무제약, gate는 합계 검사 | REFINE | `_unmapped` 한 묶음(§9.7) | 계약 테스트 |
| 6 Regime | SPY 4단계 계단, hysteresis 없음 | CHALLENGER | 연속 노출 + 느린 복구(§10) | OOS-NOW |
| 7 No-trade band | 고정 1% | KEEP | 동적 밴드는 RESEARCH(§11) | OOS-NOW(비용 가정 하) |
| 8 Tail 축소 | 비례 축소, 최대 3회 | KEEP | 2025 재현에서 한 번도 발동 안 함(§12) | — |
| 9 RiskGate | 결정론 hard limit | KEEP (완화 금지) | HHI 한도의 무력함은 사람의 결정(§13.1) | — |
| 10 TCA | ADV 구간 정적 반스프레드 | KEEP | IS 계측 준비(§14) | WAIT(체결 ~400건) |
| 11 RL | direct weights, research 격리 | RESEARCH | overlay는 RL 대신 규칙으로(§15) | — |
| 12 평가·귀속 | LLM P(up) Brier, 귀속 호출자 0 | REFINE | ablation 재현 기반 출처 귀속(§16) | WAIT(채점·체결) |
| 자동 승격 | 없음 | KEEP | 영구 금지 | — |

---

## 3. 수식 대조 — 인수인계 수식과 코드가 다른 곳

인수인계 문서(2026-09-23)가 옮긴 수식을 canonical 파일과 한 줄씩 대조했다. **다른 곳만** 적는다. 여기 없는 수식은 옮긴 그대로 맞다.

| 단계 | 인수인계의 서술 | 코드의 실제 | 영향 |
|---|---|---|---|
| 2 | "ML 몫 c = min(0.8, 10·IC)가 alpha에 들어간다" | `artifacts/trading/ml_models/active_ml_model.json`이 **존재하지 않는다**. `champion_forecast`가 "no adopted ML model artifact"를 돌려주고 c=0이다 | **단계 2 전체가 운영 경로에서 꺼져 있다.** 2025 재현도 `ml_forecasts_applied=0` [실측] |
| 2.5 | "뒤쪽 호출(RM·trader·PM·structuring)이 앞선 리포트를 다시 싣는다" | 5개 리포트 전문은 **8개 호출**(bull·bear·RM·trader·aggressive·conservative·neutral·PM)에 실리고, structuring은 그것을 state 안에 한 번 더 싣는다 | 중복 규모가 인수인계보다 크다(§54) |
| 2.5 | "structuring이 state를 통째로 싣는다" | state 안에서 토론 발언이 `*_history`·`history`·`current_*`로 **2~3번씩 중복**된다. 57/57건에서 무손실 제거 가능 [실측] | §55.2 |
| 2.5 | "payload 실측 artifact 57건" | 57건은 전부 **옛 엔진**(`0.5.0` 20건, `0.6.0` 37건)이다. 현재 엔진 `0.7.1-local-graph-macro-h20-news7d`(macro 분석가 포함, `thesis`·`hard_constraint` 계약)로 **완료된 판단은 0건**이다 [실측] | 모든 토큰 수치는 현재 그래프의 근사치다 |
| 2.5 | "UsageLedger가 호출별 토큰을 누적" | `prompt_tokens`·`completion_tokens`만 읽는다. **reasoning 토큰·cached 토큰은 버린다.** 역할별로는 호출 **수**만 남고 토큰은 합계뿐이다. 분석가 입력 원문은 저장되지 않는다 | 역할별 최적화의 근거를 만들 수 없다(§50) |
| 3 | "p(i) = alpha universe 내 백분위" | `_z_scores`는 **점수가 있는 전 종목**(약 500)의 백분위다 | 후보 40종목의 z는 대략 1.4~2.05에 몰리고, **상위 약 2%(≈10종목)는 전부 2.05로 동률**이 된다(§7.3) |
| 3 | tilt 조건 "논지 positive && α₀ > 0" | `thesis=='positive'` **그리고** `expected_excess_return>0 && probability_up>0.5`일 때만 positive | 긍정 논지라도 수치가 엇갈리면 neutral이다 |
| 3 | (누락) | 품질 게이트 탈락 보유 종목은 `α = min(0, α)` + `block_increase`(`FACTOR_BREAKDOWN`) | — |
| 5 | "infeasible이면 노출 제약 제거" | **어떤 `ContractError`든** 노출 제약을 빼고 다시 푼다(노출과 무관한 실패 포함). 두 번째도 실패하면 목표를 갱신하지 않는다 | §9.5 |
| 5 | "섹터 맵 결측 종목은 제약을 받지 않는다" | optimizer에서는 맞다. 그러나 RiskGate는 **미분류 합계 > 0.30이면 목표 전체를 거부**한다 | optimizer와 gate가 다른 규칙 → 거부로 이어질 수 있다(§9.7) |
| 5·9 | "sector" | 섹터는 GICS가 아니라 **SIC division**(`select_sp500_sector_map`)이다. value의 "업종 내 순위"도 같다 | 상한 0.30과 업종 내 순위의 의미가 GICS와 다르다(§5.6, §13.2) |
| 8 | "CVaR 한도 0.08" | 맞다. 단 이것은 `SystemPortfolioPolicy.max_cvar_95_5d`가 넘기는 값이고, gate 기본값의 유도식(2.0627·σ·√(5/252)≈0.087)은 이 경로에서 **쓰이지 않는다** | §13.3 |
| 8 | "260일 표본이면 5일 창이 52개" | 창은 **겹친다** — 약 255개이고 최악 5%는 12개다. 다만 겹침 때문에 독립 표본은 약 51개다 | 추정 오차 논의는 §12.2 |
| 9 | (누락) | 스트레스 시나리오 손실 한도 `β_max × 0.10 = 0.15`로 위험자산 비례 축소, turnover 뒤 최종 위험 재측정·재축소가 있다 | — |
| 11 | reward `log(1+R) − λ_TO·TO − λ_DD·ΔDD⁺ − λ_tail·Tail` | 이것은 문서의 제안이다. 현재 코드는 **6항**(return·alpha·drawdown·volatility·turnover·concentration) 가중합이다 | §15 |
| 12 | (누락) | `direction_correct`는 `signal` 단어로 판정한다. 새 계약은 `legacy_signal()`이 논지에서 `signal`을 유도하므로 동작은 한다. `neutral` 논지는 `watch` → 방향 판정 없음 | — |
| 재현 | "평균 현금 59%" (이 문서 앞 판) | `performance_summary`의 `cash_weight`는 **마지막 날** 값이다. 재현에 기간 평균(`average_cash_weight`)을 추가했다 | 앞 판의 수치 표현 정정 |
| 재현 | (발견) | 변형마다 NAV를 자기 첫 기록일부터 쌓아, 공통 구간만 잘라도 **SPY 수익률이 변형마다 달랐다**. 공통 구간 첫날을 100으로 다시 맞춘다 | 변형 간 비교가 같은 기간이 됐다 |
| 회계 | (발견, 수정됨) | `market.prices_daily.close`는 **분할 조정** 가격인데 System 회계가 분할일에 `split_ratio`를 한 번 더 곱했다 — GOOGL 20:1 분할일 +92%, NVDA 10:1 분할일 +25% | 운영 System NAV·성과 카드에도 같은 오류. 수정 전 재현 결과는 무효 |
| 5·9 | (발견, 수정됨) | GOOG·GOOGL(표본 상관 0.998)·FOX·FOXA(0.986)가 둘 다 상위에 들어 optimizer가 둘 다 사면 RiskGate가 **목표 전체**를 거절했다(2025 재현에서 목표의 약 40%) | 거절된 주는 현금이 그대로 남는다 — 현금 편향의 두 번째 원인 |

---

## 4. 데이터 현실과 검증 가능성

```text
decision_evaluations   0행   첫 20일 채점 가능 ≈ 2026-10-07 (하네스가 돌 때만)
attribution_reports    0행
intents/orders/fills   0행
completed 판단        57건   2026-09-09~15, 전부 옛 엔진(0.5/0.6)
현재 엔진 판단         0건
feature snapshot     260개   주간(중앙 간격 7일), 2021-09-03 ~ 2026-09-22
                             revision 계열은 2026-09-13 이후에만 값이 있다
가격 이력            약 7년 (Supabase)
채택 ML 모델          없음
LLM 토큰 계측          0건   계측 코드도 reasoning·cached·역할별 토큰을 버린다
system_ablation      2025 재현 1회 (factor 스냅샷이 있는 51개 재조정 시점)
하네스                STOPPED
```

이 현실이 판정을 가른다.

- **LLM이 필요 없는 것은 지금 검증할 수 있다(OOS-NOW).** factor·ML·alpha 스케일·optimizer·regime·공분산은 가격 7년과 주간 스냅샷 260개로 rolling OOS 재현이 된다. `system_ablation`의 `factor_only` 변형이 그 인프라다.
- **LLM 논지·체결이 필요한 것은 기다려야 한다(WAIT).** LLM 신뢰도 R_L, 논지 tilt, 비용 모델 교체, 귀속은 표본이 없다.
- 따라서 **Part I의 개선은 표본을 기다릴 이유가 없고, Part II의 품질 판단은 기다려야 한다.** 비용 절감 중 품질과 무관한 것(무손실 payload 축소)은 기다리지 않는다(§56).

---

## Part I — 수치 엔진

## 5. 단계 1 — Factor 점수

Canonical: `src/investment_agent/research/factors/core.py`

### 5.1 현재 (코드 대조 완료)

```text
members: quality 6, balance_sheet 2, growth 2, value 3, revision 2, momentum 2
rank_f(i)   같은 시점 백분위(동률 평균순위, 단일 종목 0.5). value만 SIC division 안 순위(표본<5면 전체 순위)
C_k(i)      = mean(rank_f) over 관측된 members,  단 |관측|/|members| ≥ 0.5 일 때만
Composite   = Σ_k w_k·C_k / Σ_k w_k  (C_k가 있는 k만),  w_k = 1
게이트      quality 결측 → 탈락, C_quality < 0.3 → 탈락, C_bs 존재 && < 0.2 → 탈락
```

실측(2026-09-22 횡단면): 게이트 통과 347종목 중 6개 category를 모두 가진 종목 312, 5개 30, 4개 이하 5. 상위 40 중 36종목이 6개 전부다.

### 5.2 비평

1. **재정규화는 결측을 "평균 이상"으로 읽는다.** 결측 category는 분모에서 빠지므로, 좋은 category 셋만 있는 종목이 여섯이 다 있는 종목보다 높아질 수 있다. 결측이 무작위가 아니라는 점(공시 지연·특수 재무구조)을 생각하면 방향이 정해지지 않은 편향이다.
2. **coverage 문턱과 재정규화가 서로 싸운다.** 문턱을 올리면 category가 결측이 되고, 결측은 재정규화로 오히려 점수를 올린다. 두 장치를 따로 조정하면 안 된다 — 하나로 합쳐야 한다.
3. `Composite × Coverage^γ`는 이 문제를 풀지 못한다. 백분위 척도에서 곱셈 벌점은 점수를 **0 쪽으로** 끌어 결측을 "나쁨"으로 읽는 것과 같다(0.5가 아니라). γ에 근거도 없다. **채택하지 않는다.**
4. 백분위 → rank-gauss/winsorized z 변환은 composite의 **순서**를 거의 바꾸지 않는다(category 평균이 이미 중앙 극한으로 부드럽다). 20일 horizon에서 차이를 만들 곳은 composite 계산이 아니라 단계 3의 z 변환이다(§7.3). **DO NOT IMPLEMENT**.

### 5.3 대체 수식 — 신뢰도 가중 중립 수축 (REFINE)

한 category의 m개 member 순위를 같은 잠재 점수의 잡음 섞인 측정으로 본다. member 간 평균 순위상관이 ρ_k이면 m개 평균의 신뢰도는 Spearman-Brown 식이다.

```text
R_k(m)  = m·ρ_k / (1 + (m−1)·ρ_k)  =  m / (m + n0_k),   n0_k = (1 − ρ_k)/ρ_k

C̃_k(i) = 0.5 + [R_k(m_i) / R_k(M_k)] · (C_k(i) − 0.5)     m_i: 관측 member 수, M_k: 전체 member 수
         m_i = 0 이면 C̃_k = 0.5

Composite(i) = Σ_k w_k · C̃_k(i) / Σ_k w_k        (분모는 모든 k — 재정규화 없음)
```

- **완전 관측이면 현행과 정확히 같다**(R(M)/R(M)=1). 바뀌는 것은 결측·부분 관측 종목뿐이다 — 변경이 필요한 곳에만 닿는다.
- coverage 문턱 `_MIN_CATEGORY_COVERAGE`는 **필요 없어진다.** 부분 관측은 버리지 않고 신뢰도만큼 줄인다. §5.2-2의 상호작용이 식 하나로 사라진다.
- ρ_k는 추정값이 아니라 데이터로 정한다. 주간 스냅샷(4주 간격 표본)의 member 간 평균 순위상관 중앙값 [실측]:

  | category | ρ_k | n0_k | 1개만 관측 시 R(1)/R(M) |
  |---|---|---|---|
  | quality (6) | 0.164 | 5.10 | 0.30 |
  | balance_sheet (2) | 0.404 | 1.47 | 0.71 |
  | growth (2) | 0.304 | 2.29 | 0.64 |
  | value (3) | 0.457 | 1.19 | 0.53 |
  | momentum (2) | 0.649 | 0.54 | 0.88 |
  | revision (2) | 표본 부족(2026-09-13 이후) | — | 수집 3개월 뒤 산출 |

  ρ_k는 `FactorModel` 버전에 고정해 기록하고, 재추정은 버전을 올릴 때만 한다(학습 데이터로 매번 움직이면 순위가 조용히 흔들린다).
- 품질 게이트는 C̃가 아니라 **원래 C_k**로 판정한다 — 게이트는 "알려진 나쁨"을 거르는 장치이고, 수축된 값으로 판정하면 결측 종목이 게이트를 더 쉽게 통과한다.

**검증 (OOS-NOW)**
- 비교: Champion(재정규화) vs Challenger(§5.3), 같은 260개 스냅샷, 20거래일 SPY 대비 초과수익.
- 메트릭: 주간 횡단면 rank IC의 평균·ICIR·HAC t(겹침 lag = 3주), 그리고 **두 방법이 다르게 순위를 매긴 종목**(부분 관측 종목)만의 상위 40 편입 후 20일 초과수익 차이.
- 필요 표본: 부분 관측 종목은 스냅샷당 약 35종목이라 260개 스냅샷이면 약 9천 관측 — 충분하다.
- 판정 기준: 전체 IC가 나빠지지 않고(차이의 HAC 95% 구간이 −0.005 이상), 부분 관측 종목의 상위 편입 성과가 Champion보다 낮지 않으면 채택 후보. 그 다음 `system_ablation` factor_only 재현에서 포트폴리오 지표를 본다.

### 5.4 balance_sheet 결측 — 비대칭이 아니라 feature 정의 문제

2026-09-22 횡단면에서 balance_sheet가 결측인데 게이트를 통과한 18종목 [실측]:

```text
AES AMP ANET AZO CAT CPRT ERIE GM HCA ISRG MNST MO NVR PCAR PM SBAC TDG YUM
```

은행이 아니다. 두 부류가 섞여 있다.

- **무차입·이자비용 0**(ANET·ISRG·MNST·CPRT·NVR·ERIE 등): 이자보상배율이 정의되지 않는다. 재무건전성은 **최상위**다.
- **음(-)의 자기자본**(AZO·MO·PM·YUM·HCA·SBAC·TDG 등, 대규모 자사주 매입): D/E가 정의되지 않는다. 건전성은 **불확실하거나 낮다**.

게이트가 결측을 건너뛰는 것(현행)도, 결측을 탈락시키는 것도, §5.3의 중립 0.5도 이 두 부류를 **같은 값**으로 다룬다. 고칠 곳은 게이트가 아니라 feature다.

```text
interest_coverage: 이자비용 = 0 이고 영업이익 > 0  →  상위 cap 값(유니버스 99백분위)
debt_to_equity:    자기자본 ≤ 0                    →  D/E 대신 net_debt / EBITDA 순위로 대체
                   (EBITDA ≤ 0 이면 최하위)
```

- 판정: **REFINE (feature 정의)**. 게이트 규칙은 그대로 두고, 정의가 생긴 뒤 결측이 남는 종목만 §5.3을 따른다.
- 검증(OOS-NOW): 18종목류의 게이트 통과·순위 변화를 과거 스냅샷에서 세고, 그 종목들의 20일 초과수익 분포를 비교한다. 순위를 바꾸므로 사람의 결정을 거친다(감사 RR2-02와 같은 자리).
- 구현 위치는 feature owner(`src/investment_agent/research/features/`)이고 PIT 규칙(공시 가용 시각)을 그대로 따른다.

### 5.5 가중치 — 경험적 Bayes 수축 IC (CHALLENGER)

롤링 IC는 잡음이 크다. 인수인계의 `IC* = ρ·IC_long + (1−ρ)·IC_recent`에서 ρ를 사람이 고르지 않고 **잡음 분산과 신호 분산의 비**로 정한다.

```text
IC_long,k   전체 과거(확장 창) 평균 주간 rank IC
IC_rec,k    최근 26주 평균
σ²_e,k      IC_rec의 표본오차 분산 = HAC 분산(겹침 lag 3) / 26
τ²_k        진짜 IC의 시간 변동 = max(0, Var(26주 롤링 IC) − mean(σ²_e))
B_k         = σ²_e,k / (σ²_e,k + τ²_k)            (0이면 최근을 믿고, 1이면 장기만 믿는다)
IC*_k       = IC_long,k + (1 − B_k)·(IC_rec,k − IC_long,k)

w_k         = max(0, IC*_k) / Σ_j max(0, IC*_j),   단 w_k ≤ 0.35, 모든 w_k = 0 이면 equal weight 유지
```

- 가중치는 **자동으로 바뀌지 않는다.** 분기마다 산출해 새 `FactorModel` 버전 artifact로 만들고 사람이 채택한다(`load_factor_model_from_ic_report`가 이미 그 경로다).
- 검증(OOS-NOW): 가중치를 t 시점까지의 IC로만 만들고 t 이후 20일로 평가하는 확장 창 walk-forward. 메트릭은 composite rank IC·ICIR과 factor_only 재현의 초과수익·turnover. 다중비교: equal / IC* / IC_long 세 후보이므로 `required_t_stat(3)`을 적용한다.
- 판정 기준: IC* 가중이 equal weight 대비 ICIR을 개선하고 그 차이의 HAC t가 다중비교 보정 문턱을 넘을 때만. 넘지 못하면 equal weight가 Champion으로 남는다 — 이것이 가장 흔한 결과일 것이다([문헌] 복합 factor 가중 최적화의 OOS 이득은 대개 작다. 다만 그 연구들은 수천 종목·월간 리밸런싱이라 이 시스템의 500종목·주간과 표본 구조가 다르다).
- revision은 2026-09-13부터 값이 있어 IC 추정에 최소 26주가 필요하다 → revision 가중은 **WAIT(2027-03경)**. 그 전까지 revision은 equal weight를 유지한다.

### 5.6 value의 업종 내 순위가 SIC division 기준이다

`sp500_sector_map`은 GICS가 아니라 SIC division을 준다. "Manufacturing" 하나에 반도체·제약·자동차·소비재가 섞여 PSR 업종 내 비교의 의미가 약하다. 판정: **RESEARCH** — 대체 분류(SIC 2자리 major group)는 그룹당 표본이 5 미만인 경우가 많아 전체 순위로 떨어진다. 두 분류의 value IC를 OOS-NOW로 비교한 뒤에만 바꾼다.

---

## 6. 단계 2 — ML 예측과 신뢰도

Canonical: `src/investment_agent/research/ml_inference.py`, `src/investment_agent/research/ml_serving.py`, `src/investment_agent/research/training/walk_forward.py`

### 6.1 현재 — 운영에서 꺼져 있다

```text
y_i = R_i(20d) − R_SPY(20d)
c   = min(0.8, max(0, 10·mean_IC))   if has_dependence_aware_oos and HAC t ≥ 2,  else 0
P(up|i) = direction_accuracy (예측>0) / 1 − direction_accuracy (예측<0)  — 소비자 없음
검증 = purged_row_splits → splits[0] 하나
```

**채택 파일 `active_ml_model.json`이 없다** [실측]. 따라서 운영 alpha는 factor 사전값과 LLM 논지만으로 돈다. 이 절의 개선은 "ML을 켤 것인가"를 사람이 정하기 위한 **근거를 만드는 작업**이다. 채택은 `adopt_ml_model`, 사람의 행위로 남는다.

### 6.2 비평

1. `10·IC`는 "IC 0.05면 강하다"는 관례를 선형으로 옮긴 것이다. 결합 가중치가 IC에 비례해야 한다는 근거는 없다 — 최적 가중은 두 추정기의 **오차 분산과 공분산**에 달려 있다(§7.4).
2. Brier 기반 `c = 1 − 2·Brier`는 회귀 모델에 맞지 않는다. 이 ML은 확률을 내지 않는다. **채택하지 않는다.**
3. c가 모든 종목에 같다. 종목별 불확실성을 쓰려면 분위수/conformal 모델이 먼저 있어야 한다 → CHALLENGER로 남긴다(§6.6).
4. 단일 분할은 결과가 "그 분할이 어느 regime이었나"에 좌우된다. `make_purged_walk_forward_splits`가 이미 여러 창을 만드는데 첫 창만 쓴다.

### 6.3 대체 — OOS 스태킹으로 c를 대신한다 (PARTIAL REPLACE)

ML 신뢰도를 따로 만들지 않고, 단계 3의 결합 가중치를 **OOS 회귀로 직접 추정**한다(§7.4에 식). c는 그 회귀의 ML 계수로 대체된다. 이렇게 하면 "ML이 factor와 얼마나 겹치는가"(공분산)도 가중치에 들어간다 — 현재 `10·IC`는 ML이 factor를 그대로 재현해도 높은 몫을 준다.

### 6.4 `probability_up` — 보정하지 않는다

소비자가 0이다. Platt/Isotonic 보정을 만들어도 읽는 곳이 없다. 단계 12의 Brier는 LLM 값을 쓴다. **DO NOT IMPLEMENT** — 소비자가 생기면(예: 분류 challenger) 그때 그 모델의 OOS 예측 점수 → 실현 부호로 Isotonic을 학습한다. 그 전까지는 필드를 "전체 적중률 복사"라고 명시해 오해를 막는다.

### 6.5 Walk-forward — 모든 창을 쓴다 (REFINE, OOS-NOW)

```text
기간 단위 = feature 스냅샷(주간)
purge     = label 구간 [t, t+20거래일]이 다음 창 시작과 겹치는 train 행 제거  (≈ 4 스냅샷)
embargo   = max(1, feature 자기상관이 0.5 아래로 떨어지는 lag)  — 주간 스냅샷에서 1~2 예상, 실측으로 고정
창        = 확장 train, 26주 test, step 26주 → 260 스냅샷이면 약 7~8개 test 창
보고      = 창별 IC, 평균 IC, ICIR, 최악 창 IC, HAC t(창 결합)
```

- 채택 문턱은 `required_t_stat(comparisons)`을 그대로 쓴다. 판정은 **모든 창의 결합 t**와 **음(-)인 창의 수**를 같이 본다 — 평균 t가 높아도 창 절반이 음이면 불안정이다.
- `has_dependence_aware_oos`는 결합 통계에 대해 같은 조건(inference_method, horizon, hac_lags)을 요구하도록 옮긴다.

### 6.6 Learning-to-Rank·분위수 (CHALLENGER, OOS-NOW)

- LTR 학습은 "후보 40, 선택 20"이 아니라 **날짜별 전체 유니버스(~500)**를 query group으로 한다. 이 규모에서 LambdaMART는 유효하다. 평가는 NDCG@40, 상위 40 평균 초과수익, rank IC.
- 분위수 회귀(Q10/Q50/Q90)의 폭 `u_i = Q90 − Q10`은 §9.3의 불확실성 항 입력이 된다. conformal은 커버리지 보장이 교환 가능성 가정에 기대는데 시계열 횡단면에서는 깨진다 — 분위수 폭을 먼저 본다.
- 판정 기준은 §6.5와 같은 walk-forward, Champion 회귀 대비 IC 차이의 HAC t가 다중비교 문턱을 넘을 것.

---

## 7. 단계 3 — Alpha 결합

Canonical: `src/investment_agent/trading/decision/alpha.py`

### 7.1 현재 (코드 대조 완료, 차이는 §3)

```text
p(i)   = 점수가 있는 전 종목(≈500) 안의 composite 백분위
z(i)   = Φ⁻¹(clip(p, 0.02, 0.98))
prior  = IC·σ_i·z,   IC = 0.04,  σ_i = √Σ_ii (20일)
α₀     = (1 − c)·prior + c·clip(ml, ±σ)
품질 탈락 보유 → α = min(0, α₀) + block_increase
논지 broken/negative → α = min(α₀, view, 0) (bearish일 때) 또는 min(α₀, 0) + FORCE_EXIT/BLOCK_INCREASE
논지 positive(수치 동의) && α₀ > 0 → α = α₀ + 0.25·conf_LLM·(view − α₀)
유효 논지 없음 && 미보유 → α = min(α₀, 0) + BLOCK_INCREASE
confidence = 방향을 말한 근거 중 최종 α와 같은 방향의 비율
```

### 7.2 IC 0.04 고정 → 측정된 IC (REFINE, OOS-NOW)

IC가 전체 α의 스케일을 정한다. 0.04는 "문헌의 복합 factor IC 0.03~0.06"에서 온 값이다([문헌] 미국 대형주 월간 횡단면 연구가 대부분이며, 이 시스템은 20거래일·S&P 500·주간 재조정이다).

**실측** (`src/investment_agent/research/commands/factor_research.py`, 2021-09~2026-08 주간 259시점, 가격 수익률, 생존 종목 편향 있음):

| 신호 | 5일 IC (t_adj) | 20일 IC (t_adj) | 60일 IC (t_adj) |
|---|---|---|---|
| composite | +0.016 (1.65) | +0.014 (0.76) | +0.022 (0.77) |
| **composite, 품질 게이트 통과분** | +0.022 (2.31) | **+0.027 (1.49)** | +0.039 (1.38) |
| value | +0.015 (1.51) | +0.027 (1.36) | +0.038 (1.12) |
| growth | +0.009 (1.24) | +0.006 (0.48) | +0.013 (0.63) |
| momentum | +0.013 (0.95) | +0.002 (0.08) | +0.012 (0.32) |
| balance_sheet | +0.000 (0.06) | +0.002 (0.13) | −0.008 (−0.40) |
| **quality** | −0.005 (−0.56) | **−0.011 (−0.60)** | −0.019 (−0.70) |

- 가정한 0.04는 실측의 약 1.5~3배다. 20일에서 t≥2인 신호가 **없다** — factor 신호는 약하다.
- 품질은 **순위로는 음(-)**인데, 품질 **게이트**는 composite IC를 0.014 → 0.027로 올린다. 거르는 용도로는 쓸모가
  있고, 순위를 매기는 용도로는 해롭다. 이 구분이 §5.5 가중 연구의 출발점이다.
- t<2라 가중치 변경은 과적합 위험이 크다 — equal weight를 유지한다. IC는 아래 규칙으로 0.02다.
- revision은 이 표본에 값이 없다(2026-09-13부터 수집).

```text
IC_used = max(0, IC*_composite)   — §5.5의 수축 식을 composite 한 줄에 적용
          HAC t < 2 이면 IC_used = 0.02 (하한; 0으로 두면 factor 사전값이 사라져 alpha가 LLM만 남는다)
          상한 0.08
```

- **regime별 IC는 DO NOT IMPLEMENT.** 7년 동안 regime 전환이 수십 번뿐이라 regime당 IC 추정 표본이 부족하고, 추정 잡음이 곧바로 기대수익이 된다.
- IC는 `AlphaPolicy` 버전과 함께 기록한다. 자동 갱신하지 않는다.

### 7.3 z의 hard clip → Blom 점수 (REFINE, OOS-NOW)

현재 clip(0.02, 0.98)은 약 500종목 중 상위 약 10종목을 **전부 z=2.05로 동률**로 만든다 — optimizer가 가장 원하는 종목들 사이의 순서 정보가 사라진다.

```text
z(i) = Φ⁻¹( (r_i − 0.375) / (N + 0.25) )        r_i: 1..N 순위(Blom)
      N ≈ 500 이면 최댓값 ≈ 2.88, clip 없음
```

- 극단값의 폭주는 여기서가 아니라 optimizer의 기대수익 상한(§9.6)이 막는다.
- 검증: factor_only 재현에서 상위 10종목 간 비중 분포와 초과수익. 판정 기준은 초과수익이 나빠지지 않고 집중도(유효 종목 수 1/HHI)가 한도 안일 것.

### 7.4 factor·ML 결합 — OOS 스태킹 (PARTIAL REPLACE, OOS-NOW)

역분산 가중 `α = (prior/v_p + ml/v_m)/(1/v_p + 1/v_m)`은 두 추정기의 오차가 **독립**일 때만 최적이다. factor와 ML은 같은 feature를 먹으므로 오차가 상관된다. 상관까지 담는 가장 단순한 형태가 OOS 회귀다.

```text
각 날짜 t의 횡단면에서 (prior_i,t, ml_i,t, y_i,t) — 모두 t 이전 데이터로 만든 OOS 값
y_i,t = b_p·prior_i,t + b_m·ml_i,t + e_i,t            (날짜 고정효과 제거 = 횡단면 demean)

제약  b_p ≥ 0, b_m ≥ 0
수축  (b_p, b_m) ← (1−s)·(b̂_p, b̂_m) + s·(1, 0),   s = 1 / (1 + T_eff/T_0)
      T_eff: 겹침 보정한 독립 날짜 수, T_0 = 52(1년치) — 표본이 짧으면 "factor만"(현행 c=0)으로 당긴다
α₀ = b_p·prior + b_m·clip(ml, ±σ)
```

- ML 모델이 없으면 b_m = 0이고 b_p = 1 → **현행과 같다.** ML 채택 전에는 운영 동작이 바뀌지 않는다.
- 이 회귀는 IC 스케일도 함께 보정한다(b_p가 1에서 벗어나면 IC_used가 틀렸다는 뜻).
- 검증: 회귀를 확장 창으로 추정해 다음 26주에 적용, α₀의 rank IC와 "예측 α 대비 실현 초과수익 기울기"(1이면 스케일이 맞다).

### 7.5 LLM tilt — 자칭 confidence를 쓰지 않는다 (REFINE, WAIT)

비대칭 구조(LLM은 깎거나 소폭 확인만)는 **유지한다.** 대칭 가중평균은 LLM에게 기대수익 생성 권한을 준다(Master §4.2).

바꿀 것은 tilt 배율의 `view.confidence`(LLM 자칭)다. 옛 엔진 57건에서 이 값은 0.35~0.75, 중앙 0.6, 서로 다른 값 16개였다 [실측] — 정보인지 잡음인지 검증된 적이 없다.

```text
단계 A (지금 가능, 행동 변화 작음):  tilt = 0.25 × 0.6 = 0.15  (상수)
      자칭값의 중앙값으로 고정해 평균 효과는 유지하고 검증되지 않은 분산만 제거한다.
단계 B (WAIT: 채점된 현재 엔진 논지 ≥ 200건, 서로 다른 날짜 ≥ 40):
      R_L = clip( (AUC_L − 0.5)/0.5 , 0, 1 ) × CitationValidRate
      AUC_L: thesis_state=positive 여부로 20일 초과수익 부호를 가른 AUC (HAC 부트스트랩 CI)
      CitationValidRate: 구조화 1차 출력의 evidence 인용이 허용 ID 안에 있던 비율
      tilt = 0.25 × R_L
      AUC_L의 95% CI 하한이 0.5 이하이면 R_L = 0 → tilt 없음(거부권은 유지)
```

- 단계 A도 포트폴리오를 바꾸므로 factor_ml_thesis 재현 없이는 적용하지 않는다. 그런데 **논지 기록이 7일뿐이라 재현이 결론을 못 낸다**(Master P0-10). 따라서 단계 A는 **현재 엔진 논지가 4주 이상 쌓인 뒤** 과거 재현과 함께 판단한다.
- falsification 성공률은 R_L에 넣지 않는다 — falsification 조건이 계약에 없고, 넣으려면 스키마 변경이 먼저다(Phase 4).

### 7.6 Black-Litterman — DO NOT IMPLEMENT

BL은 τ(사전 불확실성)와 Ω(view 오차 공분산)를 정해야 한다. Ω는 LLM view의 실현 오차 분산이 필요한데 채점 0건이다. τ는 관례값(0.025~0.05)밖에 없다. 두 값을 임의로 두면 BL은 "임의 가중 평균"이 된다. §7.4의 스태킹이 측정 가능한 방식으로 같은 수축을 한다. **Ω를 WAIT(채점 ≥ 500) 뒤에도 추정할 수 없으면 도입하지 않는다.**

---

## 8. 단계 4 — 공분산

Canonical: `src/investment_agent/trading/portfolio/market_risk.py`

### 8.1 현재

LW 상수상관 수축(강도는 LW 2003 해석해, 하이퍼파라미터 없음), 가격 260행 → 일수익 약 259개, `× horizon_days(20)`. 한 종목이라도 날짜가 비면 `ContractError`로 목표를 만들지 않는다.

### 8.2 비평과 판정

- N ≈ 40~65, T ≈ 259 → N/T ≈ 0.15~0.25. 상수상관 타깃은 이 비율에서 적절하다. **KEEP.**
- EWMA(half-life 63일)는 regime 전환 뒤 반응이 빠르다. 대가는 유효 표본이 약 90일로 줄어 N/T가 0.5에 가까워지는 것이다 → EWMA 표본 공분산에 **같은 LW 상수상관 수축**을 얹은 형태만 CHALLENGER로 둔다. 통계적 factor(PCA 3~5)는 N=40에서 이득이 작다 — RESEARCH.
- 일별 × 20의 자기상관 무시: 분산비 `VR(20) = Var(R_20)/(20·Var(R_1))`를 optimizer 결과 포트폴리오들에 대해 과거 7년에서 잰다. VR의 95% 구간이 1을 포함하면 보정하지 않는다. 벗어나면 Newey-West 형태 `Σ_20 = 20·(Γ₀ + Σ_{l=1..5}(1 − l/6)(Γ_l + Γ_lᵀ))`를 CHALLENGER로 둔다.

**검증 (OOS-NOW)**: 매 재조정 시점에 각 추정기로 최소분산·optimizer 포트폴리오를 만들고 다음 20일 실현 분산과 비교한다. 손실은 QLIKE `L = σ²_real/σ²_pred − ln(σ²_real/σ²_pred) − 1`, 보조로 bias ratio. Diebold-Mariano 검정으로 Champion과 비교, 판정 기준 p < 0.05(두 challenger면 Holm 보정).

---

## 9. 단계 5 — Optimizer

Canonical: `src/investment_agent/trading/portfolio/optimizer.py`, `src/investment_agent/trading/system/target.py`

### 9.1 현재

```text
ᾱ = clip(α, ±1.0·σ),  μ = ᾱ × confidence
max μᵀw − 5·wᵀΣw − 0·‖w − w₀‖₁ − hᵀ|w − w₀|
s.t. 0 ≤ w ≤ u,  Σw ≤ 1 − min_cash − fixed,  turnover(base) ≤ 0.25,  βᵀw ≤ budget,
     factor 노출(quality ≥ 0.55, momentum ≤ 0.8, value ≤ 0.8), force_exit, block_increase, 섹터 ≤ 0.30
```

### 9.2 핵심 결함 — 구조적 현금 편향 (PARTIAL REPLACE, OOS-NOW)

**μ는 SPY 대비 초과수익인데, 대안 자산은 현금이다.** optimizer 입장에서 주식은 "α만큼만 벌고 시장 위험 전체를 지는" 자산이다 — 주식 위험 프리미엄이 어디에도 없다. 그래서 시장 위험이 보상받지 못한 위험으로 보이고, 현금이 합리적 선택이 된다.

크기를 [추정]으로 확인한다. 대각 근사에서 `w_i* = μ_i / (2λσ_i²) = IC·z/(2λσ_i)`. σ_i(20일) ≈ 0.085, IC = 0.04, z ≈ 1.7이면 종목당 약 8%지만, 후보 40종목의 평균 상관(≈0.3)이 공통 위험을 만들어 합계 위험자산 비중은 대략 `IC·z̄/(2λ·σ·ρ̄) ≈ 0.28` 수준에서 멈춘다. 거기에 confidence(≤1)를 곱한다.

**재현이 이것을 확인한다** [실측, `artifacts/research/ablation/latest.json`, 2025년, factor 스냅샷이 있는 51개 재조정]:

```text
factor_only   평균 현금 59.4%   수익 +9.44%   SPY +17.21%   초과 −7.77%p   연변동성 4.9%
              market_risk 조임 29/51회, tail 한도 발동 0/51회
factor_ml_thesis  현금 100% (재현 기간에 논지 0건 → 전부 UNVERIFIED_ENTRY_BLOCKED)
```

평균 40% 투자로 SPY의 0.41배 시장 노출이면 시장 몫은 약 +7.0%이고 나머지 약 +2.4%p가 선택 몫이다 [추정, 베타≈1 가정]. **선택은 작동했을 가능성이 있는데, 노출이 목표를 깎았다.** 초과수익 −7.8%p의 대부분은 종목 선택이 아니라 이 결함이다.

대체안 — **노출과 종목 선택을 분리한다.** Master §3의 철학("시장 위험이 커지면 개별 종목보다 전체 Exposure를 줄인다")을 식으로 옮긴 것이다.

```text
E_t   = 위험자산 목표 노출 = 1 − min_cash_t        (§10의 regime/overlay가 정한다 — optimizer가 아니다)

max_w  αᵀw − λ_a·(w − E_t·e_SPY)ᵀ Σ̃ (w − E_t·e_SPY) − hᵀ|w − w₀|
s.t.   Σw = E_t − fixed                             (투자 가능한 후보가 부족하면 아래 fallback)
       기존 제약 전부(종목·섹터·turnover·베타·노출·force_exit·block_increase)

Σ̃     : 후보 + SPY의 공분산(SPY 가격은 이미 조회하고 있다)
λ_a    : 목표 tracking error TE*에서 유도.  α의 횡단면 표준편차 s_α와 평균 잔차분산 σ²_ε에 대해
         λ_a ≈ s_α·√N_eff / (2·TE*_20d),  TE* = 연 6% (정책값, 재현에서 4%/6%/8% 비교)
```

- α가 SPY 대비 초과수익이므로 목적함수도 **SPY 대비 active 위험**이어야 일관된다. 시장 노출의 크기(E_t)는 α와 위험회피 계수의 부산물이 아니라 명시적 위험 예산이 된다.
- **등식 Σw = E_t의 fallback**: block_increase·검증 전 편입 차단으로 늘릴 수 있는 종목이 부족하면 해가 없다. 두 선택지가 있고 이것은 **사람의 결정**이다.
  - (F1) `Σw ≤ E_t`로 풀고 남는 것은 현금 — 안전하지만 편향이 부분적으로 남는다.
  - (F2) 남는 노출을 SPY(ETF)로 채운다 — "모르는 것은 시장으로". SPY가 tracked 종목이 아니라 RiskGate의 tradable 검사와 My Portfolio 실행 경로를 함께 바꿔야 한다.
- 이것은 **hard limit을 하나도 완화하지 않는다.** 최소 현금 5%, 종목 10%, 섹터 30%, 베타 1.5, CVaR·스트레스 한도는 그대로다. 바뀌는 것은 한도 안에서 현금을 얼마나 두느냐의 기본값이다.

**검증 (OOS-NOW)**: `system_ablation`에 변형 `exposure_split(F1)`을 추가하고 2021-09~2026-08 주간 스냅샷 전 구간(2025만이 아니라)에서 factor_only 두 변형을 비교한다.

| 메트릭 | 판정 기준 |
|---|---|
| SPY 대비 초과수익, 정보비율 | Challenger ≥ Champion |
| 실현 tracking error | TE* ± 50% 안 |
| 최대낙폭, CVaR95(5일) | 2022 약세장 구간에서 SPY보다 나쁘지 않을 것 |
| 연 turnover | 현행 한도 안(재조정당 0.25) |
| 평균 현금 | E_t 목표와 일치(설계 확인) |

2025년 한 해만으로는 판정하지 않는다 — 한 해는 regime 표본 하나다.

**재현 결과** [실측, `artifacts/research/ablation/v2_a`·`v2_b`, 2021-09-14~2026-08-31 공통 1,246거래일, 분할 회계
수정 뒤, 전 변형 NAV 가격 대사 불일치 0일, 논지·ML 없음]:

| 변형 | 초과수익 | IR | TE | 평균 현금 | 2022 MDD (SPY 24.5%) | 2022 CVaR95 5일 (SPY 7.0%) |
|---|---|---|---|---|---|---|
| factor_only (현행) | −45.8%p | −0.52 | 13.5% | 59.6% | 6.4% | 2.5% |
| benchmark_relative | **+12.4%p** | 0.14 | 7.1% | 14.7% | 19.7% | 6.0% |
| + 연속 노출(§10) | +12.2%p | 0.12 | 7.3% | 16.3% | 18.2% | 5.5% |
| + Blom z(§8) | −0.3%p | −0.05 | 7.3% | 14.3% | 19.9% | 6.0% |
| + IC 0.02(§7.2) | −8.0%p | −0.22 | 6.7% | 20.9% | 18.6% | 5.6% |

읽는 법:

- **현금 편향은 실재했고 교정은 효과가 있다.** 평균 현금 60% → 15%, TE가 목표 대역 안으로 들어온다.
- **그러나 교정 뒤의 초과수익은 선택이 아니라 2022년에서 나온다.** benchmark_relative의 연도별 초과수익은
  2021 +0.5%p, **2022 +4.5%p**, 2023 +0.9%p, 2024 −0.5%p, 2025 −0.6%p, 2026 +1.0%p다. IR 0.14는 5년이면
  t ≈ 0.3이다 — "SPY와 비슷하게 가면서 약세장 낙폭이 조금 작다"가 정확한 요약이다.
- **Blom z 하나로 초과수익이 12.7%p 움직인다.** 경로 하나에서 이 크기의 차이는 신호가 아니라 잡음이다.
  같은 이유로 연속 노출과 benchmark_relative의 차이(−0.2%p)도 판정할 수 없다. IC 0.02는 기대수익이 작아져
  현금이 다시 늘고(20.9%) 초과수익이 −8%p다 — 약한 신호를 더 약하게 쓰는 것은 노출 문제를 되살린다.
- **채택 기준표(`adoption_checks`)를 benchmark_relative와 연속 노출 변형이 모두 통과한다** [실측, `v3`]. 한도
  0.25를 넘은 재조정 4일(2022-06-15, 2022-09-28, 2024-08-07, 2025-04-08, 최대 0.31)은 모두 게이트가 현금 하한
  상향·섹터 상한·최소 비중 정리를 한 위험 축소였다 — 게이트는 재량 매매에만 turnover 한도를 건다.

**단계 진단** [실측, `stage_diagnosis`, 겹치지 않는 목표로만 t 판정]: 5년 동안 t≥2로 **손해를 낸 단계는
노출(현금) 하나**다 — factor_only 60일 t=−2.1·120일 t=−3.0, benchmark_relative도 남은 현금 15%가 60일 t=−2.5.
선택·비중 효과는 어느 기간에서도 판정 불가이고, factor IC는 5일에서만 유의(0.041, factor_only)하다.
품질 탈락·중복 차단 게이트도 판정 불가다.

노출 효과를 "시장 위험 예산이 강제한 현금 하한"과 "그 위에 optimizer가 남긴 현금"으로 나누면 [실측, `v3`,
시장 상태 252회 중 RISK_ON 97·NORMAL 92·RISK_OFF 47·CRISIS 16]:

| 변형 | optimizer가 남긴 현금 | 규칙이 강제한 현금 |
|---|---|---|
| factor_only | 120일 −3.4% (**t=−2.9, 손해**) | 60일 −0.4% (**t=−2.6, 손해**) |
| benchmark_relative | 60일 −0.3% (t=−1.4, 판정 불가) | 60일 −0.4% (**t=−2.6, 손해**) |
| + 연속 노출 | 60일 −0.3% (t=−1.3) | 60일 −0.3% (t=−1.3, 판정 불가) |

benchmark_relative는 optimizer의 현금 편향을 없앤다. 남는 손해는 RISK_OFF 15%·CRISIS 40% 계단식 현금 하한이고,
연속 노출(§10)이 그것을 판정 불가 수준으로 줄인다. 다만 두 변형의 총 초과수익 차이(−0.2%p)는 판정할 수 없다.

### 9.3 `μ = ᾱ × confidence` → 불확실성 항 (PARTIAL REPLACE)

confidence를 기대수익에 곱하면 "근거가 엇갈린다"가 "기대수익이 작다"로 읽힌다. 그리고 {0, ½, 1} 계단이라 근거 하나가 방향을 바꾸면 μ가 50% 점프한다(ML이 꺼진 현재는 방향 근거가 factor·논지 둘뿐이다).

```text
μ_i = ᾱ_i                                   (confidence를 곱하지 않는다)
목적함수에 −λ_a·Σ_i d_i·w_i²  추가
d_i = κ·ᾱ_i²·(1 − a_i)                        a_i: 방향 일치도(0~1, 현행 confidence 그대로)
    + (ML 분위수 모델 채택 후) κ_u·(u_i/3.29)²    u_i = Q90 − Q10
```

- 불일치가 크면 그 종목의 **추가 분산**으로 비중이 줄어든다. 계단 점프가 비중에는 2차 항으로 부드럽게 전달된다.
- κ는 "완전 불일치(a=0)면 해당 종목 최적 비중이 절반이 되는 값"으로 정의해 해석 가능하게 둔다: 대각 근사에서 `κ = σ_i²/ᾱ_i²`의 횡단면 중앙값.
- 검증: factor_only에서는 a_i가 거의 항상 1이라 차이가 없다 → factor_ml 변형(ML 모델 후보로)과 WAIT(논지)에서만 의미가 있다. 우선순위는 §9.2 뒤다.

### 9.4 turnover 벌점 τ = 0 — KEEP (의도대로 동작)

`_optimizer_policy_for`가 0으로 덮는다. 비용은 반스프레드 L1 항과 no-trade band, turnover 하드 제약이 맡는다. 반스프레드 1~10bp는 20일 α(수십 bp)보다 작아 L1 무거래 영역이 좁고, 실질 무거래 영역은 1% band가 만든다(§11). 의도대로다. 다만 `OptimizerPolicy`의 기본값 0.01은 운영에서 쓰이지 않는 값이라 오해를 부른다 — 기본값 주석에 "System 경로는 0으로 덮는다"를 적는 것으로 충분하다.

### 9.5 factor 노출 제약 — slack과 쌍대가격 (REFINE, OOS-NOW)

```text
(loadings − max)ᵀw ≤ ξ_max,k,   (loadings − min)ᵀw ≥ −ξ_min,k,   ξ ≥ 0
목적함수에 − Σ_k ν_k·ξ_k
ν_k = 과거 재현에서 제약이 풀렸던 날들의 쌍대변수(dual value) 분포의 90백분위
```

- ν_k를 "그 제약이 평소에 얼마만큼의 목적함수 가치를 막았는가"로 정하면, 평소(90%)에는 hard와 같게 작동하고 예외적인 날에만 굽는다. 너무 크면 infeasible과 같고 너무 작으면 장식이라는 딜레마를 데이터로 푼다.
- 부수 효과: 현재는 **노출과 무관한 실패**(예: 다른 제약 충돌)에도 노출 제약을 지운다. slack이 들어가면 재풀이 분기 자체가 없어지고, 남은 실패는 진짜 infeasible이 되어 목표 미갱신(fail-closed)으로 남는다.
- 검증: 재현에서 `exposure_limits_relaxed` 발생 횟수, 노출 위반 크기 분포, 성과 차이.

### 9.6 기대수익 상한 1σ

IC 0.04 × z 최대 2.05 = 0.082σ라 상한은 factor 사전값에 **발동하지 않는다.** 실제로 막는 것은 LLM view(옛 엔진 57건에서 최대 +25%/20일 [실측])다. 그런데 view는 alpha에서 이미 ±σ로 잘린 뒤 tilt 0.25로만 들어가므로 α의 실질 최대는 약 0.25σ다. 상한은 두 겹의 clip 뒤에 있는 **방어 장치**로 남기고(KEEP), IC·z로 유도한 값 `cap = 0.10 × 2.88 × σ ≈ 0.29σ`로 좁히는 것은 §7.2·§7.3과 함께 재현할 때 같이 본다.

### 9.7 미분류 섹터 — optimizer와 gate를 같은 규칙으로 (REFINE)

optimizer는 섹터 맵에 없는 종목을 제약하지 않고, RiskGate는 미분류 합계가 0.30을 넘으면 **목표 전체를 거부**한다. optimizer가 gate의 규칙을 몰라 거부될 목표를 만들 수 있다. 미분류 종목을 optimizer에서 `_unmapped` 한 섹터로 묶어 같은 상한을 건다. 후보에서 빼는 것보다 낫다 — 분류가 빠진 것은 데이터 문제이지 종목 문제가 아니다. 검증은 계약 테스트(미분류 3종목 × 0.12 입력에서 gate 거부가 사라지는지)로 충분하다.

### 9.8 시장충격 무시 — KEEP

[추정] 따라가는 계좌가 수천 달러, S&P 500 종목 ADV가 수억 달러면 주문/ADV ≈ 1e-6 수준이다. 제곱근 충격 모형 `I = η·σ_daily·√(q/ADV)`에서 η≈1, σ_daily≈2%면 약 0.2bp로 반스프레드보다 한 자릿수 작다. 계좌가 100배 커져도 약 2bp다. 가정은 타당하다. 체결 데이터가 생기면 §14에서 확인한다.

---

## 10. 단계 6 — Regime과 위험예산

Canonical: `src/investment_agent/trading/decision/regime.py`, `src/investment_agent/trading/risk/regime_budget.py`

### 10.1 현재

SPY 일봉만으로 trend(20일)·vol(20일 연율)·drawdown(252일). RISK_ON과 NORMAL의 한도가 같아 **trend는 한도에 영향이 없다.** 실효 규칙은 `drawdown ≥ 8% 또는 vol ≥ 30% → RISK_OFF(현금 15%)`, `drawdown ≥ 20% 또는 vol ≥ 50% → CRISIS(현금 40%, 증가 금지)`다. 2025 재현에서 51회 중 29회 조였다 [실측].

### 10.2 대체 — 연속 노출 + 느린 복구 (CHALLENGER, OOS-NOW)

§9.2가 노출 E_t를 optimizer 입력으로 만들면, 이 단계가 E_t의 owner가 된다. 새 경계를 발명하지 않고 **현재 경계 사이를 선형으로 잇는다.**

```text
E_vol = clip( σ*/σ̂_20 , E_min, 1 )
        σ* = SPY 20일 실현 변동성의 과거 7년 중앙값(실측으로 고정, 버전 기록),  E_min = 0.60
E_dd  = 1                                   DD < 0.08
      = 1 − 0.15·(DD − 0.08)/0.12            0.08 ≤ DD < 0.20   (0.08에서 0.85 → 0.20에서 0.70)
      = 0.60                                 DD ≥ 0.20
E*_t  = min(E_vol, E_dd, 0.95)
E_t   = E*_t                                 E*_t < E_{t−1}   (Fast Down)
      = E_{t−1} + η·(E*_t − E_{t−1})         otherwise        (Slow Up)
η     = 1 − 2^(−1/h),  h = 복구 반감기(재조정 횟수 단위). 후보 h ∈ {1, 2, 4} (주간 재조정 → 1·2·4주)
min_cash_t = max(0.05, 1 − E_t)
```

- CRISIS의 "증가 금지"와 종목·섹터 배율은 **그대로 둔다** — 조이기만 하는 hard 쪽 장치이고, 연속화 대상은 현금 수준뿐이다.
- 결과는 항상 기본 한도보다 같거나 엄격하다(`min_cash ≥ 0.05`).
- hysteresis의 비용과 이득을 재는 메트릭(재현, 2021-09~2026-08):

  | 메트릭 | 정의 |
  |---|---|
  | 회복 지연 비용 | Σ_t (E*_t − E_t)·r_SPY,t — 느린 복구로 놓친 시장 수익 |
  | whipsaw | 4주 안에 부호가 바뀐 |ΔE| > 0.05 변화 횟수 × 그때의 거래비용 |
  | 거짓 축소 | E_t < 0.9였는데 다음 20일 SPY가 +2% 이상인 횟수 |
  | 꼬리 절감 | 노출 축소 구간의 실현 CVaR95 − 축소 안 했을 때 |

  판정 기준: h 후보 중 (회복 지연 비용 + whipsaw 비용)이 가장 작으면서 꼬리 절감이 계단식 Champion보다 나쁘지 않은 것. 다중비교(3후보)는 부트스트랩으로 CI를 낸다.

### 10.3 regime과 tail 축소는 이중이 아니다

2025 재현에서 tail 한도 발동은 0회, regime 조임은 29회다 [실측]. 역할이 이미 갈라져 있다 — regime은 **시장 상태**로 노출을 정하고, tail(§12)은 **이 포트폴리오 고유의 꼬리**가 한도를 넘을 때만 막는 backstop이다. 합치지 않는다.

### 10.4 breadth·금리·크레딧 입력 — RESEARCH

입력 하나가 늘 때마다 PIT 신선도 실패 지점이 하나 는다(regime은 지금도 SPY 가격이 4일 넘게 낡으면 목표 생성을 멈춘다). 특히 HY 스프레드는 FRED ICE BofA가 최근 3년만 제공해 과거 재현이 3년으로 잘린다. 입력을 늘리려면 "그 입력이 없을 때 E_t를 어떻게 정하는가"(fail-safe = 입력 없는 식으로 계산)를 먼저 정하고, SPY-only 대비 거짓 축소·회복 지연이 줄어드는지 OOS로 보인 뒤에만 넣는다.

---

## 11. 단계 7 — No-trade band

Canonical: `apply_no_trade_band` in `src/investment_agent/trading/system/target.py`

- 현재: 고정 1%, 전량 청산은 예외, 합계가 1을 넘으면 band 미적용.
- 비용항과 중복인가: 아니다. 반스프레드 1~10bp의 L1 무거래 영역은 비중으로 환산하면 매우 좁아(α 수십 bp 대비), band가 실질 무거래 영역이다. band를 없애면 매 재조정마다 0.1~0.5%짜리 미세 거래가 쏟아진다 — 비용은 작지만 My Portfolio 쪽 주문 수와 사람 승인 부담이 는다.
- 동적 밴드 `band_i = max(b_min, β₁·σ_i·√Δt + β₂·s_i/P_i)`: 이론적으로 무거래 영역 폭은 비용과 위험회피의 세제곱근에 비례한다([문헌] Davis-Norman·Gârleanu-Pedersen 계열; 연속시간·단일 자산 가정이라 여기와 다르다). 이 시스템에서 β를 정할 비용 실측이 없다(fills 0행). **RESEARCH** — 체결 비용이 생기면 재현에서 turnover × 비용 − 추적 손실을 최소화하는 β를 격자 탐색한다.
- 작은 계좌 주의: My Portfolio가 따라갈 때 1%가 1주 가격보다 작을 수 있다. 이것은 System band가 아니라 execution의 정수 주식 반올림 문제다 — 여기서 풀지 않는다.
- 판정: **KEEP.**

---

## 12. 단계 8 — Tail risk 축소

Canonical: `fit_tail_risk` in `src/investment_agent/trading/system/target.py`, `historical_tail_losses` in `market_risk.py`

### 12.1 수렴 — 한 번이면 정확하다

현금 수익을 0으로 두므로 포트폴리오 수익률은 위험자산 비중의 배율에 **정확히 선형**이다. 변동성과 역사적 CVaR는 양의 1차 동차(`f(s·w) = s·f(w)`)라 `scale = limit/metric`을 한 번 적용하면 한도에 정확히 도달한다. 0.99 여유를 곱하므로 첫 반복에서 한도 안에 들고 둘째 반복은 break한다. **3회 한계에 걸려 한도를 넘긴 채 끝나는 경우는 없다**(가격 행렬이 반복 사이에 바뀌지 않는 한). KEEP.

### 12.2 추정 오차

260행이면 겹치는 5일 창 약 255개, 최악 5%는 12개다. 겹침 때문에 이 12개는 대개 **2~4개의 독립 사건**이다. 95% CVaR의 추정 오차가 크다는 뜻이다. EVT(GPD 꼬리)는 초과 표본이 수십 개 필요해 이 표본에서 불안정하고, filtered historical simulation은 GARCH 추정이 필요하다 — 둘 다 **RESEARCH**. 대신 판단 기록에 `worst_count`와 창 기간을 함께 남겨 "몇 개의 사건으로 잰 값인가"를 보이게 한다.

### 12.3 종목별 기여 축소·optimizer 안 CVaR — 지금은 가치가 낮다

component CVaR 기반 차등 축소나 Rockafellar-Uryasev 제약(`CVaR ≤ c`를 255개 시나리오의 선형 제약으로)은 구현이 어렵지 않다. 그러나 2025 재현에서 tail 한도는 **한 번도 발동하지 않았다**(cvar_5·cvar_12 변형도 결과 동일) [실측]. 발동하지 않는 장치를 정교하게 만드는 것은 순서가 틀렸다. §9.2가 노출을 올린 뒤 재현에서 발동 빈도가 의미 있게(재조정의 5% 이상) 생기면 그때 RU 제약을 CHALLENGER로 올린다.

---

## 13. 단계 9 — Deterministic RiskGate (완화 금지)

Canonical: `src/investment_agent/trading/risk/gate.py`. 한도 값의 SSOT는 코드이고 설명 표는 [INVESTMENT_SYSTEM.md](INVESTMENT_SYSTEM.md)다.

### 13.1 HHI 한도 0.15는 발동할 수 없다

`HHI ≤ max_symbol × (1 − min_cash) = 0.095 < 0.15`. 코드가 `concentration_hhi_limit_binds=False`로 이미 기록한다. 선택지는 둘이고 **사람의 결정**이다.

- 한도를 유효하게: `max_concentration_hhi = 1/N_min`. N_min = 15면 0.0667 — 투자 비중 95%에서 최소 약 14종목 분산을 강제한다. 이것은 **조이는** 변경이라 불변 원칙에 걸리지 않지만 포트폴리오를 바꾼다(재현 필요).
- 그대로 두기: 종목 상한 10%가 이미 더 센 제약이다. 장식이라는 사실이 원장에 남으므로 오해는 없다.

권고: §9.2 적용 뒤 재현에서 유효 종목 수(1/HHI)의 분포를 보고 정한다. 지금 바꾸지 않는다.

### 13.2 섹터 상한이 SIC division 기준이다

"Manufacturing" division이 유니버스의 큰 몫이라 0.30 상한이 GICS 섹터 상한보다 **훨씬 자주 걸릴 수 있다.** 어느 division이 얼마나 걸리는지 재현의 adjustment 기록으로 먼저 센다(§13.4). 분류 체계를 바꾸는 것은 한도의 의미를 바꾸는 것이라 코드 리뷰와 사람의 결정을 거친다.

### 13.3 CVaR 한도의 정규분포 유도

gate 기본값은 `2.0627·σ_max·√(5/252)`(정규 CVaR95)이지만 System 경로는 0.08을 명시로 넘겨 이 식을 쓰지 않는다. 식 자체는 모순이 아니다 — "최대 변동성의 정규분포 포트폴리오보다 꼬리가 나쁘지 않을 것"이라는 **기준 분포**를 둔 것이고, 측정은 역사적 분포로 한다. 두 경로의 값(0.08 vs 0.087)을 하나로 맞출지는 정책 결정이며 차이는 작다. KEEP.

### 13.4 어느 한도가 binding인가 — 측정 방법

`RiskDecision.adjustments`와 `violations` 문자열이 한도별로 구분된다. `system_ablation` 재현 결과에 **한도별 발동 횟수 표**(symbol cap, sector cap(division별), max_positions, min_position, turnover scale, stress scale, post-turnover tail scale, CASH raise)를 추가 집계한다. 2025 재현의 `risk_adjustment_count = 137`이 어디서 왔는지가 첫 질문이다. 새 코드가 아니라 재현 리포트의 집계다.

### 13.5 max_positions 25 × min_position 0.005 × max_symbol 0.10

투자 가능 비중 0.95에서 최소 10종목(⌈0.95/0.10⌉), 최대 25종목. CRISIS에서는 종목 상한 0.05·현금 0.40 → 최소 12종목. min_position 0.005는 25종목 × 평균 3.8%에서 거의 걸리지 않는다. 실현 가능 공간은 충분히 넓다 — 제약 조합의 문제는 없다.

---

## 14. 단계 10 — 거래비용과 TCA

Canonical: `estimate_trading_costs` in `market_risk.py`

- 현재: `adv_usd = mean(close×volume, 20일)` → 반스프레드 1bp(≥$1B)/3bp(≥$100M)/10bp.
- 일봉 스프레드 추정(Corwin-Schultz, Abdi-Ranaldo): S&P 500 대형주의 실제 반스프레드 1~3bp 수준에서는 이 추정량들이 **변동성을 스프레드로 오인해 상향 편향**되는 것으로 알려져 있다([문헌] 두 추정량의 검증은 대부분 소형주·전체 CRSP 표본이다). 대형주에서 정적 표보다 낫다는 근거가 없다 → **DO NOT IMPLEMENT**.
- IS 소급 계산에 필요한 DecisionPrice가 원장에 없다. 정의를 먼저 고정한다.

  ```text
  DecisionPrice = 판단 시각 as_of_at 이전에 가용했던 마지막 종가(PIT) — System 목표가 실제로 본 가격
  ArrivalPrice  = 주문 제출 시각의 브로커 호가 중간값(없으면 직전 체결가)
  IS            = side × (FillPrice − DecisionPrice)/DecisionPrice
  지연 비용      = side × (ArrivalPrice − DecisionPrice)/DecisionPrice
  실행 비용      = IS − 지연 비용
  ```

  intent 생성 시 두 가격을 함께 기록한다. execution 코드 변경이므로 정비 보류가 선행한다.
- 교체 표본 [추정]: 주문당 IS의 표준편차를 판단→체결 지연 동안의 가격 변동으로 약 50bp로 두면, 비용 모델의 5bp 편향을 95%로 검출하는 데 `n ≈ (1.96·50/5)² ≈ 384`건이 필요하다. **WAIT(fills ≈ 400)**. 그 전에는 정적 표를 교체하지 않는다.

---

## 15. 단계 11 — RL (연구 격리)

Canonical: `src/investment_agent/research/rl/`. trading·execution·operations 어디에서도 import하지 않는다 [실측, grep].

- 현재 action: 종목 logit → softmax → `_project_to_constraints`. reward는 6항 가중합(§3).
- **Risk Overlay 스칼라 g_t를 RL로 배우는 것은 권하지 않는다.** 결정 빈도가 주 1회라 7년 재현에서 약 360 스텝이다. 연속 행동 하나, 상태 서너 개짜리 문제에서 PPO가 이 표본으로 규칙 기반 overlay(§10.2)를 이긴다고 판정할 통계적 힘이 없다. §10.2는 파라미터 2~3개로 같은 일을 하고 재현으로 검증할 수 있다. **결론: overlay는 규칙으로 하고 RL은 하지 않는다.**
- 그래도 연구 비교군이 필요하면 정의는 다음과 같다(RESEARCH):

  ```text
  state  s_t = [σ̂_SPY,20/σ*, DD_t, trend_t, E_{t−1}, 포트폴리오 σ̂]
  action g_t ∈ [0, 1]   (E_t = 0.60 + 0.35·g_t)
  reward r_t = log(1 + E_t·R_p,t + (1 − E_t)·r_f) − λ_TO·|E_t − E_{t−1}| − λ_DD·max(0, DD_t − DD_{t−1})
  λ_TO = 실측 비용(편도 반스프레드 × 2),  λ_DD = 1 (낙폭 1%p = 수익 1%p)
  ```

  λ를 세 개 이상 두면 서로 상쇄되는 조합이 무수해 식별이 안 된다. tail 항은 넣지 않는다(DD가 이미 경로 꼬리를 담는다).
- Offline RL(CQL/IQL): 행동 정책의 **선택 확률**이 필요한데 이 시스템의 판단은 결정론이다. 같은 상태에서 다른 행동이 관측되지 않아(overlap 없음) off-policy 평가가 성립하지 않는다. **판단 원장은 요건을 만족하지 않는다** — DO NOT IMPLEMENT.

---

## 16. 단계 12 — 평가와 귀속

Canonical: `src/investment_agent/research/evaluation/evaluator.py`, `src/investment_agent/trading/performance/attribution.py`

### 16.1 Brier를 LLM 자칭 확률로 계산하는 것

§7.5의 취지와 **맞는다.** 자칭값을 **판단 입력으로** 쓰지 말라는 것이지 채점하지 말라는 것이 아니다. 채점해야 자칭값이 보정됐는지 알 수 있다. 다만 옛 엔진 57건의 P(up)는 0.20~0.68(중앙 0.53)로 좁다 [실측] — Brier만 보면 "0.5 근처라 손해가 적은" 모델이 좋아 보인다. 판정은 Brier가 아니라 **AUC와 신뢰도 도표(reliability diagram)**로 한다.

### 16.2 신호 출처별 귀속 — ablation 재현

alpha 결합이 min·clip으로 비선형이라 선형 분해(합 identity)가 성립하지 않는다. Shapley는 3개 출처에 2³=8 조합 재현이면 계산 가능하지만, 조합 중 "LLM만"은 이 시스템에서 정의되지 않는다(논지는 factor 사전값을 수정할 뿐이다). 그래서 **순서가 정해진 사다리 차분**을 쓴다.

```text
factor 기여       = R(factor_only) − R(현금)
ML 기여           = R(factor_ml) − R(factor_only)
LLM 기여          = R(factor_ml_thesis) − R(factor_ml)
overlay 기여      = R(Champion) − R(no_market_risk)
```

`system_ablation`이 이미 그 변형들을 돌린다. 이 차분은 **재현 수익**의 귀속이고, 체결 손익(`AttributionReport`)의 귀속과는 별개로 둔다. 체결 기반 귀속은 fills가 생긴 뒤(Master P0-5).

### 16.3 5·60일 horizon의 역할

20일만 의사결정에 쓴다. 5일은 **논지 붕괴의 조기 경보**(판단 직후 급락이 반복되는지), 60일은 **20일 신호가 반전되는지**(단기 모멘텀의 되돌림)를 보는 진단이다. 둘 다 판단 입력이 아니라 평가 리포트의 열로 남긴다. KEEP.

---

## 17. 공통 검증·다중검정·승격

모든 변경은 Master §14의 절차를 따른다.

- **재현 창**: 2021-09 ~ 2026-08(주간 스냅샷 260개). 연 단위 하위 구간(특히 2022 약세장)을 따로 보고한다. 2025년 한 해로 판정하지 않는다.
- **다중검정**: 한 단계에서 비교한 후보 수 k를 artifact에 기록하고 `required_t_stat(k)`(또는 Holm)로 문턱을 올린다. 후보를 먼저 줄이고 돌린다.
- **artifact 불변성**: `evaluation_id`, `candidate_count`, `dataset_hash`, 정책 버전, 코드 커밋을 남긴다.
- **승격**: Research → Historical Replay → Rolling OOS → Shadow → Stress/Failure Injection → Manual Promotion. 자동 승격 금지.

---

## 18. Part I 우선순위

표본 없이 지금 할 수 있는 것(OOS-NOW)부터, 포트폴리오 영향이 큰 순서.

| 순위 | 항목 | 이유 |
|---|---|---|
| 1 | §9.2 노출 분리(현금 편향) | 재현 초과수익 −7.8%p의 대부분을 설명하는 구조 결함. LLM 없이 검증 가능 |
| 2 | §13.4 binding 한도 집계 | 새 코드가 아니라 재현 리포트 집계. 1의 해석에 필요 |
| 3 | §7.2·§7.3 측정 IC·Blom z | α 스케일과 상위 종목 동률 해소. 1과 함께 재현 |
| 4 | §5.3·§5.4 결측 수축·feature 정의 | 영향 종목은 적지만 명확한 편향 |
| 5 | §10.2 연속 노출·느린 복구 | 1이 E_t를 입력으로 만든 뒤에 의미가 있다 |
| 6 | §6.5·§7.4 walk-forward·스태킹 | ML 채택 결정의 근거. 채택 전 운영 영향 0 |
| 7 | §9.5·§9.7 slack·미분류 섹터 | fail 경로 정리 |
| WAIT | §7.5-B R_L, §14 비용 교체, §16.2 체결 귀속 | 표본 대기 |
| 하지 않음 | BL, RL overlay, Offline RL, 일봉 스프레드 추정, ML 확률 보정 | §7.6·§15·§14·§6.4 |

---

## 19. Part I 최종 원칙

```text
동일한 PIT 데이터, 동일한 비용, 동일한 OOS 창에서 Champion보다
더 안정적이고, 재현 가능하고, 낙폭·꼬리위험이 작고, 감당 가능한 turnover로,
비용을 빼고도 좋아졌고, 여러 regime에서 살아남는가.
```

통과한 것만 수동으로 승격한다. 그리고 **검증할 수 있는 것을 표본 부족을 이유로 미루지 않는다.**

---
---

## Part II — AI 판단 계층 (Deep LLM · System-One · 토큰 비용)

> Part I이 "기대수익이 얼마인가"를 다룬다면, Part II는 "구조화되지 않은 근거를 어떤 비용으로 해석하는가"를 다룬다. 현재 Production 경로는 `src/investment_agent/trading/decision/agents/`의 저장소 소유 Multi-Agent 그래프(Champion)다.

## 41. 판단 세 질문의 분리

| 질문 | Owner |
|---|---|
| 무엇이 사실인가 | DB / Python 결정론 계산 |
| 그 사실이 무엇을 의미하는가 | Factor / ML / System-One / Deep LLM |
| 그래서 비중을 얼마로 할 것인가 | Alpha / Optimizer / RiskGate (Part I) |

System-One·Deep LLM은 두 번째 질문에만 답한다(Master §4.2·§4.3, 절대 불변).

## 42. Intelligence Hierarchy와 실제 수요

```text
Level 0  결정론 코드            Level 1  Factor / ML
Level 2  System-One (후보)      Level 3  Deep LLM (현재 Production)
Level 4  사람(Discord 승인)
```

Level 3 앞에는 이미 결정론 깔때기가 있다(`candidates.py`, `candidate_ranker.py`): priority lane → factor shortlist 60 + 28일 재분석 게이트 → 모델 예산(300요청 ÷ 15 = 20종목/일) → 아무것도 due가 아니면 회차 전체를 건너뛴다.

**정상 상태 수요는 20종목/일이 아니다** [실측 + 추정]. 주간 스냅샷 260개에서:

```text
상위 60 신규 진입          주당 평균 5.3종목
28일 주기 재분석            60 ÷ 4주 = 주당 15종목
보유·사건 priority         보유 ≤ 25, 대부분 상위 60과 겹친다
→ 정상 상태 약 20종목/주 ≈ 거래일당 4~6종목 (+ 사건)
```

2026-09-09~15에 매일 20종목 상한을 채운 것은 **처음 한 번의 백로그**였다. 따라서 비용은 "상한 × 종목당 비용"이 아니라 **"due 발생률 × 종목당 비용"**이다. 상한은 백로그 기간의 처리 속도를 정할 뿐이다.

또 하나: shortlist(60)와 alpha 후보(40)의 차이 20종목은 낭비처럼 보이지만 **아니다.** 41~60위의 35.2%가 28일 안에 상위 40에 들어오고(1,817/5,160) [실측], shortlist가 60이라서 "논지 없이 상위 40에 들어오는 종목"이 주당 3.8에서 0.8로 줄어든다 [실측]. `require_verified_entry` 때문에 논지 없는 종목은 편입이 막히므로(§43), 이 버퍼가 투자 가능 종목을 지킨다.

## 43. LLM 판단은 편입 게이트다 — 비용 절감이 포트폴리오를 바꾼다

`AlphaPolicy.require_verified_entry=True`이므로 **유효한 논지가 없는 미보유 종목은 기대수익이 0 이하로 깎이고 편입이 막힌다.** 2025 재현에서 논지가 0건이었던 `factor_ml_thesis`는 1년 내내 현금 100%였다 [실측].

즉 Deep LLM 호출을 건너뛰는 것은 "비용을 아끼는 것"이 아니라 **"그 종목을 그날 편입 후보에서 빼는 것"**이다. 이것이 escalation 설계의 첫 제약이다(§55.1).

## 44. System-One Provider — 벤더가 아니라 계약

Jev를 architecture에 하드코딩하지 않는다. 어떤 provider도 이름만으로 채택하지 않는다(§52). 계약은 §45가 정한다.

## 45. §45 판정 — "SystemOneDecisionProvider를 만들지 않는다"는 결론은 틀렸다

앞 판은 "`LLMClient.complete_json(system, user, output_schema, task_name) -> dict`가 이미 질문→구조화 답변 shape이므로 System-One provider는 그 구현체를 하나 더 붙이면 된다"고 결론지었다. **전제가 틀렸다.**

1. **대체 가능성이 없다.** `LLMClient`의 호출자 8곳은 전부 한국어 서술(`report`, `argument`, `plan`, `decision`)이나 서술을 포함한 제안(`thesis` + `reasoning`·`key_risks`)을 요구한다. Jev는 문자열을 만들지 못한다(설계상). Jev를 `LLMClient`로 구현하면 **어떤 호출자에도 끼울 수 없는 구현체**가 된다 — Protocol을 만족하는 척하는 것이지 대체가 아니다.
2. **담을 자리가 없다.** System-One의 산출은 질문별 **확률분포**, 질문 집합의 **버전**, 답하지 않은 질문(**unanswered**)이다. `dict` 반환에 넣으면 키 이름 규약이 계약을 대신하고, 분포 합·버전 고정을 타입이 지키지 못한다.
3. **호출 단위가 다르다.** Deep LLM은 역할 하나에 한 번, System-One은 질문 집합 하나에 한 번(질문들은 provider 쪽에서 병렬)이다.

따라서 **별도 계약이 맞다.** 다만 "지금 만든다"와는 다른 문제다(§45.2).

### 45.1 계약 (설계 확정, 구현은 §56 단계에서)

```text
Question(question_id, kind, prompt, choices, domains)
    kind ∈ {boolean, choice, score}          — 벤더 primitive 이름(Noul/Choice/Score)을 계약에 노출하지 않는다
QuestionSet(name, version, language, questions)
    문구가 한 글자라도 바뀌면 version을 올린다. language를 artifact에 남긴다(§56.3)
Answer(question_id, distribution, top, confidence)
    distribution: choice → 확률, 합이 1 ± 1e-6 아니면 계약 위반
    confidence  = p(최빈) − p(차순위)          — provider 자칭 confidence를 쓰지 않는다(§7.5와 같은 원칙)
JudgmentResult(provider, model, model_version, question_set_key, answers, unanswered,
               latency_ms, input_tokens, output_tokens)
    model_version은 핀 고정 값만(`*-latest` 거부, §52)
JudgmentProvider.judge(state: EvidenceBundle, question_set: QuestionSet) -> JudgmentResult
```

- state 입력은 앞 판의 결론대로 `EvidenceBundle`(PIT)을 그대로 쓴다 — 이 부분은 맞았다.
- 결정론 구현(`DeterministicJudge`, Level 0)은 feature만으로 답할 수 있는 질문에만 답하고 **모르는 것은 0.5가 아니라 unanswered**로 둔다.
- routing은 새 `DecisionRouter` 파일이 아니라 `trading/decision/analysis.py`의 후보 선정·엔진 선택 지점에서 한다 — 앞 판의 이 결론은 유지한다.

### 45.2 되돌린 구현(`83f11dd`)을 복원하는가

**부분 복원이 맞다.** 되돌린 이유였던 "문서와 모순"은 이 절로 해소된다. 그러나 전부 되살리지 않는다.

| 구성 | 판정 | 이유 |
|---|---|---|
| contracts·questions | 복원 (§45.1에 맞춰 `language` 추가) | 계약이 있어야 shadow 기록의 형식이 고정된다 |
| deterministic judge | 복원 | 비용 0으로 **지금** shadow 데이터를 만든다(§55.1) |
| router(`decide_escalation`) | **복원하지 않았다** — 대신 `trading/decision/escalation.py`의 재분석 shadow(§55.1)를 새로 만들었다 | 되돌린 router는 "깊은 판단이 필요한가"를 결정론 judge가 답하지 못해 사실상 항상 escalate했다. 새 shadow는 관측 가능한 변화 부재만 보고, 판정만 기록한다 |
| TypeSafe(Jev) 어댑터 | 복원하지 않는다 | 키가 없고, §56.3의 전제(영어 질문 집합)가 먼저다 |

contracts·questions·deterministic judge도 **Jev를 붙일 때 함께** 복원한다. 지금은 쓰는 곳이 없어 복원하면
"있으니까 쓴다"가 된다 — 되돌린 이유와 같다.

## 46. Universe Funnel — Change Detection은 이미 있다

Deterministic Change Detector는 신규 컴포넌트가 아니다. `candidate_tickers()`·`priority_candidates()`·`select_factor_candidates()`가 신규 공시·고영향 사건·품질 붕괴·28일 주기·예산 상한을 이미 한다. 작업은 도입이 아니라 **기존 owner의 정밀화**다. System-One Light/Deep Scan은 RESEARCH.

## 47. Question Design

### 47.1 Atomic Question 원칙

하나의 질문은 하나의 판단만 묻는다. 예: `material_news_present`, `guidance_changed`, `thesis_still_valid_given_new_filing`, `evidence_sufficient`, `deep_reasoning_required`.

### 47.2 Question Registry

§45.1의 `QuestionSet`이 registry다. QuestionSet이 바뀌면 새 평가 artifact로 취급한다(§17 다중검정과 같은 불변성). 질문의 자동 변경은 금지(§52).

### 47.3 Escalation 조건

§55.1이 구체 식을 갖는다.

### 47.4 Verification Layer

Deep LLM 출력은 바로 Alpha에 들어가지 않는다 — 이미 `SecurityProposal.from_dict(allowed_evidence_ids=...)`가 인용 ID를 검증하고 1회 repair 뒤 fail-closed한다. 관측된 유일한 계약 위반(59건 중 1건)이 이 검증에서 잡혔다 [실측]. 추가 검증(주장-근거 일치, 모순)은 §7.5의 CitationValidRate와 같은 계약을 공유한다.

## 48. Multi-Agent 재평가 — Champion vs Challenger

| Challenger | 설명 |
|---|---|
| B. Parallel Atomic Decisions | 원자 질문 병렬 평가 후 집계 |
| C. System-One + 조건부 Deep LLM | §46 funnel 전체 |
| D. Deterministic + ML only (AI 없음) | AI 계층이 가치를 더하는지의 baseline |

Ablation 사다리 `factor_only → factor_ml → factor_ml_thesis`는 `src/investment_agent/research/system_validation/ablation.py`와 진입점 `src/investment_agent/operations/commands/system_ablation.py`에 이미 있다. **지금은 돌려도 LLM 쪽 결론이 나오지 않는다** — 현재 엔진 논지 0건, 채점 0건이다. 판정: RESEARCH, 선행 조건 §58.

## 49. Provider Registry — 시간에 민감한 사실

모델·가격·API 한도는 시점 스냅샷이다. 본문에 고정 수치를 박지 않고 이 형식으로만 기록한다. 새 세션은 작업 시점에 공식 자료로 다시 확인한다.

### 49.1 조사 기록 (2026-09-23 재확인)

```text
provider:          TypeSafe AI
model:             jev (jev-latest는 쓰지 않는다; 핀 가능한 jev-1.12, jev-1.13.0)
checked_at:        2026-09-23
official_source:   https://docs.typesafe.ai/llms-full.txt
                   https://typesafe.ai/blog/introducing-system-one-models-and-jev
input_price:       $0.042 / MTok (jev-1.12 예시 기준, 2026-09)
output_price:      $0.00
rate_limit:        수치 미공개 (429·529 반환, SDK가 지수 백오프 재시도)
context_limit:     미공개
latency:           "대부분 약 100ms"
primitives:        Noul(예/아니오 → 확률만, confidence 없음)
                   Choice(최대 255 옵션 → 선택 + 전체 분포 + confidence)
                   Score(2~10 수준 → 확률가중 값 + 분포 + confidence)
                   한 요청의 질문들은 독립적으로 병렬 평가된다
known_limitations: 문자열 생성 불가 / 텍스트 전용 /
                   "주 학습 언어는 영어, CJK 포함 타 언어는 현재 정확도가 낮다"(공식)
                   공개 2026-09-15, GA 2026-09-20
benchmark_result:  없음. 키 없음(.env) → 호출한 적 없다
```

```text
provider:          Azure OpenAI (운영 Champion)
model:             gpt-5-mini, version 2025-08-07
checked_at:        2026-09-23
official_source:   https://developers.openai.com/api/docs/models/gpt-5-mini
                   https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/prompt-caching
                   https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/reasoning
input_price:       $0.25 / MTok        cached input: $0.025 / MTok
output_price:      $2.00 / MTok        (reasoning 토큰은 output으로 과금된다)
context_limit:     400,000 (input 272,000 / output 128,000)
reasoning_effort:  minimal / low / medium / high 지원 (minimal은 원조 GPT-5 계열만). 현재 코드는 보내지 않는다 → 모델 기본값
verbosity:         low / medium / high 지원. 현재 코드는 보내지 않는다
prompt caching:    자동. 1,024토큰 이상 + 첫 1,024토큰 동일, 이후 128토큰 단위 적중.
                   in-memory: 5~10분 비활성 시 소멸, 최대 1시간. 사용량은
                   prompt_tokens_details.cached_tokens로 보고된다. gpt-5-mini는 24h 확장 보존 목록에 없다
structured output: json_schema + strict 지원. 현재 코드는 json_object
usage 필드:        completion_tokens_details.reasoning_tokens, prompt_tokens_details.cached_tokens 제공
                   → 현재 UsageLedger는 둘 다 버린다(§50)
Batch:             이 조사에서 Azure Batch 가격·turnaround를 재확인하지 않았다(§55.4에서 구조적으로 배제)
```

### 49.2 Jev 판정 — `RESEARCH`, 단 shadow 레일의 결정론 부분은 지금 만든다

1. **비교 기준이 없다.** 현재 엔진 판단 0건, 채점 0건. Champion을 못 재는데 Challenger를 잴 수 없다.
2. **절감의 크기가 작다.** §54의 재구성으로 종목당 하한 약 $0.10, 정상 상태 하루 4~6종목이다. Jev 자체 비용은 무시할 만하지만(§55.5), 절감은 **Deep LLM을 건너뛸 때만** 생기고 건너뛰기는 편입 게이트를 바꾼다(§43).
3. **대체재가 아니라 추가 계층이다.** 서술 필드를 만들지 못하므로 Deep LLM은 남는다.
4. **언어.** §56.3에서 해결 방향을 정했다 — 걸림돌이지만 막다른 길은 아니다.
5. **공개 이력 8일.** "환각 0%"는 스키마 일치 보장이지 사실 정확도의 실증이 아니다.

앞 판의 "데이터가 없어서 shadow 레일을 만들지 않는다"는 순환 논리였다. 레일 중 **비용 0인 결정론 부분**(DeterministicJudge + shadow router)은 지금 만들어 데이터를 쌓는다(§45.2). Jev 호출 부분은 §58의 조건이 충족될 때 붙인다.

## 50. AI Cost / Latency 계측

계측 항목:

```text
requests/ticker, input_tokens/ticker, cached_input_tokens/ticker,
output_tokens/ticker, reasoning_tokens/ticker,
위 토큰의 역할(task_name)별 합, cost/ticker, latency p50/p95/max,
retry_rate, failure_rate, escalation_rate(shadow)
```

**현재 상태 (2026-09-23 실측)**

| 항목 | 상태 |
|---|---|
| 호출 수·지연 | `UsageLedger`가 기록 |
| input·output 토큰 합계 | 기록 (종목당 합계만) |
| **reasoning 토큰** | **버린다** — output 비용의 내역을 모른다 |
| **cached 토큰** | **버린다** — 캐시 최적화의 효과를 확인할 수 없다 |
| **역할별 토큰** | **없다** — 역할별로는 호출 수만 센다 |
| 분석가 입력 원문 | **저장하지 않는다** — 분석가 단계를 재현·벤치마크할 수 없다 |
| durable 저장 | 로그뿐(회전) |

**이 공백들은 하네스를 다시 띄우기 전에 닫아야 한다.** 현재 엔진은 한 번도 완료되지 않았으므로, 재기동 후 첫 1~2주가 곧 공짜 계측 기간이다. 계측이 불완전한 채로 재기동하면 그 기간이 버려진다(§56 단계 1).

계측 없이 "N% 절감" 같은 수치를 문서·주석에 남기지 않는다(Master §16.12). §54의 수치는 [재구성] 표시를 달고, 계측이 쌓이면 대체한다.

## 51. Promotion Path (AI 계층)

```text
Research Candidate → 동일 evidence로 Shadow(기록만, Alpha에 닿지 않음) → §48 Ablation + 벤치마크
→ §50 계측 확인 → Verification 통과율 → Manual Promotion
```

Shadow 단계의 System-One·Deep LLM은 broker·최종 비중에 어떤 영향도 주지 않는다.

## 52. Do Not Implement Yet (AI 계층)

```text
System-One/Deep LLM의 직접 broker 제어 또는 position weight 산출
Question Set의 자동 mutation
Provider model version floating (*-latest)
Deep LLM 건너뛰기(escalation skip)를 shadow 검증 없이 운영에 적용  — 편입 게이트가 바뀐다(§43)
Jev(또는 임의 provider)를 이름만으로 채택
Batch API로 역할 그래프 전환 (§55.4)
```

## 53. Part II 원칙

Python이 계산할 것을 계산하고, Factor/ML이 예측할 것을 예측하고, System-One(검증되면)이 반복 판단을 싸게 처리하고, Deep LLM이 어려운 문제만 생각하고, Optimizer/RiskGate가 비중과 안전을 결정한다. **AI 계층의 복잡성은 §48 Ablation이 가치를 증명했을 때만 늘린다.**

---

## 54. 토큰 비용의 구조 — 재구성

### 54.1 방법과 한계

저장된 옛 엔진 판단 57건(`artifacts/ai_investor/tradingagents/decision-evidence/`)의 `role_analyses`로 **호출 6~14의 user payload를 코드와 같은 방식(`canonical_json`)으로 다시 만들고** `o200k_base` 토크나이저로 셌다 [재구성]. 한계:

- 옛 엔진에는 macro 분석가가 없다. 현재 엔진은 리포트가 하나 더 붙어 8개 호출의 입력이 조금씩 더 크다.
- system 프롬프트·스키마 텍스트(호출당 수백 토큰), `evaluated_case_memory`, 분석가 5명의 입력(원문 미저장)은 **빠져 있다.**
- reasoning 토큰은 **알 수 없다**(기록되지 않았다).
- 따라서 아래 비용은 **하한**이다.

### 54.2 역할별 입력 (중앙값, 토큰) [재구성]

| 호출 | 입력 | 그중 5개 리포트 블록 |
|---|---|---|
| bull | 12,177 | 12,166 |
| bear | 17,749 | 12,166 |
| research_manager | 17,872 | 12,166 |
| trader | 13,390 | 12,166 |
| aggressive | 12,450 | 12,166 |
| conservative | 14,785 | 12,166 |
| neutral | 17,188 | 12,166 |
| portfolio_manager | 19,625 | 12,166 |
| **structuring** | **55,156** | state 안에 포함 |
| 합계(호출 6~14) | **179,554** | 리포트 블록만 97,328 (54%) |
| 분석가 5명 | 미상 | evidence bundle 전체가 19,414 |

structuring의 state(50,647)는 토론 발언의 2~3중 복사를 빼면 27,171이 된다 — **57/57건에서 빠지는 필드가 남는 필드의 부분 문자열이다**(무손실) [실측].

### 54.3 출력 (중앙값, 토큰, 보이는 텍스트만) [재구성]

```text
분석가 리포트 합   11,810      risk 토론 3개   7,287      bull 2,709   bear 2,846
research_manager    1,163      portfolio_mgr     512      trader 266
합계               26,485  + reasoning 토큰(미상)
```

### 54.4 종목당·월간 비용 하한 [추정]

```text
입력  179.6K × $0.25/M = $0.045   (+ 분석가 입력·프롬프트·메모리: 미상)
출력   26.5K × $2.00/M = $0.053   (+ reasoning: 미상)
────────────────────────────────
종목당 하한 ≈ $0.10

정상 상태 4~6종목/일 × 30일  →  월 하한 ≈ $12~18
상한 20종목/일 × 30일        →  월 하한 ≈ $59
```

**해석**:
- 보이는 것만으로도 **출력이 입력보다 비싸다**(단가 8배). 출력 중 reasoning 몫을 모르므로, 가장 큰 단일 레버가 reasoning일 **가능성**이 높지만 확정할 수 없다 — 이것이 "계측 먼저"가 필요한 정확한 자리다.
- 절대 금액은 월 수십 달러 규모다. 동시에 **요청 수 한도(300/일)**가 백로그 기간의 처리량을 묶는다. 호출 수를 줄이면 달러보다 처리량에서 더 크게 효과가 난다.

---

## 55. 레버별 분석

### 55.1 (a) 호출 자체를 줄인다 — escalation

**하루 20종목 상한에서 50% 건너뛰기의 절대 절감**: 10종목 × $0.10 = **하루 $1 이상**(하한, [추정]). 정상 상태(4~6종목)에서는 **하루 $0.2~0.3 이상**. reasoning이 크면 비례해 커진다.

**위험**: 건너뛴 미보유 종목은 편입이 막힌다(§43). 보유 종목을 건너뛰면 논지 붕괴를 28일 동안 못 본다.

**판정 기준(식)** — 건너뛰기를 허용하는 조건을 모두 만족해야 한다:

```text
skip(i) = ¬held(i)
        ∧ ¬priority_event(i)                      신규 공시·8-K·고영향 사건 없음
        ∧ prev_view(i) 존재 ∧ age(prev_view) < 56일
        ∧ prev_view(i).thesis_state ∈ {positive, neutral}
        ∧ |R_i(since prev) − β_i·R_SPY(since prev)| < 1.5·σ_i·√(Δt/20)     예상 밖 가격 충격 없음
        ∧ |rank_i(now) − rank_i(prev)| < 15                                  factor 순위 급변 없음
동작: skip이면 Deep LLM을 부르지 않고 prev_view의 유효기간을 +28일(최대 56일) 연장
```

- 즉 escalation을 "건너뛰기"가 아니라 **"변화 없는 재분석의 유효기간 연장"**으로 정의한다. 편입 게이트는 그대로 열려 있다(기존 논지가 유효하다).
- 대상은 정상 상태 수요의 가장 큰 몫인 **28일 주기 재분석**(주당 약 15종목)이다.
- 확신 문턱을 LLM 확률이 아니라 **관측 가능한 변화 부재**로 정한다. 틀렸을 때의 기본값이 "기존 판단 유지"라서, 가장 흔한 실패는 "오래된 긍정 논지로 편입이 허용되는 것"이다.

**틀렸을 때 비용을 어떻게 재는가 — 양쪽을 다 돌리지 않고.** 비싼 쪽(Deep LLM)은 Champion에서 **어차피 돈다.** 싼 쪽(결정론 router)만 shadow로 돌려 "건너뛰었을 것"을 기록한다. 절감이 사라지지 않는다 — shadow 기간에는 절감이 없지만, 그 기간의 비용은 원래 쓰던 비용이다.

```text
기록: 재분석마다 (would_skip, prev_view, new_view)
놓친 논지 붕괴율  = P(new_view.thesis_state ∈ {negative, broken} | would_skip, prev ∈ {positive, neutral})
놓친 기회          = P(new_view=positive | would_skip, prev=neutral)
판정: 놓친 붕괴율의 95% 상한 < 5%  그리고  would_skip 비율 ≥ 30%  → 운영 적용 후보(사람 결정)
표본: 붕괴 기저율 ~10%일 때 상한 5%를 보이려면 would_skip 사례 ≈ 100건 이상
      → 정상 상태 주당 약 15건 재분석, 그중 절반이 would_skip이면 약 14주   WAIT
```

### 55.2 (b) 호출당 payload를 줄인다

| 항목 | 절감 [재구성] | 잃는 것 | 계측 필요? |
|---|---|---|---|
| structuring state 중복 제거 | 입력 약 23.5K/종목 ≈ $0.006 (하한의 약 6%) | **없음** — 57/57 무손실 | 아니오 (절감은 계산됨. 품질 동등성만 §57 단계 2에서 확인) |
| 캐시 적중을 위한 배치 순서 | 리포트 블록 12.2K × 7회 적중 × 90% ≈ $0.019/종목 (하한의 약 19%) | 역할 지시문이 user 안으로 이동 → 프롬프트가 바뀐다 | 적중 확인에 `cached_tokens` 계측 필요 |
| 뒤쪽 호출에 리포트 요약본(주장 N개 + evidence ID) | 리포트 블록 대신 요약 ~3K → 8회 × 9K ≈ 72K ≈ $0.018/종목 | 서술 뉘앙스, 역할 간 반박의 구체성 | 품질 벤치마크 필요 |

**캐싱이 지금 걸리지 않는 이유**: 캐시는 요청의 **첫 토큰부터** 같은 접두부에만 걸린다. 현재 모든 호출의 첫 메시지가 **역할마다 다른 system 프롬프트**다. 리포트 블록이 같아도 앞의 system이 다르면 0 적중이다. 게다가 `canonical_json`이 키를 정렬하므로 bull·bear·RM에서는 `debate_history`가 `reports`보다 **앞에** 온다.

재배치 형태:

```text
messages[0] system: 공통 규칙(모든 역할 동일, 20거래일·금지사항·인용 규칙)
messages[1] user:   {"reports": ...}                 ← 8개 호출 공통 접두부(≥ 1,024 토큰 충족)
messages[2] user:   역할 지시 + 역할별 payload(토론 이력·trader_plan 등)
```

- 같은 종목의 14호출은 수 분 안에 순차 실행되므로 in-memory 캐시(5~10분)에 들어간다.
- **적중은 확률적이다** [실측, 2026-09-23]. 같은 6,654토큰 요청을 몇 초 간격으로 세 번 보냈을 때
  첫째·둘째는 0, 셋째만 6,528토큰 적중했다. 같은 57K 구조화 요청을 연달아 보낸 재현에서도 적중이
  0인 경우가 대부분이었다. 요청이 서로 다른 백엔드로 가는 것으로 보인다(`prompt_cache_key`는
  GPT-5.6 이후 모델에서만 지원). 따라서 아래 절감은 **상한**이고, 실제 적중률은 재기동 뒤
  `cached_input_tokens`로 잰다.
- **절감 크기 비교**: 캐시 재배치(하한 약 $0.019/종목)는 Jev 도입(Deep LLM을 건너뛰지 않으면 절감 0)보다 **확실히 크다.** 이것이 인수인계 질문 "재배치가 Jev보다 큰가"의 답이다.

**structuring이 받아야 하는 것**: 최종 thesis·hard_constraint·key_risks·인용 ID를 만들려면 (1) 5개 리포트(인용 근거), (2) RM과 PM의 결론, (3) 각 토론 발언 **한 번씩**이면 충분하다. `*_history`·`current_*`·`investment_plan`·`final_trade_decision`은 이미 다른 필드에 있는 텍스트의 사본이다.

### 55.3 (c) 모델을 바꾼다

- **역할별 reasoning_effort·verbosity**: 분석가 5명은 사실 요약이다. `reasoning_effort=low`(또는 minimal), `verbosity=low`의 후보. 첫 실측은 구조화 호출 하나다 — output 약 2,400~2,900토큰 중 **reasoning이 약 절반**(1,150~1,650)이었다 [실측, 재현 초기 표본]. 역할별 몫은 재기동 뒤 `tokens_by_task`로 잰다.
- **동시 요청은 배포 한도에 걸린다** [실측]. 구조화 호출(약 57K 입력) 3개를 동시에 보내자 429가 연달아 났다. 분석가 5명 병렬화를 보류한 판단(Master "보류" 절)이 이 실측으로 뒷받침된다 — 병렬화는 배포 TPM 증설과 한 묶음이다.
- **역할별 등급 분리(nano/mini)**: 분석가 출력 11.8K를 싼 모델로 옮기면 출력 비용의 약 45%가 대상이다. 그러나 분석가 리포트가 **8개 뒤쪽 호출 전부의 입력**이라, 여기의 품질 손실은 전 그래프에 번진다. 벤치마크:

  ```text
  사실 근거율     리포트의 숫자·날짜 중 evidence 원문에 나타나는 비율 (결정론 검사)
  누락률          evidence의 핵심 수치(결정론 추출) 중 리포트가 언급하지 않은 비율
  하류 일치도     같은 evidence로 두 모델의 리포트를 넣었을 때 structuring의 thesis·hard_constraint 일치율
  A/A 기준선      같은 모델을 두 번 돌린 일치율 — 하류 일치도는 이것과 비교한다(LLM 자체 흔들림)
  판정            사실 근거율 차이 ≤ 2%p, 하류 일치도가 A/A 기준선의 95% CI 안
  ```

  분석가 입력 원문이 저장되지 않아 **지금은 벤치마크를 만들 수 없다**(§50). 계측 필요 + WAIT.
- **`json_object` → `json_schema` strict**: 관측된 위반 1건(59건 중)은 evidence ID 오인용이라 strict가 막지 못한다. 허용 ID를 enum으로 넣는 것은 가능하다 — enum 크기는 bundle 크기(58KB 문자)가 아니라 **ID 개수**에 비례하고, 옛 엔진 bundle의 evidence는 종목당 수 개~수십 개다. 그러나 이득(repair 1건/59)이 변경 폭(스키마 리터럴 6곳)보다 작다. **보류 유지.** 재검토: 현재 엔진에서 repair 비율이 5% 이상.

### 55.4 Batch API — 구조적으로 배제

그래프는 의존 단계가 약 10개다(분석가 → bull → bear → RM → trader → aggressive → conservative → neutral → PM → structuring). Batch의 turnaround가 최대 24시간이면 한 종목 판단이 최악 열흘이 된다. 분석가 5명만 batch로 묶는 것은 가능하지만 전체의 일부이고, 하네스 job을 submit→poll 상태 기계로 바꾸는 비용이 크다. **DO NOT IMPLEMENT.**

### 55.5 (d) Jev를 어디에 꽂는가

| 자리 | 절감 | 품질 위험 | 판정 |
|---|---|---|---|
| 1) 라우터 질문만(§55.1의 결정론 조건을 보강: "새 공시가 논지를 바꾸는가") | 호출 수 감소는 router가 결정한다. Jev 비용: 질문 10개 × 3K 토큰 = 30K × $0.042/M ≈ **$0.0013/종목** | 라우터가 틀리면 편입 게이트·논지 붕괴를 놓친다 | 결정론 router shadow 뒤 비교 challenger로만 |
| 2) fundamental/event 질문으로 분석가 일부 대체 | 분석가 호출 1~2개 × (입력 + 출력) | **서술 리포트가 사라져 뒤쪽 8호출의 입력이 바뀐다** | DO NOT IMPLEMENT |
| 3) Verification(인용·모순 검증) | 절감 없음(추가 비용) | 낮음(판단을 바꾸지 않고 표시만) | 가장 안전하지만 돈을 아끼지 않는다 |

**결론**: Jev의 비용 가치는 자리 1)에서만 나오고, 그 가치의 대부분은 Jev가 아니라 **결정론 router가 이미 만든다.** Jev가 더하는 것은 "변화가 있는데 논지에 무관한 변화"를 가려내는 정밀도다. 그 증분은 결정론 router의 shadow 결과(§55.1)가 있어야 잴 수 있다.

## 56. 순위와 로드맵

### 56.1 순위 (절감 크기 × 위험 × 구현 비용)

| 순위 | 레버 | 절감 [재구성/추정] | 위험 | 구현 | 분류 |
|---|---|---|---|---|---|
| 0 | 계측 보강(reasoning·cached·역할별 토큰, 분석가 입력 저장, durable) | 없음 — 다른 모든 레버의 근거 | 없음(판단 불변) | 작다 | **지금** |
| 1 | structuring state 중복 제거 | 하한의 ~6% | 매우 낮음(무손실) | 작다 | **지금**(품질 동등성 확인 포함) |
| 2 | 캐시용 메시지 재배치 | 하한의 최대 ~19% (적중이 확률적 — §55.2) | 낮음(프롬프트 순서 변경) | 작다 | **구현됨, 재기동 뒤 적중률 실측** |
| 3 | 역할별 reasoning_effort·verbosity | 미상(가장 클 가능성) | 중간(품질) | 작다 | 계측 필요 → 2주 뒤 A/B |
| 4 | 결정론 escalation(유효기간 연장) | 정상 상태 재분석의 일부 | 중간(편입·붕괴 놓침) | 중간 | shadow 지금 → 적용은 WAIT(≈14주) |
| 5 | 뒤쪽 호출 리포트 요약 | 하한의 ~18% | 중간(뉘앙스) | 중간 | 계측 + 벤치마크 필요 |
| 6 | 역할별 모델 등급 | 출력의 최대 ~45% 대상 | 높음(전파) | 중간 | 벤치마크 인프라 필요 |
| 7 | Jev 라우터 | 결정론 router 대비 증분만 | 중간 | 중간 | RESEARCH(§58) |
| — | strict schema, Batch, Jev 분석가 대체 | — | — | — | 보류 / 배제 |

### 56.2 "계측 먼저"가 정답인가 — 구분

- **측정 없이 해도 되는 것**: 절감이 산술로 계산되고 **판단에 들어가는 정보가 바뀌지 않는 것**. 1(무손실 중복 제거), 2(순서만 바꿈). 이 둘의 절감은 저장된 artifact로 이미 계산됐다. 남는 질문(품질 동등성)은 저비용 재현으로 확인한다.
- **측정 없이 하면 안 되는 것**: 모델이 **생각하거나 보는 양**을 줄이는 것. 3·5·6. 이득 크기(reasoning 몫)도 손실(품질)도 모른다.
- **데이터가 쌓여야 하는 것**: 4·7. 판정 표본이 shadow로만 만들어진다.
- 앞 세션이 전부를 계측 이유로 미룬 것은 1·2까지 묶었다는 점에서 틀렸다. 동시에 **계측 보강(0)이 재기동 전에 들어가지 않으면** 재기동 후의 공짜 계측 기간을 잃는다 — 그래서 0이 1·2보다 먼저다.

### 56.3 CJK — Jev 질문만 영어로 한다 (선택지 i)

- 이 저장소의 **evidence 자체는 대부분 영어이거나 숫자다** — yfinance·Reddit·StockTwits 원문, SEC 공시, 재무 수치. 한국어는 우리가 쓴 프롬프트와 분석가 리포트다.
- §48의 "동일 evidence"는 **같은 사실 입력**을 뜻한다. 질문 문장의 언어가 달라도 같은 `EvidenceBundle`을 넣으면 비교 조건은 유지된다. 차이는 `QuestionSet.language='en'`으로 artifact에 남긴다.
- (ii) Champion 영어 통일은 현재 엔진 판단이 0건이라 이력 단절 비용이 지금은 작지만, **Jev를 위해 Champion을 바꾸는 것**은 순서가 거꾸로다. Champion의 언어는 Champion의 품질로 정한다.
- (iii) 한국어로 쓰고 저하를 감수: 공식 문서가 저하를 명시한 상태에서 측정 비용만 늘린다. 채택하지 않는다.

### 56.4 Jev confidence가 우리 데이터에서 보정됐는지 확인하는 법

```text
정답이 나중에 확정되는 질문만 보정 대상으로 쓴다
  예: "이 공시 후 20일 동안 SPY 대비 초과수익이 양(+)인가"  → 20일 뒤 확정
      "이 8-K가 가이던스를 하향했는가"                      → 결정론 추출(XBRL/본문)로 확정
confidence 대신 분포의 p(선택) 사용(§45.1)
reliability diagram 10구간, ECE와 부트스트랩 95% CI
표본: 구간당 ≥ 30 → 질문당 ≥ 300개 확정 답변
판정: ECE 95% 상한 < 0.05 이고 기울기(보정 회귀) 95% CI가 1을 포함
```

## 57. 구현 계획과 진행 상태

각 단계는 독립 커밋이고 `git revert` 한 번으로 되돌릴 수 있다. 하네스·판단 코드를 만지므로 정비 보류를 건 채로 진행했다.

**진행 상태 (2026-09-23)**

| 단계 | 상태 | 커밋 | 결과 |
|---|---|---|---|
| 1 계측 보강 | 완료 | `e3aedd4` | reasoning·cached·역할별 토큰, 분석가 입력(내부 근거 원문·외부 해시) |
| 2 구조화 state 중복 제거 | 완료 | `5bcd822` | 입력 55,634 → 32,883(−41%), 판단 동등(A/A 대 A/B, 55건) |
| 3 캐시용 재배치 | 완료 | `e611368` | 적중은 확률적 — 재기동 뒤 실측 |
| 3b 거시 분석 회차당 1회 | 완료 | `4526ce6` | 종목당 14 → 13호출(첫 종목 제외), 프롬프트를 시장 국면 요약으로 |
| 4 하네스 재기동 | 사람 | — | 정비 보류 해제 뒤 |
| 5 재분석 escalation shadow | 완료 | `d3b7a93` | 판정만 기록, 건너뛰지 않음 |
| 6 현금 편향 재현 | 진행 | `05a653d`·`c17cf23` | 재현 도중 회계 결함(분할 이중 반영)과 주식 클래스 중복 거절을 발견·수정 |
| 8 reasoning_effort A/B | 계측 2주 뒤 | — | 구조화 호출 output의 약 절반이 reasoning(실측) |

**새로 생긴 후속 과제**

- **구조화 출력 strict 재검토**: 재현 171호출에서 계약 문제가 7건(수리 5, 최종 실패 2, 약 4%)이었고 그중
  enum 위반(`thesis` 칸에 설명문)은 `json_schema` strict의 enum으로 **막을 수 있는 종류**다. 앞 판의 보류 근거
  ("관측 위반이 strict로 못 막는 종류뿐")가 무너졌다. 재기동 뒤 현재 엔진의 위반율이 5%를 넘으면 구조화 호출
  하나에만 strict를 적용한다.
- **주식 클래스 LLM 중복**: GOOG·GOOGL이 LLM 후보에도 둘 다 오른다(약 2/60). 한쪽만 분석하면 다른 쪽은 논지가
  없어 편입이 막히므로, 같은 CIK의 논지를 공유하는 설계와 한 묶음으로 한다.

| 단계 | 내용 | 판단 변화 | 검증 | 되돌리기 |
|---|---|---|---|---|
| 1 | 계측 보강: `CallUsage`에 reasoning·cached 토큰, `UsageLedger`에 역할별 토큰 합, 종목당 usage와 분석가 입력 원문(해시+본문)을 decision-evidence artifact에 저장 | 없음 | 계약 테스트 + "필드 제거" 위반 주입 | revert |
| 2 | structuring payload 중복 제거 + 저장된 57 state로 A/A 대 A/B 재현(구조화 호출만, 예상 비용 수 달러) | 동등해야 함 | thesis·hard_constraint 일치율이 A/A 기준선 CI 안 | revert |
| 3 | 메시지 재배치(공통 system + 리포트 접두부) | 프롬프트 순서만 | 재기동 첫 주 `cached_tokens` > 0 확인, 역할 출력 형식 계약 테스트 | revert |
| 4 | 하네스 재기동(운영, 사람) | — | 계측 2주 누적 | — |
| 5 | 결정론 judge + shadow router 복원(§45.2), 판정만 기록 | 없음 | shadow 기록 계약 테스트 | revert |
| 6 | Part I 재현: `system_ablation`에 exposure_split 변형·binding 한도 집계 추가, 2021-09~2026-08 실행 | 운영 없음(연구) | §9.2 판정표 | revert |
| 7 | 6의 결과를 사람이 보고 결정(F1/F2, 채택 여부) | — | — | — |
| 8 | (2주 계측 뒤) reasoning_effort·verbosity 역할별 A/B 설계 제시 | — | — | — |

## 58. System-One·Jev 재검토 트리거

아래가 모두 충족되면 Jev를 shadow challenger로 붙인다.

```text
1. 현재 엔진 판단이 채점됨: decision_evaluations ≥ 200행, 서로 다른 날짜 ≥ 40
2. §50 계측이 30일 이상 누적 (reasoning·cached·역할별 포함)
3. 결정론 shadow router의 would_skip 사례 ≥ 100건 (§55.1 판정 가능)
4. system_ablation에서 LLM 계층의 기여가 유의 — 아니면 Jev가 아니라 AI 축소가 정답
5. Jev: 공개 이력 ≥ 6개월, rate limit·context 공식 명시, 핀 버전 사용
6. 영어 QuestionSet v1이 리뷰됨 (§56.3)
```

**4번이 핵심이다.** AI 계층 자체가 가치를 더하지 못하면 Jev 논의는 필요 없다.

---
---

## Part III — 데이터 사용과 기관 수준까지의 거리

## 59. 저장된 데이터를 판단 로직이 어떻게 쓰는가 (감사, 2026-09-23)

저장소는 넷이다([STORAGE_MAP.md](STORAGE_MAP.md)). 판단 로직이 읽는 경로와 실측을 적는다.

### 59.1 수치 경로 (factor → alpha → optimizer)

| 입력 | 저장소 | 쓰는 곳 | 상태 |
|---|---|---|---|
| feature 스냅샷(주간, 2021-09~) | research DuckDB | factor 점수, 후보 선정, ML | 정상. 40일 낡았던 것은 P0-7에서 복구 |
| 일봉(분할 조정, 배당 미조정) | Supabase market | 공분산·베타·비용·regime·System 회계 | **회계가 분할을 이중 반영했다 — 수정** |
| 섹터(SIC division) | Supabase universe | value 업종 내 순위, 섹터 상한 | GICS가 아니라 의미가 거칠다(§5.6, §13.2) |
| 관측 컨센서스(captured_live) | Supabase fundamentals | revision factor | 2026-09-13부터만 존재 |

### 59.2 LLM 근거 경로 (EvidenceBundle)

저장된 판단 57건 재구성, 종목당 약 16K 토큰 [재구성]:

| 영역 | 토큰(중앙) | 출처 | 비고 |
|---|---|---|---|
| fundamentals | 3,222 | SEC 재무 | 최근 분기 원자료 + 전체 이력 통계 |
| economic_calendar | 3,037 | 발표 일정·예상 | **모든 종목에서 동일** |
| segments | 2,637 | XBRL 세그먼트 | |
| macro | 2,437 | FRED/ECOS | **모든 종목에서 동일** |
| market | 1,856 | 일봉 21개 + 통계 | |
| estimates | 1,138 | 관측 컨센서스 | |
| technical | 127 | RSI·MACD | PIT 보장이 되는 두 지표만 |
| gurus(13F) | 0 | — | 판단 당시 57/57 비어 있었다. **지금은 채워진다**(AAPL 7개 매니저 25행) — 코드가 아니라 당시 데이터 상태였다 |
| news_archive | 0 | — | 로컬 intelligence 저장소가 있는데 쓰지 않고 live 외부 뉴스를 매번 받는다 |

발견과 조치:

1. **종목과 무관한 근거로 종목마다 LLM을 불렀다.** macro 분석가 입력이 macro + economic_calendar뿐이라
   같은 날 모든 종목에서 동일했다. 회차당 한 번 만들어 공유하도록 고쳤다(`4526ce6`).
2. **LLM이 숫자가 말한 것을 모른다.** 구조화 호출의 질문은 "숫자(factor·ML)가 놓친 위험이 있는가"인데,
   근거 묶음에 factor 점수·category 백분위·밸류에이션 배수가 없다. 숫자가 무엇을 말했는지 모르면 무엇을
   놓쳤는지도 판단할 수 없다. 제안: `factor` 근거 항목(composite 백분위, category 점수, 게이트 사유, P/E·
   FCF yield 백분위) 약 300토큰. **RESEARCH** — 판단을 바꾸므로 재기동 뒤 논지가 쌓인 다음 A/B로 본다.
3. **뉴스 경로가 둘이다.** 로컬 intelligence 저장소(90일)와 live 외부 호출이 따로 있다. live 호출은
   재현이 불가능하고(과거 시점의 뉴스를 다시 받을 수 없다) 외부 한도를 쓴다. 로컬 저장소를 PIT 근거로 쓰는
   것이 재현성과 비용 모두에 낫다. **REFINE** — intelligence owner의 읽기 계약부터 확인해야 한다.

## 60. 기관 수준까지의 거리

"기관급"을 이 시스템의 제약(개인 계좌, long-only, 20일 horizon) 안에서 정의한다. 각 항목은 지금 상태,
기관의 통상 기준, 격차를 메우는 구체 작업을 적는다.

| 영역 | 지금 | 기관 통상 기준 | 격차를 메우는 작업 | 우선 |
|---|---|---|---|---|
| **신호 검증** | factor IC 0.014(20일, t 0.76). 채택 ML 없음 | 신호마다 OOS IC·ICIR·decay·turnover-adjusted IC, 다중검정 기록 | §5.5 수축 가중, §6.5 전 창 walk-forward, 결과를 artifact로 버전 고정 | 높음 |
| **위험 모형** | LW 상수상관 통계 공분산, 절대 분산 목적 | 산업·스타일 factor 위험모형, **벤치마크 대비 추적오차 예산** | §9.2 SPY 대비 위험(구현, 재현 중), 추적오차 목표 명시 | 높음 |
| **포트폴리오 구성** | 현금 편향(P0-8), 목표 거절 시 현금 잔류 | 투자 비중은 위험 예산이 정하고 α는 tilt만 | §9.2·§10.2 | 높음 |
| **회계·성과** | 분할 이중 반영 결함(수정), 배당 포함 총수익 | 총수익·일별 NAV를 독립 계산으로 대사 | 재현 NAV를 SPY 총수익·독립 계산과 매일 대사하는 검사 | 높음 |
| **귀속** | 없음(fills 0) | Brinson(배분·선택) + factor 귀속 | §16.2 사다리 차분(재현), 체결 뒤 Brinson | 중간 |
| **TCA** | 정적 반스프레드 | 사전(pre-trade) 추정 + 사후 IS 측정 | §14 DecisionPrice 기록, 체결 400건 뒤 교체 | 중간 |
| **모델 위험 관리** | 문서·테스트, 수동 승격 | 모델 목록, 독립 검증 보고서, 승격 기준 사전 등록 | 채택 기준을 재현 전에 문서에 적고(§9.2 표처럼) 결과를 artifact로 | 중간 |
| **데이터 품질** | 3층 검증(schema·값·계약), 생존 편향 | 상장폐지 수익 포함, 공급자 이중화, 데이터 SLA | 상장폐지 종목의 마지막 수익을 재현에 포함 | 중간 |
| **실거래 이력** | 0건 | 모의 운용 1년 이상 기록 후 자본 투입 | 하네스 재기동 → System 목표를 매일 기록 → 6~12개월 추적 | 필수 전제 |

**가장 중요한 한 줄**: 지금 factor 신호의 20일 IC는 통계적으로 0과 구별되지 않는다. 기관 수준으로 가는
첫 걸음은 모형을 더 붙이는 것이 아니라, **약한 신호를 약한 만큼만 쓰는 포트폴리오**(벤치마크 대비 위험으로
노출을 지키고 α는 작은 tilt로)를 만들고, 그 위에서 신호를 하나씩 검증해 늘리는 것이다.
