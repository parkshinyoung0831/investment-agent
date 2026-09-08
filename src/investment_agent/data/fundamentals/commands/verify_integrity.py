"""적재된 fundamentals 데이터의 불변조건을 주기적으로 점검하는 canonical 잡.

수집 성공 여부만으로는 저장 행의 완전성과 파생 조회의 신뢰성을 보장할 수 없다.
스키마 계약, financial_versions 최신성, 회계항등식과 매핑 품질을 독립적으로 검사한다.

심각한 문제는 exit 1로 올려 공통 Actions 리포터가 Discord에 알린다. 경고는
구조화된 시스템 로그 카드로 보내되 DB에는 남기지 않는다.
"""
from __future__ import annotations

import argparse
import traceback

from investment_agent.platform.clock import us_market_today
from investment_agent.operations.runtime import notify_ops
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.operations.monitoring.incidents import (
    build_incident_embed,
    build_runtime_incident,
    current_github_run_url,
)

log = get_logger(__name__)

# 이 일수 안에 새 공시가 하나도 없으면 수집이 멈춘 것으로 본다. 실적 시즌 사이
# 공백을 감안해 넉넉히 잡는다.
STALE_FILING_DAYS = 14
# 원장의 최신 분기가 이보다 오래되면 수집이 멈춘 것이다.
STALE_MV_DAYS = 100


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.data.fundamentals.commands.verify_integrity")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="경고도 실패로 올린다. 수동 점검용.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    try:
        from investment_agent.data.fundamentals.application.verify_integrity import (
            verify_integrity,
        )
        from investment_agent.data.fundamentals.infrastructure.supabase import integrity

        report = verify_integrity(
            repository=integrity,
            today=us_market_today(),
            stale_filing_days=STALE_FILING_DAYS,
            stale_mv_days=STALE_MV_DAYS,
        )
        for check in report["checks"]:
            level = {"error": log.error, "warning": log.warning}.get(
                check["severity"], log.info
            )
            level(
                "integrity %s [%s] %s detail=%s",
                check["name"], check["severity"], check["message"], check["detail"],
            )

        errors = [c for c in report["checks"] if c["severity"] == "error"]
        warnings = [c for c in report["checks"] if c["severity"] == "warning"]
        log.info(
            "fundamentals integrity complete checks=%d errors=%d warnings=%d",
            len(report["checks"]), len(errors), len(warnings),
        )
        if warnings and not errors and not args.strict:
            summary = "; ".join(
                f"{check['name']}: {check['message']}" for check in warnings[:5]
            )
            if len(warnings) > 5:
                summary += f"; 외 {len(warnings) - 5}건"
            incident = build_runtime_incident(
                workflow="fundamentals_integrity",
                step="데이터 무결성 점검",
                summary=summary,
                conclusion="warning",
                impact="수집은 완료됐지만 일부 데이터 품질 지표가 권장 범위를 벗어났어요.",
                action="GitHub Actions 원문에서 경고 항목을 확인하고 다음 정기 실행에서도 반복되는지 점검해 주세요.",
                url=current_github_run_url(),
            )
            notify_ops("", logger=log, embeds=[build_incident_embed(incident)])
        if errors or (args.strict and warnings):
            return 1
        return 0
    except Exception as exc:  # noqa: BLE001 - canonical CLI 경계
        log.error("integrity verification failed: %s\n%s", exc, traceback.format_exc())
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
