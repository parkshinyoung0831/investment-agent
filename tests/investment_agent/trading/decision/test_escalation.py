"""재분석 escalation shadow — 건너뛰었어도 됐을지를 조건 하나하나로 판정한다. 모르면 건너뛰지 않는다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.trading.decision.escalation import refresh_shadow

_NOW = datetime(2026, 10, 20, 21, 0, tzinfo=timezone.utc)
_PREVIOUS_AT = datetime(2026, 9, 21, 21, 0, tzinfo=timezone.utc)


def _bars(returns: list[float]) -> list[dict]:
    """최신순 일봉. 첫 봉이 직전 판단 이전이다."""
    rows, price, day = [], 100.0, date(2026, 9, 18)
    for value in (0.0, *returns):
        price *= 1 + value
        rows.append({"trade_date": day.isoformat(), "close": price})
        day += timedelta(days=1)
    return list(reversed(rows))


_CALM = _bars([0.004, -0.003, 0.002, -0.004, 0.003, -0.002] * 5)
_PREVIOUS = {"case_key": "AAPL__1", "as_of_at": _PREVIOUS_AT.isoformat(), "thesis": "positive",
             "hard_constraint": "none"}


class RefreshShadowTest(unittest.TestCase):
    def _shadow(self, **overrides):
        values = dict(as_of_at=_NOW, is_held=False, previous=_PREVIOUS, latest_filed_at="2026-08-01T12:00:00+00:00",
                      bars_desc=_CALM)
        values.update(overrides)
        return refresh_shadow(**values)

    def test_an_unchanged_refresh_would_be_skipped(self):
        shadow = self._shadow()
        self.assertTrue(shadow.would_skip, shadow.reasons)
        self.assertEqual(("unchanged_since_previous",), shadow.reasons)

    def test_each_change_keeps_the_deep_call(self):
        cases = {
            "held_position": dict(is_held=True),
            "no_previous_view": dict(previous=None),
            "new_filing_since_previous": dict(latest_filed_at="2026-10-01T12:00:00+00:00"),
            "previous_view_too_old": dict(previous={**_PREVIOUS, "as_of_at": (_NOW - timedelta(days=60)).isoformat()}),
            "previous_thesis_not_extendable": dict(previous={**_PREVIOUS, "thesis": "negative"}),
            "price_shock_since_previous": dict(bars_desc=_bars([0.004, -0.003] * 10 + [0.12])),
            "price_history_does_not_cover_previous": dict(bars_desc=_bars([0.001])[:1]),
        }
        for reason, overrides in cases.items():
            with self.subTest(reason=reason):
                shadow = self._shadow(**overrides)
                self.assertFalse(shadow.would_skip)
                self.assertIn(reason, shadow.reasons)

    def test_a_hard_constraint_is_never_extended(self):
        shadow = self._shadow(previous={**_PREVIOUS, "hard_constraint": "block_new_buy"})
        self.assertFalse(shadow.would_skip)


class ShadowIsStoredBesideTheEvidenceTest(unittest.TestCase):
    def test_the_artifact_keeps_the_shadow(self):
        import tempfile

        from investment_agent.trading.evidence.artifacts import EvidenceArtifactStore

        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceArtifactStore(directory)
            manifest = store.write_case(case_key="c", evidence_bundle={"ticker": "AAPL"}, role_analyses={},
                                        escalation_shadow={"would_skip": True})
            self.assertTrue(store.read(manifest)["escalation_shadow"]["would_skip"])


if __name__ == "__main__":
    unittest.main()
