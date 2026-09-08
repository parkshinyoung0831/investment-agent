"""운영 파서와 edgartools shadow 파서의 13F 결과를 대조한다.

순수 비교 로직이라 외부 의존성이 없다. 입력은 양쪽 파서가 만든 ``RawPosition``
목록(환산 전 원본 행)이고, 출력은 라인 수·금액 합계·키별 합계 차이를 담은
``ShadowDiff``다. 분석 키는 운영 파서의 합산 기준과 같은
``(cusip, position_kind, quantity_type)``을 쓴다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from investment_agent.data.institutional.domain.models import RawPosition

# 키별 금액·수량을 비교할 때 허용하는 절대 오차(정수 합산이라 사실상 0).
_VALUE_TOLERANCE = 1

PositionKey = tuple[str, str, str]


@dataclass(frozen=True)
class KeyMismatch:
    key: PositionKey
    custom_value: int
    shadow_value: int
    custom_quantity: int
    shadow_quantity: int


@dataclass(frozen=True)
class ShadowDiff:
    accession_no: str
    custom_line_count: int
    shadow_line_count: int
    custom_value_total: int
    shadow_value_total: int
    only_in_custom: tuple[PositionKey, ...] = ()
    only_in_shadow: tuple[PositionKey, ...] = ()
    key_mismatches: tuple[KeyMismatch, ...] = ()
    error: str | None = None

    @property
    def matched(self) -> bool:
        if self.error is not None:
            return False
        return (
            self.custom_line_count == self.shadow_line_count
            and abs(self.custom_value_total - self.shadow_value_total)
            <= _VALUE_TOLERANCE
            and not self.only_in_custom
            and not self.only_in_shadow
            and not self.key_mismatches
        )

    def reason(self) -> str | None:
        """불일치 사유 요약. 일치하면 None."""
        if self.matched:
            return None
        if self.error is not None:
            return f"shadow parser error: {self.error}"
        parts: list[str] = []
        if self.custom_line_count != self.shadow_line_count:
            parts.append(
                f"line_count custom={self.custom_line_count} "
                f"shadow={self.shadow_line_count}"
            )
        if abs(self.custom_value_total - self.shadow_value_total) > _VALUE_TOLERANCE:
            parts.append(
                f"value_total custom={self.custom_value_total} "
                f"shadow={self.shadow_value_total}"
            )
        if self.only_in_custom:
            parts.append(f"only_in_custom={len(self.only_in_custom)}")
        if self.only_in_shadow:
            parts.append(f"only_in_shadow={len(self.only_in_shadow)}")
        if self.key_mismatches:
            parts.append(f"key_value_mismatch={len(self.key_mismatches)}")
        return "; ".join(parts)

    def as_payload(self) -> dict:
        return {
            "accession_no": self.accession_no,
            "custom_line_count": self.custom_line_count,
            "shadow_line_count": self.shadow_line_count,
            "custom_value_total": self.custom_value_total,
            "shadow_value_total": self.shadow_value_total,
            "only_in_custom": [list(key) for key in self.only_in_custom],
            "only_in_shadow": [list(key) for key in self.only_in_shadow],
            "key_mismatches": [
                {
                    "key": list(item.key),
                    "custom_value": item.custom_value,
                    "shadow_value": item.shadow_value,
                    "custom_quantity": item.custom_quantity,
                    "shadow_quantity": item.shadow_quantity,
                }
                for item in self.key_mismatches
            ],
            "error": self.error,
        }


def _aggregate(rows: list[RawPosition]) -> dict[PositionKey, dict[str, int]]:
    grouped: dict[PositionKey, dict[str, int]] = defaultdict(
        lambda: {"value": 0, "quantity": 0}
    )
    for row in rows:
        key = (row.cusip, row.position_kind, row.quantity_type)
        grouped[key]["value"] += row.reported_value
        grouped[key]["quantity"] += row.quantity
    return grouped


def compare(
    accession_no: str,
    custom_rows: list[RawPosition],
    shadow_rows: list[RawPosition],
) -> ShadowDiff:
    """두 파서 결과를 키별로 대조한 ``ShadowDiff``를 만든다."""
    custom = _aggregate(custom_rows)
    shadow = _aggregate(shadow_rows)

    only_in_custom = tuple(sorted(set(custom) - set(shadow)))
    only_in_shadow = tuple(sorted(set(shadow) - set(custom)))

    mismatches: list[KeyMismatch] = []
    for key in sorted(set(custom) & set(shadow)):
        c = custom[key]
        s = shadow[key]
        if (
            abs(c["value"] - s["value"]) > _VALUE_TOLERANCE
            or c["quantity"] != s["quantity"]
        ):
            mismatches.append(
                KeyMismatch(
                    key=key,
                    custom_value=c["value"],
                    shadow_value=s["value"],
                    custom_quantity=c["quantity"],
                    shadow_quantity=s["quantity"],
                )
            )

    return ShadowDiff(
        accession_no=accession_no,
        custom_line_count=len(custom_rows),
        shadow_line_count=len(shadow_rows),
        custom_value_total=sum(row.reported_value for row in custom_rows),
        shadow_value_total=sum(row.reported_value for row in shadow_rows),
        only_in_custom=only_in_custom,
        only_in_shadow=only_in_shadow,
        key_mismatches=tuple(mismatches),
    )


def errored(accession_no: str, custom_rows: list[RawPosition], message: str) -> ShadowDiff:
    """shadow 파서가 예외로 실패했을 때의 진단용 결과를 만든다."""
    return ShadowDiff(
        accession_no=accession_no,
        custom_line_count=len(custom_rows),
        shadow_line_count=0,
        custom_value_total=sum(row.reported_value for row in custom_rows),
        shadow_value_total=0,
        error=message,
    )
