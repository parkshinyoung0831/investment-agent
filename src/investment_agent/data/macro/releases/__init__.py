"""지표 발표 캘린더에서 공통으로 쓰는 설정값."""
from __future__ import annotations

# 앞으로 며칠치 일정을 유지할지. FRED는 릴리스별로 3~4개월치를 미리 공개하므로
# 이보다 늘려도 새로 들어오는 게 없다(2026-08 기준 CPI는 4건까지 공개).
HORIZON_DAYS = 120

# 예상값 스냅샷을 찍을 구간(일). 발표가 이보다 멀면 nowcast도 자체 모델도
# 아직 의미 있는 정보가 없다 — 매일 같은 숫자를 쌓기만 한다.
EXPECTATION_HORIZON_DAYS = 45

# 자체 베이스라인이 볼 과거 관측 개수(주기별).
BASELINE_WINDOW = {"weekly": 12, "monthly": 12, "quarterly": 8}
