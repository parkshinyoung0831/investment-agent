"""edgartools 기반 13F information table shadow 파서.

운영 파서(`src/investment_agent/data/institutional/parser.py`)와 같은 첨부 바이트를 입력으로 받아 edgartools의
information table 파서로 다시 해석한다. 목적은 교체가 아니라 **사후 대조(audit)**다.
이미 SEC에서 받아둔 바이트를 그대로 넘기므로 추가 SEC HTTP 호출은 발생하지 않는다.

edgartools는 무거운 선택 의존성이라 모듈 최상단에서 import하지 않고, 함수 호출
시점에 지연 import한다(프로젝트 관례). edgartools가 설치되어 있지 않으면
``EdgartoolsUnavailable``을 던지고, 호출부(ETL)는 이를 잡아 shadow 대조만 건너뛴다.
"""
from __future__ import annotations

from investment_agent.data.institutional.domain.models import RawPosition
from investment_agent.data.institutional.domain.parser import identifier_type


class EdgartoolsUnavailable(RuntimeError):
    """edgartools가 설치되어 있지 않을 때 발생한다."""


def edgartools_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("edgartools")
    except Exception:  # noqa: BLE001 - 버전 조회 실패가 대조를 막지 않게 한다.
        return None


def _text(value: object) -> str:
    return ("" if value is None else str(value)).strip()


def _quantity_type(raw: str) -> str:
    normalized = raw.upper()
    if normalized in {"SH", "SHARES", "SHARE"}:
        return "SH"
    if normalized in {"PRN", "PRINCIPAL"}:
        return "PRN"
    raise ValueError(f"edgartools row has unexpected Type: {raw!r}")


def _position_kind(raw: str) -> str:
    normalized = raw.upper()
    if normalized == "":
        return "SHARES"
    if normalized in {"PUT", "CALL"}:
        return normalized
    raise ValueError(f"edgartools row has unexpected PutCall: {raw!r}")


def _to_int(value: object, field: str) -> int:
    text = _text(value)
    if text in {"", "nan"}:
        return 0
    try:
        return round(float(text))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"edgartools row has invalid {field}: {value!r}") from exc


def parse_information_table(
    content: bytes | str,
    *,
    source_format: str,
) -> list[RawPosition]:
    """edgartools로 information table을 파싱해 운영 모델(`RawPosition`)로 정규화한다.

    ``source_format``은 ``"xml"`` 또는 ``"txt"``. 값(``Value``)은 운영 파서와 동일하게
    **원본(미환산)** 으로 유지하므로 단위 환산 전 단계에서 그대로 대조할 수 있다.
    """
    try:
        from edgar.thirteenf import parse_infotable_txt, parse_infotable_xml
    except ImportError as exc:  # pragma: no cover - 의존성 부재 경로
        raise EdgartoolsUnavailable(
            "edgartools is not installed; shadow 13F comparison skipped"
        ) from exc

    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    fmt = source_format.lower()
    if fmt == "xml":
        frame = parse_infotable_xml(text)
    elif fmt == "txt":
        frame = parse_infotable_txt(text)
    else:
        raise ValueError(f"unsupported source_format: {source_format!r}")

    rows: list[RawPosition] = []
    for source_row_no, record in enumerate(frame.to_dict("records"), start=1):
        cusip = _text(record.get("Cusip")).upper().replace(" ", "")
        rows.append(
            RawPosition(
                source_row_no=source_row_no,
                issuer_name=_text(record.get("Issuer")),
                cusip=cusip,
                identifier_type=identifier_type(cusip),
                title_of_class=_text(record.get("Class")) or None,
                reported_value=_to_int(record.get("Value"), "Value"),
                quantity=_to_int(record.get("SharesPrnAmount"), "SharesPrnAmount"),
                quantity_type=_quantity_type(_text(record.get("Type")) or "SH"),
                position_kind=_position_kind(_text(record.get("PutCall"))),
                investment_discretion=_text(record.get("InvestmentDiscretion")) or None,
                other_manager=_text(record.get("OtherManager")) or None,
                voting_sole=None,
                voting_shared=None,
                voting_none=None,
            )
        )
    return rows
