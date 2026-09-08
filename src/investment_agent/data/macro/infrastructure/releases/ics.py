"""ECON 자연키 event를 RFC 5545 iCalendar로 내보내는 순수 로직."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from investment_agent.data.macro.domain.releases.identity import row_event_key

PRODID = "-//investment-agent//econ-release-center//KO"
CALNAME = "경제발표 일정"
_FOLD_OCTETS = 75


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> list[str]:
    raw = line.encode("utf-8")
    if len(raw) <= _FOLD_OCTETS:
        return [line]
    output: list[str] = []
    start, limit = 0, _FOLD_OCTETS
    while start < len(raw):
        end = min(start + limit, len(raw))
        while end > start and end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        output.append(("" if not output else " ") + raw[start:end].decode("utf-8"))
        start, limit = end, _FOLD_OCTETS - 1
    return output


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _moment(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ECON calendar timestamps must be timezone-aware")
    return parsed


def _event_lines(row: dict[str, Any], *, stamped: datetime) -> list[str]:
    moment = _moment(row["scheduled_at"])
    name = str(row.get("series_name_ko") or row.get("series_id") or "경제발표")
    measure = str(row.get("measure_name_ko") or row.get("measure_id") or "")
    confidence = str(row.get("schedule_confidence") or "date_only")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{row_event_key(row)}@econ-calendar.investment-agent",
        f"DTSTAMP:{_utc(stamped)}",
        f"SUMMARY:{_escape(' · '.join(part for part in (name, measure) if part))}",
    ]
    if confidence == "date_only":
        local_day = moment.astimezone(ZoneInfo(str(row.get("timezone") or "Asia/Seoul"))).date()
        lines.extend([
            f"DTSTART;VALUE=DATE:{local_day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(local_day + timedelta(days=1)).strftime('%Y%m%d')}",
        ])
    else:
        lines.extend([
            f"DTSTART:{_utc(moment)}",
            f"DTEND:{_utc(moment + timedelta(minutes=30))}",
        ])
    lines.extend([
        "STATUS:" + ("CANCELLED" if row.get("status") == "cancelled"
                     else "TENTATIVE" if confidence == "date_only" else "CONFIRMED"),
        f"DESCRIPTION:{_escape('event=' + row_event_key(row) + '; confidence=' + confidence)}",
        "CATEGORIES:경제지표",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ])
    return lines


def build(rows: list[dict[str, Any]], *, stamped: datetime | None = None) -> str:
    """각 (series_id, ref_period)를 한 ICS event로 만든다. 일정 연기에도 UID는 같다."""
    stamped = stamped or datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR", f"PRODID:{PRODID}", "VERSION:2.0", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape(CALNAME)}", "X-WR-TIMEZONE:Asia/Seoul",
    ]
    for row in sorted(rows, key=lambda item: (str(item["scheduled_at"]), row_event_key(item))):
        lines.extend(_event_lines(row, stamped=stamped))
    lines.append("END:VCALENDAR")
    return "\r\n".join(piece for line in lines for piece in fold(line)) + "\r\n"


def group_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """canonical release row의 식별자·발표시각을 확인해 중복 없이 반환한다."""
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("series_id") or not row.get("ref_period") or not row.get("scheduled_at"):
            continue
        key = row_event_key(row)
        if key in seen:
            continue
        seen.add(key)
        output.append(dict(row))
    return output
