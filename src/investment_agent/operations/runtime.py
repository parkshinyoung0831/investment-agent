"""Shared ETL entrypoint utilities."""
from __future__ import annotations

import os
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import requests


# ETL 진입점의 종료코드. 셸은 0/비0만 구분하므로 "일부만 들어왔다"를 표현할 자리가
# 없다. 그래서 부분 성공에 고유한 코드를 준다 — 완전 성공으로 뭉개면 "일부 종목만
# 들어왔는데 success"가 되고, 실패로 뭉개면 매일 빨간 워크플로가 진짜 실패를 가린다.
# 워크플로는 EXIT_PARTIAL을 경고로 표시하고 잡 자체는 통과시킨다.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def elapsed_sec(start: float) -> float:
    return round(time.monotonic() - start, 1)


def _ops_webhook() -> tuple[str, str, str]:
    """(webhook, origin, 사용한 env 이름).

    Actions 실패와 로컬 하네스 실패는 고치는 방법이 다르다 — 전자는 재실행이나
    워크플로 수정, 후자는 이 컴퓨터다. 전에는 둘이 한 webhook으로 들어와서
    한 채널에서 섞였다. 어디서 돌고 있는지는 런타임이 알고 있으므로
    (`GITHUB_ACTIONS`) 부르는 쪽에 묻지 않는다.

    전용 webhook이 없으면 기존 `DISCORD_WEBHOOK_OPS`로 떨어진다 — 갈라 두기 전에
    알림이 먼저 조용해지는 것이 더 나쁘다.
    """
    on_actions = os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true"
    origin = "actions" if on_actions else "local"
    name = "DISCORD_WEBHOOK_OPS_ACTIONS" if on_actions else "DISCORD_WEBHOOK_OPS_LOCAL"
    webhook = os.environ.get(name, "").strip()
    if webhook:
        return webhook, origin, name
    return os.environ.get("DISCORD_WEBHOOK_OPS", "").strip(), origin, "DISCORD_WEBHOOK_OPS"


def notify_ops(
    message: str,
    *,
    logger: Any | None = None,
    embeds: list[Mapping[str, Any]] | None = None,
) -> bool:
    """Send an ops message to Discord when DISCORD_WEBHOOK_OPS is configured.

    embeds를 주면 본문 대신 embed로 보낸다. 운영 장애는
    ``investment_agent.operations.incidents``의
    구조화 카드 계약을 사용하고, 원문 로그는 GitHub Actions나 로컬 JSON 로그에 둔다.

    목적지는 **실행된 곳**이 정한다(:func:`_ops_webhook`). 부르는 쪽이 고르게 하면
    한 곳만 빠뜨려도 그 알림이 조용히 엉뚱한 채널로 간다.
    """
    webhook, origin, name = _ops_webhook()
    if not webhook:
        if logger is not None:
            logger.warning("%s is not set; skipped alert: %s", name, message)
        return False
    # 전용 webhook이 아직 없으면 둘이 한 채널로 떨어진다. 그때도 어디서 난
    # 실패인지 읽는 사람이 알 수 있게 출처를 이름에 남긴다.
    payload: dict[str, Any] = {
        "content": "" if embeds else message,
        "username": f"ATLAS ops · {origin}",
    }
    if embeds:
        payload["embeds"] = [dict(embed) for embed in embeds]
    try:
        requests.post(webhook, json=payload, timeout=10).raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - alerting must not hide ETL result
        if logger is not None:
            logger.warning("Discord alert failed: %s", exc)
        return False


def run_log_payload(
    *,
    workflow: str,
    status: str,
    rows_upserted: int = 0,
    tickers_processed: int = 0,
    duration_sec: float,
    started_at: str,
    detail: Mapping[str, Any] | None = None,
    quarantined: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": workflow,
        "status": status,
        "rows_upserted": rows_upserted,
        "tickers_processed": tickers_processed,
        "duration_sec": duration_sec,
        "detail": dict(detail) if detail is not None else None,
        "started_at": started_at,
    }
    if quarantined is not None:
        payload["quarantined"] = quarantined
    return payload
