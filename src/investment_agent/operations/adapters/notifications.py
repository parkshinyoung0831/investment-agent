"""Notification-owner harness stage adapters."""
from __future__ import annotations

from investment_agent.operations.harness.commands import PythonModuleCommand
from investment_agent.operations.harness.contracts import StageContext, StageOutcome
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


class NotificationAdapters:
    def _notify(self, context: StageContext, kinds: tuple[str, ...], label: str) -> StageOutcome:
        """알림 발송은 실패해도 판단·주문 결과를 가리지 않는다 (관례 8).

        보고서가 안 나간 것은 되돌릴 수 있지만, 여기서 예외를 올리면 그 회차의
        판단·체결까지 실패로 기록돼 다음 주기가 잘못된 상태에서 시작한다.
        """
        failed: list[str] = []
        for kind in kinds:
            try:
                self.command_runner.run(
                    PythonModuleCommand(
                        "investment_agent.operations.commands.notify",
                        ("--kind", kind),
                        self.timeouts.get("notify_investment", 5 * 60),
                    ),
                    stop_event=context.stop_event,
                )
            except Exception as exc:  # noqa: BLE001 - 알림 실패는 경고로만 남긴다
                failed.append(f"{kind}:{type(exc).__name__}")
                log.warning("%s notification failed kind=%s: %s", label, kind, exc)
        metadata = {"notified_at": self.now().isoformat(), "kinds": list(kinds)}
        if failed:
            return StageOutcome.skipped({**metadata, "failed": failed})
        return StageOutcome.succeeded(metadata)
    def notify_investment(self, context: StageContext) -> StageOutcome:
        """종합 판단과 상위 후보 리포트를 `#투자-리포트`로 보낸다."""
        return self._notify(
            context, ("investment_portfolio", "investment_candidates"), "investment",
        )
    def notify_trades(self, context: StageContext) -> StageOutcome:
        """실제로 나간 주문·체결을 `#매매-기록`으로 보낸다."""
        return self._notify(context, ("investment_trades",), "trade")
    def notify_reports(self, context: StageContext) -> StageOutcome:
        """독립 주기에서 누락 보고와 뒤늦게 확정된 체결의 발송을 재시도한다."""
        return self._notify(context, (
            "investment_portfolio", "investment_candidates", "investment_trades", "investment_performance",
        ), "reports")
