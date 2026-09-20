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
