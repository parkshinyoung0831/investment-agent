"""고정 30개 지표의 수집기 설정. API 옵션·라이선스 설명은 사실표에 반복하지 않는다."""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any


_MEASURE_SPECS = """US_CPI.LEVEL|index|level|3|0|average
US_CPI.MOM|percent|pct_change_1|2|1|none
US_CPI.YOY|percent|pct_change_12|2|0|none
US_CORE_CPI.MOM|percent|pct_change_1|2|1|none
US_CORE_CPI.YOY|percent|pct_change_12|2|0|none
US_PPI.MOM|percent|pct_change_1|2|1|none
US_PPI.YOY|percent|pct_change_12|2|0|none
US_CORE_PPI.MOM|percent|pct_change_1|2|1|none
US_CORE_PPI.YOY|percent|pct_change_12|2|0|none
US_PCE.MOM|percent|pct_change_1|2|1|none
US_PCE.YOY|percent|pct_change_12|2|0|none
US_CORE_PCE.MOM|percent|pct_change_1|2|1|none
US_CORE_PCE.YOY|percent|pct_change_12|2|0|none
KR_CPI.MOM|percent|pct_change_1|2|1|none
KR_CPI.YOY|percent|pct_change_12|2|0|none
KR_CORE_CPI.MOM|percent|pct_change_1|2|1|none
KR_CORE_CPI.YOY|percent|pct_change_12|2|0|none
US_NFP.MONTHLY_CHANGE|thousand_jobs|change_1|1|1|none
US_UNEMPLOYMENT.LEVEL|percent|level|1|1|average
US_AHE.MOM|percent|pct_change_1|2|1|none
US_AHE.YOY|percent|pct_change_12|2|0|none
US_JOLTS_OPENINGS.LEVEL|thousand_jobs|level|0|1|average
US_INITIAL_CLAIMS.LEVEL|thousand_persons|level|0|1|average
US_CONTINUING_CLAIMS.LEVEL|thousand_persons|level|0|1|average
US_GDP.QOQ_ANNUALIZED|percent_annualized|level|1|1|none
KR_GDP.QOQ|percent|level|1|1|none
US_RETAIL_SALES.MOM|percent|pct_change_1|2|1|none
US_RETAIL_SALES.YOY|percent|pct_change_12|2|0|none
US_INDUSTRIAL_PRODUCTION.MOM|percent|pct_change_1|2|1|none
US_INDUSTRIAL_PRODUCTION.YOY|percent|pct_change_12|2|0|none
US_ISM_MANUFACTURING.PMI|pmi|level|1|1|average
US_ISM_SERVICES.PMI|pmi|level|1|1|average
US_MICHIGAN_SENTIMENT.LEVEL|index|level|1|1|average
US_FOMC_FED_FUNDS.UPPER_BOUND|percent|level|2|1|none
KR_BASE_RATE.LEVEL|percent|level|2|1|none
US_MORTGAGE_30Y.LEVEL|percent|level|2|1|average
US_NEW_HOME_SALES.LEVEL|thousand_units|level|0|1|average
US_EXISTING_HOME_SALES.LEVEL|thousand_units|level|0|1|average
US_M2.LEVEL|usd_billions|level|1|1|average
US_M2.YOY|percent|pct_change_12|2|0|none
FED_NET_LIQUIDITY.LEVEL|usd_billions|level|1|1|last
FED_NET_LIQUIDITY.CHANGE_4W|usd_billions|change_4|1|0|none
KR_EXPORT.LEVEL|billion_usd|level|1|1|sum
KR_EXPORT.YOY|percent|pct_change_12|2|0|none
EIA_CRUDE_OIL_INVENTORIES.LEVEL|thousand_barrels|level|0|1|last
EIA_CRUDE_OIL_INVENTORIES.WEEKLY_CHANGE|thousand_barrels|change_previous|0|0|none"""


@lru_cache(maxsize=1)
def _settings() -> dict[str, dict[str, Any]]:
    path = Path(__file__).parents[2] / "releases" / "series_config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def series_config(series_id: str) -> dict[str, Any]:
    """호출자가 고정 설정을 수정하지 못하도록 복사해 반환한다."""
    try:
        return deepcopy(_settings()[series_id])
    except KeyError as exc:
        raise ValueError(f"unknown ECON series: {series_id}") from exc


def enrich_series(row: dict[str, Any]) -> dict[str, Any]:
    """DB의 표시·단위 master와 코드의 수집 계약을 실행 시점에 결합한다."""
    config = series_config(str(row["series_id"]))
    forecast_measure_id = str(config.get("forecast_measure_id") or "")
    if not forecast_measure_id.startswith(f"{row['series_id']}."):
        raise ValueError(f"{row['series_id']}: forecast measure differs from the series")
    contract = config["source_contract"]
    for column, expected in (("base_unit", contract.get("actual", {}).get("unit")),
                             ("timezone", contract.get("schedule", {}).get("timezone"))):
        if column in row and expected is not None and row[column] != expected:
            raise ValueError(f"{row['series_id']}: {column} differs from the fixed provider contract")
    return {**row, **config, "is_enabled": True}


def series_ids() -> frozenset[str]:
    return frozenset(_settings())


def series_definitions() -> tuple[dict[str, Any], ...]:
    """빈 DB의 경제지표 master를 재현할 수 있는 코드 catalog."""
    path = Path(__file__).parents[2] / "releases" / "catalog_metadata.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if {row["series_id"] for row in rows} != set(series_ids()):
        raise ValueError("economic metadata and collector catalog differ")
    return tuple(rows)


def measure_definitions() -> tuple[dict[str, Any], ...]:
    """경제 발표 계산에 필요한 고정 measure 정의를 반환한다."""
    rows = []
    for line in _MEASURE_SPECS.splitlines():
        measure_id, unit, transform, decimals, primary, rollup = line.split("|")
        series_id = measure_id.rsplit(".", 1)[0]
        rows.append({"measure_id": measure_id, "series_id": series_id, "name_ko": measure_id,
                     "unit": unit, "transform": transform, "decimal_places": int(decimals),
                     "is_primary": primary == "1", "rollup_method": rollup})
    return tuple(rows)
