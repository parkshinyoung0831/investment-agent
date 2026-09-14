"""LLM의 진입 조건과 재판단을 제한된 순수 계약으로 검증한다."""
from __future__ import annotations

import math
from datetime import timedelta
from investment_agent.platform.serialization import parse_datetime


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise ValueError('positive finite number required')
    return float(value)


def create_plan(raw, *, reference_price, now, source_expires_at):
    lower, upper, invalid = (_positive(raw[key]) for key in ('lower_price','upper_price','invalidate_below'))
    reference = _positive(reference_price)
    if not .8*reference <= lower <= upper <= 1.2*reference or upper/lower > 1.1 or invalid >= lower:
        raise ValueError('entry price range exceeds deterministic bounds')
    reason = str(raw.get('reason') or '').strip()
    if not reason:
        raise ValueError('entry rationale required')
    expires = min(parse_datetime(source_expires_at), now+timedelta(hours=min(24, _positive(raw['valid_hours']))))
    if expires <= now:
        raise ValueError('entry source expired')
    return dict(lower_price=lower,upper_price=upper,invalidate_below=invalid,
                expires_at=expires.isoformat(), reason=reason[:2000], created_at=now.isoformat())


def trigger_status(plan, *, price, quoted_at, now):
    if now >= parse_datetime(plan['expires_at']):
        return 'expired'
    if quoted_at is None or not 0 <= (now-parse_datetime(quoted_at)).total_seconds() <= 120:
        return 'stale_quote'
    value = _positive(price)
    if value <= plan['invalidate_below']:
        return 'cancelled'
    return 'triggered' if plan['lower_price'] <= value <= plan['upper_price'] else 'waiting'


def validate_review(raw, *, now, expires_at):
    decision = raw.get('decision')
    reason = str(raw.get('reason') or '').strip()
    if decision not in ('enter','wait','cancel') or not reason:
        raise ValueError('entry review requires enter/wait/cancel and rationale')
    expires = min(parse_datetime(expires_at), now+timedelta(minutes=min(5, _positive(raw.get('valid_minutes',5)))))
    if expires <= now:
        raise ValueError('entry review expired')
    return dict(decision=decision,reason=reason[:2000],reviewed_at=now.isoformat(),expires_at=expires.isoformat())
