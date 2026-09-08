"""토스증권 실주문 REST 경계.

공식 Open API v1 주문 규격을 따르며 자동 재시도를 하지 않는다. 주문 POST 뒤
응답을 잃은 경우는 거절이 아니라 결과 불명이다. 호출자는 같은 clientOrderId와
동일 payload를 보존하고 reconciliation 절차로 넘겨야 한다.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

from investment_agent.platform.serialization import canonical_json
from investment_agent.execution.brokers.toss.auth import (
    TossAuthError,
)
from investment_agent.execution.brokers.toss.auth import (
    refresh_access_token as shared_refresh_access_token,
)
from investment_agent.execution.approval.ledger import LiveExecutionPermit
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.safety.control import (
    LiveCancellationPermit,
    LiveTradingControls,
    RuntimeRiskState,
    assert_live_cancel_allowed,
    assert_live_order_allowed,
)
from investment_agent.execution.brokers.toss.client import access_token, to_toss_symbol

_BASE = "https://openapi.tossinvest.com"
_ORDERS_URL = f"{_BASE}/api/v1/orders"
_BUYING_POWER_URL = f"{_BASE}/api/v1/buying-power"
_SELLABLE_URL = f"{_BASE}/api/v1/sellable-quantity"
_COMMISSIONS_URL = f"{_BASE}/api/v1/commissions"
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
_US_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


class TossOrderApiError(RuntimeError):
    """토스 주문 API의 응답 또는 로컬 계약 오류."""


class TossOrderRejected(TossOrderApiError):
    """토스가 명시적인 4xx 응답으로 주문을 거절했다."""

    def __init__(self, *, status_code: int, code: str, message: str, request_id: str | None):
        super().__init__(f"Toss rejected request status={status_code} code={code}: {message}")
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


class TossOrderOutcomeUnknown(TossOrderApiError):
    """주문이 접수됐는지 단정할 수 없어 자동 재전송하면 안 되는 상태."""

    def __init__(self, *, client_order_id: str, reason: str, status_code: int | None = None):
        super().__init__(
            f"Toss order outcome is unknown for clientOrderId={client_order_id}: {reason}"
        )
        self.client_order_id = client_order_id
        self.status_code = status_code


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExecutionSafetyError(f"{field_name} must be decimal") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ExecutionSafetyError(f"{field_name} must be finite and positive")
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True)
class TossOrderCommand:
    """현재 플랫폼이 허용하는 S&P 500 미국주식 주문."""

    client_order_id: str
    symbol: str
    side: str
    order_type: str
    reference_price_usd: Decimal | str | float
    quantity: Decimal | str | float | None = None
    order_amount_usd: Decimal | str | float | None = None
    limit_price_usd: Decimal | str | float | None = None
    time_in_force: str = "DAY"

    def __post_init__(self) -> None:
        if not _CLIENT_ID_RE.fullmatch(self.client_order_id):
            raise ExecutionSafetyError("client_order_id must match Toss's 36-character format")
        symbol = self.symbol.strip().upper()
        if not _US_SYMBOL_RE.fullmatch(symbol):
            raise ExecutionSafetyError("live Toss command requires a valid US ticker")
        side = self.side.strip().upper()
        order_type = self.order_type.strip().upper()
        tif = self.time_in_force.strip().upper()
        if side not in {"BUY", "SELL"}:
            raise ExecutionSafetyError("side must be BUY or SELL")
        if order_type not in {"LIMIT", "MARKET"}:
            raise ExecutionSafetyError("order_type must be LIMIT or MARKET")
        if tif not in {"DAY", "CLS"}:
            raise ExecutionSafetyError("time_in_force must be DAY or CLS")
        if tif == "CLS" and order_type != "LIMIT":
            raise ExecutionSafetyError("CLS is supported only for LIMIT orders")
        if (self.quantity is None) == (self.order_amount_usd is None):
            raise ExecutionSafetyError("exactly one of quantity and order_amount_usd is required")

        reference = _decimal(self.reference_price_usd, "reference_price_usd")
        quantity = _decimal(self.quantity, "quantity") if self.quantity is not None else None
        amount = (
            _decimal(self.order_amount_usd, "order_amount_usd")
            if self.order_amount_usd is not None
            else None
        )
        limit_price = (
            _decimal(self.limit_price_usd, "limit_price_usd")
            if self.limit_price_usd is not None
            else None
        )
        if order_type == "LIMIT" and limit_price is None:
            raise ExecutionSafetyError("LIMIT order requires limit_price_usd")
        if order_type == "MARKET" and limit_price is not None:
            raise ExecutionSafetyError("MARKET order cannot carry limit_price_usd")
        if amount is not None and (order_type != "MARKET" or side != "BUY" or tif != "DAY"):
            raise ExecutionSafetyError("amount order is allowed only for US MARKET BUY DAY")
        if quantity is not None and quantity != quantity.to_integral_value():
            if not (side == "SELL" and order_type == "MARKET" and tif == "DAY"):
                raise ExecutionSafetyError(
                    "fractional quantity is allowed only for US MARKET SELL DAY"
                )
            if -quantity.as_tuple().exponent > 6:
                raise ExecutionSafetyError("fractional sell quantity supports at most 6 decimals")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "time_in_force", tif)
        object.__setattr__(self, "reference_price_usd", reference)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "order_amount_usd", amount)
        object.__setattr__(self, "limit_price_usd", limit_price)

    @property
    def estimated_notional_usd(self) -> float:
        amount = self.order_amount_usd
        if isinstance(amount, Decimal):
            return float(amount)
        quantity = self.quantity
        assert isinstance(quantity, Decimal)
        assert isinstance(self.reference_price_usd, Decimal)
        return float(quantity * self.reference_price_usd)

    @property
    def payload_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.payload()).encode("utf-8")).hexdigest()

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "clientOrderId": self.client_order_id,
            "symbol": to_toss_symbol(self.symbol),
            "side": self.side,
            "orderType": self.order_type,
            "timeInForce": self.time_in_force,
            # 사람의 고액 인지 확인을 AI가 대신 표시하지 않는다.
            "confirmHighValueOrder": False,
        }
        if isinstance(self.quantity, Decimal):
            payload["quantity"] = _decimal_text(self.quantity)
        if isinstance(self.order_amount_usd, Decimal):
            payload["orderAmount"] = _decimal_text(self.order_amount_usd)
        if isinstance(self.limit_price_usd, Decimal):
            payload["price"] = _decimal_text(self.limit_price_usd)
        return payload


@dataclass(frozen=True)
class TossOrderReceipt:
    order_id: str
    client_order_id: str
    payload_hash: str
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class TossOrderModification:
    """미국주식 주문의 호가 유형·가격만 바꾸는 재승인 대상."""

    client_order_id: str
    order_type: str
    existing_quantity: Decimal | str | float
    reference_price_usd: Decimal | str | float
    limit_price_usd: Decimal | str | float | None = None

    def __post_init__(self) -> None:
        if not _CLIENT_ID_RE.fullmatch(self.client_order_id):
            raise ExecutionSafetyError("modification authorization id is invalid")
        order_type = self.order_type.strip().upper()
        if order_type not in {"LIMIT", "MARKET"}:
            raise ExecutionSafetyError("modified order_type must be LIMIT or MARKET")
        quantity = _decimal(self.existing_quantity, "existing_quantity")
        if quantity != quantity.to_integral_value():
            raise ExecutionSafetyError("US order modification requires whole existing quantity")
        reference = _decimal(self.reference_price_usd, "reference_price_usd")
        price = (
            _decimal(self.limit_price_usd, "limit_price_usd")
            if self.limit_price_usd is not None
            else None
        )
        if order_type == "LIMIT" and price is None:
            raise ExecutionSafetyError("LIMIT modification requires limit_price_usd")
        if order_type == "MARKET" and price is not None:
            raise ExecutionSafetyError("MARKET modification cannot carry limit_price_usd")
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "existing_quantity", quantity)
        object.__setattr__(self, "reference_price_usd", reference)
        object.__setattr__(self, "limit_price_usd", price)

    @property
    def estimated_notional_usd(self) -> float:
        assert isinstance(self.existing_quantity, Decimal)
        assert isinstance(self.reference_price_usd, Decimal)
        return float(self.existing_quantity * self.reference_price_usd)

    def payload(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "orderType": self.order_type,
            "confirmHighValueOrder": False,
        }
        if isinstance(self.limit_price_usd, Decimal):
            value["price"] = _decimal_text(self.limit_price_usd)
        return value


@dataclass(frozen=True)
class TossOrderSnapshot:
    order_id: str
    symbol: str
    side: str
    order_type: str
    time_in_force: str
    status: str
    quantity: Decimal
    currency: str
    ordered_at: str
    price: Decimal | None
    filled_quantity: Decimal
    average_filled_price: Decimal | None
    commission: Decimal | None
    tax: Decimal | None
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, value: Mapping[str, Any]) -> TossOrderSnapshot:
        required = (
            "orderId", "symbol", "side", "orderType", "timeInForce", "status",
            "quantity", "currency", "orderedAt", "execution",
        )
        missing = [name for name in required if name not in value]
        if missing:
            raise TossOrderApiError(f"Toss order response missing fields: {missing}")
        execution = value["execution"]
        if not isinstance(execution, Mapping) or "filledQuantity" not in execution:
            raise TossOrderApiError("Toss order execution is invalid")

        def optional_decimal(raw: Any) -> Decimal | None:
            if raw is None:
                return None
            try:
                parsed = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise TossOrderApiError("Toss order contains invalid decimal data") from exc
            if not parsed.is_finite():
                raise TossOrderApiError("Toss order contains non-finite decimal data")
            return parsed

        quantity = optional_decimal(value["quantity"])
        filled = optional_decimal(execution["filledQuantity"])
        if quantity is None or quantity < 0 or filled is None or filled < 0 or filled > quantity:
            raise TossOrderApiError("Toss order quantities are inconsistent")
        # 공식 스펙은 unknown enum을 허용하라고 요구하므로 문자열 자체를 보존한다.
        return cls(
            order_id=str(value["orderId"]),
            symbol=str(value["symbol"]),
            side=str(value["side"]),
            order_type=str(value["orderType"]),
            time_in_force=str(value["timeInForce"]),
            status=str(value["status"]),
            quantity=quantity,
            currency=str(value["currency"]),
            ordered_at=str(value["orderedAt"]),
            price=optional_decimal(value.get("price")),
            filled_quantity=filled,
            average_filled_price=optional_decimal(execution.get("averageFilledPrice")),
            commission=optional_decimal(execution.get("commission")),
            tax=optional_decimal(execution.get("tax")),
            raw=dict(value),
        )


class TossOrderApi:
    """안전 permit 없이는 mutation 메서드가 호출될 수 없는 토스 REST 어댑터."""

    def __init__(
        self,
        *,
        token_provider: Callable[[], str] = access_token,
        token_refresher: Callable[[str], str] | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
        lockdown_state_dir: Path | str | None = None,
    ) -> None:
        self._token_provider = token_provider
        if token_refresher is None and token_provider is access_token:
            token_refresher = lambda rejected: shared_refresh_access_token(
                rejected_token=rejected
            )
        self._token_refresher = token_refresher
        self._session = session or requests.Session()
        self._timeout = timeout_seconds
        self._lockdown_state_dir = lockdown_state_dir

    @staticmethod
    def _headers(account_seq: int, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-Tossinvest-Account": str(account_seq),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        account_seq: int,
        **kwargs: Any,
    ) -> requests.Response:
        """401만 공용 token 갱신 뒤 한 번 재전송하고 그 밖의 retry는 하지 않는다."""
        token = self._token_provider()
        sender = getattr(self._session, method)
        response = sender(
            url,
            headers=self._headers(account_seq, token),
            **kwargs,
        )
        if response.status_code != 401 or self._token_refresher is None:
            return response
        try:
            refreshed = self._token_refresher(token)
        except TossAuthError as exc:
            raise TossOrderApiError("Toss authentication refresh failed") from exc
        return sender(
            url,
            headers=self._headers(account_seq, refreshed),
            **kwargs,
        )

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise TossOrderApiError("Toss returned non-JSON data") from exc
        if not isinstance(payload, dict):
            raise TossOrderApiError("Toss response must be an object")
        return payload

    @staticmethod
    def _raise_rejection(response: requests.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, Mapping):
            error = {}
        raise TossOrderRejected(
            status_code=response.status_code,
            code=str(error.get("code") or "unknown-error"),
            message=str(error.get("message") or "Toss rejected the request"),
            request_id=str(error["requestId"]) if error.get("requestId") else None,
        )

    def create_order(
        self,
        command: TossOrderCommand,
        *,
        permit: LiveExecutionPermit,
        controls: LiveTradingControls,
        risk_state: RuntimeRiskState,
        manifest_hash: str,
        now: datetime | None = None,
    ) -> TossOrderReceipt:
        assert_live_order_allowed(
            permit=permit,
            controls=controls,
            state=risk_state,
            order=command,
            manifest_hash=manifest_hash,
            now=now,
            lockdown_state_dir=self._lockdown_state_dir,
        )
        try:
            response = self._request(
                "post",
                _ORDERS_URL,
                account_seq=controls.account_seq,
                json=command.payload(),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise TossOrderOutcomeUnknown(
                client_order_id=command.client_order_id,
                reason=exc.__class__.__name__,
            ) from exc
        if response.status_code >= 500:
            raise TossOrderOutcomeUnknown(
                client_order_id=command.client_order_id,
                reason="server error after order submission",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            self._raise_rejection(response)
        payload = self._json(response)
        result = payload.get("result")
        if not isinstance(result, Mapping) or not result.get("orderId"):
            raise TossOrderOutcomeUnknown(
                client_order_id=command.client_order_id,
                reason="successful response omitted orderId",
                status_code=response.status_code,
            )
        returned_client_id = result.get("clientOrderId")
        if returned_client_id != command.client_order_id:
            raise TossOrderOutcomeUnknown(
                client_order_id=command.client_order_id,
                reason="clientOrderId mismatch",
                status_code=response.status_code,
            )
        return TossOrderReceipt(
            order_id=str(result["orderId"]),
            client_order_id=command.client_order_id,
            payload_hash=command.payload_hash,
            raw_response=dict(result),
        )

    def get_order(self, *, account_seq: int, order_id: str) -> TossOrderSnapshot:
        if account_seq <= 0 or not order_id:
            raise TossOrderApiError("account_seq and order_id are required")
        response = self._request(
            "get",
            f"{_ORDERS_URL}/{order_id}",
            account_seq=account_seq,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            self._raise_rejection(response)
        payload = self._json(response)
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise TossOrderApiError("Toss order detail result must be an object")
        return TossOrderSnapshot.from_api(result)

    def modify_order(
        self,
        *,
        account_seq: int,
        order_id: str,
        modification: TossOrderModification,
        permit: LiveExecutionPermit,
        controls: LiveTradingControls,
        risk_state: RuntimeRiskState,
        manifest_hash: str,
        now: datetime | None = None,
    ) -> str:
        """기존 미국주식 주문 정정도 신규 주문과 동일한 재승인·한도를 요구한다."""
        if account_seq != controls.account_seq or not order_id:
            raise ExecutionSafetyError("modification account or order_id is invalid")
        assert_live_order_allowed(
            permit=permit,
            controls=controls,
            state=risk_state,
            order=modification,
            manifest_hash=manifest_hash,
            now=now,
            lockdown_state_dir=self._lockdown_state_dir,
        )
        try:
            response = self._request(
                "post",
                f"{_ORDERS_URL}/{order_id}/modify",
                account_seq=account_seq,
                json=modification.payload(),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise TossOrderOutcomeUnknown(
                client_order_id=modification.client_order_id,
                reason=exc.__class__.__name__,
            ) from exc
        if response.status_code >= 500:
            raise TossOrderOutcomeUnknown(
                client_order_id=modification.client_order_id,
                reason="server error after modification submission",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            self._raise_rejection(response)
        result = self._json(response).get("result")
        if not isinstance(result, Mapping) or not result.get("orderId"):
            raise TossOrderOutcomeUnknown(
                client_order_id=modification.client_order_id,
                reason="successful modification response omitted replacement orderId",
                status_code=response.status_code,
            )
        return str(result["orderId"])

    def list_orders(
        self,
        *,
        account_seq: int,
        lifecycle: str,
        symbol: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[tuple[TossOrderSnapshot, ...], str | None, bool]:
        lifecycle = lifecycle.upper()
        if lifecycle not in {"OPEN", "CLOSED"}:
            raise TossOrderApiError("lifecycle must be OPEN or CLOSED")
        if not 1 <= limit <= 100:
            raise TossOrderApiError("limit must be between 1 and 100")
        params: dict[str, Any] = {"status": lifecycle, "limit": limit}
        if symbol:
            params["symbol"] = to_toss_symbol(symbol)
        if cursor:
            params["cursor"] = cursor
        response = self._request(
            "get",
            _ORDERS_URL,
            account_seq=account_seq,
            params=params,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            self._raise_rejection(response)
        payload = self._json(response)
        result = payload.get("result")
        if not isinstance(result, Mapping) or not isinstance(result.get("orders"), list):
            raise TossOrderApiError("Toss order list result is invalid")
        rows = tuple(TossOrderSnapshot.from_api(row) for row in result["orders"])
        next_cursor = result.get("nextCursor")
        has_next = result.get("hasNext")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise TossOrderApiError("Toss nextCursor is invalid")
        if not isinstance(has_next, bool):
            raise TossOrderApiError("Toss hasNext is invalid")
        return rows, next_cursor, has_next

    def buying_power(self, *, account_seq: int, currency: str = "USD") -> Decimal:
        currency = currency.upper()
        if currency not in {"USD", "KRW"}:
            raise TossOrderApiError("currency must be USD or KRW")
        response = self._request(
            "get",
            _BUYING_POWER_URL,
            account_seq=account_seq,
            params={"currency": currency},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            self._raise_rejection(response)
        result = self._json(response).get("result")
        if not isinstance(result, Mapping) or result.get("currency") != currency:
            raise TossOrderApiError("Toss buying power result is invalid")
        value = _decimal(result.get("cashBuyingPower"), "cashBuyingPower")
        return value

    def sellable_quantity(self, *, account_seq: int, symbol: str) -> Decimal:
        response = self._request(
            "get",
            _SELLABLE_URL,
            account_seq=account_seq,
            params={"symbol": to_toss_symbol(symbol)},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            self._raise_rejection(response)
        result = self._json(response).get("result")
        if not isinstance(result, Mapping):
            raise TossOrderApiError("Toss sellable quantity result is invalid")
        # 판매 가능 수량 0은 정상이라 양수 전용 helper를 쓰지 않는다.
        try:
            value = Decimal(str(result.get("sellableQuantity")))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise TossOrderApiError("Toss sellable quantity is invalid") from exc
        if not value.is_finite() or value < 0:
            raise TossOrderApiError("Toss sellable quantity is invalid")
        return value

    def commissions(self, *, account_seq: int) -> tuple[dict[str, Any], ...]:
        response = self._request(
            "get",
            _COMMISSIONS_URL,
            account_seq=account_seq,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            self._raise_rejection(response)
        result = self._json(response).get("result")
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise TossOrderApiError("Toss commissions result is invalid")
        validated: list[dict[str, Any]] = []
        for row in result:
            country = row.get("marketCountry")
            if not isinstance(country, str):
                raise TossOrderApiError("Toss commission marketCountry is invalid")
            try:
                rate = Decimal(str(row.get("commissionRate")))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise TossOrderApiError("Toss commission rate is invalid") from exc
            if not rate.is_finite() or rate < 0:
                raise TossOrderApiError("Toss commission rate is invalid")
            validated.append({**row, "commissionRate": rate})
        return tuple(validated)

    def cancel_order(
        self,
        *,
        account_seq: int,
        order_id: str,
        permit: LiveCancellationPermit,
        controls: LiveTradingControls,
        now: datetime | None = None,
    ) -> str:
        """정확한 주문 하나에 대한 소비된 운영자 승인이 있을 때만 취소한다."""
        if account_seq <= 0 or not order_id:
            raise TossOrderApiError("account_seq and order_id are required")
        assert_live_cancel_allowed(
            permit=permit,
            controls=controls,
            account_seq=account_seq,
            broker_order_id=order_id,
            now=now,
        )
        try:
            response = self._request(
                "post",
                f"{_ORDERS_URL}/{order_id}/cancel",
                account_seq=account_seq,
                json={},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise TossOrderOutcomeUnknown(
                client_order_id=f"cancel:{order_id}",
                reason=exc.__class__.__name__,
            ) from exc
        if response.status_code >= 500:
            raise TossOrderOutcomeUnknown(
                client_order_id=f"cancel:{order_id}",
                reason="server error after cancel submission",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            self._raise_rejection(response)
        payload = self._json(response)
        result = payload.get("result")
        if not isinstance(result, Mapping) or not result.get("orderId"):
            raise TossOrderOutcomeUnknown(
                client_order_id=f"cancel:{order_id}",
                reason="successful cancel response omitted replacement orderId",
                status_code=response.status_code,
            )
        return str(result["orderId"])


def parse_personal_order_event(
    payload: Mapping[str, Any], *, expected_account_seq: int
) -> tuple[str, TossOrderSnapshot]:
    """AsyncAPI personal:order 프레임을 계좌 혼선 없이 검증한다."""
    if payload.get("type") != "message":
        raise TossOrderApiError("not a Toss message frame")
    expected_topic = f"personal:order:{expected_account_seq}"
    if payload.get("topic") != expected_topic:
        raise TossOrderApiError("personal order topic does not match the configured account")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise TossOrderApiError("personal order data must be an object")
    if str(data.get("accountSeq")) != str(expected_account_seq):
        raise TossOrderApiError("personal order accountSeq mismatch")
    event = data.get("event")
    order = data.get("order")
    if not isinstance(event, str) or not isinstance(order, Mapping):
        raise TossOrderApiError("personal order event is invalid")
    return event, TossOrderSnapshot.from_api(order)
