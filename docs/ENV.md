# 환경변수 레퍼런스

실행할 job에 어떤 설정이 필요한지 찾는 조회용 문서다. 값은 `.env`(로컬) 또는 GitHub
Actions secrets/variables(CI)에 주입하며, 이 파일에는 이름·용도·안전 기본값만 적는다.

처음 띄울 때 필요한 최소값과 안전 기본값은
[OPERATIONS.md의 '최소 환경변수와 안전 기본값'](OPERATIONS.md#최소-환경변수와-안전-기본값)에 있다.

공통: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (모든 잡 필수).

| 변수 | 용도 |
|---|---|
| `SUPABASE_DB_URL` | Postgres 직결 (DDL 적용·스키마 점검). 로컬 전용, CI에 주입하지 않음 |
| `EDGAR_USER_AGENT` | SEC 호출 (universe, fundamentals, gurus). 이름 + 실제 이메일 포함 |
| `SEC_REQUEST_GAP_SEC` | SEC 호출 간격(기본 0.12) |
| `FRED_API_KEY`, `ECOS_API_KEY`, `EIA_API_KEY` | macro와 econ calendar의 provider 호출. 필요한 job만 해당 key를 사용 |
| `MACRO_SOURCE_BUDGET_SEC` | macro 소스별 수집 상한(초, 기본 360). 느린 출처 하나가 실행 전체를 삼키지 못하게 한다 |
| `OPENFIGI_API_KEY` | gurus CUSIP 매핑 대량 배치 |
| `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET` | 선택적인 종목명·보유종목·주문 adapter. 허용 IP와 broker 정책을 확인한 로컬 환경에서만 사용 |
| `TOSS_TOKEN_CACHE_PATH` | 선택. 토스 OAuth 공용 cache 경로. 기본 `artifacts/toss_auth/oauth-token.json` |
| `DISCORD_BOT_TOKEN` | 알림 카드 전송 (봇) |
| `DISCORD_WEBHOOK_OPS_ACTIONS` | GitHub Actions 실패 webhook (`#액션-실패`) |
| `DISCORD_WEBHOOK_OPS_LOCAL` | 로컬 하네스·실행 실패 webhook (`#로컬-실패`). 목적지는 실행된 곳이 정한다 — `GITHUB_ACTIONS` 유무로 고른다 |
| `DISCORD_CHANNEL_OPS_DIGEST` | 일일 점검 요약 채널 ID (`#운영-요약`) |
| `DISCORD_CHANNEL_OPS_ACTIONS`, `DISCORD_CHANNEL_OPS_LOCAL`, `DISCORD_CHANNEL_OPS_DELIVERY` | 실패 채널 ID. 조용한 것이 정상이라 heartbeat는 침묵을 묻지 않는다 |
| `DISCORD_CHANNEL_MACRO_DAILY` / `_MACRO_ALERT` / `DISCORD_CHANNEL_ECON_CALENDAR_RELEASE` / `_GURUS` / `_STRATEGY_MONTHLY` | 채널 라우팅 |
| `DISCORD_CHANNEL_EARNINGS` / `_EARNINGS_CALENDAR` | 실적. `_EARNINGS`는 **포럼 채널**이라 스레드로 발송한다 |
| `DISCORD_CHANNEL_AI_REPORTS` / `_AI_TRADES` | 자동매매. 판단·후보 리포트와 실제 체결 기록. `_AI_APPROVALS`와 같은 비공개 카테고리 |
| `AI_INVESTOR_REPORT_TOP_N` | 하루에 보낼 종목 심층 카드 수(기본 5, 1~25) |
| `AI_INVESTOR_TRADE_LOOKBACK_HOURS` | 체결 보고가 되돌아볼 시간(기본 26, 1~168) |
| `AI_INVESTOR_NOTIFY_FORCE` | 자동매매 보고서를 선점 기록 무시하고 다시 보낼 때(수동 재발송) |
| `DISCORD_CHANNEL_LAB_CARDS` / `_LAB_OPS` / `_LAB_FORUM` | 실험용. 카드 형식을 다듬을 때 운영 채널 대신 여기로 (포럼은 포럼끼리 바꿔 끼운다) |
| `DISCORD_ADMIN_TOKEN` | Discord 채널·역할을 만들고 고치는 adapter. **로컬 전용 — CI에 주입 금지** |
| `DISCORD_GUILD_ID` | 봇이 채널을 **이름으로** 찾을 때 쓰는 길드 ID. 자격증명이 아니라 식별자라 CI에도 넣는다 — 거장 포럼처럼 채널이 늘어날 수 있는 곳은 채널 ID를 시크릿으로 받지 않는다 |
| `FUNDAMENTALS_KILL`, `GURUS_KILL`, `ECON_CALENDAR_KILL` | 킬 스위치 (레포 변수) |
| `GURUS_POLL_WINDOW_DAYS`, `GURUS_NOTIFY_FORCE` | gurus 수집 창·수동 재발송 |
| `SUPABASE_ANON_KEY` | 공개 읽기 클라이언트용. 현재 실행 경로에서는 쓰지 않음 |
| `AI_INVESTOR_LOCAL_DATA_ROOT` | 로컬 저장소 공통 루트. 기본 `data/local`; store별 명시 경로가 우선 |
| `AI_INVESTOR_LOCAL_ARTIFACT_ROOT` | 모델·evidence·broker·report artifact 루트. 기본 `data/local/artifacts` |
| `INVESTMENT_AGENT_RESEARCH_ROOT` | Research DuckDB·Parquet 루트. 기본 `data/local/research` |
| `AI_INVESTOR_RUNTIME_DB_PATH` | Runtime SQLite 경로. 기본 `data/local/runtime/runtime.sqlite3` |
| `AI_INVESTOR_MARKET_CHANGE_MANIFEST_PATH` | Market 변경 manifest 경로. 기본 `data/local/artifacts/market_change_manifest.json` |
| `INVESTMENT_AGENT_MARKET_ARCHIVE_DIR` | Yahoo 원본 daily Parquet archive의 **영속** 루트. 기본 `artifacts/market_history`; CI에서는 runner 밖의 영속 볼륨을 지정한다 |
| `GURUS_SHADOW_PARSER` | `on`이면 edgartools로 13F를 다시 파싱해 직접 파서 결과와 사후 대조한다. 불일치는 JSON 로그와 Discord 시스템 로그로 진단하며, 기본 off·운영 적재는 항상 직접 파서다 |
| `FUNDAMENTALS_INDEX_LOOKBACK_DAYS`, `FUNDAMENTALS_NOTIFY_LOOKBACK_DAYS` | 증분 창 조정 |
| `FUNDAMENTALS_SEGMENT_WAIT_DAYS` | 정밀 카드가 세그먼트를 기다리는 기한(기본 3일). 넘기면 재무 카드만 보낸다 — 세그먼트는 SEC 분기 데이터셋에서 와 한 분기 늦다 |
| `FUNDAMENTALS_EXPECTATIONS_WORKERS` | Yahoo 예상치 동시 수집 수(기본 4, 1~16). Actions는 명시적으로 4 사용 |
| `FUNDAMENTALS_FAST_LEAD_DAYS`, `FUNDAMENTALS_FAST_LAG_DAYS`, `FUNDAMENTALS_FAST_STALE_DAYS` | fast path 시즌 창(기본 5·10·7일). `.env.example`의 빈 값은 코드 기본값을 사용 |
| `FUNDAMENTALS_CALENDAR_FORCE` | 발표 예정 카드를 같은 주에 다시 보낼 때(수동 재발송) |
| `MACRO_NOTIFY_FORCE` | 매크로 코어 카드를 같은 날 다시 보낼 때(수동 재발송) |
| `ECON_CALENDAR_ICS_BUCKET` | 캘린더 구독 파일을 올릴 Supabase Storage **공개** 버킷(기본 `econ-calendar`). 버킷은 사람이 만든다 — 코드가 공개 버킷을 만들지 않는다 |
| `OPS_HEARTBEAT_PING_URL` | 외부 dead-man's switch(healthchecks.io 등). 일일 점검 발송 뒤 핑. 비어 있으면 아무 일도 하지 않는다 |
| `LOG_LEVEL` | 로그 레벨 (기본 INFO) |
| `AI_INVESTOR_MODE` | LLM 연구 entry 모드. `shadow_daily`/`portfolio_shadow`는 `shadow`만 허용 |
| `AI_INVESTOR_BASE_URL`, `AI_INVESTOR_MODEL` | OpenAI 호환 로컬/원격 LLM 주소와 모델 이름 |
| `AI_INVESTOR_AZURE_API_KEY`, `AZURE_AI_BASE_URL` | 선택적인 Azure OpenAI 호환 provider credential과 endpoint |
| `AI_INVESTOR_AZURE_DAILY_REQUESTS` | Azure provider에 적용할 프로젝트별 일일 지출·호출 가드 |
| `AI_INVESTOR_GEMINI_API_KEY`, `GROQ_API_KEY` | 선택적인 provider credential. 각 provider의 현재 요금·rate limit·약관을 직접 확인 |
| `AI_INVESTOR_LLM_MAX_RETRIES` | 429를 견딜 SDK 재시도 횟수(기본 15, 0~20). 대기는 provider가 준 Retry-After를 따른다 |
| `AI_INVESTOR_API_KEY`, `AI_INVESTOR_PROVIDER`, `AI_INVESTOR_TIMEOUT_SEC`, `AI_INVESTOR_DAILY_LIMIT` | 선택 API 키·공급자 라벨·호출 제한·하루 종목 한도 |
| `AI_INVESTOR_TRADINGAGENTS_PROVIDER` | TradingAgents provider 이름. Ollama는 `ollama` |
| `AI_INVESTOR_TRADINGAGENTS_NEWS_VENDOR` | live News upstream vendor. 기본 `yfinance` |
| `ALPHA_VANTAGE_API_KEY` | News vendor가 `alpha_vantage`이면 필수 |
| `AI_INVESTOR_EXTERNAL_NEWS_SOCIAL` | TradingAgents live 외부 뉴스·소셜 전체 kill switch |
| `AI_INVESTOR_EXTERNAL_SOCIAL_VENDORS` | 사용 권한이 준비된 소셜 provider 목록. 기본 비활성; Reddit RSS는 미지원 |
| `STOCKTWITS_API_ACCESS_APPROVED` | StockTwits 승인 API/서면 허가 확인 플래그. 기본 `false`; consumer 구독만으로 켜지 않는다 |
| `AI_INVESTOR_EXTERNAL_MAX_CALLS_PER_TICKER` | 외부 공급자 실제 호출의 종목별 상한. 기본 4 |
| `AI_INVESTOR_EXTERNAL_DAILY_CAPS`, `AI_INVESTOR_EXTERNAL_USAGE_LEDGER_PATH` | provider별 UTC 일일 cap과 metadata-only 로컬 원장. 80% 1회 경고·cap 이후 차단. **`yfinance`와 `reddit` 항목이 반드시 있어야 한다** — `provider_daily_cap()`은 한도가 선언되지 않은 공급자의 호출을 fail-closed로 거부한다 |
| `AI_INVESTOR_SAVE_EXTERNAL_RAW` | 외부 원문 로컬 저장 opt-in. 기본 `false` |
| `AI_INVESTOR_LOCAL_NEWS_CACHE_ENABLED`, `AI_INVESTOR_NEWS_CACHE_PATH` | live 뉴스·소셜 DuckDB cache와 경로. historical replay는 접근 금지 |
| `AI_INVESTOR_INTELLIGENCE_DB_PATH` | Intelligence DuckDB 경로 (기본 `data/local/intelligence/intelligence.duckdb`) |
| `AI_INVESTOR_INTELLIGENCE_PARQUET_ROOT` | Intelligence 뉴스·소셜 본문 Parquet 루트 (기본 `data/local/intelligence/parquet`) |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` | Reddit 수집 자격증명. 없으면 소셜 수집을 건너뛴다 |
| `AI_INVESTOR_ARTIFACT_DIR` | TradingAgents cache/report와 선택적 raw 저장 루트 |
| `AI_INVESTOR_RL_BLEND_ENABLED` | 승격된 RL 정책의 목표비중을 **판단에 실제로 반영**할지. 기본 `false`. 꺼져 있으면 제안은 종전과 같고 "켰다면 얼마나 달라졌을지"만 로그로 남는다. 사람이 명시적으로 켠다 |
| `LIVE_ENABLED` | broker-independent live opt-in. DB durable control/permit와 AND 결합, 기본 `false` |
| `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`, `TOSS_ACCOUNT_SEQ` | 허용 IP가 등록된 execution 전용 장비. 분석·학습 환경에는 주입 금지 |
| `TOSS_LIVE_ENABLED` | Toss 주문 생성 전역 opt-in. 기본 `false`; 모델 승격이나 서비스 설치가 자동으로 바꾸지 않음 |
| `TOSS_MAX_ORDER_NOTIONAL_USD`, `TOSS_MAX_DAILY_NOTIONAL_USD`, `TOSS_MAX_DAILY_ORDERS` | 주문별·일별 제출 한도 |
| `TOSS_MAX_DAILY_LOSS_USD`, `TOSS_MAX_DRAWDOWN_FRACTION`, `TOSS_ALLOW_MARKET_ORDERS` | 실시간 손실·drawdown·시장가 차단. 시장가는 기본 `false` |
| `TRADING_KILL_SWITCH` | 로컬 하네스의 신규 live 흐름 전역 차단. 미설정·오타도 `on`으로 해석 |
| `DISCORD_APPROVAL_BOT_TOKEN`, `DISCORD_APPROVAL_HMAC_SECRET[_FILE]` | `#투자-승인` 카드·서명 button 전용. 봇 token은 카드봇/관리봇과 분리하고, inline HMAC을 비우면 전용 파일을 현재 사용자 권한으로 자동 생성 |
| `DISCORD_CHANNEL_AI_APPROVALS`, `DISCORD_APPROVER_USER_IDS`, `AI_APPROVAL_TTL_MINUTES` | 승인 채널·본인 allowlist·만료시간 |
| `HARNESS_NY_SESSION_*`, `HARNESS_NY_RISK_*`, `HARNESS_APPROVAL_POLL_SEC` | 뉴욕 현지 신규 판단·계좌 감시 구간과 Discord 승인 polling 간격 |
| `HARNESS_*_TIMEOUT_SEC`, `HARNESS_JOB_*_KILL_SWITCH` | 로컬 하위 entry 시간 상한과 job별 차단 |
| `GRAPHIFY_NO_BACKUP` | `1`로 설정 시 `graphify update` 실행 시 `graphify-out/YYYY-MM-DD/` 날짜별 과거 백업 폴더 자동 생성을 방지 |

실적 관심종목은 환경변수가 아니라 `universe.entities.watchlist_sources`(관심 기업 컬럼)가 단일 기준이며,
`python -m investment_agent.data.universe.watchlists.watchlist`로 추가·해제합니다.

`.env`는 **절대 커밋 금지**(`.gitignore`로 차단). 비밀값은 GitHub Actions secrets/variables로
주입하며, provider key·broker credential·Discord token을 issue, log, artifact에 남기지 않습니다.

