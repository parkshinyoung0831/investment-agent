"""대시보드 매크로 관측치 요약·진단·지표 스트립 계산."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

import pandas as pd

from investment_agent.dashboard.calculations._common import (
    _records,
    finite_number,
    parse_date_safe,
    parse_datetime_safe,
)
from investment_agent.dashboard.calculations.schedule import MACRO_SPARK_POINTS
from investment_agent.reporting.services.macro.freshness import freshness_for

_MACRO_SERIES = ("VIX", "FEAR_GREED", "DXY", "TNX")

def macro_latest(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> dict[str, dict[str, Any]]:
    """관측치를 지표별 최신·직전 값으로 요약한다.

    반환 매핑의 각 값은 ``series_id``, 표시 메타데이터, ``current_value`` /
    ``current_date``, ``previous_value`` / ``previous_date``, ``change``와
    ``change_pct``를 가진다. 날짜나 값이 유효하지 않은 행은 제외하며 직전값이 없으면
    변화 관련 필드는 모두 ``None``이다.
    """
    grouped: dict[str, list[tuple[datetime, int, dict[str, Any], float]]] = {}
    for position, row in enumerate(_records(rows)):
        series_id = str(row.get("series_id") or "").strip()
        observed_at = parse_datetime_safe(row.get("obs_date"))
        value = finite_number(row.get("value"))
        if not series_id or observed_at is None or value is None:
            continue
        grouped.setdefault(series_id, []).append((observed_at, position, row, value))

    result: dict[str, dict[str, Any]] = {}
    for series_id, values in grouped.items():
        values.sort(key=lambda item: (item[0], item[1]))
        current_at, _position, current_row, current_value = values[-1]
        previous = values[-2] if len(values) >= 2 else None
        previous_value = previous[3] if previous is not None else None
        change = current_value - previous_value if previous_value is not None else None
        change_pct = (
            change / abs(previous_value)
            if change is not None and previous_value != 0.0
            else None
        )
        result[series_id] = {
            "series_id": series_id,
            "name_ko": current_row.get("name_ko"),
            "category": current_row.get("category"),
            "unit": current_row.get("unit"),
            "current_value": current_value,
            "current_date": current_at.date().isoformat(),
            "previous_value": previous_value,
            "previous_date": previous[0].date().isoformat() if previous is not None else None,
            "change": change,
            "change_pct": change_pct,
        }
    return result


def _macro_signal(
    latest: Mapping[str, Mapping[str, Any]],
    series_id: str,
) -> dict[str, Any] | None:
    """단일 매크로 지표를 임계치 또는 직전값 방향에 따라 보수적으로 분류한다."""
    row = latest.get(series_id)
    if not isinstance(row, Mapping):
        return None
    current = finite_number(row.get("current_value"))
    previous = finite_number(row.get("previous_value"))
    if current is None:
        return None

    direction = "neutral"
    reason = "중립 구간"
    if series_id == "VIX":
        if current >= 25.0:
            direction, reason = "risk_off", "VIX가 25 이상"
        elif current <= 20.0:
            direction, reason = "risk_on", "VIX가 20 이하"
    elif series_id == "FEAR_GREED":
        if current <= 45.0:
            direction, reason = "risk_off", "공포탐욕 지수가 45 이하"
        elif current >= 55.0:
            direction, reason = "risk_on", "공포탐욕 지수가 55 이상"
    elif series_id in {"DXY", "TNX"}:
        if previous is None:
            return None
        if current > previous:
            direction = "risk_off"
            reason = "달러가 직전값보다 상승" if series_id == "DXY" else "10년물 금리가 직전값보다 상승"
        elif current < previous:
            direction = "risk_on"
            reason = "달러가 직전값보다 하락" if series_id == "DXY" else "10년물 금리가 직전값보다 하락"
        else:
            reason = "직전값과 동일"
    return {
        "series_id": series_id,
        "direction": direction,
        "reason": reason,
        "current_value": current,
        "previous_value": previous,
    }


def diagnose_macro(
    latest_by_series: Mapping[str, Mapping[str, Any]],
    *,
    min_signals: int = 3,
) -> dict[str, Any]:
    """금리·달러·변동성·공포탐욕으로 보수적 Risk-on/off 진단을 만든다.

    최소 ``min_signals``개를 평가할 수 없으면 ``status='unknown'``이다. 반환값에는
    ``risk_on_signals``와 ``risk_off_signals``를 항상 함께 넣고, 방향이 정해졌을 때
    우세 근거를 ``evidence``, 반대 근거를 ``counter_signals``로 별도 제공한다.
    """
    if not isinstance(latest_by_series, Mapping) or min_signals < 1:
        latest_by_series = {}
        min_signals = max(1, int(min_signals or 1))
    signals = [signal for series_id in _MACRO_SERIES if (signal := _macro_signal(latest_by_series, series_id))]
    risk_on = tuple(signal for signal in signals if signal["direction"] == "risk_on")
    risk_off = tuple(signal for signal in signals if signal["direction"] == "risk_off")
    neutral = tuple(signal for signal in signals if signal["direction"] == "neutral")
    missing = tuple(series_id for series_id in _MACRO_SERIES if not any(
        signal["series_id"] == series_id for signal in signals
    ))

    if len(signals) < min_signals:
        status = "unknown"
        evidence: tuple[dict[str, Any], ...] = ()
        counter: tuple[dict[str, Any], ...] = ()
        guidance = "필수 지표가 충분히 확인될 때까지 판단을 보류"
        score: int | None = None
    else:
        score = len(risk_on) - len(risk_off)
        if score > 0:
            status, evidence, counter = "risk_on", risk_on, risk_off
            guidance = "위험자산 비중 확대 여부를 검토하되 반대 신호를 함께 확인"
        elif score < 0:
            status, evidence, counter = "risk_off", risk_off, risk_on
            guidance = "현금·방어자산 비중과 손실 한도를 점검"
        else:
            status, evidence, counter = "neutral", risk_on, risk_off
            guidance = "상반된 신호가 같아 현재 비중 유지 여부를 검토"
    return {
        "status": status,
        "score": score,
        "available_signals": len(signals),
        "missing_series": missing,
        "evidence": evidence,
        "counter_signals": counter,
        "risk_on_signals": risk_on,
        "risk_off_signals": risk_off,
        "neutral_signals": neutral,
        "guidance": guidance,
    }




def _macro_series_frame(observations: Sequence[Mapping[str, Any]]) -> pd.Series:
    """한 지표의 (obs_date, value) 목록을 정렬된 시계열로 만든다."""
    points: dict[pd.Timestamp, float] = {}
    for row in observations:
        moment = parse_date_safe(row.get("obs_date"))
        value = finite_number(row.get("value"))
        if moment is None or value is None:
            continue
        points[pd.Timestamp(moment)] = value
    if not points:
        return pd.Series(dtype="float64")
    return pd.Series(points, dtype="float64").sort_index()


def macro_indicator_rows(window_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`reporting.macro_observations` 원값을 지표별 최신 상태 + 경보 등급으로 접는다.

    반환 각 행: series_id·name_ko·category·unit·series_kind·frequency·obs_date·curr·
    prev_value·metrics·prev_metrics·series(pd.Series)·spark·freshness·tier·reason·
    tags. 계산은 `investment_agent.reporting.macro`의 순수 함수를 그대로 쓴다.
    """
    from investment_agent.reporting.services.macro.format import meta_tags
    from investment_agent.reporting.services.macro.catalog import market_metadata_by_series
    from investment_agent.reporting.services.macro.metrics import compute_metrics_series, row_scalars
    from investment_agent.reporting.services.macro.thresholds import eval_row

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    meta: dict[str, Mapping[str, Any]] = {}
    catalog = market_metadata_by_series()
    for row in window_rows:
        series_id = str(row.get("series_id") or "").strip()
        if not series_id:
            continue
        grouped.setdefault(series_id, []).append(row)
        meta[series_id] = row

    output: list[dict[str, Any]] = []
    for series_id, observations in grouped.items():
        ordered = sorted(observations, key=lambda item: str(item.get("obs_date") or ""))
        series = _macro_series_frame(ordered)
        if series.empty:
            continue
        header = {
            **catalog.get(series_id, {}),
            **{
                key: value
                for key, value in meta[series_id].items()
                if value not in (None, "")
            },
        }
        kind = str(header.get("series_kind") or "")
        frame = compute_metrics_series(series, kind)
        metrics = row_scalars(frame.iloc[-1]) if not frame.empty else {}
        prev_metrics = row_scalars(frame.iloc[-2]) if len(frame) >= 2 else {}
        values = [float(value) for value in series.to_numpy()]
        entry: dict[str, Any] = {
            "series_id": series_id,
            "name_ko": header.get("name_ko") or series_id,
            "category": header.get("category"),
            "unit": header.get("unit"),
            "series_kind": kind,
            "frequency": header.get("frequency"),
            "obs_date": ordered[-1].get("obs_date"),
            "curr": values[-1],
            "prev_value": values[-2] if len(values) >= 2 else None,
            "metrics": metrics,
            "prev_metrics": prev_metrics,
            "series": series,
            "spark": values[-MACRO_SPARK_POINTS:],
            "observations": len(values),
            "freshness": freshness_for(
                ordered[-1].get("obs_date"),
                str(header.get("frequency") or "daily"),
            ),
        }
        tier, reason = eval_row(entry)
        entry["tier"] = tier
        entry["reason"] = reason
        entry["tags"] = meta_tags(entry)
        output.append(entry)
    output.sort(key=lambda row: str(row["series_id"]))
    return output


def macro_change(row: Mapping[str, Any]) -> dict[str, Any]:
    """직전 관측 대비 변화를 카드와 같은 단위(%/bp)로 만든다."""
    from investment_agent.reporting.services.macro.format import fmt_change

    text, direction = fmt_change(
        row.get("curr"),
        row.get("prev_value"),
        str(row.get("series_id") or ""),
        row.get("series_kind"),
        row.get("unit"),
    )
    current = finite_number(row.get("curr"))
    previous = finite_number(row.get("prev_value"))
    delta = None if current is None or previous is None else current - previous
    return {"text": text or "—", "direction": direction or "flat", "delta": delta}


def macro_value_text(row: Mapping[str, Any]) -> str:
    """카드와 같은 자릿수·단위로 현재값을 표시한다."""
    from investment_agent.reporting.services.macro.format import fmt_val

    return fmt_val(row.get("curr"), str(row.get("series_id") or ""), row.get("unit"))


def fear_greed_scale(value: Any) -> dict[str, Any] | None:
    """공포·탐욕 지수의 진행률과 사람이 읽을 구간을 계산한다."""

    current = finite_number(value)
    if current is None:
        return None
    clamped = min(max(current, 0.0), 100.0)
    if clamped < 25.0:
        label, range_label, tone = "극단적 공포", "0–24", "red"
    elif clamped < 45.0:
        label, range_label, tone = "공포", "25–44", "orange"
    elif clamped <= 55.0:
        label, range_label, tone = "중립", "45–55", "gray"
    elif clamped < 75.0:
        label, range_label, tone = "탐욕", "56–74", "green"
    else:
        label, range_label, tone = "극단적 탐욕", "75–100", "green"
    return {
        "value": current,
        "normalized": clamped / 100.0,
        "label": label,
        "range_label": range_label,
        "tone": tone,
    }


def macro_sections(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Discord 코어 카드와 같은 4개 섹션·같은 순서로 지표를 배열한다."""
    from investment_agent.reporting.services.macro.constants import CORE_LAYOUT

    by_sid = {str(row["series_id"]): dict(row) for row in rows if row.get("series_id")}
    sections: list[dict[str, Any]] = []
    for name, icon, series_ids in CORE_LAYOUT:
        members = [by_sid[sid] for sid in series_ids if sid in by_sid]
        if members:
            sections.append({"name": name, "icon": icon, "rows": members})
    return sections


def macro_alert_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """등급별 지표 수. 첫 화면의 경보 스트립이 쓰는 값."""
    counts = {"alert": 0, "caution": 0, "watch": 0, "none": 0}
    for row in rows:
        tier = str(row.get("tier") or "")
        if "alert" in tier:
            counts["alert"] += 1
        elif "caution" in tier:
            counts["caution"] += 1
        elif "watch" in tier:
            counts["watch"] += 1
        else:
            counts["none"] += 1
    return counts


_REGIME_RULES: tuple[tuple[str, str, str, str], ...] = (
    # (series_id, 비교 지표 key, 위험선호 방향 설명, 위험회피 방향 설명)
    ("VIX", "level", "VIX가 낮아 변동성 압력이 약하다", "VIX가 높아 변동성 압력이 크다"),
    ("FEAR_GREED", "level", "공포탐욕 지수가 탐욕 구간", "공포탐욕 지수가 공포 구간"),
    ("SPY", "ma200", "S&P 500이 200일선 위", "S&P 500이 200일선 아래"),
    ("HY_SPREAD", "level", "하이일드 스프레드가 좁다", "하이일드 스프레드가 벌어졌다"),
    ("DXY", "change", "달러가 약세", "달러가 강세"),
    ("SPREAD_10Y2Y", "level", "장단기 금리차가 정상", "장단기 금리차가 역전"),
)


def macro_regime(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """위험선호/위험회피 근거와 반대 신호를 함께 낸다.

    한쪽으로 단정하지 않는다. 근거와 반대 신호 개수를 모두 세고, 어느 쪽도 우세하지
    않으면 '중립'으로 남긴다. 판단에 쓸 수 없는 지표는 세지 않는다.
    """
    by_sid = {str(row["series_id"]): dict(row) for row in rows if row.get("series_id")}
    supporting: list[str] = []
    opposing: list[str] = []

    for series_id, mode, risk_on_text, risk_off_text in _REGIME_RULES:
        row = by_sid.get(series_id)
        if row is None:
            continue
        current = finite_number(row.get("curr"))
        if current is None:
            continue
        metrics = row.get("metrics") or {}
        risk_on: bool | None = None
        if series_id == "VIX":
            risk_on = current < 20.0
        elif series_id == "FEAR_GREED":
            risk_on = current >= 55.0 if current >= 55.0 or current <= 45.0 else None
        elif mode == "ma200":
            ma200 = finite_number(metrics.get("ma200"))
            risk_on = None if ma200 in (None, 0) else current > ma200
        elif series_id == "HY_SPREAD":
            level_z = finite_number(metrics.get("level_z"))
            risk_on = None if level_z is None else level_z < 0.0
        elif series_id == "SPREAD_10Y2Y":
            risk_on = current > 0.0
        elif mode == "change":
            previous = finite_number(row.get("prev_value"))
            risk_on = None if previous is None else current < previous
        if risk_on is None:
            continue
        (supporting if risk_on else opposing).append(risk_on_text if risk_on else risk_off_text)

    total = len(supporting) + len(opposing)
    if total == 0:
        verdict, tone = "판단 불가", "flat"
    elif len(supporting) >= len(opposing) + 2:
        verdict, tone = "위험 선호", "up"
    elif len(opposing) >= len(supporting) + 2:
        verdict, tone = "위험 회피", "down"
    else:
        verdict, tone = "중립", "flat"

    return {
        "verdict": verdict,
        "tone": tone,
        "supporting": tuple(supporting),
        "opposing": tuple(opposing),
        "evaluated": total,
    }
