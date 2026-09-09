# 서드파티 고지 — 코드·데이터·외부 API

이 저장소는 서드파티 소프트웨어, vendored 참조 데이터, 공개 데이터 API를 함께 씁니다.
셋은 지켜야 할 것이 서로 달라서 나눠 적습니다.

- **소프트웨어 의존성** — 설치해서 쓰고, 저장소에 코드를 담지 않습니다.
- **vendored 데이터** — 파일을 저장소에 담습니다. 그래서 출처·라이선스·해시를 함께 적습니다.
- **외부 데이터 API** — 저장소에 담지 않고 실행 시점에 받아옵니다. 제공자 약관과 호출
  한도가 그대로 적용됩니다.

이 저장소 자체의 라이선스는 **아직 선언돼 있지 않습니다.** 루트에 `LICENSE`가 생기기
전까지 소스 사용 권한을 추정하지 마세요([README](README.md) 참고).

## 저장소에 담은 것 (vendored)

파일을 커밋했으므로 원 라이선스의 고지 의무가 이 저장소에 그대로 붙습니다. 각 파일 옆의
`NOTICE.md`가 출처·버전·해시를 갖는 단일 기준입니다.

| 담은 것 | 출처 | 라이선스 | 고지 |
|---|---|---|---|
| `data/fundamentals/data/gaap_mappings.json` | [dgunning/edgartools](https://github.com/dgunning/edgartools) 5.53.0 | MIT | [NOTICE.md](src/investment_agent/data/fundamentals/data/NOTICE.md) |
| 13F 금액 단위 판별 로직(재구현) | edgartools 5.36.0 | MIT | [NOTICE.md](src/investment_agent/data/institutional/NOTICE.md) |

`gaap_mappings.json`은 3.7MB짜리 참조 표라 런타임에 edgartools를 import하지 않고 파일만
읽습니다 — 결정적으로 읽기 위해서입니다. 반대로 13F shadow 파서는 `GURUS_SHADOW_PARSER=on`
일 때만 edgartools를 실제로 import합니다.

## 설치해서 쓰는 것 (의존성)

버전 고정의 단일 기준은 [`pyproject.toml`](pyproject.toml)의 `[dependency-groups]`입니다.
아래는 그것을 다시 적은 것이 아니라 **왜 그 그룹이 있는지**만 적습니다 — 목록이 두 곳에
있으면 한쪽이 조용히 낡습니다.

| 그룹 | 무엇을 위해 |
|---|---|
| `core` | Supabase 접근, HTTP, 표 계산, 재시도 — 모든 잡이 쓴다 |
| `data` | SEC·Yahoo 수집과 파싱(`secfsdstools`, `edgartools`, `lxml`, `beautifulsoup4`) |
| `research` | 로컬 DuckDB와 백테스트(`duckdb`, `pyqlib`, `lumibot`) |
| `ml` / `rl` | 학습·강화학습(`scikit-learn`, `lightgbm`, `xgboost` / `gymnasium`, `stable-baselines3`) |
| `portfolio` | 최적화(`cvxpy`) |
| `dashboard` | 읽기 전용 화면(`streamlit`, `plotly`) |
| `notifications` | PNG 카드 렌더(`playwright`, `jinja2`) |
| `execution` | Discord 승인 경로(`discord.py`) |
| `intelligence` | 뉴스·소셜(`praw`, `duckdb`) |

CI는 잡마다 필요한 그룹만 설치합니다. 전부 필요한 것은 로컬 개발(`dev`)뿐입니다.

`numpy<2` 상한이 한 곳에서 여러 그룹을 묶고 있습니다 — `secfsdstools`가 NumPy 2를 받지
않아서이고, 그 때문에 `cvxpy`도 1.9 미만으로 잠겨 있습니다. 셋 중 하나를 올리려면 나머지
둘을 함께 봐야 합니다.

## 실행 시점에 받아오는 것 (외부 API)

저장소는 이 데이터를 담지 않습니다. **재배포하지 않으며**, 각 제공자의 이용약관과 호출
한도가 그대로 적용됩니다. 자격증명은 환경변수로만 주입합니다([docs/ENV.md](docs/ENV.md)).

| 제공자 | 받는 것 | 쓰는 곳 |
|---|---|---|
| SEC EDGAR | 공시 원문, 재무 데이터셋, 13F, 거래소 마스터 | `data/fundamentals`, `data/institutional`, `data/universe` |
| Yahoo Finance (`yfinance`) | 일봉·분할·배당, 일부 지수·원자재 | `data/market`, `data/macro` |
| FRED (St. Louis Fed) | 미국 금리·물가·스프레드 | `data/macro` |
| ECOS (한국은행) | 한국 금리·환율·자금흐름 | `data/macro` |
| EIA | 원유 재고 | `data/macro` |
| Discord | 알림 전송, 승인 상호작용 | `notifications`, `execution` |
| 토스증권 | 계좌·주문(고정 IP 로컬 실행 전용) | `execution/brokers/toss` |

SEC는 User-Agent에 연락처를 요구합니다. 호출 한도는 `platform/external_usage.py`가 하루
단위로 예약·집계하며, 한도를 넘기면 호출 **전에** 막습니다.

## 무엇을 고쳐야 하나

- vendored 파일을 새 버전으로 올렸다 → 해당 `NOTICE.md`의 버전·바이트 수·SHA-256을 함께 고친다.
- 새 의존성을 넣었다 → `pyproject.toml`의 그룹에 넣고, 새 **성격**의 의존이면 위 표에 한 줄 추가한다.
- 새 외부 API를 붙였다 → 위 표에 한 줄, `docs/ENV.md`에 자격증명, `external_usage.py`에 cap.
- 저장소 라이선스를 정했다 → `LICENSE`를 추가하고 [README](README.md)의 마지막 문단을 고친다.
