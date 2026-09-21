"""Data-owner harness stage adapters."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from investment_agent.operations.harness.commands import PythonModuleCommand
from investment_agent.operations.harness.contracts import StageContext, StageOutcome


# 미국 지표 24개 중 21개가 ET 08:30·09:15·10:00·10:30에 나오고, 그 넷은 서머타임 양쪽에서 UTC 12~15시 안에 든다
# (`econ_calendar_watch` 워크플로 머리주석과 같은 근거). 이 창 밖의 발표는 daily ETL이 하루 안에 같은 actual을 잡는다.
ECON_RELEASE_WATCH_UTC_HOURS = range(12, 16)


def in_econ_release_window(now: datetime) -> bool:
    """평일 UTC 12~15시. 창 밖에는 subprocess를 띄우지 않는다."""
    utc = now.astimezone(timezone.utc)
    return utc.weekday() < 5 and utc.hour in ECON_RELEASE_WATCH_UTC_HOURS


class DataAdapters:
    def watch(self, context: StageContext) -> StageOutcome:
        """발표 예정 시각 창에서 관심종목 공시를 훑고 알림을 바로 보낸다.

        거래 창(risk_window)으로 막지 않는다 — 주문이 아니라 공시 수집이고, 실적은
        장 시작 전(BMO)과 장 마감 후(AMC)에 나오므로 거래 창으로 자르면 정작
        발표가 몰리는 시간대를 통째로 놓친다. 창 판정은 `--session auto`가 예정
        시각의 신뢰도와 ET 기준으로 직접 하고, 창 밖이면 대상 0건으로 즉시 끝나
        SEC를 때리지 않는다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.watch_earnings",
                ("--session", "auto", "--notify", "--report-notify"),
                self.timeouts.get("earnings_watch", 12 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"watched_at": self.now().isoformat()})
    def watch_releases(self, context: StageContext) -> StageOutcome:
        """발표 시간대에만 예정 시각이 지난 지표의 첫 actual을 확인하고 속보를 보낸다."""
        if not in_econ_release_window(context.now):
            return StageOutcome.succeeded({"skipped": "outside_release_window"})
        arguments = ["--poll-attempts", "1"]
        if os.environ.get("DISCORD_BOT_TOKEN"):  # 토큰이 없으면 확인만 하고 보내지 않는다(Actions 워크플로와 같은 규칙)
            arguments.append("--notify")
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.econ_calendar_watch_releases",
                tuple(arguments),
                self.timeouts.get("econ_release_watch", 5 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"watched_at": self.now().isoformat()})

    def sync_local_mirror(self, context: StageContext) -> StageOutcome:
        """Supabase 원본을 로컬 사본으로 증분 동기화한다. 7일마다 전체를 다시 받는다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.data.market.commands.sync_local_mirror",
            (),
            self.timeouts.get("sync_local_mirror", 60 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"local_mirror_synced_at": self.now().isoformat()})
