# 시스템 전체 아키텍처 (System Architecture)

> 💡 **대화형 다이어그램 (Interactive Showcase)**  
> 브라우저에서 확대/축소, 다크·라이트 테마 전환, 데이터 흐름 애니메이션 추적(Trace)이 가능한 인터랙티브 다이어그램은 아래 파일을 열어 확인하세요:  
> 🔗 **[대화형 시스템 아키텍처 다이어그램 열기 (HTML)](diagrams/system-architecture.html)**  
> *(컴파일 명세: `docs/diagrams/system-architecture.architecture.json`)*

---

## 1. 전체 아키텍처 다이어그램 (Mermaid)

```mermaid
flowchart TB
    %% ==========================================
    %% 1. 외부 연동
    %% ==========================================
    subgraph EXT["🌐 외부 연동 계층 (External Ingestion & API)"]
        direction LR
        SRC_PUB["공개 금융 데이터<br/>(SEC EDGAR · yfinance · FRED · ECOS · EIA)"]
        SRC_NEWS["뉴스 / 소셜 웹 수집"]
        EXT_BROKER["토스증권 (Toss Order API)<br/>*단일 브로커 경로"]
        EXT_DISCORD["Discord API<br/>(#시스템-로그, 승인 채널, 알림 카드)"]
    end

    %% ==========================================
    %% 2. 데이터 수집 및 저장 계층
    %% ==========================================
    subgraph DATA_TIER["💾 저장소 계층 (Storage & Persistence)"]
        direction TB
        DB_SUPA[("원격 Supabase (Postgres)<br/>• PIT 주가 · 재무제표 · 공시 · 거시<br/>• SSOT 도메인 원천 데이터")]
        DB_DUCK[("로컬 DuckDB (ResearchStore)<br/>• PIT Features · ML 라벨 · Event<br/>• 뉴스 원문 (최대 90일 파기)")]
        DB_SQLITE[("로컬 SQLite (Runtime Ledgers)<br/>• System NAV · Target Weights<br/>• Intents · Approvals · Orders")]
        CACHE_MIRROR["로컬 Parquet Mirror<br/>(2시간마다 최신 가격·스플릿 동기화)"]
    end

    SRC_PUB -->|"GitHub Actions cron"| DB_SUPA
    SRC_NEWS -->|"로컬 하네스 수집"| DB_DUCK
    DB_SUPA -.->|"캐시 갱신"| CACHE_MIRROR

    %% ==========================================
    %% 3. 리서치 계층
    %% ==========================================
    subgraph RES_TIER["🔬 리서치 계층 (src/investment_agent/research)"]
        direction TB
        RES_FEAT["FeatureLayer & ContextBuilder<br/>(Point-in-Time 안전 시점 보장)"]
        RES_FACT["전통 5대 팩터 사전값<br/>(IC × 변동성 × z)"]
        RES_ML["Champion ML / Qlib<br/>(기대초과수익 예측 ±1σ 제한)"]
        RES_ABLATION["Ablation & System Validation<br/>(전략/피처 오프라인 성과 검증)"]
    end

    CACHE_MIRROR --> RES_FEAT
    DB_DUCK --> RES_FEAT
    RES_FEAT --> RES_FACT
    RES_FEAT --> RES_ML
    RES_FEAT --> RES_ABLATION

    %% ==========================================
    %% 4. 투자 의사결정 계층
    %% ==========================================
    subgraph TRD_TIER["🧠 투자 의사결정 계층 (src/investment_agent/trading)"]
        direction TB
        TRD_SCREEN["후보 종목 스크리닝<br/>(상위 Percentile 이상치 선별)"]
        TRD_AGENTS["TradingAgents (LLM 5인 분석)<br/>• Bull/Bear 토론 · 위험 식별<br/>• 거부권 (Veto) 행사 (비중 권한 없음)"]
        TRD_ALPHA["ALPHA Engine (v3 결합)<br/>정밀도 1/σ² 가중합으로 기대초과수익 도출"]
        TRD_OPT["CVXPY Portfolio Optimizer<br/>Robust 최적화 (μ - k*σ) · 0.2% 교체허들"]
        TRD_RISK["DeterministicRiskGate (하드 룰)<br/>• 단일 종목 최대 10%<br/>• 현금 비중 40% 강제 · 레버리지 0"]
        TRD_SYS["System Portfolio Engine<br/>(100% 자동 추적 NAV 장부)"]
    end

    RES_FEAT --> TRD_SCREEN
    TRD_SCREEN --> TRD_AGENTS
    RES_FACT --> TRD_ALPHA
    RES_ML --> TRD_ALPHA
    TRD_AGENTS -->|"거부권/위험 논지만 전달"| TRD_ALPHA
    TRD_ALPHA --> TRD_OPT
    TRD_OPT --> TRD_RISK
    TRD_RISK --> TRD_SYS
    TRD_SYS --> DB_SQLITE

    %% ==========================================
    %% 5. 주문 실행 및 안전 원장 계층
    %% ==========================================
    subgraph EXE_TIER["🛡️ 실행 및 브로커 안전 계층 (src/investment_agent/execution)"]
        direction TB
        EXE_MY["My Portfolio Follow<br/>(Toss 계좌 잔고 vs System 목표 비중 비교)"]
        EXE_INTENT["ExecutionIntent 발급<br/>(Durable Permit · TTL 부여)"]
        EXE_APPROVAL{"Discord 승인 게이트<br/>(수동 확인 or 자율 허가)"}
        EXE_WORKER["TossLiveExecutionWorker<br/>• 매도 우선 체결<br/>• Reserve-Before-Submit<br/>• 결과 불명 시 불일치 락다운 & 대사"]
    end

    TRD_SYS --> EXE_MY
    EXE_MY --> EXE_INTENT
    EXE_INTENT --> EXE_APPROVAL
    EXE_APPROVAL -- "승인" --> EXE_WORKER
    EXE_WORKER <-->|"주문/체결/잔고"| EXT_BROKER
    EXE_WORKER -->|"원장 기록"| DB_SQLITE

    %% ==========================================
    %% 6. 보고 및 알림 계층
    %% ==========================================
    subgraph REP_TIER["📢 보고 및 알림 계층 (reporting · notifications · dashboard)"]
        direction LR
        REP_READ["Reporting Read Model<br/>(읽기 전용 게이트웨이)"]
        NOTI_ENG["Notification Engine<br/>(중복 방지 원장 · 카드 렌더링)"]
        DASH_UI["Streamlit 대시보드<br/>(운영 상태 · NAV · 포트폴리오 모니터링)"]
    end

    DB_SUPA --> REP_READ
    DB_SQLITE --> REP_READ
    REP_READ --> DASH_UI
    REP_READ --> NOTI_ENG
    NOTI_ENG -->|"PNG 카드 발송"| EXT_DISCORD
    EXE_APPROVAL <-->|"승인 요청/인터랙션"| EXT_DISCORD

    %% ==========================================
    %% 7. 운영 제어 계층
    %% ==========================================
    subgraph OPS_TIER["⚙️ 운영 및 제어 하네스 (src/investment_agent/operations)"]
        OPS_SWITCH["Harness Switch<br/>(Kill-switch · 정비 모드 플래그)"]
        OPS_RUN["Local Harness Pipeline<br/>(정기 배치 · 사건 즉시 재분석)"]
    end

    OPS_SWITCH -.->|"강제 정지 제어"| EXE_WORKER
    OPS_SWITCH -.->|"하네스 잠금"| OPS_RUN
```

---

## 2. 계층별 상세 역할과 코드 대응 관계

### 1) 저장소 계층 (Storage & Persistence)
* **Supabase (PostgreSQL)**: 모든 공식 원천 데이터의 단일 진실 공급원(SSOT). `available_at <= t` 시점 기준의 과거 재무제표, 일봉 주가, 공시 이력 저장.
* **DuckDB (`ResearchStore`)**: 연구용 파생 산출물 보관소. Feature 스냅샷, ML 학습 샘플, 이벤트 파생물 저장. 뉴스·소셜 원문은 기사 단위로 최대 90일 보관 후 폐기.
* **SQLite (Runtime Ledgers)**: 로컬 실시간 원장. `system_nav`, `system_targets`, `intents`, `approvals`, `orders`, `fills` 저장.

### 2) 리서치 계층 (`src/investment_agent/research`)
* **FeatureLayer & ContextBuilder**: 룩어헤드 편향(Look-ahead bias) 없이 과거 시점 기준의 특성 번들 생성.
* **전통 5대 팩터**: 밸류, 퀄리티, 모멘텀, 성장성, 변동성 지표를 $IC \times \sigma \times z$ 형태로 정규화하여 사전 기대수익 도출.
* **ML Serving**: Champion 머신러닝 모형(LightGBM / XGBoost / CatBoost)을 통해 잔여 초과수익을 $\pm 1\sigma$ 한도 내에서 보수적으로 예측.

### 3) 투자 판단 계층 (`src/investment_agent/trading`)
* **TradingAgents (LLM)**: 5인 에이전트(Market, Fundamental, News, Social, Risk)의 Bull/Bear 토론. **비중 결정 권한이 전혀 없으며**, 오직 논지 설명과 거부권(Veto), 위험 경고만 행사.
* **ALPHA Engine**: 정밀도($1/\sigma^2$) 역수 가중치로 팩터 사전분포와 ML 예측치를 수학적으로 융합.
* **CVXPY Optimizer**: 볼록 최적화기로 불확실성 페널티($\mu - k\sigma$)와 0.2% 교체 허들(No-trade band)을 적용해 목표 비중 산출.
* **DeterministicRiskGate**: 종목당 최대 비중 10%, 위기 시 현금 40% 강제, 레버리지 0 등 하드 리스크 룰을 절대적으로 강제.

### 4) 주문 실행 계층 (`src/investment_agent/execution`)
* **System Portfolio vs My Portfolio 분리**: 시스템 자체 알고리즘 성과(System NAV)는 실제 사용자 승인이나 체결 실패와 완전히 격리되어 100% 자동 기록됨.
* **TossLiveExecutionWorker**: 토스증권 단일 브로커 API 연동. Reserve-Before-Submit(원장 사전예약) 및 매도 우선 체결 적용. 통신 장애나 타임아웃 시 자동 재주문 없이 불일치 락다운(Fail-Closed) 진입.

### 5) 알림 및 대시보드 (`reporting`, `notifications`, `dashboard`)
* **Notification Engine**: 중복 방지 원장(`notices`, `deliveries`)을 거쳐 Discord 웹훅/봇으로 시각화된 PNG 카드와 Embed 전송.
* **Streamlit Dashboard**: 읽기 전용 게이트웨이(`SelectOnlyGateway`)를 통해 안전하게 계좌 상태와 포트폴리오 모니터링 제공.
