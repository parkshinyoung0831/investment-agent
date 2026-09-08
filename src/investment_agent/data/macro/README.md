# MACRO — v1 market-state pipeline

MACRO answers “what is the market state?” with versioned time-series observations.
The executable path is `investment_agent`; the v1 schema declaration is
`db/postgres/v1/40_macro.sql`.

```text
catalog → fetch → validate → persist observation_versions
```

## Responsibility

MACRO owns market prices and derived state: rates, spreads, FX, commodities,
volatility, sentiment, and breadth. Economic release schedules, forecasts,
actuals, surprises, and revisions belong to the economic-release portion of the
v1 macro schema, not to market-state collection.

## Execution

```powershell
python -m investment_agent.data.macro.commands.macro_refresh --lookback-days 14
python -m investment_agent.data.macro.commands.macro_refresh --dry-run
python -m investment_agent.data.macro.commands.macro_refresh --dry-run --series BREADTH_200DMA
python -m investment_agent.data.macro.commands.macro_refresh --backfill-from 2016-01-01
```

The entrypoint reads the v1 catalog through `MacroRepository`, fetches each
source independently, applies series and cross-source validation, and persists
versioned rows through `MacroService`. `--dry-run` performs no database writes.

## Source adapters

| source | responsibility |
|---|---|
| `infrastructure/sources/fred.py` | US rates, inflation expectations, and spreads |
| `infrastructure/sources/ecos.py` | Korean rates, FX, and flows |
| `infrastructure/sources/yfinance.py` | indexes, ETFs, commodities, VIX/MOVE, crypto |
| `infrastructure/sources/web.py` | registered web parsers |
| `infrastructure/sources/market.py` | breadth derived from v1 universe and market repositories |

## Code structure

```text
src/investment_agent/data/macro/
├── domain/
│   ├── catalog.py       # source/series declarations used by tests and tooling
│   ├── quality.py       # series contracts and FX cross-source checks
│   ├── revisions.py     # PIT observation rules
│   └── releases/        # economic release rules
├── application/
│   ├── refresh_market_state.py
│   └── release_calendar.py
├── infrastructure/
│   ├── fetch.py     # bounded fetch, normalization, and common validation
│   ├── settings.py  # source budgets and collector configuration
│   └── sources/     # external and internal source adapters
├── repository.py    # v1 macro reads and observation writes
├── commands/        # executable Macro entrypoints
└── releases/        # release persistence and release contracts
```

`db/postgres/v1/40_macro.sql` is the schema source of truth. Observations are append-only
versions keyed by series, reference period, source, effective time, and collection
time; consumers must choose an as-of snapshot rather than assuming one mutable
row per date.

## Snapshot retention

일정과 예상은 발표 전에는 변경 자체가 신호지만, 실제치가 나오면
`reporting.macro_release_summary`가 쓰는 것은 둘뿐이다 — 확정된 마지막 일정과
실제치 직전의 예상(closing). `macro.prune_release_snapshots()`가 실제치가 있는
ref_period만, 그것도 최근 180일 밖의 것만 그 한 건씩 남기고 정리한다
(`release_calendar.run_daily`이 실패 없는 회차에만 호출한다).

## Operational boundary

The macro workflow and tests use the v1 entrypoint and repositories. Database reset,
external recollection, and Discord delivery are separate operational actions and
are intentionally not performed by this implementation change.
