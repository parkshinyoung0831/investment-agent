"""Data-owner harness stage adapters."""
from __future__ import annotations

from investment_agent.operations.harness.commands import PythonModuleCommand
from investment_agent.operations.harness.contracts import StageContext, StageOutcome


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
    def sync_local_mirror(self, context: StageContext) -> StageOutcome:
        """Supabase 원본을 로컬 사본으로 증분 동기화한다. 7일마다 전체를 다시 받는다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.data.market.commands.sync_local_mirror",
            (),
            self.timeouts.get("sync_local_mirror", 60 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"local_mirror_synced_at": self.now().isoformat()})
