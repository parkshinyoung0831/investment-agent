"""실적 경고 등급 판정.

:func:`investment_agent.reporting.services.earnings.metrics.derive`가 만든 파생 dict 하나를 받아
(배지, 색, 한줄 라벨)을 돌려준다. 카드와 화면이 같은 등급을 주장해야 하므로 Reporting이
소유한다. 색 팔레트는 strategy 카드와 동일하게 맞춘다.
"""
from __future__ import annotations

_RED = 0xCF202F
_ORANGE = 0xF4B000
_GREEN = 0x05B169
_BLUE = 0x3182F6
_GRAY = 0x7C828A


def grade(d: dict, *, has_anomaly: bool) -> tuple[str, int, str]:
    """파생 지표 dict → (배지, 색, 한줄 라벨). 위험한 것부터 차례로 판정."""
    rev_yoy = d.get("revenue_yoy")
    ni_yoy = d.get("net_income_yoy")
    ni_now = d.get("net_income_now")
    ni_prev = d.get("net_income_prev")
    op_delta = d.get("operating_margin_delta_yoy")

    loss_turn = ni_now is not None and ni_prev is not None and ni_now < 0 <= ni_prev

    if has_anomaly:
        return "위험", _RED, "대차대조표 불일치 — 데이터 점검 필요"
    if loss_turn:
        return "위험", _RED, "흑자→적자 전환"
    if rev_yoy is not None and rev_yoy < -0.10:
        return "위험", _RED, "매출 두 자릿수 역성장"
    if ni_yoy is not None and ni_yoy < -0.25:
        return "위험", _RED, "순이익 급감(YoY −25% 초과)"
    if (rev_yoy is not None and rev_yoy < 0) or (op_delta is not None and op_delta < -0.02):
        return "주의", _ORANGE, "매출 역성장 또는 마진 둔화"
    if rev_yoy is not None and rev_yoy >= 0 and (ni_yoy is None or ni_yoy >= 0):
        return "양호", _GREEN, "매출·이익 성장"
    if d.get("is_first"):
        return "신규", _BLUE, "최초 수집 — 비교 대상 없음"
    return "중립", _GRAY, "혼조"


__all__ = ["grade"]
