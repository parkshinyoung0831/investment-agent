"""SEC 고정 13F XML을 프로젝트 표준 모델로 직접 변환한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from investment_agent.data.institutional.domain.models import Position, RawPosition
from investment_agent.data.institutional.domain.value_units import detect_value_scale


@dataclass(frozen=True)
class PrimaryMetadata:
    period_end: date
    schema_version: str | None
    report_type: str | None
    amendment_type: str | None
    amendment_no: int | None
    reported_value: int
    reported_line_count: int
    confidential_omitted: bool | None


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_root(content: bytes | str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError("invalid SEC 13F XML") from exc


def _text(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if local_name(element.tag) == name:
            value = (element.text or "").strip()
            if value:
                return value
    return None


def _child_text(root: ElementTree.Element, name: str) -> str | None:
    for element in root:
        if local_name(element.tag) == name:
            value = (element.text or "").strip()
            if value:
                return value
    return None


def _child(root: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for element in root:
        if local_name(element.tag) == name:
            return element
    return None


def _integer(value: str | None, field: str, *, default: int | None = None) -> int:
    if value in (None, ""):
        if default is not None:
            return default
        raise ValueError(f"13F XML missing {field}")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"13F XML has invalid {field}: {value!r}") from exc
    if number != number.to_integral_value():
        raise ValueError(f"13F XML has non-integer {field}: {value!r}")
    return int(number)


def _optional_integer(value: str | None, field: str) -> int | None:
    if value in (None, ""):
        return None
    return _integer(value, field)


def _date(value: str | None, field: str) -> date:
    if not value:
        raise ValueError(f"13F XML missing {field}")
    text = value[:10]
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return date.fromisoformat(text)
        if len(text) == 10 and text[2] == "-" and text[5] == "-":
            month, day, year = (int(part) for part in text.split("-"))
            return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"13F XML has invalid {field}: {value!r}") from exc
    raise ValueError(f"13F XML has invalid {field}: {value!r}")


def _boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"13F XML has invalid boolean: {value!r}")


def identifier_type(identifier: str) -> str:
    """13F의 9자리 식별자를 OpenFIGI 조회 타입으로 분류한다.

    CINS는 국가 문자로 시작하는 9자리 CUSIP 확장이다. 이 분류는 OpenFIGI의
    첫 조회 타입만 정할 뿐이고, 매퍼는 실패 시 반대 타입도 다시 검증하므로 첫
    글자만으로 영구 결론을 내리지 않는다.
    """
    normalized = identifier.strip().upper().replace(" ", "")
    if len(normalized) != 9 or not normalized.isalnum():
        raise ValueError(f"13F infoTable row has invalid identifier: {identifier!r}")
    return "CINS" if normalized[0].isalpha() else "CUSIP"


def _amendment_type(root: ElementTree.Element, form_type: str) -> str | None:
    if not form_type.endswith("/A"):
        return None
    raw = (_text(root, "amendmentType") or "").upper()
    if "RESTATE" in raw:
        return "RESTATEMENT"
    if "NEW" in raw:
        return "NEW HOLDINGS"
    raise ValueError("13F-HR/A XML has no supported amendmentType")


def _voting_value(root: ElementTree.Element, name: str) -> int | None:
    voting = _child(root, "votingAuthority")
    if voting is None:
        return None
    return _integer(_child_text(voting, name), f"votingAuthority.{name}", default=0)


def parse_primary(content: bytes | str, *, form_type: str) -> PrimaryMetadata:
    root = xml_root(content)
    if local_name(root.tag) != "edgarSubmission":
        raise ValueError("13F primary XML root is not edgarSubmission")
    return PrimaryMetadata(
        period_end=_date(_text(root, "periodOfReport"), "periodOfReport"),
        schema_version=_text(root, "schemaVersion"),
        report_type=_text(root, "reportType"),
        amendment_type=_amendment_type(root, form_type),
        amendment_no=(
            _optional_integer(
                _text(root, "amendmentNo") or _text(root, "amendmentNumber"),
                "amendmentNo",
            )
            if form_type.endswith("/A")
            else None
        ),
        reported_value=_integer(
            _text(root, "tableValueTotal"),
            "tableValueTotal",
            default=0,
        ),
        reported_line_count=_integer(
            _text(root, "tableEntryTotal"),
            "tableEntryTotal",
            default=0,
        ),
        confidential_omitted=_boolean(_text(root, "isConfidentialOmitted")),
    )


def parse_information_table(content: bytes | str) -> list[RawPosition]:
    root = xml_root(content)
    if local_name(root.tag) != "informationTable":
        raise ValueError("13F attachment root is not informationTable")

    rows: list[RawPosition] = []
    for source_row_no, element in enumerate(
        (item for item in root.iter() if local_name(item.tag) == "infoTable"),
        start=1,
    ):
        amount = _child(element, "shrsOrPrnAmt")
        if amount is None:
            raise ValueError("13F infoTable row has no shrsOrPrnAmt")
        cusip = (_child_text(element, "cusip") or "").upper().replace(" ", "")
        if len(cusip) != 9:
            raise ValueError(f"13F infoTable row has invalid CUSIP: {cusip!r}")
        put_call = (_child_text(element, "putCall") or "").upper()
        if put_call not in {"", "PUT", "CALL"}:
            raise ValueError(f"13F infoTable row has invalid putCall: {put_call!r}")
        quantity_type = (_child_text(amount, "sshPrnamtType") or "SH").upper()
        if quantity_type not in {"SH", "PRN"}:
            raise ValueError(
                f"13F infoTable row has invalid sshPrnamtType: {quantity_type!r}"
            )
        rows.append(
            RawPosition(
                source_row_no=source_row_no,
                issuer_name=_child_text(element, "nameOfIssuer") or "",
                cusip=cusip,
                identifier_type=identifier_type(cusip),
                title_of_class=_child_text(element, "titleOfClass"),
                reported_value=_integer(
                    _child_text(element, "value"),
                    "value",
                    default=0,
                ),
                quantity=_integer(
                    _child_text(amount, "sshPrnamt"),
                    "sshPrnamt",
                    default=0,
                ),
                quantity_type=quantity_type,
                position_kind=put_call or "SHARES",
                investment_discretion=_child_text(element, "investmentDiscretion"),
                other_manager=_child_text(element, "otherManager"),
                voting_sole=_voting_value(element, "Sole"),
                voting_shared=_voting_value(element, "Shared"),
                voting_none=_voting_value(element, "None"),
            )
        )
    return rows


def normalize_positions(
    rows: list[RawPosition],
    *,
    schema_version: str | None,
    period_end: date,
) -> tuple[int, tuple[Position, ...]]:
    """원본 행을 USD로 환산하되 SEC 행 단위로 보존한다."""
    scale = detect_value_scale(
        rows,
        schema_version=schema_version,
        period_end=period_end,
    )
    positions = tuple(
        Position(
            source_row_no=row.source_row_no,
            issuer_name=row.issuer_name,
            cusip=row.cusip,
            identifier_type=row.identifier_type,
            title_of_class=row.title_of_class,
            value_usd=row.reported_value * scale,
            quantity=row.quantity,
            quantity_type=row.quantity_type,
            position_kind=row.position_kind,
            investment_discretion=row.investment_discretion,
            other_manager=row.other_manager,
            voting_sole=row.voting_sole,
            voting_shared=row.voting_shared,
            voting_none=row.voting_none,
        )
        for row in rows
    )
    return scale, positions
