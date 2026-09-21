"""기준점 보관 창과 조회 창은 같은 상수에서 나와야 한다.

전에는 보관이 2일(`save_account_snapshot`의 삭제 컷오프)이고 조회가 5일
(`PRIOR_BASELINE_MAX_AGE`)이라, 연휴 뒤 첫 장에서 fallback이 보는 구간의 [2일, 5일)
부분에는 행이 남을 수 없었다. 오늘 장전 캡처가 실패하면 실주문이 전부
"capture a Toss snapshot before US market open"으로 막히고, 그 문구가 원인(보관 삭제)을
가렸다(감사 EX2-05). 두 창을 잇고, 둘이 갈라지면 실패하게 고정한다.
"""
from __future__ import annotations

import inspect
import unittest

from investment_agent.execution.brokers import repository as brokers_repository
from investment_agent.execution.safety.repository import PRIOR_BASELINE_MAX_AGE


class BaselineRetentionWindowTest(unittest.TestCase):
    def test_retention_uses_the_same_constant_as_the_read_window(self):
        source = inspect.getsource(brokers_repository.BrokerRepository.save_account_snapshot)
        self.assertIn("PRIOR_BASELINE_MAX_AGE", source)
        # 옛 리터럴이 다시 들어오면 두 창이 조용히 갈라진다.
        self.assertNotIn("timedelta(days=2)", source)
        self.assertIs(brokers_repository.PRIOR_BASELINE_MAX_AGE, PRIOR_BASELINE_MAX_AGE)

    def test_the_window_covers_a_holiday_weekend(self):
        """금요일 마감 → 월요일 휴장 → 화요일 개장은 3일 간격이다. 창은 그보다 넓어야 한다."""
        self.assertGreaterEqual(PRIOR_BASELINE_MAX_AGE.days, 4)


if __name__ == "__main__":
    unittest.main()
