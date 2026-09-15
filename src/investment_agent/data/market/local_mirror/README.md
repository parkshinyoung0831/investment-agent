# Local mirror — Supabase 원본 창고의 로컬 계산용 사본

Supabase는 공개 데이터에서 온 금융 사실을 보관하는 **원본 창고**이고, 로컬은 Feature·Factor·ML·RL·Backtest와
System Portfolio를 돌리는 **계산 작업장**이다. 계산할 때마다 종목별로 Supabase를 읽으면 표를 열 때마다 SSL 왕복이
붙어 종목 수만큼 느려진다. 그래서 자주 읽는 원본을 로컬 Parquet 사본으로 두고 먼저 읽는다.

## 사본에 담는 것

| 파일 | 원본 | 용도 |
|---|---|---|
| `securities.parquet` | `universe.securities` + `universe.entities.sic_division_name` | ticker 해석, 추적 종목, 섹터 |
| `memberships.parquet` | `universe.index_memberships`(S&P 500) | 시점별 멤버(생존 편향 방지) |
| `prices.parquet` | `market.prices_daily` | 추적 종목 + 과거 S&P 500 멤버 + 참조 ETF의 일봉 |
| `actions.parquet` | `market.actions_daily` | 배당·분할 |
| `manifest.json` | — | 동기화 시각·가격 최신일·마지막 전체 동기화 시각 |

기본 경로는 `data/local/mirror/`이고 `AI_INVESTOR_LOCAL_MIRROR_ROOT`로 바꿀 수 있다. 커밋하지 않는다.

## 규칙

- **읽기 결과는 Supabase 경로와 같은 모양이다.** `trading/supabase_repository.py`가 사본을 먼저 읽고, 사본이 없거나
  오래됐으면 Supabase로 돌아간다. 동등성은 테스트가 강제한다.
- **오래된 사본으로 "지금"을 판단하지 않는다.** 판단 시각이 동기화 뒤이고 사본이 30시간보다 오래됐으면 쓰지 않는다.
  과거 시점 조회(재현·연구)는 동기화 시각 이전이라 언제나 사본으로 답한다.
- **증분 + 주기적 전체.** 증분은 최근 10일 봉을 다시 받고, 새 가격 대상 종목과 창 안에 분할이 생긴 종목은 전체
  이력을 다시 받는다. 마지막 전체 동기화가 7일 넘으면 전체를 다시 받는다.
- **Supabase에 쓰지 않는다.** 원본 적재는 GitHub Actions 수집 파이프라인만 한다.
- 알림 중복 방지 원장(`notifications`)은 사본에 두지 않는다. Actions와 로컬이 함께 보내므로 Supabase 한 곳이어야 한다.

## 실행

```bash
python -m investment_agent.data.market.commands.sync_local_mirror
python -m investment_agent.data.market.commands.sync_local_mirror --full
```

로컬 하네스의 `local_mirror` job이 2시간마다 증분 동기화한다.
