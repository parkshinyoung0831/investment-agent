"""판단 하나를 가리키는 키와, 그 판단을 재현할 수 있는지 보는 지문.

## case_key는 계산되는 값이다

UUID를 쓰면 같은 판단을 두 번 돌렸을 때 두 행이 생기고, 그것이 중복인지 아닌지
사람이 눈으로 봐야 한다. 대신 **판단을 결정하는 것들로부터 키를 만든다** —
`(security_id, as_of_at, horizon_days, policy_key, policy_version)`. 저장소의
UNIQUE 제약과 같은 조합이라, 같은 판단은 두 번 들어갈 수 없다.

## context_hash는 재현 검증용이다

같은 입력이면 같은 판단이 나와야 한다. 모델을 바꾸거나 코드를 고친 뒤 그것이
여전한지 보려면, **그때 무엇을 입력했는지**의 지문이 필요하다.

`case_key`와 다른 값인 이유: case_key는 "어떤 질문인가"이고 context_hash는 "그 질문에
어떤 자료를 붙였나"다. 같은 질문에 다른 자료를 붙이면 다른 답이 나오는 것이 정상이고,
그때 둘을 구분할 수 있어야 한다.

## 시각은 초 단위로 자른다

`as_of_at`을 마이크로초까지 쓰면 같은 판단이 실행할 때마다 다른 키를 갖는다. 초 단위로
자르면 재실행이 같은 키로 모이고, 판단 주기가 초보다 짧은 일은 없다.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Mapping

from investment_agent.platform.clock import ensure_aware
from investment_agent.platform.serialization import canonical_json, content_hash


def truncate_to_second(moment: datetime) -> datetime:
    """마이크로초를 버린다. 재실행이 같은 키로 모이게 하는 유일한 이유다."""
    return ensure_aware(moment).replace(microsecond=0)


def case_key(
    *,
    security_id: int,
    as_of_at: datetime,
    horizon_days: int,
    policy_key: str,
    policy_version: int,
) -> str:
    """판단 하나의 키. 같은 질문이면 항상 같은 문자열.

    사람이 읽을 수 있게 앞부분을 그대로 두고 뒤에 지문을 붙인다 — 로그에서 어느
    종목·어느 시점인지 바로 보이는 편이 낫고, 지문이 충돌을 막는다.
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    moment = truncate_to_second(as_of_at)
    parts = {
        "security_id": security_id,
        "as_of_at": moment.isoformat(),
        "horizon_days": horizon_days,
        "policy_key": policy_key,
        "policy_version": policy_version,
    }
    digest = hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()[:16]
    return f"{security_id}:{moment.date().isoformat()}:h{horizon_days}:{digest}"


def context_hash(context: Mapping[str, Any]) -> str:
    """판단에 넣은 자료의 지문.

    부동소수와 `Decimal`이 섞이면 같은 값이 다른 지문을 갖는다. `canonical_json`이
    그것을 한 모양으로 맞춘 뒤 해싱한다.
    """
    return content_hash(context)


def is_reproducible(recorded_hash: str, context: Mapping[str, Any]) -> bool:
    """지금 자료로 그때의 판단을 재현할 수 있는가.

    거짓이면 판단이 틀렸다는 뜻이 아니라 **입력이 달라졌다**는 뜻이다. 그것을 구분해야
    "모델이 바뀐 것"과 "데이터가 정정된 것"을 따로 볼 수 있다.
    """
    return recorded_hash == context_hash(context)


__all__ = ["case_key", "context_hash", "is_reproducible", "truncate_to_second"]
