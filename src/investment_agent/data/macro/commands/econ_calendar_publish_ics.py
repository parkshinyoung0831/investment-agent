"""발표 일정을 .ics로 만들어 구독 가능한 곳에 올린다.

기본 대상은 Supabase Storage의 공개 버킷이다. 영구 서버가 없는 구조라 정적 파일이
가장 싸고, 이미 Supabase를 쓰므로 시크릿이 늘지 않는다.

**버킷은 자동으로 만들지 않는다.** 공개 버킷을 코드가 조용히 만들면 나중에 그 버킷에
다른 걸 넣었을 때 같이 공개된다. 없으면 만드는 법을 알려주고 멈춘다 — 무엇을 공개할지는
사람이 정할 일이다.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.operations.runtime import elapsed_sec, notify_ops
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.data.macro.releases import HORIZON_DAYS

log = get_logger(__name__)

DEFAULT_BUCKET = (os.environ.get("ECON_CALENDAR_ICS_BUCKET") or "").strip() or "econ-calendar"
OBJECT_NAME = "econ-calendar.ics"
CONTENT_TYPE = "text/calendar; charset=utf-8"


def _upload(bucket: str, payload: bytes) -> str:
    """공개 버킷에 덮어쓰고 공개 URL을 돌려준다."""
    from investment_agent.platform.db.postgres import sb

    bucket_name = (bucket or "").strip() or "econ-calendar"
    storage = sb.storage
    try:
        names = {item["name"] if isinstance(item, dict) else item.name
                 for item in storage.list_buckets()}
    except Exception as exc:
        raise RuntimeError("Supabase Storage bucket listing failed") from exc

    if bucket_name not in names:
        raise RuntimeError(
            f"Supabase Storage에 공개 버킷 '{bucket_name}'이 없습니다. "
            "대시보드 > Storage에서 Public 버킷으로 먼저 만드세요 "
            "(공개되는 것은 발표 일정뿐이며 비밀값은 담기지 않습니다)."
        )
    options = {"content-type": CONTENT_TYPE, "upsert": "true", "cache-control": "600"}
    storage.from_(bucket_name).upload(OBJECT_NAME, payload, options)
    return storage.from_(bucket_name).get_public_url(OBJECT_NAME)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="investment_agent.data.macro.commands.econ_calendar_publish_ics")
    parser.add_argument(
        "--days", type=int, default=HORIZON_DAYS,
        help="캘린더에 실을 앞으로의 일수.",
    )
    parser.add_argument(
        "--bucket", default=DEFAULT_BUCKET,
        help="업로드할 Supabase Storage 공개 버킷 이름.",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="업로드 대신 이 경로에 파일로 쓴다(다른 곳에 호스팅할 때).",
    )
    args = parser.parse_args(argv)

    from investment_agent.data.macro.releases import db
    from investment_agent.data.macro.infrastructure.releases import ics
    from investment_agent.config import load_config
    from investment_agent.platform.db.postgres import Database
    db.configure(Database.from_config(load_config()))

    started = time.monotonic()
    rows = db.upcoming(args.days, include_cancelled=True)
    groups = ics.group_events(rows)
    if not groups:
        # 조용히 빈 캘린더를 올리면 구독자에게는 일정이 사라진 것처럼 보인다.
        raise RuntimeError("econ_calendar.upcoming returned no events — 발행을 중단한다")

    document = ics.build(groups, stamped=datetime.now(timezone.utc))
    payload = document.encode("utf-8")

    if args.out is not None:
        args.out.write_bytes(payload)
        location = str(args.out)
    else:
        location = _upload(args.bucket, payload)

    log.info(
        "econ_calendar ics published: events=%d series_rows=%d bytes=%d "
        "location=%s duration_sec=%.1f",
        len(groups), len(rows), len(payload), location, elapsed_sec(started),
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        log.exception("econ_calendar ics publish failed")
        notify_ops(f"econ_calendar publish_ics failed: {exc}", logger=log)
        raise SystemExit(1)
