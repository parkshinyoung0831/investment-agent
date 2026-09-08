# Market v1

`investment_agent.data.market`는 완료된 Yahoo 일봉과 corporate action을
`security_id` 기준으로 저장한다. ticker는 외부 입력·표시용이고, market의 모든
FK와 자연키는 universe identity를 따른다.

## 저장 계약

| 사실 | v1 표 |
|---|---|
| OHLCV 관측값 | `market.prices_daily` |
| 주식분할 | `market.split_events` |
| 배당락 | `market.dividend_events` |

조정가·수익률·이동평균은 저장하지 않는다. PIT 조회는 `trade_date`와
`ingested_at`을 함께 잘라야 한다.

## 실행 흐름

```text
universe.securities(is_tracked) → Yahoo download
  → ticker → security_id 변환
  → 원본 daily Parquet archive
  → prices_daily / split_events / dividend_events upsert
```

```powershell
python -m investment_agent.data.market.commands.market_daily
python -m investment_agent.data.market.commands.market_backfill
python -m investment_agent.data.market.commands.market_backfill --scope all-current
```

분할 이벤트가 새로 발견되면 daily entrypoint가 해당 ticker의 장기 가격을 다시
받아 같은 v1 key로 멱등 저장한다. `persistence.py`는
`UniverseRepository`·`MarketRepository`를 통해서만 읽고 쓴다.

## 보존 정책

`compact_price_rows()`는 백필 입력을 정규화하는 순수 함수다. compact 전에 Yahoo 원본
일봉은 `INVESTMENT_AGENT_MARKET_ARCHIVE_DIR`(기본 `artifacts/market_history`)에 ticker별
Parquet으로 원자 기록한다. CI에서는 이 값을 runner 수명보다 긴 영속 볼륨으로 지정해야
하며, archive 기록 실패 시 DB write를 시작하지 않는다. 현재 v1 DDL은
append-only 관측 원장만 정의하므로 `prune_history()`는 명시적으로 기록하고 no-op으로
끝낸다.

스키마의 단일 선언은 `db/postgres/v1/20_market.sql`이며, bootstrap은 이 파일을 사용한다.
