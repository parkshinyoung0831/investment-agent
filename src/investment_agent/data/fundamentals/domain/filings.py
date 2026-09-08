"""SEC 공시 식별자와 종류의 규칙.

## accession_no 하나로 부른다

같은 값을 `accession`, `accessionNo`, `accession_number`로 부르던 자리가 있었고, 그때
같은 공시가 다른 키로 두 번 저장됐다. 이름은 `accession_no` 하나이고 모양은
`0000320193-25-000073`이다 — 하이픈 없이 오는 소스가 있어 정규화가 필요하다.

## 정정공시는 원본을 대체하지 않는다

`10-K/A`는 새 사실이 아니라 **같은 기간의 다른 버전**이다. 그것으로 원본을 덮으면
"그때 우리가 알던 값"을 영영 잃는다. 저장은 공시 단위로 하고, 어느 것이 최신인지는
읽는 시점에 정한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from investment_agent.platform.clock import as_date
from investment_agent.platform.serialization import parse_datetime


def _as_datetime(value: Any) -> datetime | None:
    """시각 컬럼을 datetime으로. 없거나 읽을 수 없으면 None."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return parse_datetime(str(value))
    except ValueError:
        return None


ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")

# 우리가 다루는 서식. 다른 것이 오면 저장소가 거부한다.
FORM_TYPES = ("10-Q", "10-Q/A", "10-K", "10-K/A", "8-K")

# 실적 보도자료가 실리는 8-K 항목. 다른 항목의 8-K는 실적과 무관하다.
EARNINGS_ITEM = "2.02"


class FilingError(ValueError):
    """공시 식별자나 종류가 계약을 어겼다."""


@dataclass(frozen=True)
class FilingRef:
    """원천 수집기가 넘기는 SEC 공시 참조.

    ``Filing``은 v1 저장 계약이고, 이 타입은 아직 원문을 읽기 전의 최소 식별자다.
    둘을 하나로 합치면 원천에 없는 ``available_at``을 지어내거나, 반대로 저장할 때
    필요한 PIT 경계를 잃는다.
    """

    accession_no: str
    filing_date: str
    report_date: str
    form_type: str
    is_xbrl: bool = True
    cik: int | None = None
    source: str | None = None

    def as_filing_row(self, cik: object = None) -> dict[str, Any]:
        """canonical `filings` 행. 자식 행의 FK 부모라 먼저 있어야 한다.

        `Filing.as_row()`와 같은 모양이지만 `available_at` 같은 PIT 값은 만들지
        않는다 — 원문을 아직 읽지 않았으므로 지어낼 근거가 없다. CIK는 참조에
        없을 수 있어 호출자가 자기 문맥의 값을 넘긴다.
        """
        return {
            "accession_no": self.accession_no,
            "cik": str(self.cik if self.cik is not None else cik or "").zfill(10),
            "form_type": self.form_type,
            "filing_date": self.filing_date,
            "report_date": self.report_date or None,
            "source": self.source or "sec_edgar",
        }


def normalize_accession(value: object) -> str | None:
    """공시 번호를 표준 모양으로. 읽을 수 없으면 `None`.

    하이픈 없는 18자리로 오는 소스가 있다. 그대로 저장하면 같은 공시가 두 키로 남는다.
    """
    text = str(value or "").strip()
    if ACCESSION_RE.match(text):
        return text
    digits = text.replace("-", "")
    if len(digits) == 18 and digits.isdigit():
        return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"
    return None


def is_amendment(form_type: str) -> bool:
    """정정공시인가. 원본과 같은 기간의 다른 버전이라는 뜻이다."""
    return form_type.endswith("/A")


def base_form(form_type: str) -> str:
    """정정 표시를 뗀 서식. `10-K/A`와 `10-K`를 같은 종류로 묶을 때 쓴다."""
    return form_type[:-2] if is_amendment(form_type) else form_type


def is_periodic(form_type: str) -> bool:
    """정기보고서인가(10-Q/10-K). 8-K는 사건 보고라 재무 전체가 없다."""
    return base_form(form_type) in {"10-Q", "10-K"}


@dataclass(frozen=True)
class Filing:
    """공시가 존재한다는 사실. 우리가 그것을 어떻게 처리했는지는 여기 없다."""

    accession_no: str
    cik: str
    form_type: str
    filing_date: date
    report_date: date | None = None
    # 우리가 이 공시를 손에 넣은 시각. PIT 경계이며 `filing_date`와 다르다.
    available_at: datetime | None = None
    source: str = "sec_edgar"

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Filing":
        from investment_agent.data.universe.domain.identifiers import normalize_cik

        accession = normalize_accession(row.get("accession_no"))
        if accession is None:
            raise FilingError(f"unreadable accession_no: {row.get('accession_no')!r}")
        cik = normalize_cik(row.get("cik"))
        if cik is None:
            raise FilingError(f"{accession}: unreadable cik {row.get('cik')!r}")
        form_type = str(row.get("form_type") or "").strip().upper()
        if form_type not in FORM_TYPES:
            raise FilingError(f"{accession}: unsupported form_type {form_type!r}")
        filing_date = as_date(row.get("filing_date"))
        if filing_date is None:
            raise FilingError(f"{accession}: unreadable filing_date")
        return cls(
            accession_no=accession,
            cik=cik,
            form_type=form_type,
            filing_date=filing_date,
            report_date=as_date(row.get("report_date")),
            # PostgREST는 timestamptz를 문자열로 준다. 비교하는 자리에서 터지지 않게
            # 여기서 맞춘다.
            available_at=_as_datetime(row.get("available_at")),
            source=str(row.get("source") or "sec_edgar"),
        )

    @property
    def is_amendment(self) -> bool:
        return is_amendment(self.form_type)

    def as_row(self) -> dict[str, Any]:
        return {
            "accession_no": self.accession_no,
            "cik": self.cik,
            "form_type": self.form_type,
            "filing_date": self.filing_date.isoformat(),
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "source": self.source,
        }


def filing_row(filing: object, cik: object = None) -> dict[str, Any]:
    """어떤 모양으로 오든 canonical `filings` 행 하나로 바꾼다.

    `Filing`(저장 계약)과 `FilingRef`(원문 읽기 전 참조)는 일부러 다른 타입이지만,
    **부모 행을 만드는 일은 같다.** 전에는 쓰는 쪽마다 `as_row()`를 직접 불러서
    참조가 섞여 들어오는 경로에서 `AttributeError`가 났다 — company backfill이
    첫 기업에서 그렇게 죽었고 재무가 한 줄도 들어오지 않았다.
    """
    if isinstance(filing, Filing):
        return filing.as_row()
    if isinstance(filing, FilingRef):
        return filing.as_filing_row(cik)
    if isinstance(filing, Mapping):
        return {
            "accession_no": filing["accession_no"],
            "cik": str(filing.get("cik") or cik or "").zfill(10),
            "form_type": filing["form_type"],
            "filing_date": filing.get("filing_date") or filing.get("accepted_date"),
            "report_date": filing.get("report_date"),
            "source": filing.get("source") or "sec_edgar",
        }
    raise FilingError(f"unsupported filing row: {type(filing).__name__}")


__all__ = [
    "filing_row",
    "ACCESSION_RE",
    "EARNINGS_ITEM",
    "FORM_TYPES",
    "Filing",
    "FilingError",
    "FilingRef",
    "base_form",
    "is_amendment",
    "is_periodic",
    "normalize_accession",
]
