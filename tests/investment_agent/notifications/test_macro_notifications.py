"""매크로 알림 — 경보는 상태가 바뀔 때만, 오늘의 시장은 내용이 바뀔 때만 사람에게 닿는다."""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest import mock

from investment_agent.notifications.macro import core as macro_core
from investment_agent.notifications.macro import embeds
from investment_agent.notifications.macro import watch as macro_watch
from tests.investment_agent.notifications.fakes import memory_context

ALERT, CAUTION = "🔴 alert", "🟡 caution"


def _series(series_id: str, tiers: list[str | None], *, end: date = date(2026, 9, 11)) -> dict:
    """관측마다 등급 표식을 심어 둔 지표 한 줄. 등급 판정은 표식을 그대로 돌려준다."""
    start = end - timedelta(days=len(tiers) - 1)
    history = [
        {"obs_date": (start + timedelta(days=i)).isoformat(), "curr": 1.0, "prev_value": 1.0,
         "metrics": {"marker": tier}, "prev_metrics": {}}
        for i, tier in enumerate(tiers)
    ]
    return {
        "series_id": series_id, "name_ko": series_id, "category": "rates", "unit": "%",
        "series_kind": "", "frequency": "daily", "obs_date": history[-1]["obs_date"], "curr": 1.0,
        "prev_value": 1.0, "metrics": {}, "prev_metrics": {}, "spark": [], "history": history,
        "freshness": {"state": "fresh", "obs_date": history[-1]["obs_date"], "age_days": 0},
    }


def _marker_tier(row: dict):
    tier = (row.get("metrics") or {}).get("marker")
    return (tier, f"marker={tier}") if tier else (None, None)


class WatchStateTest(unittest.TestCase):
    def _state(self, tiers):
        with mock.patch.object(macro_watch, "eval_row", side_effect=_marker_tier):
            return macro_watch.state_of(_series("TYX", tiers))

    def test_the_latest_tier_is_the_state(self) -> None:
        self.assertEqual(self._state([None, CAUTION, ALERT])[0], ALERT)

    def test_one_quiet_observation_does_not_end_an_alert(self) -> None:
        self.assertEqual(self._state([ALERT, ALERT, None])[0], ALERT)

    def test_two_quiet_observations_after_an_alert_are_a_return_to_normal(self) -> None:
        self.assertEqual(self._state([ALERT, None, None])[0], macro_watch.CLEAR)

    def test_a_series_that_never_alerted_has_nothing_to_say(self) -> None:
        self.assertIsNone(self._state([None] * 30))


class WatchPublishTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context, self.ledger, self.channel = memory_context()

    def _day(self, rows: list[dict]) -> int:
        store = mock.Mock()
        store.load_watch.return_value = rows
        with (
            mock.patch.object(macro_watch, "eval_row", side_effect=_marker_tier),
            mock.patch.object(macro_watch, "load_config", return_value=None),
            mock.patch.object(macro_watch, "discord_target", return_value="42"),
        ):
            return macro_watch.run(store=store, context=self.context)

    def _sent_series(self) -> list[list[str]]:
        return [
            sorted(line.split()[0] for field in m["message"]["embeds"][0]["fields"] for line in field["value"].splitlines()[1:-1] if line.strip())
            for m in self.channel.created
        ]

    def test_an_alert_that_persists_for_weeks_is_sent_once(self) -> None:
        days = [self._day([_series("TYX", [None, ALERT] + [ALERT] * n, end=date(2026, 9, 1) + timedelta(days=n))])
                for n in range(15)]

        self.assertEqual(sum(days), 1)

    def test_escalation_and_return_to_normal_are_each_sent_once(self) -> None:
        self._day([_series("TYX", [None, CAUTION], end=date(2026, 9, 1))])
        self._day([_series("TYX", [None, CAUTION, ALERT], end=date(2026, 9, 2))])
        self._day([_series("TYX", [None, CAUTION, ALERT, None, None], end=date(2026, 9, 4))])
        self._day([_series("TYX", [None, CAUTION, ALERT, None, None, None], end=date(2026, 9, 5))])

        self.assertEqual(len(self.channel.created), 3)

    def test_a_late_series_is_not_dropped_because_another_series_used_its_date(self) -> None:
        """관측일 하나로 원장을 치면 늦게 들어온 다른 지표의 새 경보가 버려진다."""
        self._day([_series("TYX", [None, ALERT], end=date(2026, 9, 10))])

        delivered = self._day([
            _series("TYX", [None, ALERT, ALERT], end=date(2026, 9, 11)),
            _series("KR_CORP_AA3Y", [None, ALERT], end=date(2026, 9, 10)),
        ])

        self.assertEqual(delivered, 1)
        self.assertEqual(self.ledger.status("macro.alert", "KR_CORP_AA3Y", "2026-09-10"), "sent")

    def test_the_embed_lists_returns_to_normal_apart_from_the_tiers(self) -> None:
        rows = [
            {**_series("TYX", [ALERT]), "tier": ALERT, "reason": "z=+3.1"},
            {**_series("MOVE", [None]), "tier": macro_watch.CLEAR, "reason": "평시 범위로 돌아옴"},
        ]

        embed = embeds.build_watch(rows)

        names = [field["name"] for field in embed["fields"]]
        self.assertTrue(any(name.startswith("✅ 평시 복귀") for name in names), names)
        self.assertIn("✅ 1", embed["description"])


class CoreDigestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context, self.ledger, self.channel = memory_context()

    def _run(self, rows: list[dict], today: date, *, replay: str = "") -> int:
        store = mock.Mock()
        store.load_core.return_value = rows
        with (
            mock.patch.dict(macro_core.__dict__, {}),
            mock.patch.object(macro_core, "load_config", return_value=None),
            mock.patch.object(macro_core, "discord_target", return_value="42"),
            mock.patch.object(macro_core, "shoot", new=mock.AsyncMock(return_value="card.png")),
            mock.patch.object(macro_core, "persist_png", return_value="card.png"),
            mock.patch.dict("os.environ", {"NOTIFY_REPLAY": replay}),
        ):
            return macro_core.run(store=store, context=self.context, today=today)

    @staticmethod
    def _rows(value: float) -> list[dict]:
        return [{"series_id": "SPY", "obs_date": "2026-09-11", "curr": value}]

    def test_a_second_trigger_on_the_same_day_sends_nothing(self) -> None:
        self.assertEqual(self._run(self._rows(1.0), date(2026, 9, 12)), 1)
        self.assertEqual(self._run(self._rows(1.0), date(2026, 9, 12)), 0)

    def test_new_values_on_the_same_day_edit_the_card(self) -> None:
        self._run(self._rows(1.0), date(2026, 9, 12))

        self._run(self._rows(2.0), date(2026, 9, 12))

        self.assertEqual((len(self.channel.created), len(self.channel.edited)), (1, 1))
        self.assertEqual(self.channel.edited[0]["attachment_path"], "card.png")

    def test_a_monday_with_saturdays_values_sends_nothing(self) -> None:
        self._run(self._rows(1.0), date(2026, 9, 12))

        self.assertEqual(self._run(self._rows(1.0), date(2026, 9, 14)), 0)
        self.assertEqual(self._run(self._rows(3.0), date(2026, 9, 15)), 1)

    def test_force_redraws_todays_card_in_place(self) -> None:
        self._run(self._rows(1.0), date(2026, 9, 12))

        self._run(self._rows(1.0), date(2026, 9, 12), replay="true")

        self.assertEqual((len(self.channel.created), len(self.channel.edited)), (1, 1))


if __name__ == "__main__":
    unittest.main()


class DailyChangeReasonTest(unittest.TestCase):
    """경보 사유는 **판정한 값과 같은 단위**로 적혀야 한다.

    전에는 ±0.10 밴드로 걸고 사유에는 상대 변화율(%)을 적어서, 같은 0.12 변화가
    기준값에 따라 "+3.00%"와 "+60.00%"로 달리 보였다(감사 RR2-14).
    """

    def _reason(self, series_id: str, curr: float, prev: float) -> str:
        from investment_agent.reporting.services.macro.thresholds import eval_row

        tier, reason = eval_row({
            "series_id": series_id, "series_kind": "", "curr": curr,
            "prev_value": prev, "metrics": {},
        })
        self.assertIsNotNone(tier, "0.12 변화는 daily_change watch 밴드를 넘어야 한다")
        return reason

    def test_reason_reports_the_judged_change_not_a_relative_rate(self) -> None:
        low_base = self._reason("TYX", 0.32, 0.20)
        high_base = self._reason("TNX", 4.12, 4.00)
        # 같은 변화폭이면 기준값과 무관하게 같은 문구다.
        self.assertEqual(low_base, high_base)
        self.assertIn("daily_change=+0.12", low_base)
        self.assertNotIn("%", low_base)
