# Reporting — 화면과 알림이 공유하는 읽기 모델

`investment_agent.reporting`은 **"이 사실이 어디에 저장돼 있는가"를 소비자에게서 감춘다.**
대시보드와 Discord 카드는 같은 질문을 하고 같은 답을 받아야 하는데, 그 답의 원천은 넷으로
갈라져 있다 — Supabase Postgres, 로컬 SQLite, 로컬 DuckDB, 외부 provider.

감추는 쪽이 흩어지면 화면과 카드가 **서로 다른 숫자를 말한다.** 그래서 저장소를 여는 곳은
`readers/`와 `notifications/` 둘뿐이다.

## 세 계층

| 디렉터리 | 하는 일 | 저장소를 여는가 |
|---|---|---|
| `readers/` | 저장소별 읽기 경계. 파일 이름이 "어디서 오는가"를 말한다 | **연다** |
| `notifications/` | 알림 producer가 쓰는 read model | **연다** |
| `services/` | 주제별 조립·계산. 순수 함수 | 열지 않는다 |

`models.py`의 `DataResult`가 셋을 관통하는 반환 계약이다 — **빈 결과와 연결 실패를 섞지
않는다.** `ok`/`empty`/`unconfigured`/`offline`/`blocked`/`error` 여섯 상태를 구분하므로,
화면은 "데이터가 없다"와 "연결이 안 됐다"를 다르게 그릴 수 있다.

## readers — 어디서 오는가

| 파일 | 원천 |
|---|---|
| `financial.py` | Supabase `reporting.*` 뷰. 연결은 호출자가 주입하고 쓰기·RPC는 없다 |
| `dashboard.py` | 화면이 쓰는 얇은 래퍼. 화면에 스키마 이름·pagination을 들이지 않는다 |
| `runtime.py` | 로컬 SQLite 실행 원장. SELECT만, 파일·스키마를 만들지 않는다 |
| `research.py` | 로컬 DuckDB 연구 산출물 |
| `intelligence.py` | 로컬 DuckDB 뉴스·소셜 색인 |
| `news.py` | 외부 뉴스 provider 결과를 화면 형태로 |

`reporting.*`라는 이름은 **논리적 읽기 계약**이지 Postgres 뷰 목록이 아니다.
`ReportingQueries.VIEWS`의 절반은 SQL 뷰이고 나머지는 `runtime.py`가 SQLite에서 만든다
(`LOCAL_VIEWS`). 소비자는 그 차이를 모른 채 같은 이름으로 읽는다.

## 이력 뷰는 범위를 요구한다

`ReportingQueries.read()`는 `scope_column`이 있는 뷰에 종목·주체 필터나 기간 경계를 요구한다.
무제한 스캔을 막기 위해서다 — PostgREST `authenticator`의 statement_timeout은 8초이고,
넘으면 예외가 아니라 **부분 결과처럼 보이는 실패**로 돌아온다.

시간 컬럼이 없는 master 뷰(`macro_measures`)에는 scope를 걸지 않는다. 걸면 범위로 풀 길이
없어 **영구히 못 읽는다.** `tests/investment_agent/reporting/test_view_reachability.py`가
이것을 강제한다.

## 계산을 저장하지 않는 이유

TTM·margin·서프라이즈·밸류에이션 배수는 표에 굳혀 두지 않고 읽는 시점에 만든다. 계산
규칙이 표시 규칙과 함께 움직이기 때문이다 — DB에 굳혀 두면 규칙이 바뀔 때 과거 행이
**조용히 옛 규칙을 말한다.** market이 조정가를 저장하지 않는 것과 같은 이유다.

## 조용히 틀리는 것

- 화면·알림 계층에서 Supabase client를 직접 열기. 두 곳이 서로 다른 숫자를 말하게 된다.
- `DataResult.empty`와 `error`를 같이 다루기. "데이터 없음"이 장애를 가린다.
- 대량 읽기에 `select_all_paged()` 빠뜨리기 — 1,000행에서 조용히 잘린다.
- 뷰가 `{}`를 돌려주도록 두기. 카드 블록이 에러 없이 사라지고 아무도 모른다.

## 고칠 때 함께 볼 곳

- 새 뷰를 노출한다 → `financial.py`의 `VIEWS` + `db/postgres/v1/90_reporting.sql`
- 로컬 원장 뷰를 늘린다 → `runtime.py`의 `LOCAL_VIEWS`
- 알림 read model → `notifications/` (규칙 15: 알림 패키지는 이 계약을 소비만 한다)
- 화면 read model → `readers/dashboard.py`와 `dashboard/db.py`의 `SelectOnlyGateway`
