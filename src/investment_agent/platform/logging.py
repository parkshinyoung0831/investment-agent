"""JSON 한 줄 로깅과 비밀값 가리기.

## 왜 JSON인가

로그를 사람이 읽는 문장으로 쓰면 나중에 기계가 못 읽는다. GitHub Actions 로그에서
"어제 몇 행 들어왔나"를 물으려면 문장을 파싱해야 하고, 그 파서는 문구를 조금만
바꿔도 깨진다. 한 줄 JSON이면 그냥 필드를 읽으면 된다.

## 왜 print를 막는가

`print()`는 레벨도 시각도 출처도 없다. 문제가 생겼을 때 "이 줄이 어디서 나왔나"에
답할 수 없고, 조용한 실패를 찾는 일은 대개 그 질문에서 시작한다.

## 비밀값

로그와 예외 메시지는 사람 눈과 외부 서비스로 나간다. API 키가 붙은 URL을 그대로
찍으면 그 키는 유출된 것이다. `redact()`가 알려진 모양을 가리지만, 이것은 마지막
방어선이지 허가가 아니다 — **애초에 비밀값을 메시지에 넣지 않는다.**
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

# logging.LogRecord가 원래 갖는 속성 + Formatter가 나중에 채우는 둘. 이 이름들로
# extra를 넘기면 `Logger.makeRecord`가 KeyError를 던진다. 목록을 손으로 적지 않고
# 실제 레코드에서 뽑는 이유는, 파이썬 판올림으로 속성이 늘어도 따라가기 위해서다.
_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}

# 질의문자열에 실린 키. 외부 API URL을 로그에 찍는 자리가 실제로 있다.
_SECRET_QUERY = re.compile(r"(?i)([?&](?:api_?key|key|token|access_token|secret)=)[^&\s]+")
# `Bearer <token>` 형태의 인증 헤더.
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")

_CONFIGURED = False


def redact(text: str) -> str:
    """알려진 비밀값 모양을 가린다. 값의 길이도 남기지 않는다."""
    return _BEARER.sub(r"\1<redacted>", _SECRET_QUERY.sub(r"\1<redacted>", str(text)))


class JsonFormatter(logging.Formatter):
    """한 줄 JSON. `extra=`로 넘긴 필드는 그대로 최상위에 붙는다."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        # default=str: 로깅이 직렬화 때문에 죽으면 안 된다. 로그는 관측이지 계약이 아니다.
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, force: bool = False) -> None:
    """루트 로거를 JSON 한 줄로 맞춘다. **진입점에서만** 부른다.

    라이브러리 코드가 부르면 그 모듈을 import한 다른 프로그램의 로깅 설정까지
    빼앗는다.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # httpx는 PostgREST 페이지 하나마다 INFO 한 줄을 낸다. 대량 조회에서 수백 줄이
    # 쌓여 정작 봐야 할 파이프라인 사건을 밀어낸다.
    for noisy in ("httpx", "httpcore", "hpack", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """로거를 얻는다. 이름은 항상 `__name__` — 출처를 손으로 적으면 파일을 옮길 때
    조용히 거짓말이 된다."""
    return logging.getLogger(name)


def log_fields(**fields: Any) -> Mapping[str, Any]:
    """`logger.info("...", extra=log_fields(rows=12))` 형태로 쓰는 helper.

    예약된 이름을 넘기면 `logging`이 `KeyError`를 던지므로 여기서 먼저 막는다.
    """
    clashes = sorted(set(fields) & _RESERVED)
    if clashes:
        raise ValueError(f"reserved log field names: {', '.join(clashes)}")
    return fields


__all__ = ["JsonFormatter", "configure_logging", "get_logger", "log_fields", "redact"]
