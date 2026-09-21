"""파괴적 DB 도구가 대상 프로젝트를 확인하는 규칙 하나.

`--confirm <project ref>`가 연결 URL의 실제 project ref와 같을 때만 지운다. ref를 URL에서 읽지 못하면
(로컬·사설 IP·커스텀 도메인) 확인을 건너뛰지 않고 **거절**한다 — 확인할 수 없는 대상에는 지우기를 허락하지 않는다.
"""
from __future__ import annotations

from urllib.parse import urlparse


def project_ref_from_db_url(url: str) -> str:
    """Supabase 연결 URL에서 project ref를 읽는다. 읽지 못하면 빈 문자열."""
    parsed = urlparse(url)
    user = parsed.username or ""
    if user.startswith("postgres.") and len(user) > len("postgres."):
        return user.split(".", 1)[1]
    host = parsed.hostname or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return host[len("db.") : -len(".supabase.co")]
    return ""


def require_confirmation(url: str, confirm: str | None) -> str:
    """대상 ref를 확인하고 돌려준다. 확인할 수 없거나 다르면 SystemExit."""
    ref = project_ref_from_db_url(url)
    if not ref:
        raise SystemExit(
            "연결 URL에서 project ref를 읽지 못했다 — 대상을 확인할 수 없는 연결에는 지우기를 허락하지 않는다."
        )
    if confirm != ref:
        raise SystemExit(f"--confirm {ref} 가 필요하다 (이 연결의 project ref).")
    return ref
