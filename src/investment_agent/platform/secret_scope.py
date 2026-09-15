"""프로세스별 비밀값 범위. 판단·학습 프로세스는 broker·승인 비밀을 갖지 않는다.

하네스가 자식 프로세스를 띄울 때 범위를 정하고, 자식은 `.env`를 다시 읽은 직후 범위 밖
비밀을 지운다. 둘 다 필요하다 — 부모가 빼도 자식의 `load_dotenv`가 같은 파일에서 되살린다.

실행 범위(`execution`)가 아닌 모든 프로세스는 판단 범위로 취급한다(fail-closed). 범위
표시가 없는 수동 실행은 사람이 직접 띄운 것이라 기존처럼 전체 환경을 쓴다.
"""
from __future__ import annotations

import os
from typing import Mapping, MutableMapping

SCOPE_ENV = "INVESTMENT_AGENT_SECRET_SCOPE"
SCOPE_EXECUTION = "execution"
SCOPE_ANALYSIS = "analysis"

# 주문을 낼 수 있거나 승인 서명을 위조할 수 있는 값. 한도·플래그 같은 비밀이 아닌 설정은
# 판단 프로세스도 읽어야 해서(대시보드·보고서가 현재 한도를 보여준다) 여기 두지 않는다.
EXECUTION_SECRET_NAMES = frozenset({
    "TOSS_CLIENT_ID",
    "TOSS_CLIENT_SECRET",
    "TOSS_ACCOUNT_SEQ",
    "TOSS_TOKEN_CACHE_PATH",
    "DISCORD_APPROVAL_BOT_TOKEN",
    "DISCORD_APPROVAL_HMAC_SECRET",
    "DISCORD_APPROVAL_HMAC_SECRET_FILE",
})


class SecretScopeError(RuntimeError):
    """판단 범위 프로세스가 실행 전용 자원에 닿으려 했다."""


def current_scope(environ: Mapping[str, str] | None = None) -> str | None:
    value = (os.environ if environ is None else environ).get(SCOPE_ENV, "").strip().lower()
    return value or None


def is_analysis_scope(environ: Mapping[str, str] | None = None) -> bool:
    scope = current_scope(environ)
    return scope is not None and scope != SCOPE_EXECUTION


def environ_for_scope(environ: Mapping[str, str], scope: str) -> dict[str, str]:
    """자식 프로세스에 넘길 환경. 판단 범위면 실행 비밀을 뺀다."""
    child = dict(environ)
    if scope != SCOPE_EXECUTION:
        scope = SCOPE_ANALYSIS
        for name in EXECUTION_SECRET_NAMES:
            child.pop(name, None)
    child[SCOPE_ENV] = scope
    return child


def strip_out_of_scope_secrets(environ: MutableMapping[str, str] | None = None) -> tuple[str, ...]:
    """`.env`를 읽은 뒤 부른다. 판단 범위면 되살아난 실행 비밀을 지우고 지운 이름을 돌려준다."""
    target = os.environ if environ is None else environ
    if not is_analysis_scope(target):
        return ()
    removed = tuple(sorted(name for name in EXECUTION_SECRET_NAMES if name in target))
    for name in removed:
        target.pop(name, None)
    return removed


def require_execution_scope(resource: str) -> None:
    """broker 인증처럼 실행 범위에서만 열려야 하는 자원의 입구에서 부른다."""
    if is_analysis_scope():
        raise SecretScopeError(f"{resource} is not available in the analysis secret scope")


__all__ = [
    "EXECUTION_SECRET_NAMES",
    "SCOPE_ANALYSIS",
    "SCOPE_ENV",
    "SCOPE_EXECUTION",
    "SecretScopeError",
    "current_scope",
    "environ_for_scope",
    "is_analysis_scope",
    "require_execution_scope",
    "strip_out_of_scope_secrets",
]
