"""실적 속보의 서프라이즈 계산과 판정. 차트와 embed가 같은 정의를 쓴다."""
from __future__ import annotations

# 예상 대비 이 값(%)보다 못하면 하회로 본다. 상회는 0을 넘는 것만이라 비대칭인데,
# 컨센서스가 반올림된 값이라 소폭 미달을 쇼크로 칠하지 않으려는 선택이다.
MISS_THRESHOLD_PCT = -1.0
BEAT_THRESHOLD_PCT = 0.0


def compute_surprise(actual: float | None, estimate: float | None) -> float | None:
    """(실제-예상)/|예상|, 퍼센트. 예상이 음수(적자)여도 손실 축소가 양수로 나온다."""
    if actual is not None and estimate is not None and estimate != 0:
        return round(((actual - estimate) / abs(estimate)) * 100.0, 2)
    return None


def eps_basis(flash: dict) -> str | None:
    """실제 EPS와 예상 EPS가 같은 정의인지(`match`/`unknown`/`mismatch`). 예상이 없으면 None."""
    value = flash.get("eps_basis_match")
    return str(value) if value else None


def eps_surprise(flash: dict) -> float | None:
    """EPS 서프라이즈(%). GAAP 실제와 조정 예상처럼 정의가 다르면 비교가 무의미해 내지 않는다.

    reporting.earnings_surprise 뷰가 같은 이유로 `eps_surprise_ratio`를 비운다 — 속보도 같은 규칙을 따른다.
    """
    if eps_basis(flash) == "mismatch":
        return None
    return compute_surprise(flash.get("eps_actual"), flash.get("eps_estimate"))


def eps_decides_verdict(flash: dict) -> bool:
    """정의를 확인한 EPS만 상회·하회 판정에 쓴다. 미확인이면 값은 보이되 색을 정하지 않는다."""
    return eps_basis(flash) not in {"mismatch", "unknown"}


def eps_basis_note(flash: dict) -> str | None:
    basis = eps_basis(flash)
    if basis == "mismatch":
        return "EPS 정의 불일치(GAAP↔조정)로 비교 제외"
    if basis == "unknown":
        return "EPS 정의 미확인"
    return None


def judge(surprises: list[float | None]) -> str:
    """축(EPS·매출) 전부가 같은 방향일 때만 `beat`/`miss`를 단정하고, 엇갈리면 `inline`.

    한 축만 상회해도 초록이면 EPS가 크게 하회한 발표가 "서프라이즈"로 나간다.
    """
    present = [value for value in surprises if value is not None]
    if not present:
        return "inline"
    if all(value > BEAT_THRESHOLD_PCT for value in present):
        return "beat"
    if all(value < MISS_THRESHOLD_PCT for value in present):
        return "miss"
    return "inline"
