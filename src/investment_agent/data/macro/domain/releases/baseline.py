"""자체 베이스라인 예상값 — 외부 의존 없는 순수 로직.

무료 컨센서스가 없는 지표(23종 중 22종)를 위한 최소한의 기준선이다.
**이건 컨센서스가 아니다.** `kind='own_model'`로 저장돼 카드가 서베이·nowcast와
섞어 부르지 못하게 한다.

후보는 둘뿐이다.
  drift  마지막 값 + 최근 변화폭의 중앙값 — 추세가 있는 지수(CPI·M2)에 맞는다
  naive  마지막 값 그대로            — 노이즈가 큰 지표(실업수당·GDP·소매판매)에 맞는다

**어느 쪽이 나은지는 지표마다 다르고, 하드코딩하지 않는다.** 2024년 이후(지수 기준연도가
같은 구간) 최초 발표값으로 채점해 보면 갈린다: 근원 CPI는 drift가 naive보다 80% 정확했고,
소매판매는 22% 더 틀렸다. 그래서 매 실행마다 최근 구간에서 둘을 걸어 보고 나은 쪽을 쓴다.
고른 방법은 `forecasts.source`에 그대로 남아 사후 채점이 가능하다.

평균이 아니라 중앙값을 쓰는 이유는 발표 지표에 한 번씩 튀는 값이 섞이기 때문이다
(허리케인 주의 실업수당, 셧다운 직후 고용 등). 평균이면 그 한 건이 다음 예상을 끌고 간다.

범위(low/high)는 최근 변화폭의 10~90 백분위다. **신뢰구간이 아니다** — 변화폭 자체가
몰려 다니기 때문에(변동성 군집) 실측 적중률은 지표에 따라 10~83%로 흩어진다.
사분위(25~75)를 쓰던 것을 넓힌 결과이며, 카드에는 '최근 변동 범위'로만 표시해야 한다.
"""
from __future__ import annotations

from itertools import pairwise
from statistics import median

# 모델 선택에 쓸 최근 시점 수. 너무 짧으면 한두 건에 흔들리고, 너무 길면
# 현재 지표 특성의 변화를 충분히 반영하지 못한다.
SELECT_POINTS = 12
# 범위의 백분위. 25~75는 실측 적중률이 3~47%로 지나치게 좁았다.
BAND_LOW, BAND_HIGH = 0.10, 0.90
# drift를 고르려면 naive보다 이만큼은 나아야 한다.
#
# 왜 여유가 필요한가: 선택기는 **개정된 현재값**으로 채점하는데, 정작 맞혀야 하는 건
# 개정 전 **최초 발표값**이라 훨씬 노이즈가 크다. 그래서 선택기는 체계적으로 drift를
# 과대평가한다. 2024년 이후 최초 발표값으로 재 보면 여유 0%일 때 소매판매가 naive보다
# 21.9% 나빴는데, 20%를 요구하면 3.3%로 줄고 전체 합계도 오히려 좋아진다.
SELECT_MARGIN = 0.20


def _quantile(sorted_values: list[float], fraction: float) -> float:
    """선형 보간 분위수. 표본이 작아 numpy를 끌어오지 않는다."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _diffs(values: list[float], window: int) -> list[float]:
    return [b - a for a, b in pairwise(values)][-window:]


def _predict(values: list[float], window: int, *, use_drift: bool) -> float:
    if not use_drift:
        return values[-1]
    diffs = _diffs(values, window)
    return values[-1] + (median(diffs) if diffs else 0.0)


def _walk_forward_error(
    values: list[float], window: int, *, use_drift: bool, points: int,
) -> float | None:
    """최근 points개 시점에서 그 방법을 실제로 걸어 봤을 때의 중앙 절대오차."""
    errors: list[float] = []
    for index in range(max(3, len(values) - points), len(values)):
        prior = values[:index]
        if len(prior) < 3:
            continue
        errors.append(abs(values[index] - _predict(prior, window, use_drift=use_drift)))
    return median(errors) if errors else None


def select_method(
    values: list[float], *, window: int = 12, points: int = SELECT_POINTS,
) -> str:
    """이 지표에 지금 맞는 방법('drift' 또는 'naive').

    증거가 뚜렷할 때만 추세를 좇는다(SELECT_MARGIN). 채점이 안 되면(이력이 짧으면)
    drift로 둔다 — 추세가 있는 지표를 놓치는 쪽이 노이즈를 좇는 쪽보다 덜 나쁘다.
    """
    drift_error = _walk_forward_error(values, window, use_drift=True, points=points)
    naive_error = _walk_forward_error(values, window, use_drift=False, points=points)
    if drift_error is None or naive_error is None:
        return "drift"
    return "drift" if drift_error < naive_error * (1 - SELECT_MARGIN) else "naive"


def drift_forecast(
    values: list[float], *, window: int = 12, points: int = SELECT_POINTS,
) -> dict[str, float] | None:
    """다음 관측 예측값과 최근 변동 범위, 그리고 고른 방법.

    변화폭이 둘 미만이면(관측이 셋 미만) 아무것도 내지 않는다 — 표본 하나로 만든
    범위는 범위가 아니고, 없는 예상을 있는 척하는 게 제일 나쁘다.
    """
    if len(values) < 3:
        return None
    diffs = _diffs(values, window)
    if len(diffs) < 2:
        return None
    method = select_method(values, window=window, points=points)
    ordered = sorted(diffs)
    last = values[-1]
    return {
        "value": _predict(values, window, use_drift=method == "drift"),
        "low": last + _quantile(ordered, BAND_LOW),
        "high": last + _quantile(ordered, BAND_HIGH),
        "method": method,
    }
