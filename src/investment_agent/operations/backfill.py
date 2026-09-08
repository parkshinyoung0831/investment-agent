"""ETL 백필 구간 계산용 공용 헬퍼."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

TRADING_DAYS_PER_YEAR = 252
BACKFILL_SCOPES = ("missing", "gaps", "all")


@dataclass(frozen=True)
class BackfillWindow:
    start: date
    end: date

    @property
    def start_iso(self) -> str:
        return self.start.isoformat()

    @property
    def days(self) -> int:
        return max((self.end - self.start).days, 0)

    @property
    def trading_days(self) -> int:
        return max((self.days * 5 + 6) // 7, 1)


def add_backfill_from_arg(
    parser: argparse.ArgumentParser,
    *,
    required: bool = False,
    aliases: tuple[str, ...] = (),
    help_text: str = "Backfill start date, YYYY-MM-DD.",
) -> None:
    """표준 백필 시작일 인자와 선택적 별칭을 추가한다."""
    parser.add_argument(
        "--backfill-from",
        dest="backfill_from",
        required=required,
        help=help_text,
    )
    for alias in aliases:
        parser.add_argument(alias, dest="backfill_from", help=argparse.SUPPRESS)


def add_backfill_scope_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = "gaps",
) -> None:
    """모든 ETL에서 같은 의미로 쓰는 백필 범위를 추가한다.

    ``missing``은 데이터가 전혀 없는 종목의 초기 적재, ``gaps``는 완료되지 않은
    accession_no, ``all``은 완료 여부와 무관하게 발견된 전부를 뜻한다. 실패 상태는
    DB에 저장하지 않으므로 미완료 공시는 자동으로 ``gaps``에 다시 포함된다.

    daily 진입점의 ``--reprocess``와 혼동하지 말 것 — 이쪽은 SEC 벌크가 이미 게시한
    구간이 대상이고, ``--reprocess``는 벌크가 아직 안 나온 최신 구간이 대상이다.
    """
    parser.add_argument(
        "--scope",
        choices=BACKFILL_SCOPES,
        default=default,
        help="Backfill scope: missing, gaps, or all.",
    )


def select_accessions(
    discovered: set[str],
    *,
    scope: str,
    completed: set[str] | None = None,
) -> set[str]:
    """발견된 accession_no 중 표준 백필 범위에 맞는 집합을 반환한다."""
    if scope not in BACKFILL_SCOPES:
        raise ValueError(f"unknown backfill scope: {scope}")
    completed_set = completed or set()
    if scope == "all":
        return set(discovered)
    # missing은 종목 선별이 먼저 끝난 뒤 accession_no 수준에서는 gaps와 같다.
    return set(discovered) - completed_set


def resolve_backfill_window(
    backfill_from: str | None,
    *,
    default_years: int | None = None,
    today: date | None = None,
) -> BackfillWindow:
    """CLI 날짜나 연 단위 기본값을 실제 날짜 구간으로 변환한다."""
    end = today or datetime.now(timezone.utc).date()
    if backfill_from:
        start = date.fromisoformat(backfill_from)
    elif default_years is not None:
        start = end - timedelta(days=default_years * 365)
    else:
        raise ValueError("backfill_from or default_years is required")
    return BackfillWindow(start=start, end=end)


def trading_days_from_years(years: int) -> int:
    return years * TRADING_DAYS_PER_YEAR
