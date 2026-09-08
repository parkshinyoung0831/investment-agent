"""투자 하네스 및 실계좌 연동 보안 사전 점검(Preflight Security & Safety Audit).

Fail-closed 킬스위치, Discord 봇 토큰 분리, HMAC 키 강도, 비밀값 노출 방지,
트레이딩 한도 및 세션 윈도우 무결성을 검사한다.
"""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from investment_agent.operations.paths import REPOSITORY_ROOT
from typing import Any, Mapping

from investment_agent.operations.harness.contracts import HarnessMode

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_WEAK_SECRETS = {
    "123456", "12345678", "password", "secret", "default", "example",
    "test", "changeme", "admin", "null", "none", "hmac_secret",
}


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    category: str
    code: str
    status: CheckStatus
    message: str
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class SecurityAuditReport:
    timestamp: str
    mode: str
    healthy: bool
    summary: dict[str, int]
    results: tuple[CheckResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mode": self.mode,
            "healthy": self.healthy,
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
        }


def generate_hmac_secret(num_bytes: int = 32) -> str:
    """암호학적으로 안전한 256비트(64자리 Hex) HMAC 서명 키 생성."""
    return secrets.token_hex(num_bytes)


def _check_kill_switches(environ: Mapping[str, str], mode: HarnessMode) -> list[CheckResult]:
    results: list[CheckResult] = []
    category = "KILL_SWITCHES"

    # 1. TRADING_KILL_SWITCH
    raw_kill = environ.get("TRADING_KILL_SWITCH", "on").strip().lower()
    is_kill_on = raw_kill not in {"off", "false", "0", "no", "disabled"}

    if is_kill_on:
        results.append(CheckResult(
            category=category,
            code="TRADING_KILL_SWITCH_ACTIVE",
            status=CheckStatus.PASS,
            message="전역 트레이딩 킬스위치가 안전하게 활성화(ON)되어 있습니다.",
            details=f"TRADING_KILL_SWITCH={raw_kill}",
        ))
    else:
        if mode == HarnessMode.ANALYSIS_ONLY:
            results.append(CheckResult(
                category=category,
                code="TRADING_KILL_SWITCH_UNNECESSARY_OFF",
                status=CheckStatus.WARN,
                message="analysis_only 모드에서는 킬스위치를 ON으로 유지하는 것이 권장됩니다.",
                details=f"TRADING_KILL_SWITCH={raw_kill}",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="TRADING_KILL_SWITCH_DISARMED",
                status=CheckStatus.WARN,
                message="전역 트레이딩 킬스위치가 해제(OFF)되어 실제 주문이 가능합니다. 주의하세요.",
                details=f"TRADING_KILL_SWITCH={raw_kill}",
            ))

    # 2. TOSS_LIVE_ENABLED
    raw_live = environ.get("TOSS_LIVE_ENABLED", "false").strip().lower()
    is_live = raw_live in {"true", "1", "yes", "enabled", "on"}

    if not is_live:
        results.append(CheckResult(
            category=category,
            code="TOSS_LIVE_DISABLED",
            status=CheckStatus.PASS,
            message="토스 실주문 플래그가 비활성화(FALSE)되어 안전합니다.",
            details=f"TOSS_LIVE_ENABLED={raw_live}",
        ))
    else:
        if is_kill_on:
            results.append(CheckResult(
                category=category,
                code="TOSS_LIVE_BLOCKED_BY_KILL_SWITCH",
                status=CheckStatus.PASS,
                message="TOSS_LIVE_ENABLED=true 이나 TRADING_KILL_SWITCH=on 에 의해 보호됩니다.",
                details="Live 주문이 킬스위치에 의해 Fail-closed 차단됨",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="TOSS_LIVE_ARMED",
                status=CheckStatus.WARN,
                message="실계좌 실시간 주문이 완전히 무장(ARMED)되었습니다.",
                details="TOSS_LIVE_ENABLED=true & TRADING_KILL_SWITCH=off",
            ))

    # 3. TOSS_ALLOW_MARKET_ORDERS
    raw_mkt = environ.get("TOSS_ALLOW_MARKET_ORDERS", "false").strip().lower()
    if raw_mkt in {"true", "1", "yes", "enabled"}:
        results.append(CheckResult(
            category=category,
            code="MARKET_ORDERS_PROHIBITED",
            status=CheckStatus.FAIL,
            message="시장가 주문(Market Order)은 슬리피지 위험으로 금지되어 있습니다. false로 설정하세요.",
            details=f"TOSS_ALLOW_MARKET_ORDERS={raw_mkt}",
        ))
    else:
        results.append(CheckResult(
            category=category,
            code="MARKET_ORDERS_DISABLED",
            status=CheckStatus.PASS,
            message="시장가 주문이 차단되어 지정가(Limit Order)만 발주됩니다.",
        ))

    return results


def _check_discord_security(environ: Mapping[str, str], mode: HarnessMode) -> list[CheckResult]:
    results: list[CheckResult] = []
    category = "DISCORD_AUTHENTICATION"

    general_token = environ.get("DISCORD_BOT_TOKEN", "").strip()
    approval_token = environ.get("DISCORD_APPROVAL_BOT_TOKEN", "").strip()
    hmac_secret = environ.get("DISCORD_APPROVAL_HMAC_SECRET", "").strip()
    channel_id = environ.get("DISCORD_CHANNEL_AI_APPROVALS", "").strip()
    approver_ids = (
        environ.get("DISCORD_APPROVER_USER_IDS", "").strip()
        or environ.get("DISCORD_APPROVER_USER_ID", "").strip()
    )

    # 1. 봇 토큰 분리 점검
    if general_token and approval_token:
        if general_token == approval_token:
            results.append(CheckResult(
                category=category,
                code="DISCORD_BOT_TOKENS_IDENTICAL",
                status=CheckStatus.FAIL,
                message="일반 알림 봇과 주문 승인 봇 토큰이 동일합니다. 최소 권한 원칙을 위해 반드시 분리해야 합니다.",
                details="DISCORD_BOT_TOKEN == DISCORD_APPROVAL_BOT_TOKEN",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="DISCORD_BOT_TOKENS_SEPARATED",
                status=CheckStatus.PASS,
                message="일반 알림 봇과 주문 승인 봇 토큰이 안전하게 분리되어 있습니다.",
            ))
    elif mode == HarnessMode.APPROVAL_WORKFLOW and not approval_token:
        results.append(CheckResult(
            category=category,
            code="DISCORD_APPROVAL_BOT_TOKEN_MISSING",
            status=CheckStatus.FAIL,
            message="approval_workflow 모드 구동을 위한 DISCORD_APPROVAL_BOT_TOKEN이 설정되지 않았습니다.",
        ))

    # 2. HMAC Secret 키 강도 점검
    if hmac_secret:
        if len(hmac_secret) < 32:
            results.append(CheckResult(
                category=category,
                code="HMAC_SECRET_TOO_SHORT",
                status=CheckStatus.FAIL,
                message="HMAC 서명 키 길이가 너무 짧습니다 (최소 32자 이상 필요).",
                details=f"Current length: {len(hmac_secret)} chars",
            ))
        elif hmac_secret.lower() in _WEAK_SECRETS:
            results.append(CheckResult(
                category=category,
                code="HMAC_SECRET_WEAK_OR_DEFAULT",
                status=CheckStatus.FAIL,
                message="기본 예시나 취약한 비밀번호가 HMAC 키로 설정되어 있습니다. 난수로 재생성하세요.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="HMAC_SECRET_STRONG",
                status=CheckStatus.PASS,
                message=f"HMAC 서명 키가 충분한 길이({len(hmac_secret)}자)로 설정되어 있습니다.",
            ))
    else:
        key_file = environ.get("DISCORD_APPROVAL_HMAC_SECRET_FILE", "").strip()
        if key_file and Path(key_file).exists():
            results.append(CheckResult(
                category=category,
                code="HMAC_SECRET_FILE_EXISTS",
                status=CheckStatus.PASS,
                message=f"HMAC 서명 키 파일이 존재합니다: {key_file}",
            ))
        elif mode == HarnessMode.APPROVAL_WORKFLOW:
            results.append(CheckResult(
                category=category,
                code="HMAC_SECRET_MISSING",
                status=CheckStatus.FAIL,
                message="DISCORD_APPROVAL_HMAC_SECRET 또는 유효한 키 파일이 필요합니다.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="HMAC_SECRET_FILE_AUTO_MANAGED",
                status=CheckStatus.PASS,
                message="HMAC 키는 최초 실행 시 artifacts/execution/approval-hmac.key 로 자동 생성됩니다.",
            ))

    # 3. 승인 채널 및 승인자 Allowlist
    if mode == HarnessMode.APPROVAL_WORKFLOW:
        if not channel_id:
            results.append(CheckResult(
                category=category,
                code="APPROVAL_CHANNEL_MISSING",
                status=CheckStatus.FAIL,
                message="승인 카드 전송을 위한 DISCORD_CHANNEL_AI_APPROVALS 가 지정되지 않았습니다.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="APPROVAL_CHANNEL_CONFIGURED",
                status=CheckStatus.PASS,
                message=f"승인 채널 ID: {channel_id}",
            ))

        if not approver_ids:
            results.append(CheckResult(
                category=category,
                code="APPROVER_ALLOWLIST_EMPTY",
                status=CheckStatus.FAIL,
                message="승인 권한자(DISCORD_APPROVER_USER_IDS)가 비어있습니다. 누구나 승인하거나 거부될 수 없습니다.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="APPROVER_ALLOWLIST_CONFIGURED",
                status=CheckStatus.PASS,
                message=f"등록된 승인자 ID: {approver_ids}",
            ))

    # 4. 승인 유효기간 (TTL)
    raw_ttl = environ.get("AI_APPROVAL_TTL_MINUTES", "15").strip()
    try:
        ttl = int(raw_ttl)
        if ttl <= 0 or ttl > 60:
            results.append(CheckResult(
                category=category,
                code="APPROVAL_TTL_OUT_OF_RANGE",
                status=CheckStatus.WARN,
                message=f"승인 유효시간({ttl}분)이 비정상 범위(1~60분 권장)입니다.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="APPROVAL_TTL_VALID",
                status=CheckStatus.PASS,
                message=f"승인 카드 유효 시간: {ttl}분",
            ))
    except ValueError:
        results.append(CheckResult(
            category=category,
            code="APPROVAL_TTL_INVALID",
            status=CheckStatus.FAIL,
            message="AI_APPROVAL_TTL_MINUTES는 정수여야 합니다.",
        ))

    return results


def _check_secrets_exposure(repository_root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    category = "SECRETS_EXPOSURE"

    gitignore_path = repository_root / ".gitignore"
    if not gitignore_path.exists():
        results.append(CheckResult(
            category=category,
            code="GITIGNORE_MISSING",
            status=CheckStatus.FAIL,
            message=".gitignore 파일이 루트에 없습니다.",
        ))
        return results

    content = gitignore_path.read_text(encoding="utf-8")
    has_env = ".env" in content
    has_artifacts = "artifacts/" in content or all(
        p in content for p in ("artifacts/execution/", "artifacts/toss_auth/", "artifacts/ops/")
    )

    if not has_env or not has_artifacts:
        missing = []
        if not has_env:
            missing.append(".env")
        if not has_artifacts:
            missing.append("artifacts/")
        results.append(CheckResult(
            category=category,
            code="GITIGNORE_SECRETS_MISSING",
            status=CheckStatus.FAIL,
            message=f".gitignore에 비밀 디렉터리가 누락되어 있습니다: {missing}",
        ))
    else:
        results.append(CheckResult(
            category=category,
            code="GITIGNORE_SECRETS_PROTECTED",
            status=CheckStatus.PASS,
            message=".env 및 민감한 artifacts 디렉터리가 .gitignore에 정상 등록되어 있습니다.",
        ))

    # .env 파일 실제 존재 여부
    env_path = repository_root / ".env"
    if env_path.exists():
        results.append(CheckResult(
            category=category,
            code="ENV_FILE_FOUND",
            status=CheckStatus.PASS,
            message="로컬 .env 파일이 존재합니다.",
        ))
    else:
        results.append(CheckResult(
            category=category,
            code="ENV_FILE_NOT_FOUND",
            status=CheckStatus.WARN,
            message="로컬 .env 파일이 없습니다. .env.example을 복사하여 작성하세요.",
        ))

    return results


def _check_trading_limits(environ: Mapping[str, str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    category = "TRADING_LIMITS"

    def _parse_float(key: str, default: float) -> float | None:
        raw = environ.get(key, str(default)).strip()
        try:
            return float(raw)
        except ValueError:
            return None

    daily_max = _parse_float("TOSS_MAX_DAILY_NOTIONAL_USD", 20000.0)
    order_max = _parse_float("TOSS_MAX_ORDER_NOTIONAL_USD", 5000.0)
    daily_loss = _parse_float("TOSS_MAX_DAILY_LOSS_USD", 500.0)
    drawdown = _parse_float("TOSS_MAX_DRAWDOWN_FRACTION", 0.05)

    if daily_max is None or daily_max <= 0:
        results.append(CheckResult(
            category=category,
            code="DAILY_MAX_NOTIONAL_INVALID",
            status=CheckStatus.FAIL,
            message="TOSS_MAX_DAILY_NOTIONAL_USD가 올바른 양수여야 합니다.",
        ))
    elif daily_max > 100000.0:
        results.append(CheckResult(
            category=category,
            code="DAILY_MAX_NOTIONAL_HIGH",
            status=CheckStatus.WARN,
            message=f"일일 최대 거래 한도(${daily_max:,.0f})가 $100,000를 초과합니다.",
        ))
    else:
        results.append(CheckResult(
            category=category,
            code="DAILY_MAX_NOTIONAL_OK",
            status=CheckStatus.PASS,
            message=f"일일 최대 거래 한도: ${daily_max:,.0f}",
        ))

    if order_max is not None and daily_max is not None:
        if order_max > daily_max:
            results.append(CheckResult(
                category=category,
                code="ORDER_MAX_EXCEEDS_DAILY",
                status=CheckStatus.FAIL,
                message=f"건별 주문 한도(${order_max:,.0f})가 일일 총 한도(${daily_max:,.0f})보다 큽니다.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="ORDER_MAX_NOTIONAL_OK",
                status=CheckStatus.PASS,
                message=f"건별 최대 주문 한도: ${order_max:,.0f}",
            ))

    if daily_loss is not None:
        if daily_loss <= 0 or daily_loss > 5000.0:
            results.append(CheckResult(
                category=category,
                code="DAILY_LOSS_LIMIT_OUT_OF_BOUNDS",
                status=CheckStatus.WARN,
                message=f"일일 손실 차단 한도(${daily_loss:,.0f})가 일반적 허용 범위(0~$5,000)를 벗어납니다.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="DAILY_LOSS_LIMIT_OK",
                status=CheckStatus.PASS,
                message=f"일일 최대 손실 한도: ${daily_loss:,.0f}",
            ))

    if drawdown is not None:
        if drawdown <= 0 or drawdown > 0.20:
            results.append(CheckResult(
                category=category,
                code="DRAWDOWN_LIMIT_OUT_OF_BOUNDS",
                status=CheckStatus.WARN,
                message=f"최대 허용 낙폭({drawdown * 100:.1f}%)이 일반적 허용 범위(0~20%)를 벗어납니다.",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="DRAWDOWN_LIMIT_OK",
                status=CheckStatus.PASS,
                message=f"최대 허용 계좌 낙폭: {drawdown * 100:.1f}%",
            ))

    return results


def _check_session_windows(environ: Mapping[str, str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    category = "SESSION_WINDOWS"

    sess_start = environ.get("HARNESS_NY_SESSION_START", "09:40").strip()
    sess_end = environ.get("HARNESS_NY_SESSION_END", "14:30").strip()
    risk_start = environ.get("HARNESS_NY_RISK_START", "09:15").strip()
    risk_end = environ.get("HARNESS_NY_RISK_END", "16:30").strip()

    valid_times = True
    for name, val in [
        ("HARNESS_NY_SESSION_START", sess_start),
        ("HARNESS_NY_SESSION_END", sess_end),
        ("HARNESS_NY_RISK_START", risk_start),
        ("HARNESS_NY_RISK_END", risk_end),
    ]:
        if not _TIME_RE.match(val):
            results.append(CheckResult(
                category=category,
                code=f"INVALID_TIME_FORMAT_{name}",
                status=CheckStatus.FAIL,
                message=f"{name} 시각 포맷이 잘못되었습니다 (HH:MM 필요): {val}",
            ))
            valid_times = False

    if valid_times:
        if sess_start >= sess_end:
            results.append(CheckResult(
                category=category,
                code="SESSION_WINDOW_INVALID",
                status=CheckStatus.FAIL,
                message=f"분석 세션 시작시각({sess_start})이 종료시각({sess_end})보다 늦거나 같습니다.",
            ))
        elif risk_start > sess_start or risk_end < sess_end:
            results.append(CheckResult(
                category=category,
                code="RISK_WINDOW_TOO_NARROW",
                status=CheckStatus.WARN,
                message="리스크 감시 구간이 분석 구간을 완전히 포함하지 않습니다.",
                details=f"Risk: {risk_start}~{risk_end}, Session: {sess_start}~{sess_end}",
            ))
        else:
            results.append(CheckResult(
                category=category,
                code="SESSION_WINDOWS_VALID",
                status=CheckStatus.PASS,
                message=f"뉴욕 정규 세션: 분석({sess_start}~{sess_end} ET), 감시({risk_start}~{risk_end} ET)",
            ))

    return results


def run_security_audit(
    *,
    environ: Mapping[str, str] | None = None,
    repository_root: Path | None = None,
    mode: HarnessMode = HarnessMode.ANALYSIS_ONLY,
) -> SecurityAuditReport:
    """환경변수 및 저장소 파일 상태를 점검하여 종합 보안 감사 보고서를 생성한다."""
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    env = environ if environ is not None else os.environ
    root = repository_root or REPOSITORY_ROOT

    all_checks: list[CheckResult] = []
    all_checks.extend(_check_kill_switches(env, mode))
    all_checks.extend(_check_discord_security(env, mode))
    all_checks.extend(_check_secrets_exposure(root))
    all_checks.extend(_check_trading_limits(env))
    all_checks.extend(_check_session_windows(env))

    summary = {
        CheckStatus.PASS.value: sum(1 for c in all_checks if c.status == CheckStatus.PASS),
        CheckStatus.WARN.value: sum(1 for c in all_checks if c.status == CheckStatus.WARN),
        CheckStatus.FAIL.value: sum(1 for c in all_checks if c.status == CheckStatus.FAIL),
    }
    healthy = summary[CheckStatus.FAIL.value] == 0

    return SecurityAuditReport(
        timestamp=now_iso,
        mode=mode.value,
        healthy=healthy,
        summary=summary,
        results=tuple(all_checks),
    )
