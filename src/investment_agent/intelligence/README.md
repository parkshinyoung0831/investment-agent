# Intelligence — 뉴스·소셜 텍스트를 종목 언급으로

`investment_agent.intelligence`는 외부 비정형 텍스트를 받아 **어느 종목이 언제 얼마나
언급됐는가**로 바꾼다.

`data/` 옆에 두고 그 안에 넣지 않은 이유는 **저장소가 다르기 때문이다.** `data/`의 금융
사실은 Supabase가 소유하고, 여기의 원문은 로컬 Parquet에, 색인과 언급은 로컬 DuckDB에
남는다. 뉴스와 소셜을 한 패키지로 묶은 것도 같은 이유다 — 출처는 다르지만 목적이 같아서
(외부 텍스트 → 종목 언급) 도메인 규칙과 저장소를 공유한다.

## 저장 계약

| 사실 | 어디에 |
|---|---|
| 기사·게시글 **원문**(제목·본문·요약) | 날짜 파티션 Parquet |
| 중복 제거·보존·신선도용 metadata 색인 | `content_index` (DuckDB) |
| Parquet 뿌리 catalog | `content_files`, `content_catalog_state` |
| 종목 언급 | `entity_mentions` |
| 일별 언급 집계·신선도 | `ticker_mention_daily`, `intelligence_freshness` (뷰) |

**뉴스와 소셜을 한 표에 둔다.** 두 표로 나누면 같은 일(중복 제거·보존·신선도)을 두 번
쓰게 되고, 실제로 한쪽만 고쳐 조용히 갈라진 적이 있다. 다른 축은 하나뿐이다 — 뉴스는 같은
기사가 여러 URL로 오므로 `url_hash`로도 접는다.

두 시각 축을 구분한다. `observed_at`은 **발행** 시각이고 retention이 자르는 기준이다.
`first_seen_at`은 PIT 축이다 — "그때 우리가 이미 갖고 있었나"는 이것으로만 답한다.

단일 선언은 `db/duckdb/intelligence/v1/*.sql`이며 기본 경로는
`data/local/intelligence/intelligence.duckdb`다. 커밋하지 않는다.

## 구조

```text
provider(yfinance news · Reddit)
  → domain/         무엇이 중복인가, 무엇이 언급인가 (순수 규칙)
  → application/    collect_news · collect_social · retention
  → infrastructure/sources/   provider 어댑터
  → repository.py   Parquet 쓰기 + DuckDB 색인 경계
```

## 실행

```bash
python -m investment_agent.intelligence.commands.collect_news
python -m investment_agent.intelligence.commands.collect_social
python -m investment_agent.intelligence.commands.prune
```

로컬 하네스가 주기적으로 부른다. GitHub Actions에서는 돌지 않는다 — provider 호출 한도와
로컬 저장소가 실행 컴퓨터에 묶여 있기 때문이다.

## 보존은 90일, 기준은 발행 시각

`collected_at`을 기준으로 자르면 100일 전 글을 오늘 주워 90일을 더 들고 있게 된다.
기준은 `coalesce(published_at, first_seen_at)`이다 — **오래된 글은 오늘 수집해도 오래된
글이다.**

뉴스와 소셜을 함께 지운다. 컷오프가 세 표에 동시에 걸리지 않으면 부모 없는 mention이
남는 창이 반드시 생긴다.

## 조용히 틀리는 것

- provider 호출 전에 cap 슬롯을 예약하지 않기. 한도를 넘기면 조용히 빈 결과가 온다
  (`platform/external_usage.py`가 호출 **전에** 막는다).
- `collected_at`으로 보존을 자르기.
- 원문을 DuckDB나 Supabase에 넣기. 본문은 Parquet가 소유한다.
- 화면에서 provider를 직접 부르기. 화면은 `reporting/readers/intelligence.py`와
  `news.py` 계약만 소비한다.

## 고칠 때 함께 볼 곳

- provider 추가 → `infrastructure/sources/` + `platform/external_usage.py`의 cap
- 화면 노출 → `reporting/readers/intelligence.py`, `reporting/readers/news.py`
- 하네스 주기 → `operations/harness/pipeline.py`의 `intelligence_job`
- 킬 스위치·자격증명 → [docs/ENV.md](../../../docs/ENV.md)
