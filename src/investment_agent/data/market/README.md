# Market — 일봉과 corporate action

`investment_agent.data.market`는 완료된 Yahoo 일봉과 corporate action을
`security_id` 기준으로 저장한다. ticker는 외부 입력·표시용이고, market의 모든
FK와 자연키는 universe identity를 따른다.

## 저장 계약

| 사실 | v1 표 |
|---|---|
| OHLCV 관측값 | `market.prices_daily` |
| 날짜별 분할·배당 | `market.actions_daily` |

조정가·수익률·이동평균은 저장하지 않는다. 일봉은 거래일 종료 뒤 공개된 사실이라 PIT
조회는 `trade_date`로 자른다.

분할과 배당은 같은 날 한 행이다. 쓰기는 `market.merge_actions` RPC 하나로만 한다 — 응답에
없는 값을 NULL로 지우지 않고, 같은 배당을 두 번 받아도 더하지 않는다.

## 실행 흐름

daily와 backfill은 `application/price_collection.py`의 같은 절차를 쓰고 대상·기간만 다르다.

```text
수집 계획 고정: PriceTarget(security_id, 요청 symbol)
  → Yahoo download
  → 계획의 security_id 부착 (계획에 없는 symbol은 거절)
  → (backfill) 원본 daily Parquet archive
  → actions_daily 병합 → prices_daily upsert
```

저장할 때 ticker를 다시 security_id로 풀지 않는다. 수집 도중 개명·티커 재사용이 반영되면
다른 종목에 쓸 수 있기 때문이다.

```powershell
python -m investment_agent.data.market.commands.market_daily
python -m investment_agent.data.market.commands.market_backfill
python -m investment_agent.data.market.commands.market_backfill --scope all-current
```

분할 이벤트가 새로 발견되면 daily entrypoint가 그 종목의 장기 가격을 같은 계획으로 다시
받아 같은 key로 멱등 저장한다. `persistence.py`는
`UniverseRepository`·`MarketRepository`를 통해서만 읽고 쓴다.

## 보존 정책

`compact_price_rows()`는 백필 입력을 정규화하는 순수 함수다. compact 전에 Yahoo 원본
일봉은 `INVESTMENT_AGENT_MARKET_ARCHIVE_DIR`(기본 `artifacts/market_history`)에 security_id별
Parquet으로 원자 기록한다. CI에서는 이 값을 runner 수명보다 긴 영속 볼륨으로 지정해야
하며, archive 기록 실패 시 DB write를 시작하지 않는다. 현재 v1 DDL은
append-only 관측 원장만 정의하므로 `prune_history()`는 명시적으로 기록하고 no-op으로
끝낸다.

스키마의 단일 선언은 `db/postgres/v1/20_market.sql`이며, bootstrap은 이 파일을 사용한다.
